from __future__ import annotations

import asyncio
import copy
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import WindActual, WindForecast
from app.ingest.elexon_client import ElexonUnavailableError
from app.ingest.runner import IngestAlreadyRunningError, IngestRequest, IngestRunner, plan_slices
from app.ingest.validate import ContractError
from tests.conftest import FakeElexonClient, factory_for

# Delivery 6-11 Jan -> actuals from 5 Jan (persistence baseline), vintages from 2 Jan.
REQ = IngestRequest(delivery_from=date(2026, 1, 6), delivery_to=date(2026, 1, 12))
SM = async_sessionmaker[AsyncSession]


async def counts(sm: SM) -> tuple[int, int]:
    async with sm() as s:
        a = (await s.execute(select(func.count()).select_from(WindActual))).scalar_one()
        f = (await s.execute(select(func.count()).select_from(WindForecast))).scalar_one()
    return a, f


def expected_forecasts(windfor: list[dict[str, Any]]) -> int:
    lo, hi = "2026-01-02T00:00:00Z", "2026-01-12T00:00:00Z"
    return len(
        {(r["startTime"], r["publishTime"]) for r in windfor if lo <= r["publishTime"] <= hi}
    )


def test_plan_slices_windows() -> None:
    s = plan_slices(REQ)
    fuel = [x for x in s if x.dataset == "FUELHH"]
    wind = [x for x in s if x.dataset == "WINDFOR"]
    assert fuel[0].start == date(2026, 1, 5) and fuel[-1].end == date(2026, 1, 11)
    assert wind[0].start == datetime(2026, 1, 2, tzinfo=UTC)
    assert wind[-1].end == datetime(2026, 1, 12, tzinfo=UTC)


async def test_ingest_then_rerun_is_idempotent(
    sessionmaker: SM, fuelhh_week: list[dict[str, Any]], windfor_week: list[dict[str, Any]]
) -> None:
    runner = IngestRunner(sessionmaker, factory_for(FakeElexonClient(fuelhh_week, windfor_week)))
    run = await runner.run(REQ)
    assert run.status == "succeeded", run.quality
    n_fc = expected_forecasts(windfor_week)
    assert await counts(sessionmaker) == (7 * 48, n_fc)
    assert run.rows_upserted == 7 * 48 + n_fc
    assert run.slices_done == run.slices_total
    assert run.quality["forecast_resolution"] == "hourly"
    assert run.quality["incomplete_days"] == {}

    again = await runner.run(REQ)
    assert again.status == "succeeded"
    assert again.rows_upserted == 0
    assert await counts(sessionmaker) == (7 * 48, n_fc)


async def test_provenance_and_utc_roundtrip(
    sessionmaker: SM, fuelhh_week: list[dict[str, Any]], windfor_week: list[dict[str, Any]]
) -> None:
    run = await IngestRunner(
        sessionmaker, factory_for(FakeElexonClient(fuelhh_week, windfor_week))
    ).run(REQ)
    async with sessionmaker() as s:
        a = await s.get(WindActual, (datetime(2026, 1, 5, tzinfo=UTC), "WIND"))
        f = (await s.execute(select(WindForecast).limit(1))).scalar_one()
    assert a is not None
    assert a.start_time.tzinfo is not None and a.settlement_period == 1
    assert a.ingest_run_id == run.id and a.source_url == "fake://FUELHH"
    assert f.lead_time_h == pytest.approx((f.start_time - f.publish_time).total_seconds() / 3600)


async def test_republished_actual_updates_and_counts_revision(
    sessionmaker: SM, fuelhh_week: list[dict[str, Any]]
) -> None:
    req = IngestRequest(date(2026, 1, 6), date(2026, 1, 12), dataset="FUELHH")
    await IngestRunner(sessionmaker, factory_for(FakeElexonClient(fuelhh_week, []))).run(req)

    revised = copy.deepcopy(fuelhh_week)
    target = next(r for r in revised if r["startTime"] == "2026-01-05T00:00:00Z")
    target["generation"] = 1.0
    target["publishTime"] = "2026-01-06T12:00:00Z"
    run = await IngestRunner(sessionmaker, factory_for(FakeElexonClient(revised, []))).run(req)

    assert run.rows_upserted == 1
    async with sessionmaker() as s:
        a = await s.get(WindActual, (datetime(2026, 1, 5, tzinfo=UTC), "WIND"))
    assert a is not None and a.generation_mw == 1.0 and a.revision_count == 1


async def test_failed_slice_makes_run_partial_not_complete(
    sessionmaker: SM, fuelhh_week: list[dict[str, Any]], windfor_week: list[dict[str, Any]]
) -> None:
    client = FakeElexonClient(
        fuelhh_week, windfor_week, fail={"WINDFOR": ElexonUnavailableError("HTTP 503 x6")}
    )
    run = await IngestRunner(sessionmaker, factory_for(client)).run(REQ)
    assert run.status == "partial"
    assert run.error and "HTTP 503" in run.error
    assert len(run.quality["slice_errors"]) == sum(1 for c in client.calls if c[0] == "WINDFOR")
    assert await counts(sessionmaker) == (7 * 48, 0)


async def test_every_slice_failing_is_failed(sessionmaker: SM) -> None:
    err = ElexonUnavailableError("down")
    client = FakeElexonClient([], [], fail={"FUELHH": err, "WINDFOR": err})
    run = await IngestRunner(sessionmaker, factory_for(client)).run(REQ)
    assert run.status == "failed"


async def test_contract_violation_fails_run(
    sessionmaker: SM, fuelhh_week: list[dict[str, Any]], windfor_week: list[dict[str, Any]]
) -> None:
    client = FakeElexonClient(
        fuelhh_week, windfor_week, fail={"WINDFOR": ContractError("WINDFOR contract violation")}
    )
    run = await IngestRunner(sessionmaker, factory_for(client)).run(REQ)
    assert run.status == "failed"
    assert "contract violation" in (run.error or "")


async def test_missing_periods_are_reported_not_hidden(
    sessionmaker: SM, fuelhh_week: list[dict[str, Any]], windfor_week: list[dict[str, Any]]
) -> None:
    holes = [
        r
        for r in fuelhh_week
        if not (r["settlementDate"] == "2026-01-08" and r["settlementPeriod"] > 44)
    ]
    run = await IngestRunner(sessionmaker, factory_for(FakeElexonClient(holes, windfor_week))).run(
        REQ
    )
    assert run.status == "partial"
    assert run.quality["incomplete_days"] == {"2026-01-08": {"got": 44, "expected": 48}}


async def test_null_rows_counted_in_quality(
    sessionmaker: SM, fuelhh_week: list[dict[str, Any]]
) -> None:
    rows = copy.deepcopy(fuelhh_week)
    rows[0]["generation"] = None
    req = IngestRequest(date(2026, 1, 6), date(2026, 1, 12), dataset="FUELHH")
    run = await IngestRunner(sessionmaker, factory_for(FakeElexonClient(rows, []))).run(req)
    assert run.rows_rejected == 1
    assert run.quality["FUELHH"]["null_generation"] == 1
    assert run.status == "partial"  # that half-hour is now missing


async def test_single_flight(sessionmaker: SM) -> None:
    gate = asyncio.Event()
    runner = IngestRunner(sessionmaker, factory_for(FakeElexonClient([], [], gate=gate)))
    first = await runner.start(REQ)
    with pytest.raises(IngestAlreadyRunningError) as exc:
        await runner.start(REQ)
    assert exc.value.run_id == first
    gate.set()
    await runner.wait()
    assert runner.running_id is None
