from __future__ import annotations

from pathlib import Path

import pytest

from ctf_swarm.config import (
    AccountsConfig,
    AppConfig,
    CTFConfig,
    EndpointConfig,
    LimitsConfig,
    PathsConfig,
    PoolConfig,
    RunArgs,
    SandboxConfig,
)
from ctf_swarm.orchestrator import SwarmOrchestrator
from ctf_swarm.schemas import Hypothesis, TaskSpec
from ctf_swarm.state import create_initial_snapshot


def make_config() -> AppConfig:
    return AppConfig(
        cliproxyapi=EndpointConfig(),
        accounts=AccountsConfig(
            cc_master=PoolConfig(model="claude-code", emails=["cc1@example.com"]),
            cc_support=PoolConfig(model="claude-code", emails=["cc2@example.com"]),
            smart_reserve=PoolConfig(
                model="codex",
                emails=["s1@example.com", "s2@example.com", "s3@example.com", "s4@example.com"],
            ),
            executors=PoolConfig(model="codex", emails=["w1@example.com", "w2@example.com"]),
        ),
        limits=LimitsConfig(),
        sandbox=SandboxConfig(),
        ctf=CTFConfig(flag_format="CTF{...}"),
        paths=PathsConfig(workspace_root="workspace-test"),
    )


def make_args(task_dir: str | None = None) -> RunArgs:
    return RunArgs(
        mode="single",
        task_dir=task_dir,
        config_path="config.yaml",
        flag_format="CTF{...}",
        ctfd_url=None,
        ctfd_token=None,
        ctfd_session=None,
        resume=False,
    )


def test_next_hypothesis_id_skips_existing_ids(tmp_path: Path) -> None:
    orchestrator = SwarmOrchestrator(make_config(), make_args(str(tmp_path)), tmp_path)
    task = orchestrator._make_task_state(
        TaskSpec(
            task_id="demo",
            name="demo",
            task_dir=str(tmp_path),
            description="demo",
            source="local",
        )
    )
    task.hypotheses.append(
        Hypothesis(
            hypothesis_id="hyp-001",
            title="a",
            rationale="a",
            plan=["a"],
            priority=1,
        )
    )
    task.dead_hypotheses.append(
        Hypothesis(
            hypothesis_id="hyp-002",
            title="b",
            rationale="b",
            plan=["b"],
            priority=1,
        )
    )

    assert orchestrator._next_hypothesis_id(task) == "hyp-003"


def test_finalize_cancelled_hypothesis_moves_to_dead_when_not_requeue(tmp_path: Path) -> None:
    orchestrator = SwarmOrchestrator(make_config(), make_args(str(tmp_path)), tmp_path)
    task = orchestrator._make_task_state(
        TaskSpec(
            task_id="demo",
            name="demo",
            task_dir=str(tmp_path),
            description="demo",
            source="local",
        )
    )
    hypothesis = Hypothesis(
        hypothesis_id="hyp-001",
        title="test",
        rationale="why",
        plan=["step"],
        priority=50,
        status="running",
    )
    task.hypotheses.append(hypothesis)
    task.status = "running"
    orchestrator.tasks[task.spec.task_id] = task

    orchestrator._finalize_cancelled_hypothesis(
        task.spec.task_id, hypothesis.hypothesis_id, "killed", requeue=False
    )

    assert not task.hypotheses
    assert task.dead_hypotheses[0].status == "dead"
    assert task.dead_hypotheses[0].last_summary == "killed"
    assert task.status == "pending"


def test_save_state_persists_worker_counter(tmp_path: Path) -> None:
    orchestrator = SwarmOrchestrator(make_config(), make_args(str(tmp_path)), tmp_path)
    task = orchestrator._make_task_state(
        TaskSpec(
            task_id="demo",
            name="demo",
            task_dir=str(tmp_path),
            description="demo",
            source="local",
        )
    )
    orchestrator.tasks[task.spec.task_id] = task
    orchestrator.worker_counter = 7
    orchestrator.snapshot = create_initial_snapshot(
        "single",
        orchestrator.tasks,
        orchestrator.roles,
        worker_counter=orchestrator.worker_counter,
    )

    orchestrator._save_state(force=True)
    restored = orchestrator.state_store.load()

    assert restored.worker_counter == 7


def test_log_caps_event_log(tmp_path: Path) -> None:
    config = make_config()
    config.limits.event_log_max_entries = 2
    orchestrator = SwarmOrchestrator(config, make_args(str(tmp_path)), tmp_path)
    task = orchestrator._make_task_state(
        TaskSpec(
            task_id="demo",
            name="demo",
            task_dir=str(tmp_path),
            description="demo",
            source="local",
        )
    )
    orchestrator.tasks[task.spec.task_id] = task
    orchestrator.snapshot = create_initial_snapshot("single", orchestrator.tasks, orchestrator.roles)

    orchestrator._log("one")
    orchestrator._log("two")
    orchestrator._log("three")

    assert len(orchestrator.snapshot.event_log) == 2
    assert orchestrator.snapshot.event_log[-1].endswith("three")


@pytest.mark.asyncio
async def test_apply_master_plan_persists_profile_on_hypothesis(tmp_path: Path) -> None:
    orchestrator = SwarmOrchestrator(make_config(), make_args(str(tmp_path)), tmp_path)
    task = orchestrator._make_task_state(
        TaskSpec(
            task_id="demo",
            name="demo",
            task_dir=str(tmp_path),
            description="demo",
            source="local",
        )
    )

    await orchestrator._apply_master_plan(
        task,
        {
            "analysis": "analysis",
            "task_summary": "summary",
            "network_required": False,
            "focus_recommendation": "focus",
            "cancel_hypotheses": [],
            "new_hypotheses": [
                {
                    "title": "check http",
                    "rationale": "web-ish",
                    "plan": ["curl", "ffuf"],
                    "priority": 80,
                    "profile": "web",
                    "network_required": True,
                    "tools": ["shell"],
                }
            ],
            "notes_for_support": "",
            "notes_for_user": "",
        },
    )

    assert task.hypotheses[0].profile == "web"
