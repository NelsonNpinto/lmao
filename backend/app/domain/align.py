"""Build the aligned half-hourly frame every metric is computed from.

One row per half-hour in the delivery window, whether or not data exists, so
gaps are explicit (``has_actual`` / ``has_forecast``) instead of silently
dropped by an inner join.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.domain.baseline import date_and_period, persistence_baseline
from app.domain.timeutil import UK, local_day_bounds_utc
from app.domain.vintage import (
    CutoffRule,
    day_cutoffs,
    forecast_is_hourly,
    select_vintage,
    to_half_hourly,
)

SELECTED_COLUMNS = [
    "start_time",
    "publish_time",
    "forecast_hour",
    "lead_time_h",
    "vintage_age_h",
    "stale",
    "forecast_mw",
]

ALIGNED_COLUMNS = [
    "start_time",
    "delivery_date",
    "period",
    "hour_of_day",
    "weekday",
    "cutoff",
    *SELECTED_COLUMNS[1:],
    "actual_mw",
    "persistence_mw",
    "error_mw",
    "persistence_error_mw",
    "has_forecast",
    "has_actual",
]


def half_hour_grid(day_from: date, day_to: date) -> pd.DatetimeIndex:
    """Every half-hour start (UTC) of UK delivery days in ``[day_from, day_to)``."""
    start, _ = local_day_bounds_utc(day_from)
    end, _ = local_day_bounds_utc(day_to)
    return pd.date_range(start, end, freq="30min", inclusive="left")


def _empty_selection() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype="float64") for c in SELECTED_COLUMNS})
    for c in ("start_time", "publish_time", "forecast_hour"):
        df[c] = pd.Series(dtype="datetime64[ns, UTC]")
    df["stale"] = df["stale"].astype(bool)
    return df


def build_aligned(
    actuals: pd.DataFrame,
    forecasts: pd.DataFrame,
    day_from: date,
    day_to: date,
    rule: CutoffRule,
) -> pd.DataFrame:
    """Align actuals with the as-of forecast for each half-hour of ``[day_from, day_to)``.

    ``actuals``: start_time, generation_mw (include the day before ``day_from``
    for the persistence baseline). ``forecasts``: start_time, publish_time,
    generation_mw, every vintage.
    """
    grid = half_hour_grid(day_from, day_to)
    if len(forecasts):
        targets = grid.floor("h").unique() if forecast_is_hourly(forecasts) else grid
        selected = to_half_hourly(select_vintage(forecasts, rule, targets))[SELECTED_COLUMNS]
    else:
        selected = _empty_selection()

    df = pd.DataFrame({"start_time": grid})
    df["delivery_date"], df["period"] = date_and_period(df["start_time"])
    local = df["start_time"].dt.tz_convert(UK)
    df["hour_of_day"] = local.dt.hour
    df["weekday"] = local.dt.day_of_week
    df["cutoff"] = day_cutoffs(df["delivery_date"], rule)

    df = df.merge(selected, on="start_time", how="left")
    df = df.merge(
        actuals[["start_time", "generation_mw"]].rename(columns={"generation_mw": "actual_mw"}),
        on="start_time",
        how="left",
    )
    df = df.merge(persistence_baseline(actuals), on="start_time", how="left")

    df["stale"] = df["stale"].astype("boolean").fillna(False).astype(bool)
    for col in ("forecast_mw", "actual_mw", "persistence_mw"):
        df[col] = df[col].astype(float)
    df["error_mw"] = df["forecast_mw"] - df["actual_mw"]
    df["persistence_error_mw"] = df["persistence_mw"] - df["actual_mw"]
    df["has_forecast"] = df["forecast_mw"].notna()
    df["has_actual"] = df["actual_mw"].notna()
    return df[ALIGNED_COLUMNS]
