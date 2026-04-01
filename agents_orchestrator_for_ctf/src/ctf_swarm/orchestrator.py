from __future__ import annotations

import asyncio
import contextlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agents import AgentProtocolError, AgentService
from .config import AppConfig, RunArgs, load_config, parse_args
from .console import ConsoleController
from .ctfd import CTFdClient, compute_priority
from .docker_runtime import DockerSandbox, parse_ctf_install_command
from .llm import LLMGateway, LLMRateLimitError, UsageInfo
from .memory import MemoryStore
from .schemas import (
    Finding,
    Hypothesis,
    RoleUsage,
    TaskSpec,
    TaskState,
    WorkerExecution,
    WorkerResult,
)
from .state import RoleState, StateStore, create_initial_snapshot
from .task_loader import load_local_task
from .utils import ensure_dir, flag_format_to_regex, slugify, trim_block, utc_now
from .writeup import fallback_writeup, save_writeup

TERMINAL_TASK_STATUSES = {"solved", "skipped", "failed"}


@dataclass
class PoolTarget:
    label: str
    model: str
    base_url: str | None
    api_key: str | None


@dataclass
class ExecutorOutcome:
    execution: WorkerExecution
    result: WorkerResult
    cancelled: bool = False


class SwarmOrchestrator:
    def __init__(self, config: AppConfig, args: RunArgs, project_root: Path) -> None:
        self.config = config
        self.args = args
        self.project_root = project_root
        self.workspace_root = ensure_dir(project_root / config.paths.workspace_root)
        self.artifacts_root = ensure_dir(self.workspace_root / "artifacts")
        self.tool_cache_root = ensure_dir(self.workspace_root / "tool-cache")
        self.state_store = StateStore(self.workspace_root)
        self.memory = MemoryStore(self.workspace_root)
        self.console = ConsoleController()
        self.llm = LLMGateway(
            default_base_url=config.cliproxyapi.base_url,
            default_api_key=config.cliproxyapi.api_key,
            timeout_seconds=config.cliproxyapi.timeout_seconds,
        )
        self.agents = AgentService(self.llm)
        self.docker = DockerSandbox(project_root=project_root)

        self.flag_regex = flag_format_to_regex(config.ctf.flag_format)
        self.flag_pattern = re.compile(self.flag_regex)
        self.tasks: dict[str, TaskState] = {}
        self.roles: dict[str, RoleState] = self._build_role_states()
        self.snapshot = None
        self.active_task_id: str | None = None
        self.worker_counter = 0
        self.active_workers: dict[str, WorkerExecution] = {}
        self.worker_jobs: dict[str, asyncio.Task[ExecutorOutcome]] = {}
        self.pending_replans: dict[str, list[str]] = {}
        self.forced_messages: dict[str, str] = {}
        self.rotation_in_progress: set[str] = set()
        self.priority_refresh_at = 0.0
        self.should_exit = False
        self.state_dirty = True
        self.last_state_save_at = 0.0

    async def run(self) -> int:
        self.console.install()
        try:
            await self._prepare()
            await self._main_loop()
            self._save_state(force=True)
            return 0
        finally:
            await self._cancel_all_workers("shutdown", requeue=True)
            self._save_state(force=True)
            await self.llm.aclose()
            self.memory.close()
            self.console.restore()

    async def _prepare(self) -> None:
        if self.args.resume and self.state_store.exists():
            self.snapshot = self.state_store.load()
            self.tasks = self.snapshot.tasks
            self.roles = self.snapshot.roles
            self.active_task_id = self.snapshot.active_task_id
            self.worker_counter = self.snapshot.worker_counter
            self._normalize_resumed_state()
            self._log("Состояние восстановлено из checkpoint.")
            self._save_state(force=True)
            return

        if self.args.mode == "single":
            if not self.args.task_dir:
                raise ValueError("Для SINGLE режима нужен --task-dir")
            spec = load_local_task(self.args.task_dir)
            task = self._make_task_state(spec)
            self.tasks = {task.spec.task_id: task}
            self.active_task_id = task.spec.task_id
        else:
            if not self.args.ctfd_url:
                raise ValueError("Для MULTI режима нужен --ctfd-url")
            if not (self.args.ctfd_token or self.args.ctfd_session):
                raise ValueError("Для MULTI режима нужен --ctfd-token или --ctfd-session")
            self.tasks = await self._load_multi_tasks()
            self.active_task_id = self._best_task_id()

        self.snapshot = create_initial_snapshot(
            self.args.mode,
            self.tasks,
            self.roles,
            worker_counter=self.worker_counter,
        )
        self._save_state(force=True)

    async def _load_multi_tasks(self) -> dict[str, TaskState]:
        tasks: dict[str, TaskState] = {}
        async with CTFdClient(
            self.args.ctfd_url or "",
            token=self.args.ctfd_token,
            session_cookie=self.args.ctfd_session,
        ) as client:
            challenges = await client.list_challenges()
            ranked = sorted(
                challenges,
                key=compute_priority,
                reverse=True,
            )
            for challenge in ranked:
                spec = await client.download_challenge(challenge, self.workspace_root)
                task = self._make_task_state(spec)
                task.priority_score = compute_priority(challenge)
                tasks[task.spec.task_id] = task
        return tasks

    def _make_task_state(self, spec: TaskSpec) -> TaskState:
        artifact_dir = ensure_dir(self.artifacts_root / spec.task_id)
        return TaskState(
            spec=spec,
            status="pending",
            priority_score=float(spec.points or 100),
            artifact_dir=str(artifact_dir),
        )

    def _normalize_resumed_state(self) -> None:
        for task in self.tasks.values():
            if task.status == "running":
                task.status = "pending"
            for hypothesis in task.hypotheses:
                if hypothesis.status == "running":
                    hypothesis.status = "pending"
        self._touch_state()

    async def _main_loop(self) -> None:
        while not self.should_exit:
            await self._handle_sigint_if_needed()
            await self._process_console_command()
            await self._process_finished_workers()
            await self._refresh_multi_priorities_if_needed()
            await self._ensure_plans()
            await self._schedule_workers()
            self._save_state()

            if self._all_tasks_done() and not self.worker_jobs:
                self._log("Все таски завершены.")
                break
            await asyncio.sleep(0.2)

    async def _handle_sigint_if_needed(self) -> None:
        if not self.console.sigint_requested:
            return
        self.console.sigint_requested = False
        await self._cancel_all_workers("SIGINT", requeue=True)
        action = await self.console.sigint_menu(self._task_options())
        await self._handle_menu_action(action)

    async def _process_console_command(self) -> None:
        try:
            command = await self.console.poll_command()
        except ValueError as exc:
            self._log(f"Ошибка команды: {exc}")
            return
        if command is None:
            return
        await self._handle_command(command)

    async def _handle_menu_action(self, action: dict[str, str]) -> None:
        kind = action.get("action")
        if kind == "continue":
            self._log("Продолжаю выполнение.")
            return
        if kind == "interrupt":
            await self._handle_command(
                {"action": "interrupt", "message": action.get("message", "")}
            )
            return
        if kind == "switch_task":
            self._switch_active_task(action.get("target", ""))
            return
        self.should_exit = True

    async def _handle_command(self, command: dict[str, Any]) -> None:
        action = command["action"]
        if action == "hint":
            task = self._current_task()
            if task is None:
                self._log("Нет активного таска для /hint")
                return
            message = str(command["message"]).strip()
            task.hints.append(message)
            self.pending_replans.setdefault(task.spec.task_id, []).append("human hint")
            self._log(f"Подсказка добавлена в {task.spec.name}")
            return

        if action == "interrupt":
            await self._cancel_all_workers("human interrupt", requeue=True)
            task = self._current_task()
            if task is None:
                self._log("Нет активного таска для /interrupt")
                return
            message = str(command["message"]).strip()
            self.forced_messages[task.spec.task_id] = message
            self.pending_replans.setdefault(task.spec.task_id, []).append("human interrupt")
            self._log(f"Выполнение прервано. Передаю CC1 указание для {task.spec.name}")
            return

        if action == "kill":
            await self._cancel_worker(str(command["worker_id"]), "manual kill", requeue=False)
            return

        if action == "status":
            print(self._render_status(), flush=True)
            return

        if action == "skip":
            task = self._current_task()
            if task is None:
                self._log("Нет активного таска для /skip")
                return
            await self._cancel_workers_for_task(task.spec.task_id, "skip", requeue=False)
            task.status = "skipped"
            self._log(f"Таск {task.spec.name} помечен как skipped")
            self.active_task_id = self._best_task_id()
            return

    async def _ensure_plans(self) -> None:
        tasks = [
            task for task in self._ordered_open_tasks() if task.status not in TERMINAL_TASK_STATUSES
        ]
        if not tasks:
            return
        semaphore = asyncio.Semaphore(max(1, self.config.limits.planner_parallelism))

        async def _plan_one(task: TaskState) -> None:
            async with semaphore:
                await self._ensure_task_plan(task)

        await asyncio.gather(*(_plan_one(task) for task in tasks))

    async def _ensure_task_plan(self, task: TaskState) -> None:
        await self._initialize_task_context(task)
        reasons = self.pending_replans.get(task.spec.task_id, [])
        if not task.hypotheses or reasons:
            await self._plan_task(task, reasons)
            self.pending_replans[task.spec.task_id] = []

    async def _initialize_task_context(self, task: TaskState) -> None:
        if not task.memory_hits:
            query = f"{task.spec.name} {task.spec.category or ''}".strip()
            task.memory_hits = self.memory.search(query, limit=5)
        if task.support_notes:
            return
        await self._run_support_context(task)

    async def _run_support_context(self, task: TaskState) -> None:
        target = self._current_target("support")
        try:
            result = await self.agents.support_context(
                model=target.model,
                base_url=target.base_url,
                api_key=target.api_key,
                task=task,
            )
            await self._record_usage("support", result.usage)
            payload = result.payload
            task.support_notes = "\n".join(
                [
                    payload["summary"],
                    f"Techniques: {', '.join(payload['relevant_techniques'])}"
                    if payload["relevant_techniques"]
                    else "",
                    f"CVEs: {', '.join(payload['possible_cves'])}"
                    if payload["possible_cves"]
                    else "",
                    payload["notes_for_master"],
                ]
            ).strip()
            self._touch_state()
        except (LLMRateLimitError, AgentProtocolError) as exc:
            if isinstance(exc, AgentProtocolError):
                raise RuntimeError(
                    f"Невалидный JSON от support при инициализации {task.spec.name}: {exc}"
                ) from exc
            await self._maybe_rotate_role("support", f"support init failure: {exc}", force=True)
            task.support_notes = self._fallback_support_notes(task)
            self._touch_state()

    async def _plan_task(self, task: TaskState, reasons: list[str]) -> None:
        target = self._current_target("master")
        forced_message = self.forced_messages.pop(task.spec.task_id, None)
        event_summary = "\n".join(
            [
                f"replan reasons: {', '.join(reasons)}" if reasons else "",
                *self.snapshot.event_log[-15:],
            ]
        ).strip()
        try:
            result = await self.agents.master_plan(
                model=target.model,
                base_url=target.base_url,
                api_key=target.api_key,
                task=task,
                flag_regex=self.flag_regex,
                event_summary=event_summary,
                forced_message=forced_message,
            )
            await self._record_usage("master", result.usage)
            await self._apply_master_plan(task, result.payload)
        except LLMRateLimitError as exc:
            await self._maybe_rotate_role("master", f"rate limit: {exc}", force=True)
            self._apply_fallback_plan(task, reasons, forced_message)
        except AgentProtocolError as exc:
            raise RuntimeError(f"Невалидный JSON от master для {task.spec.name}: {exc}") from exc

    async def _apply_master_plan(self, task: TaskState, payload: dict[str, Any]) -> None:
        task.master_notes = "\n".join(
            [
                payload["analysis"],
                payload["task_summary"],
                payload["focus_recommendation"],
                payload["notes_for_support"],
            ]
        ).strip()
        task.network_required = bool(payload["network_required"])
        task.last_plan_at = utc_now()

        cancel_set = set(payload["cancel_hypotheses"])
        for worker_id, execution in list(self.active_workers.items()):
            if execution.task_id == task.spec.task_id and execution.hypothesis_id in cancel_set:
                await self._cancel_worker(worker_id, "master pivot", requeue=False)

        existing_titles = {item.title.lower() for item in task.hypotheses if item.status != "dead"}
        for item in payload["new_hypotheses"]:
            if item["title"].lower() in existing_titles:
                continue
            hypothesis = Hypothesis(
                hypothesis_id=self._next_hypothesis_id(task),
                title=item["title"],
                rationale=item["rationale"],
                plan=item["plan"],
                priority=max(1, min(100, int(item["priority"]))),
                profile=item["profile"],
                network_required=bool(item["network_required"]),
                tools=item["tools"],
            )
            task.hypotheses.append(hypothesis)
            existing_titles.add(hypothesis.title.lower())

        task.hypotheses.sort(key=lambda item: item.priority, reverse=True)
        note = payload.get("notes_for_user")
        if note:
            self._log(f"[CC1] {task.spec.name}: {note}")
        self._touch_state()

    def _apply_fallback_plan(
        self, task: TaskState, reasons: list[str], forced_message: str | None
    ) -> None:
        if task.hypotheses:
            return
        base_title = forced_message or task.spec.name
        task.master_notes = (
            "Fallback план: модель недоступна или вернула невалидный JSON. "
            "Оркестратор создал базовые гипотезы из описания."
        )
        task.hypotheses.append(
            Hypothesis(
                hypothesis_id=self._next_hypothesis_id(task),
                title=f"Inspect files for obvious leads in {base_title}",
                rationale="Первичный обзор структуры и строк",
                plan=["run file on binaries", "grep strings", "look for secrets and endpoints"],
                priority=80,
                profile="base",
                network_required=False,
            )
        )
        task.hypotheses.append(
            Hypothesis(
                hypothesis_id=self._next_hypothesis_id(task),
                title=f"Search for flag-like strings in {base_title}",
                rationale="Быстрый дешёвый прогон на явные индикаторы",
                plan=["grep recursively for flag pattern", "inspect archives and images"],
                priority=70,
                profile="base",
                network_required=False,
            )
        )
        if reasons and any("interrupt" in reason for reason in reasons):
            task.hypotheses.append(
                Hypothesis(
                    hypothesis_id=self._next_hypothesis_id(task),
                    title=f"Re-evaluate with user guidance for {base_title}",
                    rationale="Нужно учесть внешнюю подсказку пользователя",
                    plan=["inspect notes", "follow the hinted path directly"],
                    priority=95,
                    profile="base",
                    network_required=task.network_required,
                )
            )
        task.hypotheses.sort(key=lambda item: item.priority, reverse=True)
        self._touch_state()

    async def _schedule_workers(self) -> None:
        while len(self.worker_jobs) < self.config.limits.max_parallel_workers:
            task = self._pick_task_for_worker()
            if task is None:
                break
            hypothesis = next((item for item in task.hypotheses if item.status == "pending"), None)
            if hypothesis is None:
                break
            await self._start_worker(task, hypothesis)

    def _pick_task_for_worker(self) -> TaskState | None:
        candidates = [
            task
            for task in self.tasks.values()
            if task.status not in TERMINAL_TASK_STATUSES
            and any(item.status == "pending" for item in task.hypotheses)
        ]
        if not candidates:
            return None
        if self.args.mode == "single":
            return candidates[0]

        def score(task: TaskState) -> float:
            active = sum(
                1
                for execution in self.active_workers.values()
                if execution.task_id == task.spec.task_id
            )
            return task.priority_score / (1 + active)

        return max(candidates, key=score)

    async def _start_worker(self, task: TaskState, hypothesis: Hypothesis) -> None:
        self.worker_counter += 1
        worker_id = f"cx-{self.worker_counter:02d}"
        profile = hypothesis.profile or "base"
        network_enabled = (
            not self.config.sandbox.network_disabled
            or task.network_required
            or hypothesis.network_required
        )
        tool_cache_dir = self._tool_cache_dir(profile)
        image = await self.docker.ensure_profile_image(profile)
        container_name = await self.docker.start_container(
            worker_id=worker_id,
            profile=profile,
            task_dir=Path(task.spec.task_dir),
            artifact_dir=Path(task.artifact_dir),
            tool_cache_dir=tool_cache_dir,
            network_enabled=network_enabled,
            image=image,
        )
        execution = WorkerExecution(
            worker_id=worker_id,
            task_id=task.spec.task_id,
            hypothesis_id=hypothesis.hypothesis_id,
            started_at=utc_now(),
            container_name=container_name,
            profile=profile,
            image=image,
            network_enabled=network_enabled,
        )
        hypothesis.status = "running"
        hypothesis.attempts += 1
        task.status = "running"
        self.active_workers[worker_id] = execution
        self.worker_jobs[worker_id] = asyncio.create_task(
            self._run_worker(execution, task, hypothesis)
        )
        self._touch_state()
        self._log(
            f"Стартовал {worker_id} для {task.spec.name}: {hypothesis.title} [profile={profile}]"
        )

    async def _run_worker(
        self, execution: WorkerExecution, task: TaskState, hypothesis: Hypothesis
    ) -> ExecutorOutcome:
        target = self._executor_target()
        transcript_lines: list[str] = []
        try:
            async with asyncio.timeout(self.config.limits.worker_timeout_seconds):
                for step in range(1, self.config.limits.worker_max_steps + 1):
                    transcript = "\n".join(transcript_lines[-20:])
                    result = await self._executor_turn_with_retries(
                        target=target,
                        task=task,
                        hypothesis=hypothesis,
                        transcript=transcript,
                    )

                    transcript_lines.append(f"STEP {step} ASSISTANT:\n{result.raw_text}")
                    payload = result.payload
                    if payload["status"] == "final":
                        final = payload["result"]
                        return ExecutorOutcome(
                            execution=execution,
                            result=WorkerResult(
                                status=final["status"],
                                summary=final["summary"],
                                evidence=final["evidence"],
                                artifacts=final["artifacts"],
                                flag=final["flag"],
                                confidence=final["confidence"],
                            ),
                        )

                    command = payload["command"]
                    command_result = await self._execute_worker_command(
                        execution=execution,
                        task=task,
                        command=command,
                    )
                    observation = "\n".join(
                        [
                            f"COMMAND: {command['cmd']}",
                            f"RETURN CODE: {command_result.return_code}",
                            f"STDOUT:\n{trim_block(command_result.stdout)}",
                            f"STDERR:\n{trim_block(command_result.stderr)}",
                        ]
                    )
                    flags = self.flag_pattern.findall(
                        command_result.stdout + "\n" + command_result.stderr
                    )
                    if flags:
                        observation += f"\nCANDIDATE FLAGS: {flags}"
                    transcript_lines.append(f"STEP {step} OBSERVATION:\n{observation}")
        except TimeoutError:
            return ExecutorOutcome(
                execution=execution,
                result=WorkerResult(
                    status="failed",
                    summary="Worker timed out",
                    evidence=["Истек общий timeout воркера"],
                    artifacts=[],
                    confidence=0,
                ),
            )
        except LLMRateLimitError as exc:
            return ExecutorOutcome(
                execution=execution,
                result=WorkerResult(
                    status="failed",
                    summary="Executor exhausted rate-limit retries",
                    evidence=[str(exc)],
                    artifacts=[],
                    confidence=0,
                ),
            )
        except asyncio.CancelledError:
            raise
        finally:
            with contextlib.suppress(Exception):
                await self.docker.kill(execution.container_name)
            for transient_image in execution.transient_images:
                with contextlib.suppress(Exception):
                    await self.docker.remove_image(transient_image)

        return ExecutorOutcome(
            execution=execution,
            result=WorkerResult(
                status="need_more_time",
                summary="Достигнут лимит шагов",
                evidence=["Воркер исчерпал max steps"],
                artifacts=[],
                confidence=10,
            ),
        )

    async def _executor_turn_with_retries(
        self,
        *,
        target: PoolTarget,
        task: TaskState,
        hypothesis: Hypothesis,
        transcript: str,
    ):
        delay = self.config.limits.rate_limit_backoff_seconds
        max_attempts = max(1, self.config.limits.llm_max_retries + 1)
        last_error: LLMRateLimitError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return await self.agents.executor_turn(
                    model=target.model,
                    base_url=target.base_url,
                    api_key=target.api_key,
                    task=task,
                    hypothesis=hypothesis,
                    transcript=transcript,
                    flag_regex=self.flag_regex,
                )
            except LLMRateLimitError as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                await asyncio.sleep(delay)
                delay *= 2
        if last_error is not None:
            raise last_error
        raise RuntimeError("Executor retry loop завершился без результата")

    async def _execute_worker_command(
        self,
        *,
        execution: WorkerExecution,
        task: TaskState,
        command: dict[str, Any],
    ):
        timeout_seconds = min(
            int(command["timeout_seconds"]),
            self.config.limits.worker_timeout_seconds,
        )
        install = parse_ctf_install_command(command["cmd"])
        if install is None:
            return await self.docker.exec(
                execution.container_name,
                command["cmd"],
                timeout_seconds=timeout_seconds,
                workdir=command["workdir"],
            )

        install_result = await self.docker.run_install(
            execution=execution,
            install=install,
            task_dir=Path(task.spec.task_dir),
            artifact_dir=Path(task.artifact_dir),
            tool_cache_dir=self._tool_cache_dir(execution.profile),
            timeout_seconds=timeout_seconds,
        )
        if install_result.replacement_container_name:
            old_container = execution.container_name
            execution.container_name = install_result.replacement_container_name
            if install_result.replacement_image:
                execution.image = install_result.replacement_image
            if install_result.transient_image:
                execution.transient_images.append(install_result.transient_image)
            with contextlib.suppress(Exception):
                await self.docker.kill(old_container)
        return install_result.command_result

    async def _process_finished_workers(self) -> None:
        if not self.worker_jobs:
            return
        done = [worker_id for worker_id, job in self.worker_jobs.items() if job.done()]
        for worker_id in done:
            job = self.worker_jobs.pop(worker_id)
            execution = self.active_workers.pop(worker_id)
            try:
                outcome = job.result()
            except asyncio.CancelledError:
                self._restore_hypothesis(
                    execution.task_id, execution.hypothesis_id, "Отменён пользователем"
                )
                continue
            except Exception as exc:
                if isinstance(exc, AgentProtocolError):
                    raise RuntimeError(
                        f"Невалидный JSON от executor {worker_id} "
                        f"для {execution.task_id}/{execution.hypothesis_id}: {exc}"
                    ) from exc
                self._finalize_cancelled_hypothesis(
                    execution.task_id,
                    execution.hypothesis_id,
                    f"Worker crashed: {exc}",
                    requeue=False,
                )
                self._log(f"Воркер {worker_id} завершился с ошибкой: {exc}")
                continue
            await self._apply_worker_outcome(outcome)

    async def _apply_worker_outcome(self, outcome: ExecutorOutcome) -> None:
        task = self.tasks[outcome.execution.task_id]
        hypothesis = self._find_hypothesis(task, outcome.execution.hypothesis_id)
        result = outcome.result
        hypothesis.last_summary = result.summary

        if outcome.cancelled:
            hypothesis.status = "pending"
            return

        if result.status in {"success", "flag_found"}:
            hypothesis.status = "completed"
            task.completed_hypotheses.append(hypothesis)
            task.hypotheses = [
                item for item in task.hypotheses if item.hypothesis_id != hypothesis.hypothesis_id
            ]
        elif result.status == "need_more_time":
            hypothesis.status = "pending"
            self.pending_replans.setdefault(task.spec.task_id, []).append(
                f"{hypothesis.title} needs more time"
            )
        else:
            hypothesis.status = "dead"
            task.dead_hypotheses.append(hypothesis)
            task.hypotheses = [
                item for item in task.hypotheses if item.hypothesis_id != hypothesis.hypothesis_id
            ]
            self.pending_replans.setdefault(task.spec.task_id, []).append(
                f"{hypothesis.title} failed"
            )

        finding = Finding(
            source=outcome.execution.worker_id,
            summary=result.summary,
            evidence=result.evidence,
            artifacts=result.artifacts,
            flag=result.flag,
            confidence=result.confidence,
            created_at=utc_now(),
        )
        task.findings.append(finding)
        self._touch_state()
        if result.flag and self.flag_pattern.search(result.flag):
            await self._handle_candidate_flag(task, finding)

        if task.status not in TERMINAL_TASK_STATUSES and not any(
            item.status == "running" for item in task.hypotheses
        ):
            task.status = "pending"
        self._touch_state()

    async def _handle_candidate_flag(self, task: TaskState, finding: Finding) -> None:
        is_valid, confidence, summary = await self._validate_flag(task, finding)
        finding.validated = is_valid
        finding.confidence = confidence
        if not is_valid:
            self._log(f"CC2 отклонил flag candidate для {task.spec.name}: {summary}")
            return
        task.flag = finding.flag
        task.flag_confidence = confidence
        task.status = "solved"
        await self._cancel_workers_for_task(task.spec.task_id, "task solved", requeue=False)
        writeup_path = await self._generate_writeup(task)
        task.writeup_path = writeup_path
        self.memory.save_solution(task)
        self.active_task_id = self._best_task_id()
        self._print_flag_banner(task)

    async def _validate_flag(self, task: TaskState, finding: Finding) -> tuple[bool, int, str]:
        target = self._current_target("support")
        try:
            result = await self.agents.validate_flag(
                model=target.model,
                base_url=target.base_url,
                api_key=target.api_key,
                task=task,
                finding=finding,
                flag_regex=self.flag_regex,
            )
            await self._record_usage("support", result.usage)
            payload = result.payload
            task.support_notes = (
                f"{task.support_notes}\n\nFlag validation: {payload['reasoning']}".strip()
            )
            self._touch_state()
            return bool(payload["valid"]), int(payload["confidence"]), payload["writeup_summary"]
        except (LLMRateLimitError, AgentProtocolError) as exc:
            if isinstance(exc, AgentProtocolError):
                raise RuntimeError(
                    f"Невалидный JSON от support при валидации флага {task.spec.name}: {exc}"
                ) from exc
            await self._maybe_rotate_role("support", f"flag validation failure: {exc}", force=True)
            return True, 80, "Fallback validation by regex"

    async def _generate_writeup(self, task: TaskState) -> str:
        target = self._current_target("support")
        try:
            result = await self.agents.writeup(
                model=target.model,
                base_url=target.base_url,
                api_key=target.api_key,
                task=task,
            )
            await self._record_usage("support", result.usage)
            return save_writeup(task, result.payload["markdown"])
        except LLMRateLimitError:
            return save_writeup(task, fallback_writeup(task))
        except AgentProtocolError as exc:
            raise RuntimeError(
                f"Невалидный JSON от support при генерации writeup {task.spec.name}: {exc}"
            ) from exc

    async def _refresh_multi_priorities_if_needed(self) -> None:
        if self.args.mode != "multi" or not self.args.ctfd_url:
            return
        loop = asyncio.get_running_loop()
        now = loop.time()
        if now < self.priority_refresh_at:
            return
        self.priority_refresh_at = now + self.config.limits.ctfd_refresh_interval_seconds
        try:
            async with CTFdClient(
                self.args.ctfd_url,
                token=self.args.ctfd_token,
                session_cookie=self.args.ctfd_session,
            ) as client:
                challenges = await client.list_challenges()
                existing_by_id = {
                    int(task.spec.metadata["challenge_id"]): task
                    for task in self.tasks.values()
                    if task.spec.source == "ctfd" and "challenge_id" in task.spec.metadata
                }
                discovered_new = False
                priorities_changed = False
                for challenge in challenges:
                    task = existing_by_id.get(challenge.challenge_id)
                    if task is None:
                        spec = await client.download_challenge(challenge, self.workspace_root)
                        task = self._make_task_state(spec)
                        task.priority_score = compute_priority(challenge)
                        self.tasks[task.spec.task_id] = task
                        discovered_new = True
                        self._log(f"Обнаружен новый challenge в CTFd: {task.spec.name}")
                        continue
                    new_priority = compute_priority(challenge)
                    if task.priority_score != new_priority:
                        priorities_changed = True
                    task.priority_score = new_priority
                    task.spec.points = challenge.value
                    task.spec.category = challenge.category
                    task.spec.metadata["solves"] = challenge.solves
                if discovered_new or priorities_changed:
                    self._touch_state()
        except Exception as exc:  # pragma: no cover
            self._log(f"Не удалось обновить scoreboard: {exc}")

    async def _cancel_worker(self, worker_id: str, reason: str, requeue: bool) -> None:
        execution = self.active_workers.get(worker_id)
        job = self.worker_jobs.pop(worker_id, None)
        if execution is None:
            self._log(f"Воркер {worker_id} не найден")
            return
        if job is not None:
            job.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await job
        with contextlib.suppress(Exception):
            await self.docker.kill(execution.container_name)
        self.active_workers.pop(worker_id, None)
        self._finalize_cancelled_hypothesis(
            execution.task_id,
            execution.hypothesis_id,
            f"Остановлен: {reason}",
            requeue=requeue,
        )
        self._log(f"Воркер {worker_id} остановлен ({reason})")

    async def _cancel_workers_for_task(self, task_id: str, reason: str, requeue: bool) -> None:
        for worker_id, execution in list(self.active_workers.items()):
            if execution.task_id == task_id:
                await self._cancel_worker(worker_id, reason, requeue=requeue)

    async def _cancel_all_workers(self, reason: str, requeue: bool) -> None:
        for worker_id in list(self.active_workers):
            await self._cancel_worker(worker_id, reason, requeue=requeue)

    def _restore_hypothesis(self, task_id: str, hypothesis_id: str, summary: str) -> None:
        task = self.tasks[task_id]
        hypothesis = self._find_hypothesis(task, hypothesis_id)
        hypothesis.status = "pending"
        hypothesis.last_summary = summary
        if task.status == "running":
            task.status = "pending"
        self._touch_state()

    def _finalize_cancelled_hypothesis(
        self, task_id: str, hypothesis_id: str, summary: str, requeue: bool
    ) -> None:
        if requeue:
            self._restore_hypothesis(task_id, hypothesis_id, summary)
            return
        task = self.tasks[task_id]
        hypothesis = self._find_hypothesis(task, hypothesis_id)
        hypothesis.status = "dead"
        hypothesis.last_summary = summary
        if hypothesis not in task.dead_hypotheses:
            task.dead_hypotheses.append(hypothesis)
        task.hypotheses = [item for item in task.hypotheses if item.hypothesis_id != hypothesis_id]
        if task.status == "running":
            task.status = "pending"
        self._touch_state()

    def _find_hypothesis(self, task: TaskState, hypothesis_id: str) -> Hypothesis:
        for collection in (task.hypotheses, task.completed_hypotheses, task.dead_hypotheses):
            for item in collection:
                if item.hypothesis_id == hypothesis_id:
                    return item
        raise KeyError(f"Hypothesis {hypothesis_id} not found in task {task.spec.task_id}")

    def _fallback_support_notes(self, task: TaskState) -> str:
        techniques = [record.get("key_insight", "") for record in task.memory_hits]
        base = "\n".join(item for item in techniques if item)
        return base or "Память не дала релевантных совпадений."

    async def _record_usage(self, role: str, usage: UsageInfo) -> None:
        state = self.roles[role]
        state.usage.total_tokens += usage.total_tokens
        state.usage.request_count += 1
        state.usage.step_count += 1
        self._touch_state()
        if self._role_needs_rotation(state):
            await self._maybe_rotate_role(role, "soft limit reached", force=False)

    def _role_needs_rotation(self, state: RoleState) -> bool:
        pct = self.config.limits.cc_usage_warning_pct
        return (
            state.usage.total_tokens >= int(self.config.limits.cc_token_soft_limit * pct)
            or state.usage.request_count >= int(self.config.limits.cc_request_soft_limit * pct)
            or state.usage.step_count >= int(self.config.limits.cc_step_soft_limit * pct)
        )

    async def _maybe_rotate_role(self, role: str, reason: str, force: bool) -> None:
        if role in self.rotation_in_progress:
            return
        self.rotation_in_progress.add(role)
        try:
            state = self.roles[role]
            max_stage = len(state.labels) - 1
            if state.stage_index >= max_stage:
                self._log(f"Ротация {role} недоступна: резервов больше нет")
                return
            summary = await self._build_rotation_summary(role, reason)
            summary_path = (
                self.workspace_root / "state" / f"rotation-{role}-{slugify(utc_now())}.md"
            )
            summary_path.write_text(summary, encoding="utf-8")
            for task in self.tasks.values():
                if task.status not in TERMINAL_TASK_STATUSES:
                    task.rotation_summaries.append(summary)
            state.stage_index += 1
            state.usage = RoleUsage()
            state.last_rotation_reason = reason
            self._touch_state()
            self._log(
                f"Роль {role} ротирована: {reason}. Новый агент: {state.labels[state.stage_index]}"
            )
            if force:
                await asyncio.sleep(0)
        finally:
            self.rotation_in_progress.discard(role)

    async def _build_rotation_summary(self, role: str, reason: str) -> str:
        open_tasks = self._ordered_open_tasks()
        if open_tasks:
            target = self._current_target(role)
            try:
                result = await self.agents.rotation_summary(
                    model=target.model,
                    base_url=target.base_url,
                    api_key=target.api_key,
                    role=role,
                    reason=reason,
                    tasks=open_tasks,
                )
                payload = result.payload
                sections = [payload["summary"]]
                if payload["key_risks"]:
                    sections.append("## Key Risks\n" + "\n".join(f"- {item}" for item in payload["key_risks"]))
                if payload["next_actions"]:
                    sections.append(
                        "## Next Actions\n" + "\n".join(f"- {item}" for item in payload["next_actions"])
                    )
                return "\n\n".join(section.strip() for section in sections if section.strip()) + "\n"
            except (LLMRateLimitError, AgentProtocolError):
                pass
        return self._build_rotation_summary_fallback(role, reason)

    def _build_rotation_summary_fallback(self, role: str, reason: str) -> str:
        lines = [f"# Rotation summary for {role}", f"Reason: {reason}", ""]
        for task in self._ordered_open_tasks():
            lines.extend(
                [
                    f"## {task.spec.name}",
                    f"status: {task.status}",
                    f"master_notes: {task.master_notes}",
                    f"support_notes: {task.support_notes}",
                    "active/pending hypotheses:",
                ]
            )
            for item in task.hypotheses[:10]:
                lines.append(f"- {item.hypothesis_id}: {item.title} [{item.status}]")
            if task.findings:
                lines.append("recent findings:")
                for finding in task.findings[-5:]:
                    lines.append(f"- {finding.summary} flag={finding.flag or '-'}")
            if task.dead_hypotheses:
                lines.append("failed branches:")
                for item in task.dead_hypotheses[-5:]:
                    lines.append(f"- {item.title}: {item.last_summary}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _build_role_states(self) -> dict[str, RoleState]:
        reserve_emails = self.config.accounts.smart_reserve.emails
        master_labels = [
            self.config.accounts.cc_master.emails[0]
            if self.config.accounts.cc_master.emails
            else "CC1",
            reserve_emails[0] if len(reserve_emails) > 0 else "S1",
            reserve_emails[2] if len(reserve_emails) > 2 else "S3",
        ]
        support_labels = [
            self.config.accounts.cc_support.emails[0]
            if self.config.accounts.cc_support.emails
            else "CC2",
            reserve_emails[1] if len(reserve_emails) > 1 else "S2",
            reserve_emails[3] if len(reserve_emails) > 3 else "S4",
        ]
        return {
            "master": RoleState(role="master", labels=master_labels),
            "support": RoleState(role="support", labels=support_labels),
        }

    def _current_target(self, role: str) -> PoolTarget:
        state = self.roles[role]
        if role == "master":
            if state.stage_index == 0:
                pool = self.config.accounts.cc_master
            else:
                pool = self.config.accounts.smart_reserve
        else:
            if state.stage_index == 0:
                pool = self.config.accounts.cc_support
            else:
                pool = self.config.accounts.smart_reserve
        return PoolTarget(
            label=state.labels[min(state.stage_index, len(state.labels) - 1)],
            model=pool.model,
            base_url=pool.base_url,
            api_key=pool.api_key,
        )

    def _executor_target(self) -> PoolTarget:
        pool = self.config.accounts.executors
        return PoolTarget(
            label="executors",
            model=pool.model,
            base_url=pool.base_url,
            api_key=pool.api_key,
        )

    def _ordered_open_tasks(self) -> list[TaskState]:
        tasks = [task for task in self.tasks.values() if task.status not in TERMINAL_TASK_STATUSES]
        return sorted(tasks, key=lambda item: item.priority_score, reverse=True)

    def _best_task_id(self) -> str | None:
        ordered = self._ordered_open_tasks()
        return ordered[0].spec.task_id if ordered else None

    def _current_task(self) -> TaskState | None:
        if self.active_task_id and self.active_task_id in self.tasks:
            return self.tasks[self.active_task_id]
        self.active_task_id = self._best_task_id()
        if self.active_task_id:
            return self.tasks[self.active_task_id]
        return None

    def _switch_active_task(self, raw_target: str) -> None:
        target = raw_target.strip().lower()
        for task in self.tasks.values():
            if task.spec.task_id.lower() == target or task.spec.name.lower() == target:
                self.active_task_id = task.spec.task_id
                self._log(f"Активный таск переключён на {task.spec.name}")
                return
        self._log(f"Таск {raw_target} не найден")

    def _next_hypothesis_id(self, task: TaskState) -> str:
        existing = {
            item.hypothesis_id
            for collection in (task.hypotheses, task.dead_hypotheses, task.completed_hypotheses)
            for item in collection
        }
        index = 1
        while True:
            candidate = f"hyp-{index:03d}"
            if candidate not in existing:
                return candidate
            index += 1

    def _all_tasks_done(self) -> bool:
        return all(task.status in TERMINAL_TASK_STATUSES for task in self.tasks.values())

    def _save_state(self, force: bool = False) -> None:
        if self.snapshot is None:
            return
        if not force and not self.state_dirty:
            return
        now = time.monotonic()
        if (
            not force
            and now - self.last_state_save_at < self.config.limits.state_checkpoint_interval_seconds
        ):
            return
        self.snapshot.tasks = self.tasks
        self.snapshot.roles = self.roles
        self.snapshot.active_task_id = self.active_task_id
        self.snapshot.worker_counter = self.worker_counter
        self.state_store.save(self.snapshot)
        self.last_state_save_at = now
        self.state_dirty = False

    def _task_options(self) -> list[str]:
        return [f"{task.spec.task_id} ({task.spec.name})" for task in self.tasks.values()]

    def _render_status(self) -> str:
        task_rows = [
            (
                f"- {task.spec.task_id}: {task.spec.name} | status={task.status} "
                f"| priority={task.priority_score:.2f} | pending={sum(1 for item in task.hypotheses if item.status == 'pending')} "
                f"| solved_flag={task.flag or '-'}"
            )
            for task in self.tasks.values()
        ]
        return self.console.render_status(
            active_task_id=self.active_task_id,
            task_rows=task_rows,
            active_workers=self.active_workers,
            roles=self.roles,
        )

    def _print_flag_banner(self, task: TaskState) -> None:
        banner = "\n".join(
            [
                "════════════════════════════════════════",
                f"  ФЛАГ НАЙДЕН: {task.spec.name}",
                f"  {task.flag}",
                f"  Уверенность: {task.flag_confidence}% (верифицирован)",
                f"  Writeup: {task.writeup_path}",
                "════════════════════════════════════════",
            ]
        )
        print(banner, flush=True)
        self._log(f"Флаг найден для {task.spec.name}")

    def _log(self, message: str) -> None:
        print(message, flush=True)
        if self.snapshot is not None:
            self.snapshot.event_log.append(f"{utc_now()} {message}")
            max_entries = max(1, self.config.limits.event_log_max_entries)
            if len(self.snapshot.event_log) > max_entries:
                self.snapshot.event_log = self.snapshot.event_log[-max_entries:]
        self._touch_state()

    def _touch_state(self) -> None:
        self.state_dirty = True

    def _tool_cache_dir(self, profile: str) -> Path:
        return ensure_dir(self.tool_cache_root / profile)


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config_path, args)
    orchestrator = SwarmOrchestrator(config, args, project_root=Path.cwd())
    return await orchestrator.run()
