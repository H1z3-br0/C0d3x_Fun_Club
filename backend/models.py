"""Model utilities — CLIProxyAPI.

All routing happens through cli-proxy-api's OpenAI-compatible `/v1/chat/completions`
endpoint. The `provider/` prefix in specs is informational and optionally maps onto
cli-proxy-api's `force-model-prefix` feature when enabled in cliproxyapi/config.yaml.
By default (`force-model-prefix: false`) the prefix is stripped at call time via
`model_id_from_spec` and the upstream is selected by alias matching inside the proxy.
"""

from __future__ import annotations

ONLY_MODEL_ID = "gpt-5.5"
ONLY_MODEL_SPEC = f"codex/{ONLY_MODEL_ID}"

# Default model specs - one entry per unique solver.
# This project is intentionally locked to GPT-5.5 only.
DEFAULT_MODELS: list[str] = [ONLY_MODEL_SPEC]

# Context window sizes (tokens)
CONTEXT_WINDOWS: dict[str, int] = {
    ONLY_MODEL_ID: 1_000_000,
}

# Models that support vision
VISION_MODELS: set[str] = {ONLY_MODEL_ID}


def model_id_from_spec(spec: str) -> str:
    """Extract just the model ID from a spec."""
    spec = spec.strip()
    parts = spec.split("/", 1)
    return parts[1] if len(parts) == 2 else spec


def provider_from_spec(spec: str) -> str:
    """Extract the provider from a spec."""
    return spec.split("/", 1)[0]


def is_allowed_model(spec: str) -> bool:
    """Return True only for the single supported model."""
    return model_id_from_spec(spec) == ONLY_MODEL_ID


def validate_model_spec(spec: str) -> str:
    """Validate a single model spec and return it unchanged."""
    if not is_allowed_model(spec):
        raise ValueError(f"Unsupported model '{spec}'. Only {ONLY_MODEL_ID} is allowed.")
    return spec


def validate_model_specs(specs: list[str]) -> list[str]:
    """Validate solver model specs."""
    if not specs:
        return list(DEFAULT_MODELS)
    for spec in specs:
        validate_model_spec(spec)
    return specs


def supports_vision(spec: str) -> bool:
    """Check if a model spec supports vision."""
    return model_id_from_spec(spec) in VISION_MODELS


def context_window(spec: str) -> int:
    """Get context window size for a model spec."""
    return CONTEXT_WINDOWS.get(model_id_from_spec(spec), 200_000)
