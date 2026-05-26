from decimal import Decimal

from app.services.pricing import estimate_cost


def test_known_model_returns_positive_cost():
    cost = estimate_cost("openai", "gpt-4o", input_tokens=1000, output_tokens=500)
    assert cost > Decimal("0")


def test_anthropic_known_model_returns_positive_cost():
    cost = estimate_cost(
        "anthropic",
        "claude-3-5-sonnet-20241022",
        input_tokens=1000,
        output_tokens=500,
    )
    assert cost > Decimal("0")


def test_unknown_model_returns_zero():
    cost = estimate_cost(
        "openai", "not-a-real-model-xyz", input_tokens=1000, output_tokens=500
    )
    assert cost == Decimal("0")


def test_unknown_provider_returns_zero():
    cost = estimate_cost("fakeprovider", "gpt-4o", input_tokens=1000, output_tokens=500)
    assert cost == Decimal("0")


def test_zero_tokens_returns_zero():
    cost = estimate_cost("openai", "gpt-4o", input_tokens=0, output_tokens=0)
    assert cost == Decimal("0")


def test_output_tokens_contribute_to_cost():
    cost_low = estimate_cost("openai", "gpt-4o", input_tokens=100, output_tokens=10)
    cost_high = estimate_cost("openai", "gpt-4o", input_tokens=100, output_tokens=1000)
    assert cost_high > cost_low
