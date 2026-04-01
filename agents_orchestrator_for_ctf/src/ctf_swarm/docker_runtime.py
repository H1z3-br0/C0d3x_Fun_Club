from __future__ import annotations

import asyncio
import contextlib
import re
import shlex
import uuid
from dataclasses import dataclass
from pathlib import Path

from .profiles import image_for_profile
from .schemas import WorkerExecution
from .utils import normalize_workspace_workdir

INSTALL_MANAGERS = {"apt", "pip", "gem", "cargo", "go", "npm"}
SHELL_META_RE = re.compile(r"[|&;<>`$()]")


@dataclass
class DockerCommandResult:
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class InstallCommand:
    raw_command: str
    manager: str
    packages: tuple[str, ...]


@dataclass
class InstallCommandResult:
    command_result: DockerCommandResult
    replacement_container_name: str | None = None
    replacement_image: str | None = None
    transient_image: str | None = None


def parse_ctf_install_command(command: str) -> InstallCommand | None:
    stripped = command.strip()
    if not stripped or SHELL_META_RE.search(stripped):
        return None
    try:
        tokens = shlex.split(stripped)
    except ValueError:
        return None
    if len(tokens) < 2 or tokens[0] != "ctf-install":
        return None
    manager = tokens[1]
    if manager not in INSTALL_MANAGERS:
        return None
    packages = tuple(tokens[2:])
    if not packages:
        return None
    return InstallCommand(raw_command=stripped, manager=manager, packages=packages)


class DockerSandbox:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self._checked_images: set[str] = set()

    async def ensure_profile_image(self, profile: str) -> str:
        image = image_for_profile(profile)
        await self._ensure_image(image)
        return image

    async def start_container(
        self,
        *,
        worker_id: str,
        profile: str,
        task_dir: Path,
        artifact_dir: Path,
        tool_cache_dir: Path,
        network_enabled: bool,
        image: str | None = None,
        purpose: str = "worker",
    ) -> str:
        runtime_image = image or image_for_profile(profile)
        await self._ensure_image(runtime_image)
        container_name = self._container_name(worker_id=worker_id, purpose=purpose)
        network = "bridge" if network_enabled else "none"
        result = await self._run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                container_name,
                "--network",
                network,
                "-e",
                "CTF_TASK=/workspace/task",
                "-e",
                "CTF_ARTIFACTS=/workspace/artifacts",
                "-e",
                "CTF_TOOL_CACHE=/workspace/tool-cache",
                "-e",
                f"CTF_PROFILE={profile}",
                "-e",
                "PIP_CACHE_DIR=/workspace/tool-cache/.pip-cache",
                "-e",
                "CTF_PYTHON_PREFIX=/workspace/tool-cache/python",
                "-e",
                "CTF_CARGO_HOME=/workspace/tool-cache/.cargo-home",
                "-e",
                "CTF_CARGO_ROOT=/workspace/tool-cache/.cargo-root",
                "-e",
                "CTF_GO_BIN=/workspace/tool-cache/bin",
                "-e",
                "CTF_BIN_DIR=/workspace/tool-cache/bin",
                "-e",
                "CTF_GEM_HOME=/workspace/tool-cache/.gem",
                "-e",
                "CTF_NPM_PREFIX=/workspace/tool-cache/.npm-global",
                "-v",
                f"{task_dir.resolve()}:/workspace/task:ro",
                "-v",
                f"{artifact_dir.resolve()}:/workspace/artifacts:rw",
                "-v",
                f"{tool_cache_dir.resolve()}:/workspace/tool-cache:rw",
                "-w",
                "/workspace/task",
                runtime_image,
                "sleep",
                "infinity",
            ],
            timeout=120,
            check=False,
        )
        if result.return_code != 0:
            raise RuntimeError(f"Не удалось стартовать контейнер {container_name}: {result.stderr}")
        return container_name

    async def exec(
        self, container_name: str, command: str, timeout_seconds: int, workdir: str
    ) -> DockerCommandResult:
        absolute_workdir = normalize_workspace_workdir(workdir)
        return await self._run(
            [
                "docker",
                "exec",
                "-w",
                absolute_workdir,
                container_name,
                "/bin/bash",
                "-c",
                command,
            ],
            timeout=timeout_seconds,
            check=False,
        )

    async def run_install(
        self,
        *,
        execution: WorkerExecution,
        install: InstallCommand,
        task_dir: Path,
        artifact_dir: Path,
        tool_cache_dir: Path,
        timeout_seconds: int,
    ) -> InstallCommandResult:
        installer_name = await self.start_container(
            worker_id=execution.worker_id,
            profile=execution.profile,
            task_dir=task_dir,
            artifact_dir=artifact_dir,
            tool_cache_dir=tool_cache_dir,
            network_enabled=True,
            image=execution.image,
            purpose="installer",
        )
        try:
            result = await self.exec(
                installer_name,
                install.raw_command,
                timeout_seconds=timeout_seconds,
                workdir="/workspace/task",
            )
            if result.return_code != 0 or install.manager != "apt":
                return InstallCommandResult(command_result=result)

            transient_image = self._transient_image_name(execution.worker_id)
            commit = await self._run(
                ["docker", "commit", installer_name, transient_image],
                timeout=180,
                check=False,
            )
            if commit.return_code != 0:
                commit_error = DockerCommandResult(
                    return_code=125,
                    stdout=result.stdout,
                    stderr=(result.stderr + "\n" + commit.stderr).strip(),
                )
                return InstallCommandResult(command_result=commit_error)

            replacement_container = await self.start_container(
                worker_id=execution.worker_id,
                profile=execution.profile,
                task_dir=task_dir,
                artifact_dir=artifact_dir,
                tool_cache_dir=tool_cache_dir,
                network_enabled=execution.network_enabled,
                image=transient_image,
                purpose="worker",
            )
            return InstallCommandResult(
                command_result=result,
                replacement_container_name=replacement_container,
                replacement_image=transient_image,
                transient_image=transient_image,
            )
        finally:
            with contextlib.suppress(Exception):
                await self.kill(installer_name)

    async def kill(self, container_name: str) -> None:
        await self._run(["docker", "kill", container_name], timeout=20, check=False)

    async def remove_image(self, image: str) -> None:
        self._checked_images.discard(image)
        await self._run(["docker", "image", "rm", "-f", image], timeout=60, check=False)

    def _container_name(self, *, worker_id: str, purpose: str) -> str:
        return f"ctf-swarm-{purpose}-{worker_id}-{uuid.uuid4().hex[:8]}"

    def _transient_image_name(self, worker_id: str) -> str:
        return f"ctf-swarm-runtime:{worker_id.lower()}-{uuid.uuid4().hex[:10]}"

    async def _ensure_image(self, image: str) -> None:
        if image in self._checked_images:
            return
        inspect = await self._run(
            ["docker", "image", "inspect", image],
            timeout=30,
            check=False,
        )
        if inspect.return_code != 0:
            profile_hint = image.split(":", 1)[1] if ":" in image else image
            raise RuntimeError(
                f"Docker image {image} не найден. Соберите его через ./build_profiles.sh {profile_hint}"
            )
        self._checked_images.add(image)

    async def _run(self, command: list[str], timeout: int, check: bool) -> DockerCommandResult:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return DockerCommandResult(return_code=124, stdout="", stderr="timeout", timed_out=True)

        result = DockerCommandResult(
            return_code=process.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )
        if check and result.return_code != 0:
            rendered = " ".join(shlex.quote(item) for item in command)
            raise RuntimeError(
                f"Команда завершилась с кодом {result.return_code}: {rendered}\n{result.stderr}"
            )
        return result
