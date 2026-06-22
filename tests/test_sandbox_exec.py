"""DockerSandbox.exec workdir-wrapping (C2), without a real Docker daemon."""

from backend.sandbox import DockerSandbox


class _FakeStream:
    async def read_out(self):
        return None

    async def close(self):
        pass


class _FakeExecInstance:
    def start(self, detach=False):
        return _FakeStream()

    async def inspect(self):
        return {"ExitCode": 0}


class _FakeContainer:
    def __init__(self):
        self.last_wrapped = None

    async def exec(self, cmd, stdout, stderr, tty):
        # cmd == ["bash", "-c", wrapped]
        self.last_wrapped = cmd[2]
        return _FakeExecInstance()


def _sandbox():
    sb = DockerSandbox(image="ctf-swarm:base", challenge_dir=".")
    sb._container = _FakeContainer()
    return sb


async def test_workdir_is_cd_into():
    sb = _sandbox()
    await sb.exec("ls -la", timeout_s=30, workdir="/challenge/workspace/gpt-5.5")
    wrapped = sb._container.last_wrapped
    assert "/challenge/workspace/gpt-5.5" in wrapped
    assert "cd " in wrapped


async def test_no_workdir_no_cd():
    sb = _sandbox()
    await sb.exec("ls -la", timeout_s=30)
    wrapped = sb._container.last_wrapped
    assert "/challenge/workspace" not in wrapped
