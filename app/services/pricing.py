import logging
from decimal import Decimal

import genai_prices
from genai_prices.types import TieredPrices
from pydantic_ai.usage import RequestUsage

logger = logging.getLogger(__name__)


def _base_rate(price: Decimal | TieredPrices) -> Decimal:
    """Collapse a possibly-tiered per-mtok price to its base (lowest-volume) rate."""
    return price.base if isinstance(price, TieredPrices) else price


def estimate_cost(
    provider: str, model: str, input_tokens: int, output_tokens: int
) -> Decimal:
    usage = RequestUsage(input_tokens=input_tokens, output_tokens=output_tokens)
    try:
        result = genai_prices.calc_price(usage, model, provider_id=provider)
        return result.total_price
    except Exception:
        logger.warning(
            "Cost estimation failed for %s/%s", provider, model, exc_info=True
        )
        return Decimal(0)


def get_model_pricing(
    provider: str, model: str
) -> tuple[Decimal | None, Decimal | None]:
    """Return (input_price_per_mtok, output_price_per_mtok), or (None, None)
    when genai_prices doesn't recognize this provider/model combination."""
    usage = RequestUsage(input_tokens=1, output_tokens=1)
    try:
        result = genai_prices.calc_price(usage, model, provider_id=provider)
        return (
            _base_rate(result.model_price.input_mtok),
            _base_rate(result.model_price.output_mtok),
        )
    except Exception:
        logger.debug("No pricing data available for %s/%s", provider, model)
        return None, None
