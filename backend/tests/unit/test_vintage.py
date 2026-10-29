from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.vintage import CutoffRule, select_vintage, to_half_hourly


def fc(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["start_time", "publish_time", "generation_mw"])
    df["start_time"] = pd.to_datetime(df["start_time"], utc=True)
    df["publish_time"] = pd.to_datetime(df["publish_time"], utc=True)
    return df


# Delivery 10 Jan 2026, hour 12:00. Three D-1 vintages and one on D itself.
TOY = fc(
    [
        ("2026-01-10T12:00Z", "2026-01-09T02:30Z", 100.0),
        ("2026-01-10T12:00Z", "2026-01-09T07:30Z", 200.0),
        ("2026-01-10T12:00Z", "2026-01-09T09:30Z", 300.0),
        ("2026-01-10T12:00Z", "2026-01-10T03:00Z", 400.0),
    ]
)


@pytest.mark.parametrize(
    ("cutoff", "value", "published"),
    [
        (time(7, 0), 100.0, "2026-01-09T02:30Z"),
        (time(9, 0), 200.0, "2026-01-09T07:30Z"),
        (time(7, 30), 200.0, "2026-01-09T07:30Z"),  # publish == cutoff is available
        (time(11, 0), 300.0, "2026-01-09T09:30Z"),
        (time(23, 0), 300.0, "2026-01-09T09:30Z"),  # D's own vintage never used
    ],
)
def test_toy_vintage_at_each_cutoff(cutoff: time, value: float, published: str) -> None:
    out = select_vintage(TOY, CutoffRule(cutoff))
    assert len(out) == 1
    row = out.iloc[0]
    assert row["forecast_mw"] == value
    assert row["publish_time"] == pd.Timestamp(published)


def test_lead_time_and_age() -> None:
    row = select_vintage(TOY, CutoffRule(time(9))).iloc[0]
    assert row["lead_time_h"] == pytest.approx(28.5)  # 07:30 D-1 -> 12:00 D
    assert row["vintage_age_h"] == pytest.approx(1.5)  # 07:30 -> 09:00
    assert not row["stale"]


def test_no_vintage_before_cutoff_gives_null_not_a_later_one() -> None:
    row = select_vintage(TOY, CutoffRule(time(2, 0))).iloc[0]
    assert pd.isna(row["forecast_mw"]) and pd.isna(row["publish_time"])


def test_stale_flag_when_only_old_vintage_exists() -> None:
    old = fc([("2026-01-10T12:00Z", "2026-01-08T05:00Z", 50.0)])
    row = select_vintage(old, CutoffRule(time(9))).iloc[0]
    assert row["forecast_mw"] == 50.0
    assert row["vintage_age_h"] == pytest.approx(28.0)
    assert row["stale"]


def test_cutoff_is_converted_per_day_across_bst() -> None:
    # Decision day 29 Mar is the first BST day: 09:00 UK = 08:00Z (Break #11).
    df = fc(
        [
            ("2026-03-30T12:00Z", "2026-03-29T07:30Z", 1.0),
            ("2026-03-30T12:00Z", "2026-03-29T08:30Z", 2.0),  # 09:30 BST: too late
        ]
    )
    row = select_vintage(df, CutoffRule(time(9))).iloc[0]
    assert row["cutoff"] == pd.Timestamp("2026-03-29T08:00Z")
    assert row["forecast_mw"] == 1.0


def test_explicit_targets_without_forecasts_are_kept_as_null() -> None:
    targets = pd.to_datetime(["2026-01-10T12:00Z", "2026-01-10T13:00Z"], utc=True)
    out = select_vintage(TOY, CutoffRule(time(9)), targets)
    assert out["forecast_mw"].isna().tolist() == [False, True]


def test_to_half_hourly_steps_hourly_values() -> None:
    sel = select_vintage(TOY, CutoffRule(time(9)))
    hh = to_half_hourly(sel)
    assert hh["start_time"].tolist() == [
        pd.Timestamp("2026-01-10T12:00Z"),
        pd.Timestamp("2026-01-10T12:30Z"),
    ]
    assert hh["forecast_mw"].tolist() == [200.0, 200.0]
    assert hh["lead_time_h"].tolist() == [28.5, 29.0]
    assert hh["forecast_hour"].nunique() == 1


# -- properties --------------------------------------------------------------

D0 = datetime(2026, 1, 7, tzinfo=UTC)


@settings(max_examples=150, deadline=None)
@given(
    pubs=st.lists(
        st.tuples(st.integers(0, 6 * 24 * 2), st.floats(0, 20_000)), min_size=1, max_size=40
    ),
    hours=st.lists(st.integers(0, 47), min_size=1, max_size=6, unique=True),
    cut_h=st.integers(0, 23),
    cut_m=st.sampled_from([0, 30]),
    days_before=st.integers(1, 2),
)
def test_never_selects_after_cutoff_and_always_latest_eligible(
    pubs: list[tuple[int, float]], hours: list[int], cut_h: int, cut_m: int, days_before: int
) -> None:
    rows = []
    for h in hours:
        start = datetime(2026, 1, 10, tzinfo=UTC) + timedelta(hours=h)
        for half_hours, v in pubs:
            rows.append((start, D0 + timedelta(minutes=30 * half_hours), v))
    df = pd.DataFrame(rows, columns=["start_time", "publish_time", "generation_mw"])
    df = df.drop_duplicates(["start_time", "publish_time"], keep="last")
    rule = CutoffRule(time(cut_h, cut_m), days_before)
    out = select_vintage(df, rule)

    for _, r in out.iterrows():
        cutoff = rule.cutoff_for(r["start_time"].tz_convert("Europe/London").date())
        eligible = df[(df["start_time"] == r["start_time"]) & (df["publish_time"] <= cutoff)]
        if eligible.empty:
            assert pd.isna(r["publish_time"])
        else:
            assert r["publish_time"] <= cutoff
            assert r["publish_time"] == eligible["publish_time"].max()


@settings(max_examples=50, deadline=None)
@given(seed=st.integers(0, 10_000))
def test_selection_is_invariant_to_row_order(seed: int) -> None:
    base = pd.concat(
        [TOY.assign(start_time=TOY["start_time"] + pd.Timedelta(hours=h)) for h in range(6)]
    )
    shuffled = base.sample(frac=1, random_state=seed)
    a = select_vintage(base, CutoffRule(time(9)))
    b = select_vintage(shuffled, CutoffRule(time(9)))
    pd.testing.assert_frame_equal(a, b)


def test_rule_label() -> None:
    assert CutoffRule(time(9), 1).label == "09:00 D-1"
    assert CutoffRule(time(9)).cutoff_for(date(2026, 1, 10)) == datetime(2026, 1, 9, 9, tzinfo=UTC)
