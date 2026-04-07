"""Model utilities — CLIProxyAPI."""

from __future__ import annotations


# Default model specs — all available solvers
DEFAULT_MODELS: list[str] = [
    "codex/gpt-5.4",
    "codex/gpt-5.4-mini",
    "codex/gpt-5.3-codex",
    "codex/gpt-5.4",
    "codex/gpt-5.4-mini",
]

# Context window sizes (tokens)
CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-5.4": 1_000_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.3-codex": 1_000_000,
    "gpt-5.3-codex-spark": 128_000,
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
}

# Models that support vision
VISION_MODELS: set[str] = {
    "gpt-5.4",
    "gpt-5.4-mini",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
}


def model_id_from_spec(spec: str) -> str:
    """Extract just the model ID from a spec (strips effort suffix)."""
    parts = spec.split("/")
    return parts[1] if len(parts) >= 2 else spec


def provider_from_spec(spec: str) -> str:
    """Extract the provider from a spec."""
    return spec.split("/", 1)[0]


def supports_vision(spec: str) -> bool:
    """Check if a model spec supports vision."""
    return model_id_from_spec(spec) in VISION_MODELS


def context_window(spec: str) -> int:
    """Get context window size for a model spec."""
    return CONTEXT_WINDOWS.get(model_id_from_spec(spec), 200_000)
