"""Procurement margin recommendation, backtests and the per-period buying plan."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from app.api.v1.convert import nn
from app.api.v1.params import ScopeDep
from app.domain.margin import (
    MIN_HISTORY_DAYS,
    PERIOD_H,
    MarginRecommendation,
    Policy,
    fit_policy,
    known_days_at_cutoff,
)
from app.domain.metrics import complete_rows
from app.schemas.analytics import BacktestOut, DayMarginOut, MarginOut, PlanOut, PlanRow
from app.schemas.common import Envelope

router = APIRouter(prefix="/procurement", tags=["procurement"])


def recommendation_sentence(rec: MarginRecommendation, cutoff_label: str) -> str:
    if rec.margin_mw is None:
        return "Not enough data in this window to recommend a margin."
    q = round(rec.quantile * 100)
    ins = rec.by("in_sample", "flat").coverage_pct
    wf = rec.by("walk_forward", "flat")
    s = (
        f"At the {cutoff_label} cutoff, plan on the forecast minus {rec.margin_mw:,.0f} MW of wind "
        f"(P{q} of the signed error, {rec.margin_mw * PERIOD_H:,.0f} MWh per half-hour)."
    )
    if ins is not None:
        s += f" In hindsight that covers {ins:.0f} % of half-hours"
        s += (
            f"; set only from days known at each cutoff it covered {wf.coverage_pct:.1f} %."
            if wf.coverage_pct is not None
            else "."
        )
    return s


def _tuples(df: pd.DataFrame) -> list[Any]:
    return list(df.itertuples())


def build_plan(aligned: pd.DataFrame, day: date, policy: Policy, q: float) -> PlanOut:
    rows = aligned[aligned["delivery_date"] == day]
    known = known_days_at_cutoff(aligned).get(day, [])
    complete = complete_rows(aligned)
    if policy == "none":
        basis: Literal["walk_forward", "window", "none"] = "none"
        train = complete.iloc[0:0]
    elif len(known) >= MIN_HISTORY_DAYS:
        basis, train = "walk_forward", complete[complete["delivery_date"].isin(known)]
    else:
        # Too little history before this day: fall back to the whole window and say so.
        basis, train = "window", complete
    with_fc = rows["forecast_mw"].notna()
    margins = pd.Series(float("nan"), index=rows.index)
    if with_fc.any():
        margins[with_fc] = fit_policy(train, policy, q)(rows[with_fc])
    plan = rows["forecast_mw"] - margins
    out = [
        PlanRow(
            start_time=nn(r.start_time),
            period=int(r.period),
            forecast_mw=nn(r.forecast_mw),
            margin_mw=nn(m),
            wind_to_plan_mw=nn(p),
            wind_to_plan_mwh=nn(p * PERIOD_H),
        )
        for r, m, p in zip(_tuples(rows), margins, plan, strict=True)
    ]
    fc_total = rows["forecast_mw"].sum(min_count=1) * PERIOD_H
    plan_total = plan.sum(min_count=1) * PERIOD_H
    return PlanOut(
        delivery_date=day,
        policy=policy,
        margin_basis=basis,
        history_days=len(known),
        publish_time=nn(rows["publish_time"].max()) if len(rows) else None,
        rows=out,
        forecast_total_mwh=nn(fc_total),
        wind_to_plan_total_mwh=nn(plan_total),
    )


@router.get("/margin", response_model=Envelope[MarginOut])
async def margin(
    sc: ScopeDep,
    quantile: Annotated[float, Query(ge=0.5, le=0.99)] = 0.9,
    policy: Annotated[Literal["none", "flat", "conditional"], Query()] = "flat",
    day: Annotated[date | None, Query(description="Delivery day for the buying plan")] = None,
) -> Envelope[MarginOut]:
    """Recommended margin, in-sample and walk-forward backtests for every policy,
    and (with ``day``) the per-period plan for that delivery day."""
    w = sc.window
    if day is not None and not (w.day_from <= day < w.day_to):
        raise HTTPException(422, f"day {day} is outside the window {w.day_from}..{w.day_to}")
    al = await sc.analysis.aligned(w, sc.rule)
    rec = await sc.analysis.margin(w, sc.rule, quantile)
    per_day = await sc.analysis.walk_forward_days(w, sc.rule, quantile, policy)
    plan = (
        await sc.analysis.compute(
            ("plan", w, sc.rule, day, policy, quantile),
            lambda: build_plan(al, day, policy, quantile),
        )
        if day
        else None
    )
    m = await sc.analysis.summary(w, sc.rule)
    return Envelope(
        data=MarginOut(
            quantile=quantile,
            margin_mw=rec.margin_mw,
            margin_mwh_per_period=rec.margin_mwh_per_period,
            recommendation=recommendation_sentence(rec, sc.rule.label),
            in_sample=[BacktestOut(**b.as_dict()) for b in rec.in_sample],
            walk_forward=[BacktestOut(**b.as_dict()) for b in rec.walk_forward],
            walk_forward_days=[DayMarginOut.model_validate(r) for r in per_day.to_dict("records")],
            plan=plan,
        ),
        meta=sc.meta(m.completeness),
    )
