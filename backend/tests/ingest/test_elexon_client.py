from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
import respx

from app.ingest.elexon_client import (
    ElexonResponseError,
    ElexonUnavailableError,
    HttpElexonClient,
)

BASE = "https://elexon.test/bmrs/api/v1"
FUEL_URL = f"{BASE}/datasets/FUELHH/stream"
ROW = {
    "dataset": "FUELHH",
    "publishTime": "2026-01-05T00:30:00Z",
    "startTime": "2026-01-05T00:00:00Z",
    "settlementDate": "2026-01-05",
    "settlementPeriod": 1,
    "fuelType": "WIND",
    "generation": 9000,
}


class SleepRecorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, d: float) -> None:
        self.delays.append(d)


def client(sleep: SleepRecorder, **kw: object) -> HttpElexonClient:
    return HttpElexonClient(BASE, max_retries=3, base_delay_s=1.0, sleep=sleep, **kw)  # type: ignore[arg-type]


@respx.mock
async def test_retries_429_then_succeeds_and_honours_retry_after() -> None:
    route = respx.get(FUEL_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(503),
            httpx.Response(200, json=[ROW]),
        ]
    )
    sleep = SleepRecorder()
    async with client(sleep) as c:
        res = await c.fetch_fuelhh(date(2026, 1, 5), date(2026, 1, 5))
    assert res.rows == [ROW]
    assert route.call_count == 3
    assert sleep.delays[0] == 7.0  # Retry-After wins
    assert 1.0 <= sleep.delays[1] <= 2.0  # 2s backoff with 50-100 % jitter
    q = route.calls[0].request.url.params
    assert q["settlementDateFrom"] == "2026-01-05" and q["fuelType"] == "WIND"


@respx.mock
async def test_gives_up_after_max_retries() -> None:
    route = respx.get(FUEL_URL).mock(return_value=httpx.Response(500))
    sleep = SleepRecorder()
    async with client(sleep) as c:
        with pytest.raises(ElexonUnavailableError, match="HTTP 500 after 4 attempts"):
            await c.fetch_fuelhh(date(2026, 1, 5), date(2026, 1, 5))
    assert route.call_count == 4
    assert len(sleep.delays) == 3


@respx.mock
async def test_timeout_is_retried() -> None:
    respx.get(FUEL_URL).mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json=[ROW])]
    )
    async with client(SleepRecorder()) as c:
        res = await c.fetch_fuelhh(date(2026, 1, 5), date(2026, 1, 5))
    assert len(res.rows) == 1


@respx.mock
async def test_html_maintenance_page_is_not_retried() -> None:
    html = "<html><body>Scheduled maintenance</body></html>"
    route = respx.get(FUEL_URL).mock(return_value=httpx.Response(200, text=html))
    async with client(SleepRecorder()) as c:
        with pytest.raises(ElexonResponseError, match=r"non-JSON.*maintenance"):
            await c.fetch_fuelhh(date(2026, 1, 5), date(2026, 1, 5))
    assert route.call_count == 1


@respx.mock
async def test_4xx_is_not_retried() -> None:
    route = respx.get(FUEL_URL).mock(return_value=httpx.Response(400, text="bad params"))
    async with client(SleepRecorder()) as c:
        with pytest.raises(ElexonResponseError, match="HTTP 400: bad params"):
            await c.fetch_fuelhh(date(2026, 1, 5), date(2026, 1, 5))
    assert route.call_count == 1


@respx.mock
async def test_data_envelope_is_unwrapped() -> None:
    respx.get(FUEL_URL).mock(return_value=httpx.Response(200, json={"data": [ROW]}))
    async with client(SleepRecorder()) as c:
        res = await c.fetch_fuelhh(date(2026, 1, 5), date(2026, 1, 5))
    assert res.rows == [ROW]


@respx.mock
async def test_windfor_params_are_iso_utc() -> None:
    route = respx.get(f"{BASE}/datasets/WINDFOR/stream").mock(
        return_value=httpx.Response(200, json=[])
    )
    async with client(SleepRecorder()) as c:
        await c.fetch_windfor(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 8, tzinfo=UTC))
    q = route.calls[0].request.url.params
    assert q["publishDateTimeFrom"] == "2026-01-01T00:00:00Z"
    assert q["publishDateTimeTo"] == "2026-01-08T00:00:00Z"


@respx.mock
async def test_read_through_cache(tmp_path: Path) -> None:
    route = respx.get(FUEL_URL).mock(return_value=httpx.Response(200, json=[ROW]))
    sleep = SleepRecorder()
    async with client(sleep, cache_dir=tmp_path) as c:
        first = await c.fetch_fuelhh(date(2026, 1, 5), date(2026, 1, 5))
        second = await c.fetch_fuelhh(date(2026, 1, 5), date(2026, 1, 5))
    assert route.call_count == 1
    assert not first.from_cache and second.from_cache
    assert second.rows == first.rows and second.url == first.url
    assert list(tmp_path.glob("FUELHH/*.json.gz"))

    async with client(sleep, cache_dir=tmp_path, cache_mode="refresh") as c:
        third = await c.fetch_fuelhh(date(2026, 1, 5), date(2026, 1, 5))
    assert route.call_count == 2 and not third.from_cache

    async with client(sleep, cache_dir=tmp_path, cache_mode="offline") as c:
        assert (await c.fetch_fuelhh(date(2026, 1, 5), date(2026, 1, 5))).from_cache
        with pytest.raises(ElexonUnavailableError, match="offline"):
            await c.fetch_fuelhh(date(2026, 1, 6), date(2026, 1, 6))
