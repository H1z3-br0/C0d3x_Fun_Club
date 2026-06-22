"""Regression tests for flag-confirmation: a rejected flag must NOT count as a win.

Guards the bug where `"CORRECT" in "INCORRECT — ... rejected"` marked a rejected
submission as confirmed and stopped the swarm as if solved.
"""

from backend.agents.openai_solver import OpenAISolver
from backend.cost_tracker import CostTracker
from backend.prompts import ChallengeMeta


class _FakeSandbox:
    pass


def _solver(submit_fn) -> OpenAISolver:
    return OpenAISolver(
        model_spec="codex/gpt-5.5",
        challenge_dir=".",
        meta=ChallengeMeta(name="t"),
        ctfd=None,
        cost_tracker=CostTracker(),
        settings=object(),
        sandbox=_FakeSandbox(),
        submit_fn=submit_fn,
    )


async def test_rejected_flag_not_confirmed():
    async def submit_fn(flag):
        return f'INCORRECT — "{flag}" rejected.', False  # contains substring "CORRECT"

    solver = _solver(submit_fn)
    display = await solver._dispatch_tool("submit_flag", {"flag": "flag{x}"})
    assert "INCORRECT" in display
    assert solver._confirmed is False
    assert solver._flag is None


async def test_correct_flag_confirmed():
    async def submit_fn(flag):
        return f'CORRECT — "{flag}" accepted.', True

    solver = _solver(submit_fn)
    await solver._dispatch_tool("submit_flag", {"flag": "flag{win}"})
    assert solver._confirmed is True
    assert solver._flag == "flag{win}"


async def test_bump_resets_step_count():
    """A bumped solver must get a fresh step budget (else it instantly re-hits the cap)."""
    solver = _solver(submit_fn=None)
    solver._step_count = 999
    solver.bump("try harder")
    assert solver._step_count == 0
