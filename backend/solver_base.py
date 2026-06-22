"""Solver result type, status constants, and solver protocol — shared across all backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

# Status constants
FLAG_FOUND = "flag_found"
GAVE_UP = "gave_up"
CANCELLED = "cancelled"
ERROR = "error"
QUOTA_ERROR = "quota_error"
CONTEXT_LIMIT = "context_limit"  # Context window nearly full — rotate to fresh agent
# NOTE: flag confirmation is a boolean from CTFdClient.submit_flag (status check),
# never a substring match on the display string ("CORRECT" is inside "INCORRECT").


@dataclass
class SolverResult:
    flag: str | None
    status: str
    findings_summary: str
    step_count: int
    cost_usd: float
    log_path: str
    handoff_summary: str | None = None  # Compressed context briefing for the next agent


class SolverProtocol(Protocol):
    """Common interface implemented by the OpenAI-compatible solver."""

    model_spec: str
    agent_name: str
    sandbox: Any

    async def start(self) -> None: ...
    async def run_until_done_or_gave_up(self) -> SolverResult: ...
    def bump(self, insights: str) -> None: ...
    def reset_with_handoff(self, summary: str) -> None: ...
    async def stop(self) -> None: ...
