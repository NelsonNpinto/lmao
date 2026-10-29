"""As-of forecast vintage selection (ADR 0001).

Input frames use UTC ``datetime64[ns, UTC]`` columns. Nothing here touches the
database or the web layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import cast

import pandas as pd

from app.domain.timeutil import UK, cutoff_utc

STALE_AFTER_H = 24.0
HOUR = pd.Timedelta(hours=1)
HALF_HOUR = pd.Timedelta(minutes=30)


@dataclass(frozen=True)
class CutoffRule:
    """Decision cutoff: ``local_time`` (UK) on ``days_before`` days before delivery."""

    local_time: time = time(9, 0)
    days_before: int = 1

    def cutoff_for(self, delivery_day: date) -> datetime:
        return cutoff_utc(delivery_day, self.local_time, self.days_before)

    @property
    def label(self) -> str:
        return f"{self.local_time:%H:%M} D-{self.days_before}"


def hours(delta: pd.Series) -> pd.Series:
    """Timedelta series -> float hours."""
    return cast(pd.Series, delta.dt.total_seconds() / 3600)


def local_dates(start_times: pd.Series) -> pd.Series:
    """UK local delivery date of each UTC timestamp."""
    return cast(pd.Series, start_times.dt.tz_convert(UK).dt.date)


def day_cutoffs(days: pd.Series, rule: CutoffRule) -> pd.Series:
    """Map each delivery date to its cutoff instant (UTC); computed once per distinct day."""
    mapping = {d: rule.cutoff_for(d) for d in pd.unique(days)}
    return cast(pd.Series, pd.to_datetime(days.map(mapping), utc=True))


def forecast_is_hourly(forecasts: pd.DataFrame) -> bool:
    """True when no forecast starts at :30 (WINDFOR today; see DECISIONS V4)."""
    return bool(len(forecasts)) and not (forecasts["start_time"].dt.minute != 0).any()


def select_vintage(
    forecasts: pd.DataFrame,
    rule: CutoffRule,
    start_times: pd.Series | pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """For each target start_time pick the latest vintage with publish_time <= cutoff.

    ``forecasts`` needs ``start_time``, ``publish_time``, ``generation_mw``.
    ``start_times`` are the targets (default: every start_time in ``forecasts``).
    A target with no vintage at or before its cutoff gets a null forecast; a later
    vintage is never used (no look-ahead, Break #3).

    Returns one row per target: start_time, cutoff, publish_time, forecast_mw,
    lead_time_h (start - publish), vintage_age_h (cutoff - publish), stale.
    """
    targets = (
        forecasts["start_time"] if start_times is None else pd.Series(start_times)
    ).drop_duplicates()
    left = pd.DataFrame({"start_time": pd.to_datetime(targets, utc=True).to_numpy()})
    left["start_time"] = pd.to_datetime(left["start_time"], utc=True)
    left["cutoff"] = day_cutoffs(local_dates(left["start_time"]), rule)

    right = forecasts[["start_time", "publish_time", "generation_mw"]].copy()
    right["publish_time"] = pd.to_datetime(right["publish_time"], utc=True)
    right["start_time"] = pd.to_datetime(right["start_time"], utc=True)

    out = pd.merge_asof(
        left.sort_values("cutoff"),
        right.sort_values("publish_time"),
        left_on="cutoff",
        right_on="publish_time",
        by="start_time",
        direction="backward",
        allow_exact_matches=True,  # publish_time == cutoff counts as available
    ).rename(columns={"generation_mw": "forecast_mw"})
    out["lead_time_h"] = hours(out["start_time"] - out["publish_time"])
    out["vintage_age_h"] = hours(out["cutoff"] - out["publish_time"])
    out["stale"] = out["vintage_age_h"] > STALE_AFTER_H
    return out.sort_values("start_time").reset_index(drop=True)


def to_half_hourly(selected: pd.DataFrame) -> pd.DataFrame:
    """Apply each hourly forecast as a step to both half-hours (DECISIONS D3).

    Adds ``forecast_hour`` (the hourly value's own start) so callers can count
    independent forecast values. Already half-hourly input is returned as is.
    """
    out = selected.copy()
    out["forecast_hour"] = out["start_time"]
    if (out["start_time"].dt.minute == 30).any():
        return out
    second = out.copy()
    second["start_time"] = second["start_time"] + HALF_HOUR
    second["lead_time_h"] = second["lead_time_h"] + 0.5
    return pd.concat([out, second]).sort_values("start_time").reset_index(drop=True)
