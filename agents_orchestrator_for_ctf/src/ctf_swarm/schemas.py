from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TaskSpec:
    task_id: str
    name: str
    task_dir: str
    description: str
    source: str
    points: int | None = None
    url: str | None = None
    host: str | None = None
    port: int | None = None
    category: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TaskSpec:
        return cls(**payload)


@dataclass
class Hypothesis:
    hypothesis_id: str
    title: str
    rationale: str
    plan: list[str]
    priority: int
    profile: str = "base"
    network_required: bool = False
    tools: list[str] = field(default_factory=lambda: ["shell"])
    status: str = "pending"
    attempts: int = 0
    last_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Hypothesis:
        return cls(**payload)


@dataclass
class Finding:
    source: str
    summary: str
    evidence: list[str]
    artifacts: list[str]
    flag: str | None = None
    confidence: int = 0
    validated: bool = False
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Finding:
        return cls(**payload)


@dataclass
class TaskState:
    spec: TaskSpec
    status: str = "pending"
    priority_score: float = 0.0
    master_notes: str = ""
    support_notes: str = ""
    memory_hits: list[dict[str, Any]] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    dead_hypotheses: list[Hypothesis] = field(default_factory=list)
    completed_hypotheses: list[Hypothesis] = field(default_factory=list)
    flag: str | None = None
    flag_confidence: int | None = None
    writeup_path: str | None = None
    artifact_dir: str = ""
    network_required: bool = False
    last_plan_at: str | None = None
    rotation_summaries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec.to_dict(),
            "status": self.status,
            "priority_score": self.priority_score,
            "master_notes": self.master_notes,
            "support_notes": self.support_notes,
            "memory_hits": self.memory_hits,
            "hints": self.hints,
            "findings": [finding.to_dict() for finding in self.findings],
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "dead_hypotheses": [item.to_dict() for item in self.dead_hypotheses],
            "completed_hypotheses": [item.to_dict() for item in self.completed_hypotheses],
            "flag": self.flag,
            "flag_confidence": self.flag_confidence,
            "writeup_path": self.writeup_path,
            "artifact_dir": self.artifact_dir,
            "network_required": self.network_required,
            "last_plan_at": self.last_plan_at,
            "rotation_summaries": self.rotation_summaries,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TaskState:
        return cls(
            spec=TaskSpec.from_dict(payload["spec"]),
            status=payload.get("status", "pending"),
            priority_score=payload.get("priority_score", 0.0),
            master_notes=payload.get("master_notes", ""),
            support_notes=payload.get("support_notes", ""),
            memory_hits=payload.get("memory_hits", []),
            hints=payload.get("hints", []),
            findings=[Finding.from_dict(item) for item in payload.get("findings", [])],
            hypotheses=[Hypothesis.from_dict(item) for item in payload.get("hypotheses", [])],
            dead_hypotheses=[Hypothesis.from_dict(item) for item in payload.get("dead_hypotheses", [])],
            completed_hypotheses=[Hypothesis.from_dict(item) for item in payload.get("completed_hypotheses", [])],
            flag=payload.get("flag"),
            flag_confidence=payload.get("flag_confidence"),
            writeup_path=payload.get("writeup_path"),
            artifact_dir=payload.get("artifact_dir", ""),
            network_required=payload.get("network_required", False),
            last_plan_at=payload.get("last_plan_at"),
            rotation_summaries=payload.get("rotation_summaries", []),
        )


@dataclass
class WorkerCommand:
    cmd: str
    reason: str
    timeout_seconds: int
    workdir: str = "/workspace/task"


@dataclass
class WorkerResult:
    status: str
    summary: str
    evidence: list[str]
    artifacts: list[str]
    flag: str | None = None
    confidence: int = 0


@dataclass
class WorkerExecution:
    worker_id: str
    task_id: str
    hypothesis_id: str
    started_at: str
    container_name: str
    profile: str
    image: str
    network_enabled: bool
    transient_images: list[str] = field(default_factory=list)


@dataclass
class RoleUsage:
    total_tokens: int = 0
    request_count: int = 0
    step_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RoleUsage:
        return cls(**payload)
