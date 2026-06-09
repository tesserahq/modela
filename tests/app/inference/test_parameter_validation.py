import pytest

from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.inference.adapters.parameter_validation import (
    clamp_model_config_parameter,
    resolve_provider_settings,
    validate_model_config_parameters,
)
from app.inference.model import _apply_config_params
from app.models.model_config import ModelConfig


def test_validate_anthropic_temperature_above_max_raises():
    with pytest.raises(InvalidParameterError, match="temperature must be <= 1.0"):
        validate_model_config_parameters("anthropic", temperature=1.5)


def test_validate_openai_temperature_within_range_passes():
    validate_model_config_parameters("openai", temperature=1.5)


def test_validate_anthropic_temperature_within_range_passes():
    validate_model_config_parameters("anthropic", temperature=0.7)


def test_clamp_anthropic_temperature_above_max():
    assert clamp_model_config_parameter("anthropic", "temperature", 1.5) == 1.0


def test_validate_anthropic_temperature_and_top_p_both_set_raises():
    with pytest.raises(
        InvalidParameterError,
        match="temperature and top_p cannot both be set",
    ):
        validate_model_config_parameters("anthropic", temperature=0.7, top_p=0.9)


def test_resolve_provider_settings_prefers_temperature_over_top_p_for_anthropic():
    resolved = resolve_provider_settings(
        "anthropic", {"temperature": 0.7, "top_p": 0.9, "max_tokens": 1024}
    )

    assert resolved == {"temperature": 0.7, "max_tokens": 1024}


def test_apply_config_params_drops_top_p_when_both_set_for_anthropic():
    config = ModelConfig(
        slug="test",
        name="Test",
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        temperature=0.7,
        top_p=0.9,
    )

    settings = _apply_config_params(config, None)

    assert settings == {"temperature": 0.7}


def test_apply_config_params_clamps_anthropic_temperature():
    config = ModelConfig(
        slug="test",
        name="Test",
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        temperature=1.5,
    )

    settings = _apply_config_params(config, None)

    assert settings["temperature"] == 1.0
