from types import SimpleNamespace

import httpx
import pytest
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
    gateway = LLMGateway(client=client, sleep=sleeps.append)
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