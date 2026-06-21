"""Docker sandbox for CTF challenge solving — native async via aiodocker."""

from __future__ import annotations

import asyncio
import io
import logging
import shlex
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiodocker

logger = logging.getLogger(__name__)

CONTAINER_LABEL = "ctf-agent"

# Single shared sandbox image. Heavy/specialised tooling is installed on demand
# from inside the container via `ctf-install` rather than baked into per-category images.
DEFAULT_SANDBOX_IMAGE = "ctf-swarm:base"

# Concurrency control
_start_semaphore: asyncio.Semaphore | None = None
_active_count: int = 0
_count_lock = asyncio.Lock()

_WARN_THRESHOLDS = {100, 200, 500}


def configure_semaphore(max_concurrent: int = 50) -> None:
    """Set the max concurrent container starts. Call once at startup."""
    global _start_semaphore
    _start_semaphore = asyncio.Semaphore(max_concurrent)


async def _track_start() -> None:
    global _active_count
    async with _count_lock:
        _active_count += 1
        if _active_count in _WARN_THRESHOLDS:
            logger.warning("Active containers: %d", _active_count)


async def _track_stop() -> None:
    global _active_count
    async with _count_lock:
        _active_count = max(0, _active_count - 1)


async def cleanup_orphan_containers() -> None:
    """Reap leftover ctf-agent containers that are NOT running.

    Only stopped/exited/dead containers are removed — never a *running* one, so a
    second instance of this project started while a first is live won't kill the
    first's active containers. (A live swarm always stops its own container in
    `finally`; a truly crashed run leaves a stopped/exited container that this reaps.)
    """
    try:
        docker = aiodocker.Docker()
        try:
            # status filter excludes "running" (and "paused", which we also leave alone).
            containers = await docker.containers.list(
                all=True,
                filters={
                    "label": [CONTAINER_LABEL],
                    "status": ["created", "exited", "dead", "restarting", "removing"],
                },
            )
            removed = 0
            for c in containers:
                try:
                    await c.delete(force=True)
                    removed += 1
                except Exception:
                    pass
            if removed:
                logger.info("Cleaned up %d stopped orphan container(s)", removed)
        finally:
            await docker.close()
    except Exception as e:
        logger.warning("Orphan cleanup failed: %s", e)


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass
class DockerSandbox:
    """One Docker container, shared by every solver model working a challenge.

    `exec`/`read_file`/`write_file` run concurrently — Docker handles multiple exec
    sessions on one container fine. Only container restarts are serialised (via
    `_restart_lock`) so a simultaneous "container gone" from several solvers doesn't
    recreate it more than once.
    """

    image: str
    challenge_dir: str
    memory_limit: str = "16g"
    workspace_dir: str = ""
    _container: Any = field(default=None, repr=False)
    _docker: Any = field(default=None, repr=False)
    _restart_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _binds: list[str] = field(default_factory=list, repr=False)
    _restart_count: int = field(default=0, repr=False)

    MAX_RESTARTS = 3

    @property
    def container_id(self) -> str:
        """The Docker container ID, available after start()."""
        if not self._container:
            raise RuntimeError("Sandbox not started")
        return self._container.id

    def _container_config(self) -> dict[str, Any]:
        """Docker create() config. Single source of truth for start() and restart."""
        return {
            "Image": self.image,
            "Cmd": ["sleep", "infinity"],
            "WorkingDir": "/challenge/workspace",
            "Tty": False,
            "Labels": {CONTAINER_LABEL: "true"},
            "HostConfig": {
                "Binds": self._binds,
                "ExtraHosts": ["host.docker.internal:host-gateway"],
                "CapAdd": ["SYS_ADMIN", "SYS_PTRACE"],
                "SecurityOpt": ["seccomp=unconfined"],
                "Devices": [{"PathOnHost": "/dev/loop-control", "PathInContainer": "/dev/loop-control", "CgroupPermissions": "rwm"}],
                "Memory": self._parse_memory_limit(),
                "NanoCpus": int(2 * 1e9),
            },
        }

    def _parse_memory_limit(self) -> int:
        s = self.memory_limit.strip().lower()
        try:
            if s.endswith("g"):
                return int(s[:-1]) * 1024 * 1024 * 1024
            if s.endswith("m"):
                return int(s[:-1]) * 1024 * 1024
            return int(s)
        except (ValueError, IndexError):
            logger.warning("Invalid memory_limit %r, defaulting to 4GB", self.memory_limit)
            return 4 * 1024 * 1024 * 1024

    async def start(self) -> None:
        sem = _start_semaphore or asyncio.Semaphore(50)
        async with sem:
            try:
                await self._start_inner()
            except Exception:
                # Roll back partially-allocated resources (docker client, temp dir,
                # half-created container) so a failed start doesn't leak.
                logger.warning("Sandbox start failed — cleaning up partial state")
                await self.stop()
                raise

    async def _start_inner(self) -> None:
        self._docker = aiodocker.Docker()

        self.workspace_dir = tempfile.mkdtemp(prefix="ctf-workspace-")

        challenge_root = Path(self.challenge_dir).resolve()
        distfiles = str(challenge_root / "distfiles")
        meta_yml = str(challenge_root / "metadata.yml")

        binds: list[str] = [f"{self.workspace_dir}:/challenge/workspace:rw"]
        if Path(distfiles).exists():
            binds.append(f"{distfiles}:/challenge/distfiles:ro")
        else:
            # No distfiles/ subdir — mount the challenge root directly as distfiles
            binds.append(f"{str(challenge_root)}:/challenge/distfiles:ro")
        if Path(meta_yml).exists():
            binds.append(f"{meta_yml}:/challenge/metadata.yml:ro")

        # Shared knowledge base (HackTricks, PayloadsAllTheThings, etc.)
        knowledge_dir = Path(__file__).resolve().parents[1] / "knowledge"
        if knowledge_dir.is_dir():
            for repo_dir in sorted(knowledge_dir.iterdir()):
                if repo_dir.is_dir():
                    binds.append(f"{repo_dir}:/knowledge/{repo_dir.name}:ro")

        self._binds = binds

        config = self._container_config()

        try:
            self._container = await self._docker.containers.create(config)
        except aiodocker.exceptions.DockerError as e:
            if getattr(e, "status", None) == 404 and self.image != "ctf-swarm:base":
                logger.warning(
                    "Image %s not found, falling back to ctf-swarm:base",
                    self.image,
                )
                self.image = "ctf-swarm:base"
                config["Image"] = self.image
                self._container = await self._docker.containers.create(config)
            else:
                raise
        await self._container.start()
        await _track_start()

        info = await self._container.show()
        short_id = info["Id"][:12]
        logger.info("Sandbox started: %s", short_id)

        # Container-wide setup only: refresh apt lists so agents can `apt install`
        # immediately. Distfiles are copied per-model into each solver's own workdir
        # (see OpenAISolver.start) so the models don't clobber each other's files.
        await self._exec_inner(
            self._container,
            "apt-get update -qq >/dev/null 2>&1 &",
            timeout_s=30,
        )

    async def _restart_container(self) -> None:
        """Recreate the container with the same mounts (workspace preserved on host)."""
        if self._restart_count >= self.MAX_RESTARTS:
            raise RuntimeError(f"Container restarted {self._restart_count} times already — giving up")

        logger.warning("Container gone — restarting (attempt %d/%d)", self._restart_count + 1, self.MAX_RESTARTS)

        # Clean up dead container reference
        if self._container:
            try:
                await self._container.delete(force=True)
            except Exception:
                pass
            self._container = None

        config = self._container_config()
        self._container = await self._docker.containers.create(config)
        await self._container.start()
        self._restart_count += 1
        info = await self._container.show()
        logger.info("Container restarted: %s (restart #%d)", info["Id"][:12], self._restart_count)

    def _is_gone_error(self, e: Exception) -> bool:
        msg = str(e).lower()
        return "404" in msg or "no such container" in msg or "not found" in msg

    async def _restart_if_stale(self, stale: Any) -> None:
        """Restart the container, but only once if several callers raced on a gone-error.

        `stale` is the container object the caller was using. If another coroutine
        already swapped in a fresh container, this is a no-op.
        """
        async with self._restart_lock:
            if self._container is stale or self._container is None:
                await self._restart_container()

    async def exec(self, command: str, timeout_s: int = 300, workdir: str | None = None) -> ExecResult:
        container = self._container
        if not container:
            raise RuntimeError("Sandbox not started")

        # Normal path runs without a global lock so multiple solver models can use
        # the shared container in parallel. We pass the captured `container` into the
        # op (rather than reading self._container again) so a concurrent restart that
        # transiently nulls self._container can't AttributeError us. `workdir` isolates
        # each solver model into its own subdir of the shared workspace.
        try:
            return await self._exec_inner(container, command, timeout_s, workdir)
        except aiodocker.exceptions.DockerError as e:
            if not self._is_gone_error(e):
                return ExecResult(exit_code=-1, stdout="", stderr=f"Docker error: {e}")
            try:
                await self._restart_if_stale(container)
                note = (
                    "NOTE: The sandbox container was automatically restarted. "
                    "/challenge/distfiles and your workspace are preserved. "
                    "Any files you created in /tmp are lost — recreate them if needed."
                )
                result = await self._exec_inner(self._container, command, timeout_s, workdir)
                result.stderr = (note + "\n" + result.stderr).strip()
                return result
            except Exception as restart_err:
                return ExecResult(exit_code=-1, stdout="", stderr=f"Container gone and restart failed: {restart_err}")

    async def _exec_inner(self, container: Any, command: str, timeout_s: int, workdir: str | None = None) -> ExecResult:
        # cd into the per-model workdir first (one bash -c, so the cd applies to the
        # whole command including multi-statement scripts). `|| exit 1` avoids silently
        # running in the wrong directory if the dir is missing.
        script = command if workdir is None else f"cd {shlex.quote(workdir)} || exit 1\n{command}"
        # Wrap with `timeout` so the container kills the process on expiry.
        # --signal=KILL ensures hard kill; --kill-after=5 is a safety net.
        wrapped = f"timeout --signal=KILL --kill-after=5 {timeout_s} bash -c {shlex.quote(script)}"
        exec_instance = await container.exec(
            cmd=["bash", "-c", wrapped],
            stdout=True,
            stderr=True,
            tty=False,
        )

        stream = exec_instance.start(detach=False)
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []

        async def _collect() -> None:
            while True:
                msg = await stream.read_out()
                if msg is None:
                    break
                if msg.stream == 1:
                    stdout_chunks.append(msg.data)
                else:
                    stderr_chunks.append(msg.data)

        try:
            # Give extra margin beyond the container-side timeout
            await asyncio.wait_for(_collect(), timeout=timeout_s + 30)
        except TimeoutError:
            try:
                await stream.close()
            except Exception:
                pass
            return ExecResult(
                exit_code=-1,
                stdout=b"".join(stdout_chunks).decode("utf-8", errors="replace"),
                stderr="Command timed out",
            )

        inspect = await exec_instance.inspect()
        exit_code = inspect.get("ExitCode", 0)

        return ExecResult(
            exit_code=exit_code,
            stdout=b"".join(stdout_chunks).decode("utf-8", errors="replace"),
            stderr=b"".join(stderr_chunks).decode("utf-8", errors="replace"),
        )

    async def read_file(self, path: str) -> str | bytes:
        """Read a file from the container. Returns str for text, bytes for binary."""
        container = self._container
        if not container:
            raise RuntimeError("Sandbox not started")

        try:
            tar = await asyncio.wait_for(
                container.get_archive(path),
                timeout=30,
            )
        except aiodocker.exceptions.DockerError as e:
            if self._is_gone_error(e):
                try:
                    await self._restart_if_stale(container)
                    tar = await asyncio.wait_for(self._container.get_archive(path), timeout=30)
                except Exception as restart_err:
                    raise RuntimeError(f"Container gone and restart failed: {restart_err}") from e
            else:
                raise
        except TimeoutError as e:
            raise TimeoutError(f"Timed out reading {path}") from e

        # aiodocker 0.26.0 returns tarfile.TarFile directly
        with tar:
            for member in tar:
                if member.isfile():
                    f = tar.extractfile(member)
                    if f:
                        data = f.read()
                        try:
                            return data.decode("utf-8")
                        except UnicodeDecodeError:
                            return data
        raise FileNotFoundError(f"No file found at {path}")

    async def read_file_bytes(self, path: str) -> bytes:
        """Read a file from the container as raw bytes."""
        result = await self.read_file(path)
        if isinstance(result, str):
            return result.encode("utf-8")
        return result

    async def write_file(self, path: str, content: str | bytes) -> None:
        """Write a file into the container via tar archive."""
        container = self._container
        if not container:
            raise RuntimeError("Sandbox not started")

        if isinstance(content, str):
            content = content.encode("utf-8")

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=Path(path).name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        buf.seek(0)

        try:
            await asyncio.wait_for(
                container.put_archive(str(Path(path).parent), buf.getvalue()),
                timeout=30,
            )
        except aiodocker.exceptions.DockerError as e:
            if self._is_gone_error(e):
                try:
                    await self._restart_if_stale(container)
                    await asyncio.wait_for(
                        self._container.put_archive(str(Path(path).parent), buf.getvalue()),
                        timeout=30,
                    )
                except Exception as restart_err:
                    raise RuntimeError(f"Container gone and restart failed: {restart_err}") from e
            else:
                raise
        except TimeoutError as e:
            raise TimeoutError(f"Timed out writing {path}") from e

    async def copy_from(self, container_path: str, host_path: str) -> None:
        """Copy a file from the container to the host."""
        data = await self.read_file_bytes(container_path)
        Path(host_path).parent.mkdir(parents=True, exist_ok=True)
        Path(host_path).write_bytes(data)

    async def stop(self) -> None:
        if self._container:
            try:
                await self._container.delete(force=True)
            except Exception:
                pass
            self._container = None
            await _track_stop()

        if self._docker:
            try:
                await self._docker.close()
            except Exception:
                pass
            self._docker = None

        if self.workspace_dir:
            import shutil
            try:
                shutil.rmtree(self.workspace_dir, ignore_errors=True)
            except Exception:
                pass
            self.workspace_dir = ""
        logger.info("Sandbox stopped")
