import random
import time

import structlog
from openai import OpenAI, RateLimitError

from maintainer_copilot.config import settings

MAX_ATTEMPTS = 4
BASE_DELAY = 1.0
log = structlog.get_logger()


class LLMGateway:
    """The only place in the app that talks to an LLM provider."""

    def __init__(self, client=None, sleep=time.sleep):
        self._client = client or OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=30,
            max_retries=0,
        )
        self._sleep = sleep

    def chat(self, messages, model=None):
        response = self._call(self._client.chat.completions.create, messages, model)
        return response.choices[0].message.content

    def parse(self, messages, response_format, model=None):
        """Return an instance of response_format (a Pydantic model) filled in by the LLM."""
        response = self._call(
            self._client.chat.completions.parse, messages, model, response_format=response_format
        )
        return response.choices[0].message.parsed

    def _call(self, method, messages, model, **kwargs):
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

            log.info(
                "llm.call",
                model=model,
                latency_ms=round((time.perf_counter() - started) * 1000),
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                attempt=attempt,
            )
            return response

    def _retry_delay(self, error, attempt):
        retry_after = error.response.headers.get("retry-after")
        if retry_after:
            return float(retry_after)
        return BASE_DELAY * 2 ** (attempt - 1) + random.uniform(0, 1)
