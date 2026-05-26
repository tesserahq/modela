import logging
from decimal import Decimal

import genai_prices
from pydantic_ai.usage import RequestUsage

logger = logging.getLogger(__name__)


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
        return Decimal("0")
