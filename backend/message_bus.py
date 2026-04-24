"""Per-challenge message bus for inter-agent communication."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class Finding:
    model: str
    content: str
    # tag distinguishes different kinds of posts:
    #   "progress" — mid-run status update (posted every N steps)
    #   "summary"  — final findings summary after a solver loop iteration
    #   "coordinator" — broadcast from the coordinator
    tag: str = "progress"
    timestamp: float = field(default_factory=time.time)


MAX_FINDINGS = 200


@dataclass
class ChallengeMessageBus:
    """Append-only shared findings list with per-model cursors."""

    findings: list[Finding] = field(default_factory=list)
    cursors: dict[str, int] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def post(self, model: str, content: str, tag: str = "progress") -> None:
        """Post a finding from a solver."""
        async with self._lock:
            self.findings.append(Finding(model=model, content=content, tag=tag))
            if len(self.findings) > MAX_FINDINGS:
                trim = len(self.findings) - MAX_FINDINGS
                self.findings = self.findings[trim:]
                self.cursors = {k: max(0, v - trim) for k, v in self.cursors.items()}

    async def check(self, model: str) -> list[Finding]:
        """Get unread findings from other models. Advances the cursor."""
        async with self._lock:
            cursor = self.cursors.get(model, 0)
            unread = [f for f in self.findings[cursor:] if f.model != model]
            self.cursors[model] = len(self.findings)
            return unread

    async def broadcast(self, content: str, source: str = "coordinator") -> None:
        """Coordinator broadcasts a message to all solvers."""
        await self.post(source, content, tag="coordinator")

    async def latest_by_model(
        self,
        *,
        exclude: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Finding]:
        """Return the most recent Finding per model, optionally filtered by tag.

        Used to gather sibling insights for a bump without touching cursors.
        """
        async with self._lock:
            latest: dict[str, Finding] = {}
            for f in self.findings:
                if exclude is not None and f.model == exclude:
                    continue
                if tag is not None and f.tag != tag:
                    continue
                latest[f.model] = f  # later overwrites earlier → newest wins
            return latest

    def format_unread(self, findings: list[Finding]) -> str:
        """Format findings for injection into a solver prompt."""
        if not findings:
            return ""
        parts = [f"[{f.model}] {f.content}" for f in findings]
        return "**Findings from other agents:**\n\n" + "\n\n".join(parts)
