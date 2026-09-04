from decimal import Decimal

from app.services.pricing import estimate_cost, get_model_pricing


def test_known_model_returns_positive_cost():
    cost = estimate_cost("openai", "gpt-4o", input_tokens=1000, output_tokens=500)
    assert cost > Decimal(0)


def test_anthropic_known_model_returns_positive_cost():
    cost = estimate_cost(
        "anthropic",
        "claude-3-5-sonnet-20241022",
        input_tokens=1000,
        output_tokens=500,
    )
    assert cost > Decimal(0)


def test_unknown_model_returns_zero():
    cost = estimate_cost(
        "openai", "not-a-real-model-xyz", input_tokens=1000, output_tokens=500
    )
    assert cost == Decimal(0)


def test_unknown_provider_returns_zero():
    cost = estimate_cost("fakeprovider", "gpt-4o", input_tokens=1000, output_tokens=500)
    assert cost == Decimal(0)


def test_zero_tokens_returns_zero():
    cost = estimate_cost("openai", "gpt-4o", input_tokens=0, output_tokens=0)
    assert cost == Decimal(0)


def test_output_tokens_contribute_to_cost():
    cost_low = estimate_cost("openai", "gpt-4o", input_tokens=100, output_tokens=10)
    cost_high = estimate_cost("openai", "gpt-4o", input_tokens=100, output_tokens=1000)
    assert cost_high > cost_low


def test_get_model_pricing_returns_rates_for_known_model():
    input_price, output_price = get_model_pricing("openai", "gpt-4o")

    assert input_price is not None
    assert output_price is not None
    assert input_price > Decimal(0)
    assert output_price > Decimal(0)


def test_get_model_pricing_returns_none_for_unknown_model():
    input_price, output_price = get_model_pricing("openai", "not-a-real-model-xyz")

    assert input_price is None
    assert output_price is None


def test_get_model_pricing_returns_none_for_unknown_provider():
    input_price, output_price = get_model_pricing("fakeprovider", "gpt-4o")

    assert input_price is None
    assert output_price is None


def test_get_model_pricing_collapses_tiered_pricing_to_a_plain_decimal():
    # claude-sonnet-4-5-20250929 has volume-based tiered pricing in genai_prices;
    # this must still come back as a single Decimal, not a TieredPrices object.
    input_price, output_price = get_model_pricing(
        "anthropic", "claude-sonnet-4-5-20250929"
    )

    assert isinstance(input_price, Decimal)
    assert isinstance(output_price, Decimal)
    assert input_price > Decimal(0)
    assert output_price > Decimal(0)
