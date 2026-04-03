"""Pydantic Settings — credentials from .env file + environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # CTFd
    ctfd_url: str = "http://localhost:8000"
    ctfd_user: str = "admin"
    ctfd_pass: str = "admin"
    ctfd_token: str = ""

    # OpenAI-compatible API (CLIProxyAPI)
    openai_base_url: str = "http://localhost:8080/v1"
    openai_api_key: str = ""

    # Infra
    sandbox_image: str = "ctf-swarm:base"
    max_concurrent_challenges: int = 10
    max_attempts_per_challenge: int = 3
    container_memory_limit: str = "16g"
    findings_dir: str = "findings"
    memory_dir: str = "findings/memory"
    context_limit_pct: float = 0.80  # Rotate agent when prompt tokens reach this fraction of context window

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}
