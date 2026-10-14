import random
import time

import structlog
from openai import OpenAI, RateLimitError

from maintainer_copilot.config import settings
from maintainer_copilot.db import record_llm_call
from maintainer_copilot.gateway.pricing import cost_usd

MAX_ATTEMPTS = 4
BASE_DELAY = 1.0
log = structlog.get_logger()


class LLMGateway:
    """The only place in the app that talks to an LLM provider."""

    def __init__(self, client=None, sleep=time.sleep, recorder=record_llm_call):
        self._client = client or OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=30,
            max_retries=0,
        )
        self._sleep = sleep
        self._recorder = recorder

    def chat(self, messages, model=None, task="chat"):
        response = self._call(self._client.chat.completions.create, messages, model, task)
        return response.choices[0].message.content

    def parse(self, messages, response_format, model=None, task="parse"):
        """Return an instance of response_format (a Pydantic model) filled in by the LLM."""
        response = self._call(
            self._client.chat.completions.parse, messages, model, task, response_format=response_format
        )
        return response.choices[0].message.parsed

    def _call(self, method, messages, model, task, **kwargs):
        model = model or settings.llm_model
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                response = method(model=model, messages=messages, **kwargs)
            except RateLimitError as error:
                if attempt == MAX_ATTEMPTS:
                    log.error("llm.rate_limited.giving_up", model=model, attempts=attempt)
                    raise
                delay = self._retry_delay(error, attempt)
                log.warning("llm.rate_limited", model=model, attempt=attempt, retry_in_s=round(delay, 2))
                self._sleep(delay)
                continue

            call = {
                # request_id was bound by the API middleware (or by a CLI script) for this unit of work.
                "request_id": structlog.contextvars.get_contextvars().get("request_id"),
                "task": task,
                "model": model,
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "cost_usd": cost_usd(model, response.usage.prompt_tokens, response.usage.completion_tokens),
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "attempt": attempt,
            }
            log.info("llm.call", **call)
            self._record(call)
            return response

    def _record(self, call):
        # Bookkeeping must never break the user-facing call: a DB hiccup costs a row, not a triage.
        try:
            self._recorder(call)
        except Exception:
            log.warning("llm.call_not_recorded", task=call["task"], exc_info=True)

    def _retry_delay(self, error, attempt):
        retry_after = error.response.headers.get("retry-after")
        if retry_after:
            return float(retry_after)
        return BASE_DELAY * 2 ** (attempt - 1) + random.uniform(0, 1)
