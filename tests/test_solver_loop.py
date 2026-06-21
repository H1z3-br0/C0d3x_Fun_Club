"""Integration tests for the solver agentic loop + stream aggregation.

Exercises the real `run_until_done_or_gave_up` loop end-to-end with a fake LLM
client and a fake sandbox — no Docker, no network. This is the highest-risk code
path (tool dispatch, confirmation, workdir threading) and was previously untested.
"""

from types import SimpleNamespace

from backend.agents.openai_solver import OpenAISolver, _aggregate_stream
from backend.cost_tracker import CostTracker
from backend.prompts import ChallengeMeta
from backend.sandbox import ExecResult
from backend.solver_base import FLAG_FOUND, GAVE_UP

# --- fakes ------------------------------------------------------------------

def _tc(index, tc_id, name, arguments):
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=tc_id, function=fn)


def _chunk(content=None, tool_calls=None, finish_reason=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


async def _stream(chunks):
    for c in chunks:
        yield c


class _FakeCompletions:
    def __init__(self, scripts):
        self._scripts = list(scripts)
        self._i = 0

    async def create(self, **kwargs):
        chunks = self._scripts[min(self._i, len(self._scripts) - 1)]
        self._i += 1
        return _stream(chunks)


class _FakeClient:
    def __init__(self, scripts):
        self.chat = SimpleNamespace(completions=_FakeCompletions(scripts))


class _FakeSandbox:
    def __init__(self):
        self.exec_calls = []
        self._container = object()

    async def exec(self, command, timeout_s=300, workdir=None):
        self.exec_calls.append((command, workdir))
        return ExecResult(exit_code=0, stdout="hello", stderr="")


def _make_solver(scripts, submit_fn=None):
    solver = OpenAISolver(
        model_spec="codex/gpt-5.5",
        challenge_dir=".",
        meta=ChallengeMeta(name="t"),
        ctfd=None,
        cost_tracker=CostTracker(),
        settings=object(),
        sandbox=_FakeSandbox(),
        submit_fn=submit_fn,
    )
    # Bypass start() (no Docker / no real client): inject the fake client + state.
    solver._client = _FakeClient(scripts)
    solver._llm_timeout = 600.0
    solver._messages = [{"role": "system", "content": "sys"}]
    return solver


# --- stream aggregation -----------------------------------------------------

async def test_aggregate_stream_reconstructs_content_and_tool_call():
    chunks = [
        _chunk(content="Hel"),
        _chunk(content="lo"),
        _chunk(tool_calls=[_tc(0, "call_1", "bash", '{"command":')]),
        _chunk(tool_calls=[_tc(0, None, None, ' "ls"}')]),
        _chunk(finish_reason="tool_calls",
               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)),
    ]
    resp = await _aggregate_stream(_stream(chunks))
    msg = resp.choices[0].message
    assert msg.content == "Hello"
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0].function.name == "bash"
    assert msg.tool_calls[0].function.arguments == '{"command": "ls"}'
    assert resp.usage.prompt_tokens == 10


# --- full loop --------------------------------------------------------------

async def test_loop_solves_via_bash_then_submit():
    async def submit_fn(flag):
        return f'CORRECT — "{flag}" accepted.', True

    scripts = [
        # turn 1: run a bash command
        [_chunk(tool_calls=[_tc(0, "c1", "bash", '{"command":"echo hi"}')], finish_reason="tool_calls")],
        # turn 2: submit the flag
        [_chunk(tool_calls=[_tc(0, "c2", "submit_flag", '{"flag":"flag{win}"}')], finish_reason="tool_calls")],
    ]
    solver = _make_solver(scripts, submit_fn=submit_fn)
    result = await solver.run_until_done_or_gave_up()

    assert result.status == FLAG_FOUND
    assert result.flag == "flag{win}"
    # bash was dispatched into THIS model's private workdir (C2 isolation)
    bash_call = next(c for c in solver.sandbox.exec_calls if "echo hi" in c[0])
    assert bash_call[1] == solver.work_dir


async def test_loop_gives_up_on_text_only_response():
    scripts = [[_chunk(content="I cannot solve this.", finish_reason="stop")]]
    solver = _make_solver(scripts)
    result = await solver.run_until_done_or_gave_up()
    assert result.status == GAVE_UP
    assert solver._confirmed is False
