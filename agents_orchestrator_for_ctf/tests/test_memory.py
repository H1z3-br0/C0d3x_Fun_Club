from __future__ import annotations

from pathlib import Path

from ctf_swarm.memory import MemoryStore
from ctf_swarm.schemas import Finding, Hypothesis, TaskSpec, TaskState


def test_memory_store_save_and_search(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    task = TaskState(
        spec=TaskSpec(
            task_id="heap-task",
            name="heap task",
            task_dir=str(tmp_path),
            description="heap exploitation task",
            source="local",
            category="pwn",
        ),
        artifact_dir=str(tmp_path / "artifacts"),
        flag="CTF{heap}",
        completed_hypotheses=[
            Hypothesis(
                hypothesis_id="hyp-001",
                title="tcache poisoning",
                rationale="classic heap path",
                plan=["check bins"],
                priority=90,
                last_summary="tcache poisoning worked",
            )
        ],
        dead_hypotheses=[
            Hypothesis(
                hypothesis_id="hyp-002",
                title="format string",
                rationale="fallback",
                plan=["try printf"],
                priority=20,
                last_summary="did not work",
            )
        ],
        findings=[
            Finding(
                source="cx-01",
                summary="used tcache poisoning to overwrite hook",
                evidence=["malloc trace"],
                artifacts=[],
                flag="CTF{heap}",
                validated=True,
            )
        ],
    )

    store.save_solution(task)
    hits = store.search("tcache")
    store.close()

    assert hits
    assert hits[0]["task_name"] == "heap task"
