import hashlib
import json
import time
from pathlib import Path

import httpx

API_URL = "https://api.github.com"


class GitHubClient:
    """Read-only GitHub REST client with ETag caching and rate-limit backoff."""

    def __init__(self, token: str, cache_dir: Path = Path("data/http_cache"), min_remaining: int = 50):
        self._http = httpx.Client(
            base_url=API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
            follow_redirects=True,
        )
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._min_remaining = min_remaining
        self.rate_remaining: int | None = None
        self.stats = {"requests": 0, "not_modified": 0, "rate_limit_waits": 0}

    def get(self, url: str, *, params: dict | None = None, raw: bool = False):
        """Return (data, next_page_url). Repeated calls send If-None-Match and reuse the cached body on 304."""
        full_url = str(self._http.build_request("GET", url, params=params).url)
        cache_file = self._cache_dir / (hashlib.sha256(full_url.encode()).hexdigest() + ".json")
        cached = json.loads(cache_file.read_text()) if cache_file.exists() else None

        headers = {}
        if raw:
            headers["Accept"] = "application/vnd.github.raw+json"
        if cached:
            headers["If-None-Match"] = cached["etag"]

        response = self._send(full_url, headers)
        if response.status_code == 304:
            # Unchanged since last time; GitHub doesn't count conditional 304s against the quota.
            self.stats["not_modified"] += 1
            return cached["data"], cached["next"]
        response.raise_for_status()

        data = response.text if raw else response.json()
        next_url = response.links.get("next", {}).get("url")
        if etag := response.headers.get("etag"):
            cache_file.write_text(json.dumps({"etag": etag, "data": data, "next": next_url}))
        return data, next_url

    def paginate(self, url: str, *, params: dict | None = None):
        """Yield items from every page, following the Link header's rel="next"."""
        while url:
            page, url = self.get(url, params=params)
            params = None  # the next URL already carries the query string
            yield from page

    def _send(self, url: str, headers: dict) -> httpx.Response:
        while True:
            response = self._http.get(url, headers=headers)
            self.stats["requests"] += 1
            self.rate_remaining = int(response.headers.get("x-ratelimit-remaining", 1))
            reset_at = int(response.headers.get("x-ratelimit-reset", 0))

            # Secondary rate limit: GitHub says exactly how long to back off.
            if response.status_code in (403, 429) and "retry-after" in response.headers:
                self._sleep(int(response.headers["retry-after"]), "secondary rate limit")
                continue
            # Primary limit exhausted: wait for the window to reset, then retry the same request.
            if response.status_code in (403, 429) and self.rate_remaining == 0:
                self._sleep(reset_at - time.time(), "rate limit exhausted")
                continue
            # Running low: let this response through, but pause before the next request.
            if self.rate_remaining < self._min_remaining:
                self._sleep(reset_at - time.time(), f"only {self.rate_remaining} requests left")
            return response

    def _sleep(self, seconds: float, reason: str) -> None:
        seconds = max(seconds, 0) + 1
        self.stats["rate_limit_waits"] += 1
        print(f"waiting {seconds:.0f}s ({reason})")
        time.sleep(seconds)
