from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schemas import RoleUsage, TaskState
from .utils import ensure_dir, utc_now


@dataclass
class RoleState:
    role: str
    labels: list[str]
    stage_index: int = 0
    usage: RoleUsage = field(default_factory=RoleUsage)
    last_rotation_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "labels": self.labels,
            "stage_index": self.stage_index,
            "usage": self.usage.to_dict(),
            "last_rotation_reason": self.last_rotation_reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RoleState:
        return cls(
            role=payload["role"],
            labels=payload["labels"],
            stage_index=payload.get("stage_index", 0),
            usage=RoleUsage.from_dict(payload.get("usage", {})),
            last_rotation_reason=payload.get("last_rotation_reason", ""),
        )


@dataclass
class RunSnapshot:
    mode: str
    created_at: str
    updated_at: str
    active_task_id: str | None
    tasks: dict[str, TaskState]
    roles: dict[str, RoleState]
    worker_counter: int = 0
    event_log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "active_task_id": self.active_task_id,
            "tasks": {task_id: task.to_dict() for task_id, task in self.tasks.items()},
            "roles": {name: role.to_dict() for name, role in self.roles.items()},
            "worker_counter": self.worker_counter,
            "event_log": self.event_log,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunSnapshot:
        return cls(
            mode=payload["mode"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            active_task_id=payload.get("active_task_id"),
            tasks={task_id: TaskState.from_dict(item) for task_id, item in payload.get("tasks", {}).items()},
            roles={name: RoleState.from_dict(item) for name, item in payload.get("roles", {}).items()},
            worker_counter=int(payload.get("worker_counter", 0)),
            event_log=payload.get("event_log", []),
        )


class StateStore:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = ensure_dir(workspace_root)
        self.state_dir = ensure_dir(self.workspace_root / "state")
        self.snapshot_path = self.state_dir / "session.json"

    def save(self, snapshot: RunSnapshot) -> Path:
        snapshot.updated_at = utc_now()
        self.snapshot_path.write_text(
            json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.snapshot_path

    def exists(self) -> bool:
        return self.snapshot_path.exists()

    def load(self) -> RunSnapshot:
        payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        return RunSnapshot.from_dict(payload)

    def append_event(self, message: str) -> None:
        events_path = self.state_dir / "events.log"
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")


def create_initial_snapshot(
    mode: str,
    tasks: dict[str, TaskState],
    roles: dict[str, RoleState],
    worker_counter: int = 0,
) -> RunSnapshot:
    now = utc_now()
    return RunSnapshot(
        mode=mode,
        created_at=now,
        updated_at=now,
        active_task_id=next(iter(tasks.keys()), None),
        tasks=tasks,
        roles=roles,
        worker_counter=worker_counter,
        event_log=[],
    )
