from maintainer_copilot.config import settings

TOKENS_PER_PRICE_UNIT = 1_000_000  # prices are quoted per 1M tokens


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Return the USD cost of one call, or None if we don't know this model's price.

    None is deliberate: reporting 0 for an unknown model would silently make it look free.
    """
    price = settings.llm_prices.get(model)
    if price is None:
        return None
    total = input_tokens * price["input"] + output_tokens * price["output"]
    return total / TOKENS_PER_PRICE_UNIT
