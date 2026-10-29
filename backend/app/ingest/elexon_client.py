"""Elexon Insights API client: retries with backoff and jitter, plus a gzipped raw cache.

The ``ElexonClient`` protocol is what the runner depends on; tests substitute a
fake. ``HttpElexonClient`` is the real implementation.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, Self

import httpx

from app.logging import get_logger

log = get_logger(__name__)

CacheMode = Literal["read_through", "refresh", "offline"]


class ElexonError(Exception):
    """Base class for ingest-visible Elexon failures."""


class ElexonResponseError(ElexonError):
    """Non-retryable: 4xx, HTML instead of JSON, or an unexpected payload shape."""


class ElexonUnavailableError(ElexonError):
    """Retries exhausted, network down, or slice missing from the cache in offline mode."""


@dataclass(frozen=True)
class FetchResult:
    rows: list[dict[str, Any]]
    url: str
    fetched_at: datetime
    from_cache: bool


class ElexonClient(Protocol):
    async def fetch_fuelhh(self, settlement_from: date, settlement_to: date) -> FetchResult:
        """FUELHH WIND rows for settlement dates in [from, to] (both inclusive, as Elexon)."""
        ...

    async def fetch_windfor(self, publish_from: datetime, publish_to: datetime) -> FetchResult:
        """Every WINDFOR vintage published in the window."""
        ...

    async def aclose(self) -> None: ...


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class HttpElexonClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 30.0,
        max_retries: int = 5,
        base_delay_s: float = 0.5,
        max_delay_s: float = 20.0,
        cache_dir: Path | None = None,
        cache_mode: CacheMode = "read_through",
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            timeout=timeout_s,
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": "windsight/0.1"},
        )
        self._max_retries = max_retries
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._cache_dir = cache_dir
        self._cache_mode = cache_mode
        self._sleep = sleep

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch_fuelhh(self, settlement_from: date, settlement_to: date) -> FetchResult:
        params = {
            "settlementDateFrom": settlement_from.isoformat(),
            "settlementDateTo": settlement_to.isoformat(),
            "fuelType": "WIND",
        }
        key = f"fuelhh_{settlement_from.isoformat()}_{settlement_to.isoformat()}"
        return await self._get("/datasets/FUELHH/stream", params, "FUELHH", key)

    async def fetch_windfor(self, publish_from: datetime, publish_to: datetime) -> FetchResult:
        params = {
            "publishDateTimeFrom": _iso_z(publish_from),
            "publishDateTimeTo": _iso_z(publish_to),
        }
        key = f"windfor_{publish_from:%Y%m%dT%H%M}_{publish_to:%Y%m%dT%H%M}"
        return await self._get("/datasets/WINDFOR/stream", params, "WINDFOR", key)

    # -- internals ---------------------------------------------------------

    def _cache_path(self, dataset: str, key: str) -> Path | None:
        return None if self._cache_dir is None else self._cache_dir / dataset / f"{key}.json.gz"

    async def _get(self, path: str, params: dict[str, str], dataset: str, key: str) -> FetchResult:
        url = str(httpx.URL(self._base_url + path, params=params))
        cache = self._cache_path(dataset, key)

        if cache is not None and self._cache_mode != "refresh" and cache.exists():
            blob = json.loads(gzip.decompress(cache.read_bytes()))
            return FetchResult(
                rows=blob["rows"],
                url=blob["url"],
                fetched_at=datetime.fromisoformat(blob["fetched_at"]),
                from_cache=True,
            )
        if self._cache_mode == "offline":
            raise ElexonUnavailableError(f"offline mode and no cached response for {key}")

        rows = await self._request_with_retries(url)
        fetched_at = datetime.now(UTC)
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".tmp")
            payload = {"url": url, "fetched_at": fetched_at.isoformat(), "rows": rows}
            tmp.write_bytes(gzip.compress(json.dumps(payload).encode(), compresslevel=9))
            tmp.replace(cache)
        return FetchResult(rows=rows, url=url, fetched_at=fetched_at, from_cache=False)

    async def _request_with_retries(self, url: str) -> list[dict[str, Any]]:
        last_error = "unknown"
        for attempt in range(self._max_retries + 1):
            retry_after: float | None = None
            try:
                resp = await self._http.get(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_error = f"HTTP {resp.status_code}"
                    retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                elif resp.status_code >= 400:
                    raise ElexonResponseError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                else:
                    return _parse_rows(resp)

            if attempt == self._max_retries:
                break
            backoff = min(self._max_delay_s, self._base_delay_s * 2**attempt)
            delay = (
                retry_after if retry_after is not None else backoff * (0.5 + random.random() / 2)
            )
            log.warning(
                "elexon_retry", url=url, attempt=attempt + 1, error=last_error, delay_s=delay
            )
            await self._sleep(delay)
        raise ElexonUnavailableError(f"{last_error} after {self._max_retries + 1} attempts: {url}")


def _parse_retry_after(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None


def _parse_rows(resp: httpx.Response) -> list[dict[str, Any]]:
    try:
        payload = resp.json()
    except ValueError as exc:
        # Typically an HTML maintenance page served with 200.
        raise ElexonResponseError(f"non-JSON response: {resp.text[:200]!r}") from exc
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        payload = payload["data"]
    if not isinstance(payload, list):
        raise ElexonResponseError(f"unexpected payload shape: {str(payload)[:200]!r}")
    return payload
