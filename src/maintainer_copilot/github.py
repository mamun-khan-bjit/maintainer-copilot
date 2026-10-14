import hashlib
import json
import time
from pathlib import Path

import httpx

API_URL = "https://api.github.com"


class GitHubClient:
    """Read-only GitHub REST client with ETag caching and rate-limit backoff."""

    def __init__(self, token: str, cache_dir: Path = Path("data/http_cache"), min_remaining: int = 50):
        # Step 1: build one shared HTTP client with auth, JSON media type and a pinned API version.
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
        # Step 2: make sure the on-disk ETag cache directory exists.
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        # Step 3: remember the low-quota threshold and set up rate-limit state and counters.
        self._min_remaining = min_remaining
        self.rate_remaining: int | None = None
        self.stats = {"requests": 0, "not_modified": 0, "rate_limit_waits": 0}

    def get(self, url: str, *, params: dict | None = None, raw: bool = False):
        """Return (data, next_page_url). Repeated calls send If-None-Match and reuse the cached body on 304."""
        # Step 1: resolve the final URL (base + path + query) so it can serve as a stable cache key.
        full_url = str(self._http.build_request("GET", url, params=params).url)
        # Step 2: look up a previously cached response for this exact URL.
        cache_file = self._cache_dir / (hashlib.sha256(full_url.encode()).hexdigest() + ".json")
        cached = json.loads(cache_file.read_text()) if cache_file.exists() else None

        # Step 3: build per-request headers: raw content type if asked, and the ETag for a conditional request.
        headers = {}
        if raw:
            headers["Accept"] = "application/vnd.github.raw+json"
        if cached:
            headers["If-None-Match"] = cached["etag"]

        # Step 4: send the request (rate-limit handling lives in _send).
        response = self._send(full_url, headers)
        # Step 5: on 304, serve the cached body instead of re-downloading.
        if response.status_code == 304:
            # Unchanged since last time; GitHub doesn't count conditional 304s against the quota.
            self.stats["not_modified"] += 1
            return cached["data"], cached["next"]
        # Step 6: any other non-2xx status is a real error.
        response.raise_for_status()

        # Step 7: parse the body and the next-page link from the Link header.
        data = response.text if raw else response.json()
        next_url = response.links.get("next", {}).get("url")
        # Step 8: store the fresh body with its ETag so the next call can be conditional.
        if etag := response.headers.get("etag"):
            cache_file.write_text(json.dumps({"etag": etag, "data": data, "next": next_url}))
        return data, next_url

    def paginate(self, url: str, *, params: dict | None = None):
        """Yield items from every page, following the Link header's rel="next"."""
        # Keep fetching until GitHub stops returning a rel="next" link.
        while url:
            # Step 1: fetch the current page and the URL of the following one.
            page, url = self.get(url, params=params)
            # Step 2: drop params after the first page.
            params = None  # the next URL already carries the query string
            # Step 3: hand each item on this page to the caller.
            yield from page

    def _send(self, url: str, headers: dict) -> httpx.Response:
        # Loop so a rate-limited request can be retried after waiting.
        while True:
            # Step 1: make the request and count it.
            response = self._http.get(url, headers=headers)
            self.stats["requests"] += 1
            # Step 2: read the quota left and when the current window resets (epoch seconds).
            self.rate_remaining = int(response.headers.get("x-ratelimit-remaining", 1))
            reset_at = int(response.headers.get("x-ratelimit-reset", 0))

            # Step 3: secondary rate limit: GitHub says exactly how long to back off.
            if response.status_code in (403, 429) and "retry-after" in response.headers:
                self._sleep(int(response.headers["retry-after"]), "secondary rate limit")
                continue
            # Step 4: primary limit exhausted: wait for the window to reset, then retry the same request.
            if response.status_code in (403, 429) and self.rate_remaining == 0:
                self._sleep(reset_at - time.time(), "rate limit exhausted")
                continue
            # Step 5: running low: let this response through, but pause before the next request.
            if self.rate_remaining < self._min_remaining:
                self._sleep(reset_at - time.time(), f"only {self.rate_remaining} requests left")
            # Step 6: return the usable response to the caller.
            return response

    def _sleep(self, seconds: float, reason: str) -> None:
        # Step 1: never sleep a negative time, and add 1s slack for clock skew.
        seconds = max(seconds, 0) + 1
        # Step 2: record and report the wait.
        self.stats["rate_limit_waits"] += 1
        print(f"waiting {seconds:.0f}s ({reason})")
        # Step 3: block until it's safe to send again.
        time.sleep(seconds)
