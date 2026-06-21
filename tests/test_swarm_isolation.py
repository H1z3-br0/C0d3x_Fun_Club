"""C2: per-model workspace isolation, with shared sandbox + shared message bus."""

from backend.agents.swarm import ChallengeSwarm
from backend.cost_tracker import CostTracker
from backend.prompts import ChallengeMeta


class _FakeCTFd:
    pass


def _swarm():
    return ChallengeSwarm(
        challenge_dir=".",
        meta=ChallengeMeta(name="t"),
        ctfd=_FakeCTFd(),
        cost_tracker=CostTracker(),
        settings=object(),
        model_specs=["codex/gpt-5.5", "claude/claude-opus-4-8"],
    )


def test_each_model_gets_its_own_workdir():
    swarm = _swarm()
    s1 = swarm._create_solver("codex/gpt-5.5")
    s2 = swarm._create_solver("claude/claude-opus-4-8")
    assert s1.work_dir == "/challenge/workspace/gpt-5.5"
    assert s2.work_dir == "/challenge/workspace/claude-opus-4-8"
    assert s1.work_dir != s2.work_dir  # no clobbering between models


def test_models_share_sandbox_and_message_bus():
    swarm = _swarm()
    s1 = swarm._create_solver("codex/gpt-5.5")
    s2 = swarm._create_solver("claude/claude-opus-4-8")
    # One container per challenge...
    assert s1.sandbox is s2.sandbox is swarm.sandbox
    # ...and shared cross-model context (findings/bumps) via the message bus.
    assert s1.message_bus is s2.message_bus is swarm.message_bus
