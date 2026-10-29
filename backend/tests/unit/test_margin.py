from datetime import date, timedelta

import numpy as np
import pytest

from app.domain.margin import (
    MIN_HISTORY_DAYS,
    fit_policy,
    in_sample,
    known_days_at_cutoff,
    recommend,
    walk_forward,
)
from tests.unit.frames import aligned


def test_flat_margin_hand_computed() -> None:
    # errors 1..100 MW: P90 (linear) = 90.1 MW; covers 90 of 100 half-hours.
    df = aligned([5_000.0] * 100, list(range(1, 101)))
    bt = in_sample(df, "flat", 0.9)
    assert bt.mean_margin_mw == pytest.approx(90.1)
    assert bt.coverage_pct == pytest.approx(90.0)
    # over-procured = sum_{e=1}^{90} (90.1 - e) * 0.5 = (8109 - 4095) * 0.5
    assert bt.over_procured_mwh == pytest.approx(2007.0)
    # shortfall = sum_{e=91}^{100} (e - 90.1) * 0.5 = (955 - 901) * 0.5
    assert bt.shortfall_mwh == pytest.approx(27.0)


def test_no_margin_policy() -> None:
    df = aligned([5_000.0] * 4, [100, -100, 50, -50])
    bt = in_sample(df, "none", 0.9)
    assert bt.mean_margin_mw == 0 and bt.coverage_pct == 50.0
    assert bt.shortfall_mwh == pytest.approx(75.0) and bt.over_procured_mwh == pytest.approx(75.0)


def test_conditional_uses_level_bins_and_falls_back_when_sparse() -> None:
    # Low forecasts err by ~0, high forecasts by ~1000: conditional margins differ by bin.
    levels = np.repeat([1_000.0, 8_000.0, 15_000.0], 60)
    errors = np.concatenate([np.zeros(60), np.full(60, 500.0), np.full(60, 1_000.0)])
    df = aligned(levels - errors, errors)  # forecast = level
    m = fit_policy(df, "conditional", 0.9)(df)
    assert set(np.round(m)) == {0, 500, 1000}

    small = df.iloc[::10]  # 18 rows: every bin below MIN_BIN_N -> flat everywhere
    m_small = fit_policy(small, "conditional", 0.9)(small)
    assert len(set(m_small)) == 1


def test_known_days_exclude_yesterday_at_morning_cutoff() -> None:
    df = aligned([1.0] * 5, [0.0] * 5, rows_per_day=1)
    known = known_days_at_cutoff(df)
    d0 = date(2026, 1, 10)
    assert known[d0 + timedelta(days=1)] == []  # D-1 still in progress at 09:00 D-1
    assert known[d0 + timedelta(days=4)] == [d0 + timedelta(days=i) for i in range(3)]


def test_walk_forward_has_no_look_ahead_and_reveals_drift() -> None:
    # Errors drift upwards day by day: a margin fitted on the whole window looks
    # fine in-sample, but a margin fitted on the past keeps under-covering.
    rng = np.random.default_rng(0)
    days, per = 30, 48
    drift = np.repeat(np.arange(days) * 150.0, per)
    e = drift + rng.normal(0, 300, days * per)
    df = aligned([8_000.0] * len(e), e, rows_per_day=per)

    ins = in_sample(df, "flat", 0.9)
    wf, per_day = walk_forward(df, "flat", 0.9)
    assert ins.coverage_pct == pytest.approx(90.0, abs=0.5)
    assert wf.coverage_pct is not None and wf.coverage_pct < 60
    # History grows by one day per day and never includes D-1 or D itself.
    assert per_day["history_days"].tolist() == list(range(MIN_HISTORY_DAYS, days - 1))
    assert wf.days_skipped == MIN_HISTORY_DAYS + 1
    assert wf.n_days == days - MIN_HISTORY_DAYS - 1


def test_walk_forward_too_short_window() -> None:
    df = aligned([1.0] * 3, [1.0] * 3, rows_per_day=1)
    wf, per_day = walk_forward(df, "flat", 0.9)
    assert wf.n == 0 and wf.coverage_pct is None and per_day.empty


def test_recommend_contains_every_policy_and_evaluation() -> None:
    df = aligned([5_000.0] * 480, np.linspace(-1_000, 3_000, 480), rows_per_day=48)
    r = recommend(df, 0.9)
    assert r.margin_mw == pytest.approx(np.quantile(np.linspace(-1_000, 3_000, 480), 0.9))
    assert r.margin_mwh_per_period == pytest.approx(r.margin_mw * 0.5)
    assert {b.policy for b in r.in_sample} == {"none", "flat", "conditional"}
    assert r.by("walk_forward", "flat").evaluation == "walk_forward"
