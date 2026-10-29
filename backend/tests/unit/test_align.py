from datetime import date, time

import pandas as pd

from app.domain.align import build_aligned, half_hour_grid
from app.domain.baseline import persistence_baseline
from app.domain.timeutil import local_day_bounds_utc
from app.domain.vintage import CutoffRule

RULE = CutoffRule(time(9))


def actuals_for(day_from: date, day_to: date, value: float | None = None) -> pd.DataFrame:
    grid = half_hour_grid(day_from, day_to)
    df = pd.DataFrame({"start_time": grid})
    # value = period index of the day * 10, so persistence is easy to check
    day_start = df["start_time"].map(
        lambda t: pd.Timestamp(local_day_bounds_utc(t.tz_convert("Europe/London").date())[0])
    )
    period = ((df["start_time"] - day_start) / pd.Timedelta(minutes=30)).astype(int) + 1
    df["generation_mw"] = float(value) if value is not None else period * 10.0
    return df


def hourly_forecasts(day: date, published: str, value: float) -> pd.DataFrame:
    start, end = local_day_bounds_utc(day)
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    return pd.DataFrame(
        {
            "start_time": hours,
            "publish_time": pd.Timestamp(published),
            "generation_mw": value,
        }
    )


def test_grid_handles_clock_changes() -> None:
    assert len(half_hour_grid(date(2026, 3, 29), date(2026, 3, 30))) == 46
    assert len(half_hour_grid(date(2026, 10, 25), date(2026, 10, 26))) == 50
    assert len(half_hour_grid(date(2026, 1, 2), date(2026, 2, 2))) == 1488


def test_aligned_has_every_half_hour_and_flags_gaps() -> None:
    a = actuals_for(date(2026, 1, 9), date(2026, 1, 11))
    a = a[
        ~a["start_time"].between(
            pd.Timestamp("2026-01-10T06:00Z"), pd.Timestamp("2026-01-10T07:30Z")
        )
    ]
    f = hourly_forecasts(date(2026, 1, 10), "2026-01-09T07:30Z", 1000.0)
    al = build_aligned(a, f, date(2026, 1, 10), date(2026, 1, 11), RULE)
    assert len(al) == 48
    assert (~al["has_actual"]).sum() == 4
    assert al["has_forecast"].all()
    assert al["forecast_mw"].eq(1000.0).all()
    gap = al[~al["has_actual"]]
    assert gap["error_mw"].isna().all()  # no silent interpolation
    assert al["period"].tolist() == list(range(1, 49))


def test_error_sign_and_persistence() -> None:
    a = actuals_for(date(2026, 1, 9), date(2026, 1, 11))
    f = hourly_forecasts(date(2026, 1, 10), "2026-01-09T07:30Z", 300.0)
    al = build_aligned(a, f, date(2026, 1, 10), date(2026, 1, 11), RULE)
    first = al.iloc[0]
    assert first["actual_mw"] == 10.0 and first["forecast_mw"] == 300.0
    assert first["error_mw"] == 290.0  # forecast - actual: positive = over-forecast
    assert (al["persistence_mw"] == al["period"] * 10.0).all()
    assert (al["persistence_error_mw"] == 0).all()


def test_forecast_published_after_cutoff_leaves_null() -> None:
    a = actuals_for(date(2026, 1, 9), date(2026, 1, 11))
    f = hourly_forecasts(date(2026, 1, 10), "2026-01-09T09:30Z", 300.0)
    al = build_aligned(a, f, date(2026, 1, 10), date(2026, 1, 11), RULE)
    assert not al["has_forecast"].any()
    assert al["cutoff"].eq(pd.Timestamp("2026-01-09T09:00Z")).all()


def test_no_forecasts_at_all() -> None:
    a = actuals_for(date(2026, 1, 9), date(2026, 1, 11))
    empty = pd.DataFrame(
        {
            "start_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "publish_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "generation_mw": pd.Series(dtype=float),
        }
    )
    al = build_aligned(a, empty, date(2026, 1, 10), date(2026, 1, 11), RULE)
    assert len(al) == 48 and not al["has_forecast"].any()


def test_persistence_across_autumn_clock_change() -> None:
    # 25 Oct has 50 periods, 26 Oct has 48: periods 49-50 have no target.
    a = actuals_for(date(2026, 10, 25), date(2026, 10, 26))
    p = persistence_baseline(a)
    assert len(p) == 48
    assert p["start_time"].min() == pd.Timestamp("2026-10-26T00:00Z")


def test_persistence_after_spring_clock_change() -> None:
    # 29 Mar has 46 periods, so 30 Mar periods 47-48 have no persistence.
    a = actuals_for(date(2026, 3, 29), date(2026, 3, 30))
    f = hourly_forecasts(date(2026, 3, 30), "2026-03-29T06:30Z", 1.0)
    al = build_aligned(a, f, date(2026, 3, 30), date(2026, 3, 31), RULE)
    assert al["persistence_mw"].isna().sum() == 2
    assert al.loc[al["persistence_mw"].isna(), "period"].tolist() == [47, 48]
