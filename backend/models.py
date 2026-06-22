"""Model utilities — CLIProxyAPI.

All routing happens through cli-proxy-api's OpenAI-compatible `/v1/chat/completions`
endpoint. The `provider/` prefix in specs (`codex/`, `claude/`) is informational and
optionally maps onto cli-proxy-api's `force-model-prefix` feature when enabled in
cliproxyapi/config.yaml. By default (`force-model-prefix: false`) the prefix is
stripped at call time via `model_id_from_spec` and the upstream is selected by alias
matching inside the proxy. Each model id below must be exposed as an alias by your
cliproxyapi/config.yaml (Codex OAuth for GPT-5.5, Claude OAuth for the Opus models).
"""

from __future__ import annotations

# --- Supported models -------------------------------------------------------
# One entry per unique solver model. Specs carry an informational provider prefix;
# only the id after the slash is sent to the proxy.
GPT_5_5 = "gpt-5.5"
OPUS_4_8 = "claude-opus-4-8"
OPUS_4_7 = "claude-opus-4-7"

# provider prefix used both for cost attribution and as a routing hint.
PROVIDER_BY_ID: dict[str, str] = {
    GPT_5_5: "codex",
    OPUS_4_8: "claude",
    OPUS_4_7: "claude",
}

ALLOWED_MODEL_IDS: set[str] = set(PROVIDER_BY_ID)

# Default solver hive — GPT-5.5 raced against both Claude Opus models. Override
# with --models to run a subset (e.g. just `codex/gpt-5.5`).
DEFAULT_MODELS: list[str] = [
    f"codex/{GPT_5_5}",
    f"claude/{OPUS_4_8}",
    f"claude/{OPUS_4_7}",
]

# Coordinator defaults to GPT-5.5 — cheaper for the high-frequency orchestration loop.
DEFAULT_COORDINATOR_MODEL = f"codex/{GPT_5_5}"

# Human-readable allow-list for CLI help / error messages.
ALLOWED_MODELS_HELP = ", ".join(sorted(ALLOWED_MODEL_IDS))

# Context window sizes (tokens)
CONTEXT_WINDOWS: dict[str, int] = {
    GPT_5_5: 1_000_000,
    OPUS_4_8: 1_000_000,
    OPUS_4_7: 1_000_000,
}

# Models that support image input (vision)
VISION_MODELS: set[str] = {GPT_5_5, OPUS_4_8, OPUS_4_7}


def model_id_from_spec(spec: str) -> str:
    """Extract just the model ID from a spec."""
    spec = spec.strip()
    parts = spec.split("/", 1)
    return parts[1] if len(parts) == 2 else spec


def provider_from_spec(spec: str) -> str:
    """Extract the provider for a spec.

    Prefers an explicit `provider/` prefix; otherwise infers from the model id
    (e.g. a bare `claude-opus-4-8` resolves to `claude`).
    """
    spec = spec.strip()
    if "/" in spec:
        return spec.split("/", 1)[0]
    return PROVIDER_BY_ID.get(model_id_from_spec(spec), "")


def is_allowed_model(spec: str) -> bool:
    """Return True for any supported model id."""
    return model_id_from_spec(spec) in ALLOWED_MODEL_IDS


def validate_model_spec(spec: str) -> str:
    """Validate a single model spec and return it unchanged."""
    if not is_allowed_model(spec):
        raise ValueError(
            f"Unsupported model '{spec}'. Allowed model ids: {ALLOWED_MODELS_HELP}."
        )
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
