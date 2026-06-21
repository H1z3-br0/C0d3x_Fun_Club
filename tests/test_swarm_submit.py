"""Behaviour tests for the swarm's dedup + cooldown-gated flag submission."""

from dataclasses import dataclass

from backend.agents.swarm import ChallengeSwarm
from backend.cost_tracker import CostTracker
from backend.ctfd import SubmitResult
from backend.prompts import ChallengeMeta


@dataclass
class FakeCTFd:
    status: str = "incorrect"
    calls: int = 0

    async def submit_flag(self, name: str, flag: str) -> SubmitResult:
        self.calls += 1
        return SubmitResult(self.status, "", f"{self.status.upper()} {flag}")


def _swarm(ctfd) -> ChallengeSwarm:
    return ChallengeSwarm(
        challenge_dir=".",
        meta=ChallengeMeta(name="t"),
        ctfd=ctfd,
        cost_tracker=CostTracker(),
        settings=object(),
        model_specs=["codex/gpt-5.5"],
    )


async def test_exact_duplicate_flag_not_resubmitted():
    ctfd = FakeCTFd(status="incorrect")
    swarm = _swarm(ctfd)
    _, ok1 = await swarm.try_submit_flag("flag{a}", "codex/gpt-5.5")
    display2, ok2 = await swarm.try_submit_flag("flag{a}", "codex/gpt-5.5")
    assert ok1 is False and ok2 is False
    assert "already tried" in display2.lower()
    assert ctfd.calls == 1  # second never hit CTFd


async def test_cooldown_after_wrong_submission():
    ctfd = FakeCTFd(status="incorrect")
    swarm = _swarm(ctfd)
    await swarm.try_submit_flag("flag{a}", "codex/gpt-5.5")  # 1st wrong → no cooldown
    display, ok = await swarm.try_submit_flag("flag{b}", "codex/gpt-5.5")  # 2nd → cooldown
    assert ok is False
    assert "cooldown" in display.lower()
    assert ctfd.calls == 1  # blocked before hitting CTFd


async def test_confirmed_flag_short_circuits():
    ctfd = FakeCTFd(status="correct")
    swarm = _swarm(ctfd)
    _, ok = await swarm.try_submit_flag("flag{win}", "codex/gpt-5.5")
    assert ok is True
    assert swarm.confirmed_flag == "flag{win}"
    display, ok2 = await swarm.try_submit_flag("flag{other}", "claude/claude-opus-4-8")
    assert ok2 is True
    assert "already solved" in display.lower()
    assert ctfd.calls == 1  # no further CTFd calls once confirmed
