"""Shared HTTP fetch: httpx + stamina exponential-backoff retry.

Retry policy (mirrors the house rule): only transient failures — connect errors,
timeouts, 429, and 5xx — are retried. Other 4xx raise immediately: a 404/403 on
a government dataset URL means the resource moved or was pulled, and retrying
would only mask it.
"""

from __future__ import annotations

import httpx
import stamina

USER_AGENT = (
    "ca-dollar-trace/0.1 "
    "(public-interest CA spending transparency; github.com/ca-dollar-trace)"
)


class TransientHTTPError(Exception):
    """A retryable failure: connect/timeout/429/5xx."""


@stamina.retry(on=TransientHTTPError, attempts=4, timeout=300)
def fetch_bytes(url: str, timeout_seconds: float = 120.0) -> bytes:
    try:
        resp = httpx.get(
            url,
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        raise TransientHTTPError(str(e)) from e
    if resp.status_code == 429 or resp.status_code >= 500:
        raise TransientHTTPError(f"HTTP {resp.status_code} from {url}")
    resp.raise_for_status()
    return resp.content


@stamina.retry(on=TransientHTTPError, attempts=4, timeout=300)
def fetch_json_post(url: str, body: dict, timeout_seconds: float = 120.0) -> bytes:
    """POST-with-JSON variant (USAspending-style search endpoints); same retry policy."""
    try:
        resp = httpx.post(
            url,
            json=body,
            timeout=timeout_seconds,
            headers={"User-Agent": USER_AGENT},
        )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        raise TransientHTTPError(str(e)) from e
    if resp.status_code == 429 or resp.status_code >= 500:
        raise TransientHTTPError(f"HTTP {resp.status_code} from {url}")
    resp.raise_for_status()
    return resp.content
