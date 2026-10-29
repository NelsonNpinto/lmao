from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from tests.conftest import FakeElexonClient

AUTH = {"X-Admin-Token": "test-token"}
BODY = {"delivery_from": "2026-01-06", "delivery_to": "2026-01-12"}


async def _wait_done(c: Any, run_id: str) -> dict[str, Any]:
    for _ in range(200):
        run = (await c.get(f"/api/v1/ingest/runs/{run_id}")).json()["data"]
        if run["status"] != "running":
            return run  # type: ignore[no-any-return]
        await asyncio.sleep(0.02)
    raise AssertionError("run did not finish")


async def test_requires_admin_token(make_client: Any) -> None:
    async with make_client(FakeElexonClient([], [])) as c:
        r = await c.post("/api/v1/ingest/runs", json=BODY)
        bad = await c.post("/api/v1/ingest/runs", json=BODY, headers={"X-Admin-Token": "no"})
    assert r.status_code == 401 and bad.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_start_poll_and_meta_coverage(
    make_client: Any, fuelhh_week: list[dict[str, Any]], windfor_week: list[dict[str, Any]]
) -> None:
    async with make_client(FakeElexonClient(fuelhh_week, windfor_week)) as c:
        r = await c.post("/api/v1/ingest/runs", json=BODY, headers=AUTH)
        assert r.status_code == 202
        run = await _wait_done(c, r.json()["data"]["id"])
        meta = (await c.get("/api/v1/meta")).json()
        runs = (await c.get("/api/v1/ingest/runs")).json()["data"]

    assert run["status"] == "succeeded" and run["progress"] == 1.0
    cov = meta["data"]["coverage"]
    assert cov["actual_rows"] == 336
    assert cov["actual_from"] == "2026-01-05T00:00:00Z"
    assert cov["forecast_vintages"] > 70
    assert meta["data"]["data_version"] == 1
    assert meta["data"]["last_ingest"]["id"] == run["id"]
    assert [x["id"] for x in runs] == [run["id"]]


async def test_concurrent_request_gets_409_with_running_job(make_client: Any) -> None:
    gate = asyncio.Event()
    async with make_client(FakeElexonClient([], [], gate=gate)) as c:
        first = await c.post("/api/v1/ingest/runs", json=BODY, headers=AUTH)
        second = await c.post("/api/v1/ingest/runs", json=BODY, headers=AUTH)
        gate.set()
        await _wait_done(c, first.json()["data"]["id"])
    assert second.status_code == 409
    assert second.json()["run"]["id"] == first.json()["data"]["id"]


async def test_bad_window_is_422_problem(make_client: Any) -> None:
    async with make_client(FakeElexonClient([], [])) as c:
        r = await c.post(
            "/api/v1/ingest/runs",
            json={"delivery_from": "2026-02-01", "delivery_to": "2026-01-01"},
            headers=AUTH,
        )
        missing = await c.get("/api/v1/ingest/runs/does-not-exist")
    assert r.status_code == 422
    assert "delivery_from must be before delivery_to" in r.json()["detail"]
    assert missing.status_code == 404


async def test_startup_seed_runs_once_until_completed(
    make_client: Any,
    settings: Any,
    fuelhh_week: list[dict[str, Any]],
    windfor_week: list[dict[str, Any]],
) -> None:
    settings.seed_on_startup = True
    settings.seed_from, settings.seed_to = date(2026, 1, 6), date(2026, 1, 12)
    fake = FakeElexonClient(fuelhh_week, windfor_week)
    async with make_client(fake) as c:
        runs = (await c.get("/api/v1/ingest/runs")).json()["data"]
        assert len(runs) == 1
        assert (await _wait_done(c, runs[0]["id"]))["status"] == "succeeded"
    calls = len(fake.calls)

    async with make_client(fake) as c:  # second boot: data already loaded
        runs = (await c.get("/api/v1/ingest/runs")).json()["data"]
    assert len(runs) == 1 and len(fake.calls) == calls


async def test_interrupted_seed_is_retried_on_next_boot(
    make_client: Any, settings: Any, fuelhh_week: list[dict[str, Any]]
) -> None:
    settings.seed_on_startup = True
    settings.seed_from, settings.seed_to = date(2026, 1, 6), date(2026, 1, 12)
    gate = asyncio.Event()  # never set: the first boot shuts down mid-run
    async with make_client(FakeElexonClient(fuelhh_week, [], gate=gate)):
        pass
    async with make_client(FakeElexonClient(fuelhh_week, [])) as c:
        runs = (await c.get("/api/v1/ingest/runs")).json()["data"]
        await _wait_done(c, runs[0]["id"])
        runs = (await c.get("/api/v1/ingest/runs")).json()["data"]
    assert [r["status"] for r in runs] == ["partial", "failed"]
    assert runs[1]["error"] == "interrupted by restart"
