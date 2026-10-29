"""How one delivery day's forecast evolved, vintage by vintage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
import pandas as pd

from app.domain.timeutil import local_day_bounds_utc
from app.domain.vintage import HOUR, CutoffRule, hours

REVISION_LOOKBACK = pd.Timedelta(hours=48)
MIN_REVISION_HOURS = 12


@dataclass(frozen=True)
class Evolution:
    delivery_date: date
    cutoff: datetime
    selected_publish_time: datetime | None
    points: pd.DataFrame  # publish_time, start_time, forecast_mw, lead_time_h
    vintages: pd.DataFrame  # one row per vintage: coverage, mean, MAE vs actual, flags
    actuals: pd.DataFrame  # start_time, actual_mw
    # Revision signal over vintages published in the 48 h up to the cutoff, compared
    # on the hours every one of them covers (D-2 vintages stop at 21:00 UTC on D).
    revision_vintages: int
    revision_hours: int
    revision_range_mw: float | None  # max - min of the vintages' mean forecast
    revision_step_mw: float | None  # mean |change| between consecutive vintages


def vintage_evolution(
    forecasts: pd.DataFrame,
    actuals: pd.DataFrame,
    delivery_day: date,
    rule: CutoffRule,
) -> Evolution:
    lo, hi = (pd.Timestamp(t) for t in local_day_bounds_utc(delivery_day))
    cutoff = rule.cutoff_for(delivery_day)
    fc = forecasts[(forecasts["start_time"] >= lo) & (forecasts["start_time"] < hi)].copy()
    fc = fc.rename(columns={"generation_mw": "forecast_mw"})
    fc["lead_time_h"] = hours(fc["start_time"] - fc["publish_time"])
    act = actuals[(actuals["start_time"] >= lo) & (actuals["start_time"] < hi)].rename(
        columns={"generation_mw": "actual_mw"}
    )[["start_time", "actual_mw"]]

    hours_in_day = int((hi - lo) / HOUR)
    # Hourly actual (mean of its two half-hours) to score hourly vintages.
    act_h = act.assign(hour=act["start_time"].dt.floor("h")).groupby("hour")["actual_mw"].mean()

    rows = []
    for pub, g in fc.groupby("publish_time", sort=True):
        joined = g.set_index("start_time")["forecast_mw"].reindex(act_h.index).dropna()
        err = joined - act_h.reindex(joined.index)
        rows.append(
            {
                "publish_time": pub,
                "n_points": len(g),
                "full_day": g["start_time"].nunique() >= hours_in_day,
                "mean_mw": float(g["forecast_mw"].mean()),
                "mae_vs_actual_mw": float(err.abs().mean()) if len(err) else None,
                "after_cutoff": pd.Timestamp(pub) > cutoff,  # type: ignore[arg-type]
            }
        )
    vintages = pd.DataFrame(
        rows,
        columns=[
            "publish_time",
            "n_points",
            "full_day",
            "mean_mw",
            "mae_vs_actual_mw",
            "after_cutoff",
        ],
    )
    eligible = vintages[~vintages["after_cutoff"]] if len(vintages) else vintages
    selected = eligible["publish_time"].max() if len(eligible) else None
    vintages["selected"] = vintages["publish_time"] == selected

    window = fc[(fc["publish_time"] <= cutoff) & (fc["publish_time"] > cutoff - REVISION_LOOKBACK)]
    wide = window.pivot_table(index="start_time", columns="publish_time", values="forecast_mw")
    common = wide.dropna()
    ok = common.shape[1] >= 2 and len(common) >= MIN_REVISION_HOURS
    means = common.mean().to_numpy(dtype=float) if ok else np.array([])
    return Evolution(
        delivery_date=delivery_day,
        cutoff=cutoff,
        selected_publish_time=None
        if selected is None or pd.isna(selected)
        else selected.to_pydatetime(),
        points=fc[["publish_time", "start_time", "forecast_mw", "lead_time_h"]].reset_index(
            drop=True
        ),
        vintages=vintages,
        actuals=act.reset_index(drop=True),
        revision_vintages=int(common.shape[1]) if ok else 0,
        revision_hours=len(common) if ok else 0,
        revision_range_mw=float(means.max() - means.min()) if ok else None,
        revision_step_mw=float(np.abs(np.diff(means)).mean()) if ok else None,
    )
