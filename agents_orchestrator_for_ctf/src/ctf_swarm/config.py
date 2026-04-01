from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .utils import load_yaml_file


@dataclass
class EndpointConfig:
    base_url: str = "http://localhost:8080/v1"
    api_key: str = "cli-proxy-local"
    timeout_seconds: int = 180


@dataclass
class PoolConfig:
    model: str
    emails: list[str] = field(default_factory=list)
    base_url: str | None = None
    api_key: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any], default_model: str) -> PoolConfig:
        return cls(
            model=str(payload.get("model", default_model)),
            emails=[str(item) for item in payload.get("emails", [])],
            base_url=payload.get("base_url"),
            api_key=payload.get("api_key"),
        )


@dataclass
class AccountsConfig:
    cc_master: PoolConfig
    cc_support: PoolConfig
    smart_reserve: PoolConfig
    executors: PoolConfig


@dataclass
class LimitsConfig:
    worker_max_steps: int = 15
    worker_timeout_seconds: int = 300
    max_parallel_workers: int = 15
    planner_parallelism: int = 4
    cc_usage_warning_pct: float = 0.80
    rate_limit_backoff_seconds: int = 65
    llm_max_retries: int = 2
    cc_token_soft_limit: int = 600_000
    cc_request_soft_limit: int = 50
    cc_step_soft_limit: int = 120
    state_checkpoint_interval_seconds: float = 2.0
    event_log_max_entries: int = 1_000
    ctfd_refresh_interval_seconds: int = 90


@dataclass
class SandboxConfig:
    enabled: bool = True
    network_disabled: bool = True
    docker_image: str = "ctf-swarm:base"
    auto_build_image: bool = False


@dataclass
class CTFConfig:
    flag_format: str = "CTF{...}"


@dataclass
class PathsConfig:
    workspace_root: str = "workspace"


@dataclass
class AppConfig:
    cliproxyapi: EndpointConfig
    accounts: AccountsConfig
    limits: LimitsConfig
    sandbox: SandboxConfig
    ctf: CTFConfig
    paths: PathsConfig


@dataclass
class RunArgs:
    mode: str
    task_dir: str | None
    config_path: str
    flag_format: str | None
    ctfd_url: str | None
    ctfd_token: str | None
    ctfd_session: str | None
    resume: bool


def parse_args(argv: list[str] | None = None) -> RunArgs:
    parser = argparse.ArgumentParser(description="CTF multi-agent swarm orchestrator")
    parser.add_argument("--mode", choices=["single", "multi"], default="single")
    parser.add_argument("--task-dir", help="Папка одной задачи для SINGLE режима")
    parser.add_argument("--config", default="config.yaml", help="Путь к config.yaml")
    parser.add_argument("--flag-format", help='Пример формата флага, например "CTF{...}"')
    parser.add_argument("--ctfd-url", help="URL CTFd для MULTI режима")
    parser.add_argument(
        "--ctfd-token",
        default=os.getenv("CTF_CTFD_TOKEN"),
        help="API token CTFd (или env CTF_CTFD_TOKEN)",
    )
    parser.add_argument(
        "--ctfd-session",
        default=os.getenv("CTF_CTFD_SESSION"),
        help="Session cookie CTFd (или env CTF_CTFD_SESSION)",
    )
    parser.add_argument(
        "--resume", action="store_true", help="Восстановить состояние из workspace/state"
    )
    args = parser.parse_args(argv)

    return RunArgs(
        mode=args.mode,
        task_dir=args.task_dir,
        config_path=args.config,
        flag_format=args.flag_format,
        ctfd_url=args.ctfd_url,
        ctfd_token=args.ctfd_token,
        ctfd_session=args.ctfd_session,
        resume=args.resume,
    )


def load_config(config_path: str, overrides: RunArgs) -> AppConfig:
    path = Path(config_path)
    raw = load_yaml_file(path)

    endpoint_raw = raw.get("cliproxyapi", {})
    endpoint = EndpointConfig(
        base_url=str(endpoint_raw.get("base_url", "http://localhost:8080/v1")),
        api_key=str(endpoint_raw.get("api_key", "cli-proxy-local")),
        timeout_seconds=int(endpoint_raw.get("timeout_seconds", 180)),
    )

    accounts_raw = raw.get("accounts", {})
    accounts = AccountsConfig(
        cc_master=PoolConfig.from_dict(accounts_raw.get("cc_master", {}), "claude-code"),
        cc_support=PoolConfig.from_dict(accounts_raw.get("cc_support", {}), "claude-code"),
        smart_reserve=PoolConfig.from_dict(accounts_raw.get("smart_reserve", {}), "codex"),
        executors=PoolConfig.from_dict(accounts_raw.get("executors", {}), "codex"),
    )

    limits_raw = raw.get("limits", {})
    limits = LimitsConfig(
        worker_max_steps=int(limits_raw.get("worker_max_steps", 15)),
        worker_timeout_seconds=int(limits_raw.get("worker_timeout_seconds", 300)),
        max_parallel_workers=int(limits_raw.get("max_parallel_workers", 15)),
        planner_parallelism=int(limits_raw.get("planner_parallelism", 4)),
        cc_usage_warning_pct=float(limits_raw.get("cc_usage_warning_pct", 0.80)),
        rate_limit_backoff_seconds=int(limits_raw.get("rate_limit_backoff_seconds", 65)),
        llm_max_retries=int(limits_raw.get("llm_max_retries", 2)),
        cc_token_soft_limit=int(limits_raw.get("cc_token_soft_limit", 600_000)),
        cc_request_soft_limit=int(limits_raw.get("cc_request_soft_limit", 50)),
        cc_step_soft_limit=int(limits_raw.get("cc_step_soft_limit", 120)),
        state_checkpoint_interval_seconds=float(
            limits_raw.get("state_checkpoint_interval_seconds", 2.0)
        ),
        event_log_max_entries=int(limits_raw.get("event_log_max_entries", 1_000)),
        ctfd_refresh_interval_seconds=int(limits_raw.get("ctfd_refresh_interval_seconds", 90)),
    )

    sandbox_raw = raw.get("sandbox", {})
    sandbox = SandboxConfig(
        enabled=bool(sandbox_raw.get("enabled", True)),
        network_disabled=bool(sandbox_raw.get("network_disabled", True)),
        docker_image=str(sandbox_raw.get("docker_image", "ctf-swarm:base")),
        auto_build_image=bool(sandbox_raw.get("auto_build_image", False)),
    )

    ctf_raw = raw.get("ctf", {})
    ctf = CTFConfig(flag_format=str(ctf_raw.get("flag_format", "CTF{...}")))
    if overrides.flag_format:
        ctf.flag_format = overrides.flag_format

    paths_raw = raw.get("paths", {})
    paths = PathsConfig(workspace_root=str(paths_raw.get("workspace_root", "workspace")))

    return AppConfig(
        cliproxyapi=endpoint,
        accounts=accounts,
        limits=limits,
        sandbox=sandbox,
        ctf=ctf,
        paths=paths,
    )
