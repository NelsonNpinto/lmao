"""One delivery day in depth: vintage fan and the time-machine replay."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal, cast

import numpy as np
import pandas as pd
from fastapi import APIRouter, Path, Query

from app.api.v1.convert import nn
from app.api.v1.params import AnalysisDep, Scope, ScopeDep
from app.domain.evolution import vintage_evolution
from app.domain.margin import MIN_HISTORY_DAYS, fit_policy, known_days_at_cutoff
from app.domain.metrics import complete_rows
from app.domain.vintage import local_dates
from app.schemas.analytics import (
    ActualPoint,
    DayVintagesOut,
    ReplayOut,
    ReplayPoint,
    RevealPoint,
    VintageOut,
    VintagePoint,
)
from app.schemas.common import Envelope
from app.services.analysis import Window

router = APIRouter(tags=["days"])


def _tuples(df: pd.DataFrame) -> list[Any]:
    return list(df.itertuples())


async def _nearest_forecast_day(analysis: AnalysisDep, day: date) -> date | None:
    f = await analysis.frames()
    if f.forecasts.empty:
        return None
    days = sorted(set(local_dates(f.forecasts["start_time"])))
    return cast(date, min(days, key=lambda d: abs((d - day).days)))


@router.get("/days/{delivery_date}/vintages", response_model=Envelope[DayVintagesOut])
async def day_vintages(
    sc: ScopeDep, delivery_date: Annotated[date, Path()]
) -> Envelope[DayVintagesOut]:
    """Every vintage covering one delivery day, the selected one, and the actual."""
    f = await sc.analysis.frames()
    ev = await sc.analysis.compute(
        ("evolution", delivery_date, sc.rule),
        lambda: vintage_evolution(f.forecasts, f.actuals, delivery_date, sc.rule),
    )
    by_pub = {pub: g for pub, g in ev.points.groupby("publish_time")}
    vintages = [
        VintageOut(
            publish_time=nn(v.publish_time),
            n_points=int(v.n_points),
            full_day=bool(v.full_day),
            mean_mw=float(v.mean_mw),
            mae_vs_actual_mw=nn(v.mae_vs_actual_mw),
            after_cutoff=bool(v.after_cutoff),
            selected=bool(v.selected),
            points=[
                VintagePoint(start_time=nn(t), forecast_mw=float(x))
                for t, x in zip(
                    by_pub[v.publish_time]["start_time"],
                    by_pub[v.publish_time]["forecast_mw"],
                    strict=True,
                )
            ],
        )
        for v in _tuples(ev.vintages)
    ]
    nearest = None if vintages else await _nearest_forecast_day(sc.analysis, delivery_date)
    data = DayVintagesOut(
        delivery_date=delivery_date,
        cutoff=ev.cutoff,
        selected_publish_time=ev.selected_publish_time,
        vintages=vintages,
        actuals=[
            ActualPoint(start_time=nn(t), actual_mw=float(a))
            for t, a in ev.actuals.itertuples(index=False)
        ],
        revision_vintages=ev.revision_vintages,
        revision_hours=ev.revision_hours,
        revision_range_mw=ev.revision_range_mw,
        revision_step_mw=ev.revision_step_mw,
        nearest_date_with_data=nearest,
    )
    notes = [] if vintages else ["No forecast vintages for this day."]
    meta = sc.meta(1.0 if vintages else 0.0, notes)
    meta.window_from, meta.window_to = delivery_date, delivery_date + timedelta(days=1)
    return Envelope(data=data, meta=meta)


@router.get("/replay/{decision_date}", response_model=Envelope[ReplayOut])
async def replay(
    sc: ScopeDep,
    decision_date: Annotated[date, Path(description="Day the desk decides (D-n)")],
    policy: Annotated[Literal["none", "flat", "conditional"], Query()] = "flat",
    quantile: Annotated[float, Query(ge=0.5, le=0.99)] = 0.9,
) -> Envelope[ReplayOut]:
    """Only what was knowable at the cutoff; the outcome sits in ``reveal``."""
    delivery = decision_date + timedelta(days=sc.rule.days_before)
    f = await sc.analysis.frames()
    # Same history rule as the dashboard plan: days of the analysis window before D.
    start = sc.window.day_from if sc.window.day_from <= delivery else delivery
    hist_window = Window(
        day_from=start,
        day_to=delivery + timedelta(days=1),
        requested_from=decision_date,
        requested_to=delivery + timedelta(days=1),
        clamped=False,
        has_data=f.first_day is not None,
    )
    al = await sc.analysis.aligned(hist_window, sc.rule)
    day = al[al["delivery_date"] == delivery]
    cutoff = sc.rule.cutoff_for(delivery)

    known_days = known_days_at_cutoff(al).get(delivery, [])
    complete = complete_rows(al)
    margins = pd.Series(np.nan, index=day.index)
    if len(known_days) >= MIN_HISTORY_DAYS and day["forecast_mw"].notna().any():
        train = complete[complete["delivery_date"].isin(known_days)]
        has = day["forecast_mw"].notna()
        margins[has] = fit_policy(train, policy, quantile)(day[has])
    plan = day["forecast_mw"] - margins
    covered = (day["error_mw"] <= margins).where(day["error_mw"].notna() & margins.notna())

    a = f.actuals
    recent = a[
        (a["start_time"] + pd.Timedelta(minutes=30) <= cutoff)
        & (a["start_time"] >= cutoff - pd.Timedelta(hours=24))
    ]
    data = ReplayOut(
        decision_date=decision_date,
        delivery_date=delivery,
        cutoff=cutoff,
        publish_time=nn(day["publish_time"].max()) if len(day) else None,
        vintage_age_h=nn(day["vintage_age_h"].max()) if len(day) else None,
        margin_mw=nn(margins.mean()) if margins.notna().any() else None,
        history_days=len(known_days),
        known=[
            ReplayPoint(
                start_time=nn(r.start_time),
                forecast_mw=nn(r.forecast_mw),
                margin_mw=nn(m),
                wind_to_plan_mw=nn(p),
            )
            for r, m, p in zip(_tuples(day), margins, plan, strict=True)
        ],
        recent_actuals=[
            ActualPoint(start_time=nn(t), actual_mw=float(v))
            for t, v in recent[["start_time", "generation_mw"]].itertuples(index=False)
        ],
        reveal=[
            RevealPoint(
                start_time=nn(r.start_time),
                actual_mw=nn(r.actual_mw),
                error_mw=nn(r.error_mw),
                covered=nn(c),
            )
            for r, c in zip(_tuples(day), covered, strict=True)
        ],
        reveal_mae_mw=nn(day["error_mw"].abs().mean()),
        reveal_coverage_pct=nn(100 * covered.dropna().astype(bool).mean())
        if covered.notna().any()
        else None,
        previous_decision=_decision_in_range(
            decision_date - timedelta(days=1), sc, f.first_day, f.last_day
        ),
        next_decision=_decision_in_range(
            decision_date + timedelta(days=1), sc, f.first_day, f.last_day
        ),
    )
    meta = sc.meta(nn(day["has_actual"].mean()) if len(day) else 0.0)
    meta.window_from, meta.window_to = delivery, delivery + timedelta(days=1)
    meta.generated_at = datetime.now(UTC)
    return Envelope(data=data, meta=meta)


def _decision_in_range(d: date, sc: Scope, first: date | None, last: date | None) -> date | None:
    if first is None or last is None:
        return None
    delivery = d + timedelta(days=sc.rule.days_before)
    return d if first + timedelta(days=1) <= delivery <= last else None
