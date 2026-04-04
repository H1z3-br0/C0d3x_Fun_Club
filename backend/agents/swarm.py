"""ChallengeSwarm — Parallel solvers racing on one challenge."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backend.cost_tracker import CostTracker
from backend.ctfd import CTFdClient
from backend.message_bus import ChallengeMessageBus
from backend.models import DEFAULT_MODELS
from backend.prompts import ChallengeMeta
from backend.memory import MemoryStore
from backend.solver_base import (
    CANCELLED,
    CONTEXT_LIMIT,
    ERROR,
    FLAG_FOUND,
    GAVE_UP,
    QUOTA_ERROR,
    SolverProtocol,
    SolverResult,
)

if TYPE_CHECKING:
    from backend.config import Settings

logger = logging.getLogger(__name__)


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip()) or "unknown"


def _summarize_trace(path: str, last_n: int = 40) -> list[str]:
    try:
        lines = Path(path).read_text().strip().split("\n")
    except FileNotFoundError:
        return ["Trace file not found."]
    except Exception as e:
        return [f"Trace read error: {e}"]
    recent = lines[-last_n:] if lines else []
    summary: list[str] = []
    for line in recent:
        try:
            d = json.loads(line)
            t = d.get("type", "?")
            if t == "tool_call":
                args_str = str(d.get("args", ""))[:120]
                summary.append(f"step {d.get('step','?')} CALL {d.get('tool','?')}: {args_str}")
            elif t == "tool_result":
                result_str = str(d.get("result", ""))[:120]
                summary.append(f"step {d.get('step','?')} RESULT {d.get('tool','?')}: {result_str}")
            elif t == "model_response":
                text = str(d.get("text", ""))[:160]
                summary.append(f"step {d.get('step','?')} MODEL: {text}")
            elif t in ("finish", "error", "bump", "turn_failed"):
                summary.append(f"** {t}: {json.dumps({k:v for k,v in d.items() if k != 'ts'})}")
            elif t == "usage":
                summary.append(
                    f"usage: in={d.get('input_tokens',0)} out={d.get('output_tokens',0)} "
                    f"cost=${d.get('cost_usd',0):.4f}"
                )
            else:
                summary.append(f"{t}: {str(d)[:120]}")
        except Exception:
            summary.append(line[:120])
    return summary


@dataclass
class ChallengeSwarm:
    """Parallel solvers racing on one challenge."""

    challenge_dir: str
    meta: ChallengeMeta
    ctfd: CTFdClient
    cost_tracker: CostTracker
    settings: Settings
    model_specs: list[str] = field(default_factory=lambda: list(DEFAULT_MODELS))
    no_submit: bool = False
    coordinator_inbox: asyncio.Queue | None = None
    memory_store: MemoryStore | None = None

    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    solvers: dict[str, SolverProtocol] = field(default_factory=dict)
    findings: dict[str, str] = field(default_factory=dict)
    winner: SolverResult | None = None
    confirmed_flag: str | None = None
    _flag_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _submit_count: dict[str, int] = field(default_factory=dict)  # per-model wrong submission count
    _submitted_flags: set[str] = field(default_factory=set)  # dedup exact flags
    _last_submit_time: dict[str, float] = field(default_factory=dict)  # per-model last submit timestamp
    message_bus: ChallengeMessageBus = field(default_factory=ChallengeMessageBus)
    def _create_solver(self, model_spec: str):
        """Create the right solver type based on provider.

        - openai-compatible (CLIProxyAPI) → OpenAISolver
        """
        def _submit_fn(flag): return self.try_submit_flag(flag, model_spec)
        _notify = self._make_notify_fn(model_spec)

        from backend.agents.openai_solver import OpenAISolver
        return OpenAISolver(
            model_spec=model_spec,
            challenge_dir=self.challenge_dir,
            meta=self.meta,
            ctfd=self.ctfd,
            cost_tracker=self.cost_tracker,
            settings=self.settings,
            cancel_event=self.cancel_event,
            no_submit=self.no_submit,
            submit_fn=_submit_fn,
            message_bus=self.message_bus,
            notify_coordinator=_notify,
        )

    def _make_notify_fn(self, model_spec: str):
        """Create a callback that pushes solver messages to the coordinator inbox."""
        async def _notify(message: str) -> None:
            if self.coordinator_inbox:
                self.coordinator_inbox.put_nowait(
                    f"[{self.meta.name}/{model_spec}] {message}"
                )
        return _notify


    def _gather_sibling_insights(self, exclude_model: str) -> str:
        parts: list[str] = []
        for model, finding in self.findings.items():
            if model != exclude_model and finding:
                parts.append(f"[{model}]: {finding}")
        return "\n\n".join(parts) if parts else "No sibling insights available yet."

    # Escalating cooldowns after incorrect submissions (per model)
    SUBMISSION_COOLDOWNS = [0, 30, 120, 300, 600]  # 0s, 30s, 2min, 5min, 10min

    async def try_submit_flag(self, flag: str, model_spec: str) -> tuple[str, bool]:
        """Cooldown-gated, deduplicated flag submission. Returns (display, is_confirmed)."""
        async with self._flag_lock:
            if self.confirmed_flag:
                return f"ALREADY SOLVED — flag already confirmed: {self.confirmed_flag}", True

            normalized = flag.strip()

            # Dedup exact flags across all models
            if normalized in self._submitted_flags:
                return "INCORRECT — already tried this exact flag.", False

            # Escalating cooldown after incorrect submissions
            wrong_count = self._submit_count.get(model_spec, 0)
            cooldown_idx = min(wrong_count, len(self.SUBMISSION_COOLDOWNS) - 1)
            cooldown = self.SUBMISSION_COOLDOWNS[cooldown_idx]
            if cooldown > 0:
                last_time = self._last_submit_time.get(model_spec, 0)
                elapsed = time.monotonic() - last_time
                if elapsed < cooldown:
                    remaining = int(cooldown - elapsed)
                    return (
                        f"COOLDOWN — wait {remaining}s before submitting again. "
                        f"You have {wrong_count} incorrect submissions. "
                        "Use this time to do deeper analysis and verify your flag.",
                        False,
                    )

            self._submitted_flags.add(normalized)

            from backend.tools.core import do_submit_flag
            display, is_confirmed = await do_submit_flag(self.ctfd, self.meta.name, flag)
            if is_confirmed:
                self.confirmed_flag = normalized
            else:
                self._submit_count[model_spec] = wrong_count + 1
                self._last_submit_time[model_spec] = time.monotonic()
            return display, is_confirmed

    async def _run_solver(self, model_spec: str) -> SolverResult | None:
        solver = self._create_solver(model_spec)
        self.solvers[model_spec] = solver

        try:
            result, final_solver = await self._run_solver_loop(solver, model_spec)
            solver = final_solver
            return result
        except Exception as e:
            logger.error(f"[{self.meta.name}/{model_spec}] Fatal: {e}", exc_info=True)
            return None
        finally:
            await solver.stop()

    async def _run_solver_loop(self, solver, model_spec: str) -> tuple[SolverResult, SolverProtocol]:
        """Inner loop: start → run → bump → run → ..."""
        bump_count = 0
        consecutive_errors = 0
        result = SolverResult(
            flag=None, status=CANCELLED, findings_summary="",
            step_count=0, cost_usd=0.0, log_path="",
        )
        await solver.start()

        while not self.cancel_event.is_set():
            result = await solver.run_until_done_or_gave_up()

            # Only broadcast useful findings — skip errors and broken solvers
            if (result.status not in (ERROR, QUOTA_ERROR)
                    and not (result.step_count == 0 and result.cost_usd == 0)
                    and result.findings_summary
                    and not result.findings_summary.startswith(("Error:", "Turn failed:"))):
                self.findings[model_spec] = result.findings_summary
                await self.message_bus.post(model_spec, result.findings_summary[:500])

            if result.status == FLAG_FOUND:
                self._save_solution(result, model_spec)
                self.cancel_event.set()
                self.winner = result
                logger.info(
                    f"[{self.meta.name}] Flag found by {model_spec}: {result.flag}"
                )
                return result, solver

            if result.status == CANCELLED:
                break

            # Quota exhaustion: stop this solver (no fallback in CLIProxyAPI mode)
            if result.status == QUOTA_ERROR:
                self._write_rotation_summary(result, model_spec, reason="quota_exhausted")
                break

            # Context window full — reset message history with a handoff summary.
            # The Docker sandbox keeps running so all files and partial work are preserved.
            if result.status == CONTEXT_LIMIT:
                handoff = result.handoff_summary or result.findings_summary or "No summary available."
                self._write_rotation_summary(result, model_spec, reason="context_limit")
                logger.info(
                    "[%s/%s] Context limit reached — rotating to fresh context window (%d char summary)",
                    self.meta.name, model_spec, len(handoff),
                )
                solver.reset_with_handoff(handoff)
                bump_count = 0
                consecutive_errors = 0
                continue

            if result.status in (GAVE_UP, ERROR):
                self._write_rotation_summary(result, model_spec, reason=result.status)
                if result.step_count == 0 and result.cost_usd == 0:
                    logger.warning(
                        f"[{self.meta.name}/{model_spec}] Broken (0 steps, $0) — not bumping"
                    )
                    break

                # Track consecutive errors — stop after 3 in a row
                if result.status == ERROR:
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        logger.warning(
                            f"[{self.meta.name}/{model_spec}] {consecutive_errors} consecutive errors — giving up"
                        )
                        break
                else:
                    consecutive_errors = 0

                bump_count += 1
                # Cooldown between bumps — check cancellation during wait
                try:
                    await asyncio.wait_for(
                        self.cancel_event.wait(),
                        timeout=min(bump_count * 30, 300),
                    )
                    break  # cancelled during cooldown
                except TimeoutError:
                    pass  # cooldown elapsed, proceed with bump
                insights = self._gather_sibling_insights(model_spec)
                solver.bump(insights)
                logger.info(
                    f"[{self.meta.name}/{model_spec}] Bumped ({bump_count}), resuming"
                )
                continue

        return result, solver

    async def run(self) -> SolverResult | None:
        """Run all solvers in parallel. Returns the winner's result or None."""
        tasks = [
            asyncio.create_task(self._run_solver(spec), name=f"solver-{spec}")
            for spec in self.model_specs
        ]

        try:
            while tasks:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

                for task in done:
                    try:
                        result = task.result()
                    except Exception:
                        continue
                    if result and result.status == FLAG_FOUND:
                        self.cancel_event.set()
                        for p in pending:
                            p.cancel()
                        await asyncio.gather(*pending, return_exceptions=True)
                        return result

                tasks = list(pending)

            self.cancel_event.set()
            return self.winner
        except Exception as e:
            logger.error(f"[{self.meta.name}] Swarm error: {e}", exc_info=True)
            self.cancel_event.set()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            return None

    def _save_solution(self, result: SolverResult, model_spec: str) -> None:
        if not self.memory_store:
            return
        try:
            techniques = [text for text in self.findings.values() if text]
            techniques_worked = "\n".join(techniques) if techniques else (result.findings_summary or "")
            key_insight = result.findings_summary or f"Flag confirmed by {model_spec}"
            self.memory_store.save_solution(
                task_name=self.meta.name,
                ctf_name="",
                category=self.meta.category,
                techniques_worked=techniques_worked,
                techniques_failed="",
                key_insight=key_insight,
                flag=result.flag or "",
                writeup_path="",
            )
        except Exception as e:
            logger.warning("[%s] Memory save failed: %s", self.meta.name, e)

    def _write_rotation_summary(self, result: SolverResult, model_spec: str, reason: str) -> None:
        base_dir = Path(getattr(self.settings, "findings_dir", "findings"))
        task_dir = base_dir / f"task_{_safe_slug(self.meta.name)}" / f"agent_{_safe_slug(model_spec)}"
        try:
            task_dir.mkdir(parents=True, exist_ok=True)
            ts = int(time.time())
            summary_path = task_dir / f"summary_{ts}.md"
            lines: list[str] = [
                f"# Rotation Summary",
                f"task: {self.meta.name}",
                f"model: {model_spec}",
                f"reason: {reason}",
                f"status: {result.status}",
                "",
                "## Findings",
                result.findings_summary or "No findings summary.",
                "",
                "## Trace (last events)",
            ]
            if result.log_path:
                lines.extend(_summarize_trace(result.log_path, last_n=40))
            else:
                lines.append("No trace path available.")
            summary_path.write_text("\n".join(lines), encoding="utf-8")
            logger.info("[%s/%s] Rotation summary written: %s", self.meta.name, model_spec, summary_path)
        except Exception as e:
            logger.warning("[%s/%s] Failed to write rotation summary: %s", self.meta.name, model_spec, e)

    def kill(self) -> None:
        """Cancel all agents for this challenge."""
        self.cancel_event.set()

    def get_status(self) -> dict:
        """Get per-agent progress and findings."""
        return {
            "challenge": self.meta.name,
            "cancelled": self.cancel_event.is_set(),
            "winner": self.winner.flag if self.winner else None,
            "agents": {
                spec: {
                    "findings": self.findings.get(spec, ""),
                    "status": "running" if spec in self.solvers and not self.cancel_event.is_set()
                             else ("won" if self.winner and self.winner.flag else "finished"),
                }
                for spec in self.model_specs
            },
        }
