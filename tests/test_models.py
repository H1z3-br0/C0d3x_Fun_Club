import pytest

from backend.models import (
    ALLOWED_MODEL_IDS,
    DEFAULT_MODELS,
    context_window,
    model_id_from_spec,
    provider_from_spec,
    supports_vision,
    validate_model_spec,
    validate_model_specs,
)


def test_default_hive_is_the_three_supported_models():
    assert validate_model_specs(DEFAULT_MODELS) == DEFAULT_MODELS
    ids = {model_id_from_spec(s) for s in DEFAULT_MODELS}
    assert ids == ALLOWED_MODEL_IDS == {"gpt-5.5", "claude-opus-4-8", "claude-opus-4-7"}


@pytest.mark.parametrize(
    "spec, provider",
    [
        ("codex/gpt-5.5", "codex"),
        ("claude/claude-opus-4-8", "claude"),
        ("claude-opus-4-7", "claude"),  # bare id → provider inferred
        ("gpt-5.5", "codex"),
    ],
)
def test_provider_inference(spec, provider):
    assert provider_from_spec(spec) == provider


@pytest.mark.parametrize("spec", ["codex/gpt-5.5", "claude/claude-opus-4-8", "claude-opus-4-7"])
def test_supported_models_have_vision_and_context(spec):
    assert supports_vision(spec) is True
    assert context_window(spec) == 1_000_000


@pytest.mark.parametrize("spec", ["gpt-4", "claude/claude-3-opus", "gemini-pro", ""])
def test_unsupported_models_rejected(spec):
    with pytest.raises(ValueError):
        validate_model_spec(spec)


def test_empty_specs_fall_back_to_default():
    assert validate_model_specs([]) == DEFAULT_MODELS
