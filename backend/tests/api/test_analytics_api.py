"""Analytics endpoints against the recorded Elexon fixture week.

Fixture: actuals for 5-11 Jan 2026, every vintage published 1-12 Jan.
"""

from __future__ import annotations

import asyncio
import csv
import io
from collections.abc import AsyncIterator
from datetime import date, datetime, time
from typing import Any

import pandas as pd
import pytest
from httpx import AsyncClient

from app.domain.align import build_aligned
from app.domain.metrics import compute_metrics
from app.domain.timeutil import cutoff_utc
from app.domain.vintage import CutoffRule
from tests.conftest import FakeElexonClient

AUTH = {"X-Admin-Token": "test-token"}
WEEK = "from=2026-01-06&to=2026-01-12"  # 6 delivery days, 288 half-hours


async def _seed(c: AsyncClient) -> None:
    r = await c.post(
        "/api/v1/ingest/runs",
        json={"delivery_from": "2026-01-06", "delivery_to": "2026-01-12"},
        headers=AUTH,
    )
    run_id = r.json()["data"]["id"]
    for _ in range(300):
        run = (await c.get(f"/api/v1/ingest/runs/{run_id}")).json()["data"]
        if run["status"] != "running":
            assert run["status"] == "succeeded", run
            return
        await asyncio.sleep(0.02)
    raise AssertionError("seed did not finish")


@pytest.fixture
async def api(
    make_client: Any, fuelhh_week: list[dict[str, Any]], windfor_week: list[dict[str, Any]]
) -> AsyncIterator[AsyncClient]:
    async with make_client(FakeElexonClient(fuelhh_week, windfor_week)) as c:
        await _seed(c)
        yield c


async def get(c: AsyncClient, url: str) -> dict[str, Any]:
    r = await c.get(f"/api/v1/{url}")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def _frame(rows: list[dict[str, Any]], time_cols: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in time_cols:
        df[col] = pd.to_datetime(df[col], utc=True)
    return df


# -- summary and windows -------------------------------------------------------


async def test_summary_matches_domain_computation(
    api: AsyncClient, fuelhh_week: list[dict[str, Any]], windfor_week: list[dict[str, Any]]
) -> None:
    body = await get(api, f"metrics/summary?{WEEK}")
    a = _frame(fuelhh_week, ["startTime"]).rename(
        columns={"startTime": "start_time", "generation": "generation_mw"}
    )
    f = _frame(windfor_week, ["startTime", "publishTime"]).rename(
        columns={
            "startTime": "start_time",
            "publishTime": "publish_time",
            "generation": "generation_mw",
        }
    )
    expected = compute_metrics(
        build_aligned(a, f, date(2026, 1, 6), date(2026, 1, 12), CutoffRule(time(9)))
    )
    d = body["data"]
    assert d["n"] == 288 == expected.n
    assert d["mae_mw"] == pytest.approx(expected.mae_mw)
    assert d["bias_mw"] == pytest.approx(expected.bias_mw)
    assert d["intervals"] is not None and "mae_mw" in d["intervals"]
    m = body["meta"]
    assert (m["window_from"], m["window_to"], m["cutoff"]) == ("2026-01-06", "2026-01-12", "09:00")
    assert m["clamped"] is False and m["completeness"] == 1.0


async def test_default_window_is_clamped_to_available_data(api: AsyncClient) -> None:
    m = (await get(api, "metrics/summary"))["meta"]
    assert m["requested_from"] == "2026-01-02" and m["requested_to"] == "2026-02-02"
    assert (m["window_from"], m["window_to"]) == ("2026-01-05", "2026-01-12")
    assert m["clamped"] is True and any("trimmed" in n for n in m["notes"])


async def test_window_without_data_is_empty_not_404(api: AsyncClient) -> None:
    body = await get(api, "series?from=2027-01-01&to=2027-01-03")
    assert body["data"]["points"] == [] and body["meta"]["completeness"] == 0
    s = (await get(api, "metrics/summary?from=2027-01-01&to=2027-01-03"))["data"]
    assert s["n"] == 0 and s["mae_mw"] is None


async def test_empty_database_returns_nulls(make_client: Any) -> None:
    async with make_client(FakeElexonClient([], [])) as c:
        body = await get(c, "metrics/summary")
        series = await get(c, "series")
    assert body["data"]["n"] == 0 and body["meta"]["completeness"] == 0
    assert series["data"]["points"] == []


# -- the as-of guarantee, end to end --------------------------------------------


@pytest.mark.parametrize(
    ("cutoff", "vintage"), [("07:00", "04:30"), ("09:00", "07:30"), ("11:00", "09:30")]
)
async def test_cutoff_changes_the_vintage_used(api: AsyncClient, cutoff: str, vintage: str) -> None:
    d = (await get(api, f"series?{WEEK}&cutoff={cutoff}"))["data"]
    assert {t[11:16] for t in d["vintages_used"]} == {vintage}
    for p in d["points"]:
        start = datetime.fromisoformat(p["start_time"])
        cut = cutoff_utc(start.date(), time.fromisoformat(cutoff))
        assert datetime.fromisoformat(p["publish_time"]) <= cut  # never look-ahead


async def test_series_resolutions_and_band(api: AsyncClient) -> None:
    hh = (await get(api, f"series?{WEEK}"))["data"]
    assert hh["resolution"] == "30m" and len(hh["points"]) == 288 and hh["gaps"] == 0
    p = hh["points"][0]
    band = hh["band"]
    assert p["band_low_mw"] == pytest.approx(p["forecast_mw"] - band["error_high_mw"])
    assert p["band_high_mw"] == pytest.approx(p["forecast_mw"] - band["error_low_mw"])
    assert len((await get(api, f"series?{WEEK}&resolution=1h"))["data"]["points"]) == 144
    daily = (await get(api, f"series?{WEEK}&resolution=1d"))["data"]["points"]
    assert len(daily) == 6 and daily[0]["start_time"] == "2026-01-06T00:00:00Z"


# -- breakdowns, distribution, calibration, sweep, findings --------------------


@pytest.mark.parametrize("dimension", ["day", "hour", "weekday", "lead_time", "regime"])
async def test_breakdowns(api: AsyncClient, dimension: str) -> None:
    groups = (await get(api, f"metrics/by/{dimension}?{WEEK}"))["data"]
    assert groups and sum(g["metrics"]["n"] for g in groups) == 288


async def test_unknown_dimension_is_422(api: AsyncClient) -> None:
    r = await api.get("/api/v1/metrics/by/moon-phase")
    assert r.status_code == 422


async def test_error_distribution(api: AsyncClient) -> None:
    h = (await get(api, f"metrics/error-distribution?{WEEK}&bins=12"))["data"]
    assert len(h["counts"]) == 12 and len(h["edges"]) == 13 and sum(h["counts"]) == 288
    pct = (await get(api, f"metrics/error-distribution?{WEEK}&normalise=true"))["data"]
    assert pct["unit"] == "%"


async def test_calibration(api: AsyncClient) -> None:
    c = (await get(api, f"metrics/calibration?{WEEK}"))["data"]
    assert c["nominal_pct"] == pytest.approx(80.0)
    assert sum(b["n"] for b in c["buckets"]) == 288


async def test_cutoff_sweep(api: AsyncClient) -> None:
    rows = (await get(api, f"metrics/cutoff-sweep?{WEEK}&cutoffs=11:00,07:00,09:00"))["data"]
    assert [r["cutoff"] for r in rows] == ["07:00", "09:00", "11:00"]
    assert [r["vintages_used"] for r in rows] == [["04:30"], ["07:30"], ["09:30"]]
    r = await api.get(f"/api/v1/metrics/cutoff-sweep?{WEEK}&cutoffs=9am")
    assert r.status_code == 422


async def test_findings_are_computed_sentences(api: AsyncClient) -> None:
    items = (await get(api, f"findings?{WEEK}"))["data"]
    ids = [f["id"] for f in items]
    assert len(ids) == len(set(ids)) >= 3
    assert {"bias", "skill", "margin"} <= set(ids)
    assert all(any(ch.isdigit() for ch in f["body"]) for f in items)


# -- procurement, days, replay ---------------------------------------------------


async def test_margin_and_plan(api: AsyncClient) -> None:
    d = (await get(api, f"procurement/margin?{WEEK}&day=2026-01-11&policy=flat"))["data"]
    assert {b["policy"] for b in d["in_sample"]} == {"none", "flat", "conditional"}
    assert "MW of wind" in d["recommendation"]
    plan = d["plan"]
    assert plan["delivery_date"] == "2026-01-11" and len(plan["rows"]) == 48
    # Only 4 days in the window precede the 11th: fall back to the window, and say so.
    assert plan["margin_basis"] == "window" and plan["history_days"] == 4
    row = plan["rows"][0]
    assert row["wind_to_plan_mw"] == pytest.approx(row["forecast_mw"] - row["margin_mw"])

    r = await api.get(f"/api/v1/procurement/margin?{WEEK}&day=2026-03-01")
    assert r.status_code == 422 and "outside the window" in r.json()["detail"]


async def test_day_vintages(api: AsyncClient) -> None:
    d = (await get(api, "days/2026-01-10/vintages"))["data"]
    assert d["selected_publish_time"] == "2026-01-09T07:30:00Z"
    selected = [v for v in d["vintages"] if v["selected"]]
    assert len(selected) == 1 and not selected[0]["after_cutoff"]
    assert len(d["actuals"]) == 48 and d["revision_range_mw"] is not None

    empty = (await get(api, "days/2025-07-01/vintages"))["data"]
    assert empty["vintages"] == [] and empty["nearest_date_with_data"] is not None


async def test_replay_only_shows_what_was_known(api: AsyncClient) -> None:
    d = (await get(api, "replay/2026-01-09"))["data"]
    cutoff = datetime.fromisoformat(d["cutoff"])
    assert d["delivery_date"] == "2026-01-10" and d["cutoff"] == "2026-01-09T09:00:00Z"
    assert datetime.fromisoformat(d["publish_time"]) <= cutoff
    assert set(d["known"][0]) == {"start_time", "forecast_mw", "margin_mw", "wind_to_plan_mw"}
    assert all(
        datetime.fromisoformat(a["start_time"]) + pd.Timedelta(minutes=30) <= cutoff
        for a in d["recent_actuals"]
    )
    assert len(d["reveal"]) == 48 and d["reveal_mae_mw"] is not None
    assert d["previous_decision"] == "2026-01-08" and d["next_decision"] == "2026-01-10"


# -- export, caching, validation -------------------------------------------------


async def test_exports(api: AsyncClient) -> None:
    r = await api.get(f"/api/v1/export?{WEEK}&format=csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:3] == ["start_time", "delivery_date", "period"] and len(rows) == 289
    assert rows[1][0] == "2026-01-06T00:00:00Z"
    x = await api.get(f"/api/v1/export?{WEEK}&format=xlsx")
    assert x.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert x.content[:2] == b"PK"
    j = await get(api, f"export?{WEEK}&format=json")
    assert len(j["data"]) == 288


async def test_etag_304_and_invalidation_after_new_data(
    api: AsyncClient, fuelhh_week: list[dict[str, Any]]
) -> None:
    url = f"/api/v1/metrics/summary?{WEEK}"
    first = await api.get(url)
    etag = first.headers["ETag"]
    assert (await api.get(url, headers={"If-None-Match": etag})).status_code == 304

    # A refresh that changes data bumps the version: old ETag no longer matches.
    app_state = api._transport.app.state  # type: ignore[attr-defined]
    app_state.data_version += 1
    again = await api.get(url, headers={"If-None-Match": etag})
    assert again.status_code == 200 and again.headers["ETag"] != etag


@pytest.mark.parametrize(
    "query",
    [
        "from=2026-01-10&to=2026-01-05",
        "from=2025-01-01&to=2026-06-01",
        "cutoff=9:00",
        "cutoff=24:00",
        "days_before=3",
        "from=not-a-date",
    ],
)
async def test_bad_params_are_422_problem_details(api: AsyncClient, query: str) -> None:
    r = await api.get(f"/api/v1/metrics/summary?{query}")
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 422 and r.json()["detail"]
