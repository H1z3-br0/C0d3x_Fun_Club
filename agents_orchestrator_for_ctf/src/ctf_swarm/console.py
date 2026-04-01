from __future__ import annotations

import asyncio
import select
import shlex
import signal
import sys
from typing import Any

from .schemas import WorkerExecution
from .state import RoleState


class ConsoleController:
    def __init__(self) -> None:
        self.sigint_requested = False
        self._previous_sigint_handler = None

    def install(self) -> None:
        self._previous_sigint_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._on_sigint)

    def restore(self) -> None:
        if self._previous_sigint_handler is not None:
            signal.signal(signal.SIGINT, self._previous_sigint_handler)

    def _on_sigint(self, signum, frame) -> None:  # pragma: no cover
        self.sigint_requested = True

    async def poll_command(self, timeout: float = 0.2) -> dict[str, Any] | None:
        line = await asyncio.to_thread(self._readline_nonblocking, timeout)
        if line is None:
            return None
        stripped = line.strip()
        if not stripped:
            return None
        return self._parse_command(stripped)

    def _readline_nonblocking(self, timeout: float) -> str | None:
        try:
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
        except (ValueError, OSError):  # pragma: no cover
            return None
        if not ready:
            return None
        return sys.stdin.readline()

    async def sigint_menu(self, task_options: list[str]) -> dict[str, str]:
        print(
            "\n[1] продолжить\n[2] дать указание CC1\n[3] сменить активный таск\n[4] выход с сохранением состояния",
            flush=True,
        )
        choice = (await asyncio.to_thread(input, "> ")).strip()
        if choice == "1":
            return {"action": "continue"}
        if choice == "2":
            message = (await asyncio.to_thread(input, "Сообщение CC1: ")).strip()
            return {"action": "interrupt", "message": message}
        if choice == "3":
            print("Доступные таски:", flush=True)
            for item in task_options:
                print(f"- {item}", flush=True)
            target = (await asyncio.to_thread(input, "Task id/name: ")).strip()
            return {"action": "switch_task", "target": target}
        return {"action": "exit"}

    def render_status(
        self,
        *,
        active_task_id: str | None,
        task_rows: list[str],
        active_workers: dict[str, WorkerExecution],
        roles: dict[str, RoleState],
    ) -> str:
        role_rows = [
            f"{name}: {state.labels[min(state.stage_index, len(state.labels) - 1)]} | "
            f"tokens={state.usage.total_tokens} requests={state.usage.request_count} steps={state.usage.step_count}"
            for name, state in roles.items()
        ]
        worker_rows = [
            f"{worker_id}: task={execution.task_id} hyp={execution.hypothesis_id} container={execution.container_name}"
            for worker_id, execution in active_workers.items()
        ]
        if not worker_rows:
            worker_rows.append("нет активных воркеров")
        return "\n".join(
            [
                "=== STATUS ===",
                f"active_task={active_task_id or '-'}",
                "tasks:",
                *task_rows,
                "roles:",
                *role_rows,
                "workers:",
                *worker_rows,
            ]
        )

    def _parse_command(self, line: str) -> dict[str, Any]:
        if line.startswith("/hint"):
            return {"action": "hint", "message": _tail_message(line, "/hint")}
        if line.startswith("/interrupt"):
            return {"action": "interrupt", "message": _tail_message(line, "/interrupt")}
        if line.startswith("/kill"):
            parts = shlex.split(line)
            if len(parts) < 2:
                raise ValueError("Использование: /kill cx-04")
            return {"action": "kill", "worker_id": parts[1]}
        if line == "/status":
            return {"action": "status"}
        if line == "/skip":
            return {"action": "skip"}
        return {"action": "hint", "message": line}


def _tail_message(line: str, prefix: str) -> str:
    message = line[len(prefix) :].strip()
    if not message:
        raise ValueError(f"Команда {prefix} требует текст")
    return message.strip().strip('"')
