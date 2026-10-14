import pytest

from maintainer_copilot.config import settings
from maintainer_copilot.gateway.pricing import cost_usd


def test_local_model_is_free():
    assert cost_usd("qwen2.5:3b", input_tokens=2206, output_tokens=107) == 0.0


def test_unknown_model_has_no_price():
    assert cost_usd("model-nobody-priced", input_tokens=1000, output_tokens=1000) is None


def test_cost_formula(monkeypatch):
    # A made-up price, so the test doesn't depend on any provider's real prices.
    monkeypatch.setitem(settings.llm_prices, "test-model", {"input": 2.0, "output": 8.0})
    # 1M input tokens at $2 + 0.5M output tokens at $8 = $2 + $4
    assert cost_usd("test-model", input_tokens=1_000_000, output_tokens=500_000) == pytest.approx(6.0)
