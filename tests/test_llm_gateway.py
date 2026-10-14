from types import SimpleNamespace

import httpx
import pytest
import structlog
from openai import RateLimitError

from maintainer_copilot.gateway.llm import LLMGateway


def rate_limit_error(retry_after=None):
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    headers = {"retry-after": retry_after} if retry_after else {}
    response = httpx.Response(429, headers=headers, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def ok_response(content="ok"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2),
    )


class FakeCompletions:
    """Plays back a scripted list of outcomes: an exception is raised, anything else is returned."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_gateway(outcomes):
    completions = FakeCompletions(outcomes)
    sleeps = []
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    gateway = LLMGateway(client=client, sleep=sleeps.append, recorder=lambda call: None)
    return gateway, completions, sleeps


def test_retries_twice_on_429_then_succeeds():
    gateway, completions, sleeps = make_gateway(
        [rate_limit_error(), rate_limit_error(retry_after="7"), ok_response("hello")]
    )

    result = gateway.chat([{"role": "user", "content": "hi"}])

    assert result == "hello"
    assert completions.calls == 3
    assert len(sleeps) == 2
    assert 1 <= sleeps[0] < 2  # first failure: exponential backoff, 2**0 + jitter
    assert sleeps[1] == 7    # second failure: Retry-After header wins


def test_gives_up_after_max_attempts():
    gateway, completions, sleeps = make_gateway([rate_limit_error()] * 4)

    with pytest.raises(RateLimitError):
        gateway.chat([{"role": "user", "content": "hi"}])

    assert completions.calls == 4

def test_records_one_row_per_successful_call():
    completions = FakeCompletions([rate_limit_error(), ok_response("hello")])
    recorded = []
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    gateway = LLMGateway(client=client, sleep=lambda seconds: None, recorder=recorded.append)

    structlog.contextvars.bind_contextvars(request_id="req-test-1")
    try:
        gateway.chat([{"role": "user", "content": "hi"}], task="unit-test")
    finally:
        structlog.contextvars.clear_contextvars()

    assert len(recorded) == 1  # the 429 attempt is not a billable call
    call = recorded[0]
    assert call["request_id"] == "req-test-1"
    assert call["task"] == "unit-test"
    assert call["attempt"] == 2
    assert (call["input_tokens"], call["output_tokens"]) == (10, 2)


def test_recording_failure_does_not_break_the_call():
    def broken_recorder(call):
        raise RuntimeError("database is down")

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions([ok_response("still fine")])))
    gateway = LLMGateway(client=client, sleep=lambda seconds: None, recorder=broken_recorder)

    assert gateway.chat([{"role": "user", "content": "hi"}]) == "still fine"
