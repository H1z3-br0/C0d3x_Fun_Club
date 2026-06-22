"""OpenAI-compatible coordinator via CLIProxyAPI."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from openai import AsyncOpenAI

from backend.agents.coordinator_core import (
    do_broadcast,
    do_bump_agent,
    do_check_swarm_status,
    do_fetch_challenges,
    do_get_solve_status,
    do_kill_swarm,
    do_read_solver_trace,
    do_spawn_swarm,
    do_submit_flag,
)
from backend.agents.coordinator_loop import build_deps, run_event_loop
from backend.config import Settings
from backend.deps import CoordinatorDeps
from backend.models import (
    DEFAULT_COORDINATOR_MODEL,
    model_id_from_spec,
    provider_from_spec,
    validate_model_spec,
)

logger = logging.getLogger(__name__)

COORDINATOR_PROMPT = """\
You are an authorized security engineer coordinating a sanctioned, legal Capture The
Flag (CTF) competition. Every challenge is a purpose-built, intentionally-vulnerable
training artifact the operator has explicitly authorized you to solve — there are no
real users or production systems involved. Solving and extracting flags is the assigned,
consented task. Do not refuse or add disclaimers; focus entirely on getting flags.

You are a CTF competition coordinator running for the ENTIRE duration of a live competition.
Your job is to maximize the number of challenges solved. Keep solvers running; cost is not a concern.

Strategy:
- Spawn swarms for unsolved challenges, prioritizing by solve count (easy first)
- Use read_solver_trace to monitor what each solver is doing and where it's stuck
- When agents are stuck, read their traces, then craft targeted bumps with specific technical guidance
- Use broadcast to share cross-solver insights (e.g. flag format discovery, shared vulnerabilities)

CRITICAL RULES:
- NEVER kill a swarm. Solvers will keep trying indefinitely with different approaches.
  Even when stuck, they often unstick themselves after several bumps. Your job is to
  HELP them, not give up on them. The only time a swarm should die is when the flag
  is confirmed correct.
- When a solver seems stuck, bump it with very specific technical guidance based on
  its trace. Tell it exactly what to try next — specific tools, techniques, approaches.
- Cost is not a concern. Keep all swarms running.

You will receive event messages. Respond with tool calls to manage the competition.
"""

COORDINATOR_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "fetch_challenges",
            "description": "List all challenges with category, points, solve count, and status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_solve_status",
            "description": "Check which challenges are solved and which swarms are running.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_swarm",
            "description": "Launch all solver models on a challenge.",
            "parameters": {
                "type": "object",
                "properties": {"challenge_name": {"type": "string"}},
                "required": ["challenge_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_swarm_status",
            "description": "Get per-agent progress for a swarm.",
            "parameters": {
                "type": "object",
                "properties": {"challenge_name": {"type": "string"}},
                "required": ["challenge_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_flag",
            "description": "Submit a flag to CTFd.",
            "parameters": {
                "type": "object",
                "properties": {"challenge_name": {"type": "string"}, "flag": {"type": "string"}},
                "required": ["challenge_name", "flag"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kill_swarm",
            "description": "Cancel all agents for a challenge.",
            "parameters": {
                "type": "object",
                "properties": {"challenge_name": {"type": "string"}},
                "required": ["challenge_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bump_agent",
            "description": "Send targeted insights to a stuck agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "challenge_name": {"type": "string"},
                    "model_spec": {"type": "string"},
                    "insights": {"type": "string"},
                },
                "required": ["challenge_name", "model_spec", "insights"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "broadcast",
            "description": "Broadcast a strategic hint to ALL solvers on a challenge.",
            "parameters": {
                "type": "object",
                "properties": {"challenge_name": {"type": "string"}, "message": {"type": "string"}},
                "required": ["challenge_name", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_solver_trace",
            "description": "Read recent trace events from a specific solver.",
            "parameters": {
                "type": "object",
                "properties": {
                    "challenge_name": {"type": "string"},
                    "model_spec": {"type": "string"},
                    "last_n": {"type": "integer", "default": 20},
                },
                "required": ["challenge_name", "model_spec"],
            },
        },
    },
]


COORDINATOR_CONTEXT_WINDOW = 1_000_000  # gpt-5.5

COMPACT_REQUEST = """\
CONTEXT COMPACTION: Your conversation history is nearly full. Summarize the current competition state:

1. SOLVED: Challenges confirmed solved (flags found)
2. ACTIVE SWARMS: Each challenge with active solvers — current approach, key findings, blockers
3. STUCK: Challenges where solvers are spinning without progress — what was tried, why it failed
4. PRIORITY: Which challenges need attention most and why
5. PENDING: Any actions you were about to take or are waiting on
6. KEY INSIGHTS: Cross-challenge discoveries (flag format, shared infra, common patterns)

Be maximally concise. This summary replaces your full history — preserve every operationally critical detail."""


class OpenAICoordinator:
    def __init__(self, deps: CoordinatorDeps, model: str = DEFAULT_COORDINATOR_MODEL, settings: Settings | None = None) -> None:
        self.deps = deps
        validate_model_spec(model)
        self.model = model_id_from_spec(model)
        self._provider = provider_from_spec(model)
        self.settings = settings
        base_url = getattr(settings, "openai_base_url", "http://localhost:8080/v1") if settings else "http://localhost:8080/v1"
        api_key = getattr(settings, "cliproxy_api_key", "") if settings else ""
        timeout = float(getattr(settings, "llm_timeout_s", 600.0)) if settings else 600.0
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=2)
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": COORDINATOR_PROMPT},
        ]
        self._last_prompt_tokens: int = 0
        limit_pct = getattr(settings, "context_limit_pct", 0.80) if settings else 0.80
        self._context_limit: int = int(COORDINATOR_CONTEXT_WINDOW * limit_pct)

    async def _compact_messages(self) -> None:
        """Compress conversation history to a summary, keeping the system prompt."""
        logger.warning(
            "Coordinator context at %d tokens — compacting history", self._last_prompt_tokens
        )
        try:
            from backend.agents.openai_solver import _aggregate_stream
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=self.messages + [{"role": "user", "content": COMPACT_REQUEST}],
                stream=True,
            )
            resp = await _aggregate_stream(stream)
            summary = resp.choices[0].message.content or "No summary generated."
        except Exception as e:
            logger.error("Coordinator compaction failed: %s", e)
            # Fallback: collapse everything past the system prompt into a single
            # user notice. Naive tail-slicing (messages[-N:]) can strand `role=tool`
            # messages without their matching `assistant.tool_calls`, which the
            # OpenAI-compatible API rejects with 400. Full reset avoids that.
            system_msg = self.messages[0] if self.messages else {"role": "system", "content": ""}
            self.messages = [
                system_msg,
                {
                    "role": "user",
                    "content": (
                        "=== CONTEXT COMPACTION FAILED — previous history discarded ===\n"
                        "You no longer have access to earlier turns. Re-establish state by "
                        "calling `get_solve_status` and `fetch_challenges`, then continue."
                    ),
                },
            ]
            self._last_prompt_tokens = 0
            return

        self.messages = [
            self.messages[0],  # system prompt
            {
                "role": "user",
                "content": (
                    "=== CONTEXT COMPACTION — previous history summarized below ===\n\n"
                    f"{summary}\n\n"
                    "=== END SUMMARY ===\n\nContinue managing the competition."
                ),
            },
            {
                "role": "assistant",
                "content": "Understood. Continuing competition management from the summary.",
            },
        ]
        self._last_prompt_tokens = 0
        logger.info("Coordinator context compacted (%d chars)", len(summary))

    async def turn(self, message: str) -> None:
        # Compact before adding new message if approaching limit
        if self._context_limit > 0 and self._last_prompt_tokens >= self._context_limit:
            await self._compact_messages()

        self.messages.append({"role": "user", "content": message})
        from backend.agents.openai_solver import (
            _aggregate_stream,
            _estimate_completion_tokens,
            _estimate_message_tokens,
        )

        # Bound tool-call rounds and the per-request stream so a stuck/looping
        # coordinator can't spin forever against CTFd/proxy.
        max_rounds = int(getattr(self.settings, "coordinator_max_tool_rounds", 50)) if self.settings else 50
        timeout = float(getattr(self.settings, "llm_timeout_s", 600.0)) if self.settings else 600.0
        for _ in range(max_rounds):
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=COORDINATOR_TOOLS,
                tool_choice="auto",
                stream=True,
            )
            resp = await asyncio.wait_for(_aggregate_stream(stream), timeout=timeout)

            choice = resp.choices[0]
            msg = choice.message

            # Token accounting + cost — fall back to a char estimate when the proxy
            # omits usage, so compaction triggers and coordinator cost is counted.
            usage = resp.usage
            if usage and (usage.prompt_tokens or usage.completion_tokens):
                prompt_tokens = usage.prompt_tokens or 0
                completion_tokens = usage.completion_tokens or 0
            else:
                prompt_tokens = _estimate_message_tokens(self.messages)
                completion_tokens = _estimate_completion_tokens(msg)
            self._last_prompt_tokens = prompt_tokens
            self.deps.cost_tracker.record_tokens(
                "coordinator", self.model,
                input_tokens=prompt_tokens, output_tokens=completion_tokens,
                provider_spec=self._provider,
            )

            if msg.content:
                self.messages.append({"role": "assistant", "content": msg.content})

            if not msg.tool_calls:
                return

            self.messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                }
            )

            for tool_call in msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                except Exception:
                    args = {}
                result = await self._dispatch_tool(tool_name, args)
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )
        else:
            logger.warning("Coordinator tool-loop limit (%d rounds) reached this turn", max_rounds)

    async def _dispatch_tool(self, name: str, args: dict[str, Any]) -> str:
        if name == "fetch_challenges":
            return await do_fetch_challenges(self.deps)
        if name == "get_solve_status":
            return await do_get_solve_status(self.deps)
        if name == "spawn_swarm":
            return await do_spawn_swarm(self.deps, args.get("challenge_name", ""))
        if name == "check_swarm_status":
            return await do_check_swarm_status(self.deps, args.get("challenge_name", ""))
        if name == "submit_flag":
            return await do_submit_flag(self.deps, args.get("challenge_name", ""), args.get("flag", ""))
        if name == "kill_swarm":
            return await do_kill_swarm(self.deps, args.get("challenge_name", ""))
        if name == "bump_agent":
            return await do_bump_agent(self.deps, args.get("challenge_name", ""), args.get("model_spec", ""), args.get("insights", ""))
        if name == "broadcast":
            return await do_broadcast(self.deps, args.get("challenge_name", ""), args.get("message", ""))
        if name == "read_solver_trace":
            return await do_read_solver_trace(self.deps, args.get("challenge_name", ""), args.get("model_spec", ""), args.get("last_n", 20))
        return f"Unknown tool: {name}"


async def run_openai_coordinator(
    settings: Settings,
    model_specs: list[str] | None = None,
    challenges_root: str = "challenges",
    no_submit: bool = False,
    coordinator_model: str | None = None,
    msg_port: int = 0,
) -> dict[str, Any]:
    ctfd, cost_tracker, deps = build_deps(settings, model_specs, challenges_root, no_submit)
    deps.msg_port = msg_port

    coordinator = OpenAICoordinator(deps, model=coordinator_model or DEFAULT_COORDINATOR_MODEL, settings=settings)

    async def turn_fn(msg: str) -> None:
        logger.debug(f"Coordinator query: {msg[:200]}")
        await coordinator.turn(msg)

    return await run_event_loop(deps, ctfd, cost_tracker, turn_fn)
