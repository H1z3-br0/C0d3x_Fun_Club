"""Pydantic Settings — credentials from .env file + environment variables."""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # CTFd
    ctfd_url: str = "http://localhost:8000"
    ctfd_user: str = "admin"
    ctfd_pass: str = "admin"
    ctfd_token: str = ""

    # CLIProxyAPI (OpenAI-compatible local proxy).
    #
    # We do NOT talk to OpenAI/Anthropic/Gemini directly. The proxy holds the
    # upstream OAuth credentials under ~/.cli-proxy-api/*.json and fans out
    # internally. `cliproxy_api_key` is the *client-side access key* to the
    # local proxy — one of the entries in `api-keys:` from cliproxyapi/config.yaml.
    # Pick any of them (or generate your own with `openssl rand -hex 32` and
    # paste it into that config).
    #
    # OPENAI_API_KEY is accepted as a legacy alias so older .env files keep working.
    openai_base_url: str = "http://127.0.0.1:8317/v1"
    cliproxy_api_key: str = ""

    # Infra
    # sandbox_image=None → solver picks a profile image per challenge category
    # (see backend/profiles.py:suggest_profile). Set via --image to force one.
    sandbox_image: str | None = None
    max_concurrent_challenges: int = 10
    max_attempts_per_challenge: int = 3
    container_memory_limit: str = "16g"
    findings_dir: str = "findings"
    memory_dir: str = "findings/memory"
    context_limit_pct: float = 0.80  # Rotate agent when prompt tokens reach this fraction of context window

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    def model_post_init(self, __ctx: object) -> None:
        # Legacy: accept OPENAI_API_KEY as an alias for CLIPROXY_API_KEY.
        if not self.cliproxy_api_key:
            legacy = os.environ.get("OPENAI_API_KEY", "")
            if legacy:
                self.cliproxy_api_key = legacy
