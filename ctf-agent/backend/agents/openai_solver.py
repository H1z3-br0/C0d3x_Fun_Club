"""OpenAI-compatible solver via CLIProxyAPI."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from backend.cost_tracker import CostTracker
from backend.ctfd import CTFdClient
from backend.loop_detect import LOOP_WARNING_MESSAGE, LoopDetector
from backend.models import context_window, model_id_from_spec, supports_vision
from backend.prompts import ChallengeMeta, build_prompt, list_distfiles
from backend.profiles import image_for_profile, suggest_profile
from backend.sandbox import DockerSandbox
from backend.solver_base import CANCELLED, CONTEXT_LIMIT, CORRECT_MARKERS, ERROR, FLAG_FOUND, GAVE_UP, QUOTA_ERROR, SolverResult
from backend.tools.core import (
    do_bash,
    do_check_findings,
    do_list_files,
    do_read_file,
    do_submit_flag,
    do_view_image,
    do_web_fetch,
    do_web_search,
    do_webhook_create,
    do_webhook_get_requests,
    do_write_file,
)
from backend.console import log_event, log_model_text, log_tool_call, log_tool_result, log_usage
from backend.tracing import SolverTracer

logger = logging.getLogger(__name__)


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a bash command in the Docker sandbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "default": 60},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the sandbox container.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a file into the sandbox container.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory in the sandbox.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "default": "/challenge/distfiles"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_flag",
            "description": "Submit a flag to CTFd. Returns CORRECT, ALREADY SOLVED, or INCORRECT.",
            "parameters": {
                "type": "object",
                "properties": {"flag": {"type": "string"}},
                "required": ["flag"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a URL from the host network.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "method": {"type": "string", "default": "GET"},
                    "body": {"type": "string", "default": ""},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "webhook_create",
            "description": "Create a webhook.site token for out-of-band HTTP callbacks (XSS, SSRF, bot challenges).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "webhook_get_requests",
            "description": "Retrieve HTTP requests received by a webhook.site token.",
            "parameters": {
                "type": "object",
                "properties": {"uuid": {"type": "string"}},
                "required": ["uuid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_image",
            "description": "View an image file from the sandbox for visual/steg analysis.",
            "parameters": {
                "type": "object",
                "properties": {"filename": {"type": "string"}},
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify_coordinator",
            "description": "Send a strategic message to the coordinator.",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_findings",
            "description": (
                "Check what your sibling agents working on this same challenge have found so far. "
                "Call this when you are stuck, about to try a new approach, or want to avoid "
                "duplicating work. Returns their latest discoveries and progress."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for CTF writeups, documentation, vulnerability details, "
                "crypto algorithms, or any reference material. Use when you encounter "
                "unfamiliar libraries, ciphers, formats, or want prior art on similar challenges."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 5, "description": "Max results to return"},
                },
                "required": ["query"],
            },
        },
    },
]


@dataclass
class OpenAISolver:
    """OpenAI-compatible solver via CLIProxyAPI."""

    model_spec: str
    challenge_dir: str
    meta: ChallengeMeta
    ctfd: CTFdClient
    cost_tracker: CostTracker
    settings: object
    cancel_event: asyncio.Event | None = None
    no_submit: bool = False
    submit_fn: Any | None = None
    message_bus: Any | None = None
    notify_coordinator: Any | None = None

    def __post_init__(self) -> None:
        self.model_id = model_id_from_spec(self.model_spec)
        self.cancel_event = self.cancel_event or asyncio.Event()
        profile = suggest_profile(self.meta.category)
        default_image = image_for_profile(profile)
        self.sandbox = DockerSandbox(
            image=getattr(self.settings, "sandbox_image", default_image),
            challenge_dir=self.challenge_dir,
            memory_limit=getattr(self.settings, "container_memory_limit", "4g"),
        )
        self.use_vision = supports_vision(self.model_spec)
        self.loop_detector = LoopDetector()
        self.tracer = SolverTracer(self.meta.name, self.model_id)
        self.agent_name = f"{self.meta.name}/{self.model_id}"
        self._messages: list[dict[str, Any]] = []
        self._step_count = 0
        self._flag: str | None = None
        self._confirmed = False
        self._findings: str = ""
        self._client: AsyncOpenAI | None = None
        self._started = False
        self._last_prompt_tokens: int = 0

    async def start(self) -> None:
        if not self.sandbox._container:
            await self.sandbox.start()

        arch_result = await self.sandbox.exec("uname -m", timeout_s=10)
        container_arch = arch_result.stdout.strip() or "unknown"
        distfile_names = list_distfiles(self.challenge_dir)
        system_prompt = build_prompt(
            self.meta,
            distfile_names,
            container_arch=container_arch,
            has_named_tools=True,
        )

        base_url = getattr(self.settings, "openai_base_url", "http://localhost:8080/v1")
        api_key = getattr(self.settings, "openai_api_key", "")
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)

        self._messages = [
            {"role": "system", "content": system_prompt},
        ]

        self.tracer.event("start", challenge=self.meta.name, model=self.model_id)
        logger.info(f"[{self.agent_name}] OpenAI solver started")

    async def run_until_done_or_gave_up(self) -> SolverResult:
        if not self._client:
            await self.start()
        assert self._client is not None

        t0 = time.monotonic()
        try:
            while not self.cancel_event.is_set():
                if not self._started:
                    self._messages.append({"role": "user", "content": "Solve this CTF challenge."})
                    self._started = True

                resp = await self._client.chat.completions.create(
                    model=self.model_id,
                    messages=self._messages,
                    tools=TOOL_SPECS,
                    tool_choice="auto",
                )

                usage = resp.usage
                if usage:
                    self.cost_tracker.record_tokens(
                        self.agent_name,
                        self.model_id,
                        input_tokens=usage.prompt_tokens or 0,
                        output_tokens=usage.completion_tokens or 0,
                        cache_read_tokens=0,
                        provider_spec="codex",
                        duration_seconds=time.monotonic() - t0,
                    )
                    agent_usage = self.cost_tracker.by_agent.get(self.agent_name)
                    cost = agent_usage.cost_usd if agent_usage else 0.0
                    self.tracer.usage(
                        usage.prompt_tokens or 0,
                        usage.completion_tokens or 0,
                        0,
                        cost,
                    )
                    log_usage(self.agent_name, usage.prompt_tokens or 0, usage.completion_tokens or 0, cost)
                    self._last_prompt_tokens = usage.prompt_tokens or 0

                    # Context limit check — rotate before the window fills completely
                    max_ctx = context_window(self.model_spec)
                    limit_pct = getattr(self.settings, "context_limit_pct", 0.80)
                    if max_ctx > 0 and self._last_prompt_tokens >= int(max_ctx * limit_pct):
                        logger.warning(
                            "[%s] Context at %d/%d (%.0f%%) — generating handoff summary",
                            self.agent_name, self._last_prompt_tokens, max_ctx,
                            self._last_prompt_tokens / max_ctx * 100,
                        )
                        summary = await self._generate_handoff_summary()
                        return self._result(CONTEXT_LIMIT, handoff_summary=summary)

                choice = resp.choices[0]
                message = choice.message

                if message.tool_calls:
                    # Append assistant message with tool calls
                    self._messages.append(
                        {
                            "role": "assistant",
                            "content": message.content or "",
                            "tool_calls": [tc.model_dump() for tc in message.tool_calls],
                        }
                    )
                else:
                    if message.content:
                        text = str(message.content)
                        self._findings = text[:2000]
                        self.tracer.model_response(text[:500], self._step_count)
                        log_model_text(self.agent_name, self._step_count, text[:300])
                    break

                for tool_call in message.tool_calls:
                    if self.cancel_event.is_set():
                        break

                    tool_name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments or "{}")
                    except Exception:
                        args = {}

                    self._step_count += 1
                    self.tracer.tool_call(tool_name, args, self._step_count)
                    log_tool_call(self.agent_name, self._step_count, tool_name, args)

                    loop_status = self.loop_detector.check(tool_name, args)
                    t_start = time.monotonic()
                    if loop_status == "break":
                        result = LOOP_WARNING_MESSAGE
                    else:
                        result = await self._dispatch_tool(tool_name, args)
                        if loop_status == "warn" and isinstance(result, str):
                            result = f"{result}\n\n{LOOP_WARNING_MESSAGE}"
                    t_dur = time.monotonic() - t_start

                    if tool_name == "submit_flag" and isinstance(result, str):
                        if any(m in result for m in CORRECT_MARKERS):
                            self._confirmed = True

                    self.tracer.tool_result(tool_name, str(result), self._step_count)
                    log_tool_result(self.agent_name, self._step_count, tool_name, str(result)[:500], t_dur)

                    # Tool result message
                    self._messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": str(result) if result is not None else "",
                        }
                    )

                    # If view_image returned image tuple, append user message with image
                    if isinstance(result, dict) and result.get("_image_data_url"):
                        self._messages.append(
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Image from view_image."},
                                    {"type": "image_url", "image_url": {"url": result["_image_data_url"]}},
                                ],
                            }
                        )

                    # Every 10 steps: broadcast our progress, then inject siblings' findings
                    if self._step_count % 10 == 0 and self.message_bus:
                        progress = self._extract_recent_progress()
                        if progress:
                            await self.message_bus.post(self.model_spec, progress)
                        findings_text = await do_check_findings(self.message_bus, self.model_spec)
                        if findings_text and "No new findings" not in findings_text:
                            self._messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "**Team update** — your sibling agents have new findings. "
                                        "Incorporate these into your analysis and avoid duplicating work:\n\n"
                                        + findings_text
                                    ),
                                }
                            )

                if self._confirmed:
                    return self._result(FLAG_FOUND)

            return self._result(GAVE_UP)

        except asyncio.CancelledError:
            return self._result(CANCELLED)
        except Exception as e:
            err = str(e)
            self._findings = f"Error: {err}"
            self.tracer.event("error", error=err)
            if any(k in err.lower() for k in ("quota", "rate", "capacity", "usage")):
                return self._result(QUOTA_ERROR)
            return self._result(ERROR)

    async def _dispatch_tool(self, name: str, args: dict[str, Any]) -> Any:
        if name == "bash":
            return await do_bash(self.sandbox, args.get("command", ""), args.get("timeout_seconds", 60))
        if name == "read_file":
            return await do_read_file(self.sandbox, args.get("path", ""))
        if name == "write_file":
            return await do_write_file(self.sandbox, args.get("path", ""), args.get("content", ""))
        if name == "list_files":
            return await do_list_files(self.sandbox, args.get("path", "/challenge/distfiles"))
        if name == "submit_flag":
            if self.no_submit:
                self._flag = args.get("flag", "")
                self._confirmed = True  # treat as confirmed so swarm stops after finding a flag
                return "DRY RUN — flag recorded, not submitted to CTFd."
            submit_fn = self.submit_fn or (lambda flag: do_submit_flag(self.ctfd, self.meta.name, flag))
            display, confirmed = await submit_fn(args.get("flag", ""))
            if confirmed:
                self._confirmed = True
                self._flag = args.get("flag", "")
            return display
        if name == "web_fetch":
            return await do_web_fetch(args.get("url", ""), args.get("method", "GET"), args.get("body", ""))
        if name == "webhook_create":
            return await do_webhook_create()
        if name == "webhook_get_requests":
            return await do_webhook_get_requests(args.get("uuid", ""))
        if name == "view_image":
            result = await do_view_image(self.sandbox, args.get("filename", ""), use_vision=self.use_vision)
            if isinstance(result, tuple):
                image_bytes, mime_type = result
                data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"
                return {"_image_data_url": data_url, "mime_type": mime_type, "bytes": len(image_bytes)}
            return result
        if name == "notify_coordinator":
            if self.notify_coordinator:
                await self.notify_coordinator(args.get("message", ""))
                return "Coordinator notified."
            return "No coordinator connected."
        if name == "check_findings":
            return await do_check_findings(self.message_bus, self.model_spec)
        if name == "web_search":
            return await do_web_search(args.get("query", ""), args.get("max_results", 5))
        return f"Unknown tool: {name}"

    def _extract_recent_progress(self) -> str:
        """Compose a short status update from recent messages for broadcasting to siblings."""
        assistant_text = ""
        tool_snippets: list[str] = []
        for msg in reversed(self._messages[-12:]):
            role = msg.get("role")
            if role == "assistant" and msg.get("content") and not assistant_text:
                assistant_text = str(msg["content"])[:300]
            elif role == "tool" and len(tool_snippets) < 2:
                content = str(msg.get("content", "")).strip()
                if content and content not in ("(no output)", "Coordinator notified."):
                    tool_snippets.append(content[:200])
        parts: list[str] = [f"[step {self._step_count}]"]
        if assistant_text:
            parts.append(assistant_text)
        if tool_snippets:
            parts.append("Recent results: " + " | ".join(reversed(tool_snippets)))
        return " ".join(parts) if len(parts) > 1 else ""

    def bump(self, insights: str) -> None:
        self._messages.append(
            {
                "role": "user",
                "content": (
                    "Your previous attempt did not find the flag. Here are insights from other agents:\n\n"
                    f"{insights}\n\nDo NOT repeat what was tried. You can still use this info to try new approaches based on it"
                ),
            }
        )
        self.loop_detector.reset()
        self.tracer.event("bump", insights=insights[:500])

    def _result(self, status: str, handoff_summary: str | None = None) -> SolverResult:
        agent_usage = self.cost_tracker.by_agent.get(self.agent_name)
        cost = agent_usage.cost_usd if agent_usage else 0.0
        self.tracer.event("finish", status=status, flag=self._flag, confirmed=self._confirmed, cost_usd=round(cost, 4))
        return SolverResult(
            flag=self._flag,
            status=status,
            findings_summary=self._findings[:2000],
            step_count=self._step_count,
            cost_usd=cost,
            log_path=self.tracer.path,
            handoff_summary=handoff_summary,
        )

    async def _generate_handoff_summary(self) -> str:
        """Ask the model to compress its full context into a structured handoff briefing."""
        assert self._client is not None
        handoff_request = (
            "CRITICAL: Your context window is nearly full and a fresh agent will continue from your summary.\n"
            "Write a maximally dense handoff briefing. Cover every point:\n\n"
            "1. CHALLENGE: What this challenge is (1-2 sentences)\n"
            "2. TRIED & FAILED: Every approach that didn't work — exact commands, error messages, why it failed\n"
            "3. KEY FINDINGS: All important discoveries — addresses, offsets, values, file contents, partial flags, patterns\n"
            "4. WORKING HYPOTHESIS: Your best current theory on how to reach the flag\n"
            "5. NEXT STEPS: The first 3-5 concrete bash commands the next agent should run immediately\n"
            "6. CRITICAL FILES: Paths of files you created/modified that contain important data\n\n"
            "No padding. No preamble. Every word must carry information the next agent needs."
        )
        try:
            resp = await self._client.chat.completions.create(
                model=self.model_id,
                messages=self._messages + [{"role": "user", "content": handoff_request}],
            )
            summary = resp.choices[0].message.content or ""
            self.tracer.event("handoff_generated", summary_len=len(summary))
            logger.info("[%s] Handoff summary generated (%d chars)", self.agent_name, len(summary))
            return summary or self._findings or "No summary available."
        except Exception as e:
            logger.warning("[%s] Handoff summary generation failed: %s", self.agent_name, e)
            return self._findings or "No summary available."

    def reset_with_handoff(self, summary: str) -> None:
        """Reset conversation history, injecting a handoff from the previous context window.

        Keeps the Docker sandbox running — all files and state created during the
        previous context window are still accessible.
        """
        system_msg = self._messages[0] if self._messages else {"role": "system", "content": ""}
        self._messages = [
            system_msg,
            {
                "role": "user",
                "content": (
                    "=== HANDOFF FROM PREVIOUS AGENT (context window reset) ===\n\n"
                    f"{summary}\n\n"
                    "=== END HANDOFF ===\n\n"
                    "You are continuing this challenge with a fresh context window. "
                    "Your Docker sandbox with all previously created files is still running. "
                    "Immediately execute the NEXT STEPS listed above."
                ),
            },
        ]
        self._step_count = 0
        self._last_prompt_tokens = 0
        self._started = True  # The handoff message serves as the initial prompt
        self.loop_detector.reset()
        self.tracer.event("context_rotation", summary_len=len(summary))
        logger.info("[%s] Context reset with handoff (%d chars)", self.agent_name, len(summary))

    async def stop(self) -> None:
        self.tracer.event("stop", step_count=self._step_count)
        self.tracer.close()
        if self.sandbox:
            await self.sandbox.stop()
