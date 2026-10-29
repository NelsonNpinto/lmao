import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.metrics import (
    compute_metrics,
    day_block_bootstrap,
    lead_labels,
    metrics_by,
    summary,
    wind_regime,
)
from tests.unit.frames import aligned

# Hand-checked fixture (worked through in docs/METHODOLOGY.md).
A = [1000, 1200, 800, 0, 500, 1500, 2000, 900, 1100, 700]
E = [100, -200, 50, 0, 300, -100, 250, -50, 0, 150]
PE = [200, -200, 100, 0, -300, 300, 500, -100, 100, 200]


@pytest.fixture
def hand() -> pd.DataFrame:
    return aligned(A, E, PE)


def test_hand_computed_values(hand: pd.DataFrame) -> None:
    m = compute_metrics(hand, capacity_mw=30_000, band_mw=100, band_pct=5)
    assert m.n == 10 and m.n_expected == 10 and m.completeness == 1.0
    assert m.n_independent == 5  # 10 half-hours from 5 hourly values
    assert m.mae_mw == pytest.approx(120.0, abs=1e-4)
    assert m.rmse_mw == pytest.approx(154.9193, abs=1e-4)  # sqrt(240000 / 10)
    assert m.bias_mw == pytest.approx(50.0, abs=1e-4)
    assert m.mean_actual_mw == pytest.approx(970.0, abs=1e-4)
    assert m.nmae_mean_pct == pytest.approx(12.3711, abs=1e-4)  # 120 / 970
    assert m.wmape_pct == pytest.approx(12.3711, abs=1e-4)  # 1200 / 9700
    assert m.nmae_capacity_pct == pytest.approx(0.4, abs=1e-4)
    assert m.r2 == pytest.approx(0.910481, abs=1e-4)  # 1 - 240000 / 2681000
    assert m.error_quantiles_mw["p10"] == pytest.approx(-110.0, abs=1e-4)
    assert m.error_quantiles_mw["p50"] == pytest.approx(25.0, abs=1e-4)
    assert m.error_quantiles_mw["p90"] == pytest.approx(255.0, abs=1e-4)
    assert m.hit_rate_mw_pct == pytest.approx(60.0, abs=1e-4)
    assert m.hit_rate_pct_pct == pytest.approx(20.0, abs=1e-4)
    assert m.persistence_mae_mw == pytest.approx(200.0, abs=1e-4)
    assert m.skill_vs_persistence == pytest.approx(0.4, abs=1e-4)
    f = np.array(A) + np.array(E)
    assert m.correlation == pytest.approx(np.corrcoef(f, A)[0, 1], abs=1e-9)


def test_empty_frame_is_all_none_and_json_safe(hand: pd.DataFrame) -> None:
    m = compute_metrics(hand.iloc[0:0])
    assert m.n == 0 and m.mae_mw is None and m.completeness is None
    assert all(v is None for v in m.error_quantiles_mw.values())
    json.dumps(m.as_dict(), allow_nan=False, default=str)


def test_zero_actuals_never_divide_by_zero() -> None:
    m = compute_metrics(aligned([0, 0, 0], [10, -10, 0], [0, 0, 0]))
    assert m.nmae_mean_pct is None and m.wmape_pct is None and m.r2 is None
    assert m.correlation is None and m.skill_vs_persistence is None  # persistence MAE 0
    json.dumps(m.as_dict(), allow_nan=False, default=str)


def test_gaps_reduce_completeness_but_not_metrics(hand: pd.DataFrame) -> None:
    gap = hand.copy()
    gap.loc[0, ["has_actual"]] = False
    m = compute_metrics(gap)
    assert m.n == 9 and m.completeness == pytest.approx(0.9)


@settings(max_examples=200, deadline=None)
@given(
    data=st.lists(
        st.tuples(st.floats(0, 20_000), st.floats(-8_000, 8_000)), min_size=1, max_size=60
    )
)
def test_mae_le_rmse_and_order_invariance(data: list[tuple[float, float]]) -> None:
    a, e = zip(*data, strict=True)
    df = aligned(list(a), list(e))
    m = compute_metrics(df)
    assert m.mae_mw is not None and m.rmse_mw is not None
    assert m.mae_mw <= m.rmse_mw + 1e-9
    shuffled = compute_metrics(df.sample(frac=1, random_state=1))
    for k in ("mae_mw", "rmse_mw", "bias_mw", "wmape_pct"):
        x, y = getattr(m, k), getattr(shuffled, k)
        assert (x is None and y is None) or x == pytest.approx(y, rel=1e-9, abs=1e-9)


@given(a=st.lists(st.floats(1, 20_000), min_size=2, max_size=40))
def test_perfect_forecast(a: list[float]) -> None:
    m = compute_metrics(aligned(a, [0.0] * len(a)))
    assert m.bias_mw == 0 and m.mae_mw == 0 and m.rmse_mw == 0
    assert m.hit_rate_mw_pct == 100


def test_bootstrap_needs_five_days(hand: pd.DataFrame) -> None:
    assert day_block_bootstrap(hand) is None


def test_bootstrap_intervals_bracket_point_estimates() -> None:
    rng = np.random.default_rng(3)
    a = rng.uniform(2_000, 15_000, 48 * 10)
    e = rng.normal(800, 1_500, len(a))
    df = aligned(a, e, rng.normal(0, 3_000, len(a)), rows_per_day=48)
    m = summary(df)
    assert m.intervals is not None
    for key, point in (("mae_mw", m.mae_mw), ("bias_mw", m.bias_mw), ("rmse_mw", m.rmse_mw)):
        lo, hi = m.intervals[key]
        assert point is not None and lo <= point <= hi
    assert day_block_bootstrap(df, seed=0) == day_block_bootstrap(df, seed=0)  # reproducible


def test_breakdowns_order_and_flags() -> None:
    df = aligned([1000] * 96, [100] * 96, rows_per_day=48)
    df.loc[:47, "lead_time_h"] = 30.0
    df.loc[48:59, "lead_time_h"] = 37.0  # 12 rows only
    df.loc[60:, "lead_time_h"] = 2.0
    groups = metrics_by(df, "lead_time")
    assert [g.key for g in groups] == ["0\u20136 h", "24\u201336 h", "36+ h"]
    assert [g.low_n for g in groups] == [False, False, True]

    df.loc[50:95, "has_actual"] = False  # day 2 at 4 % completeness
    days = metrics_by(df, "day")
    assert [d.key for d in days] == ["2026-01-10", "2026-01-11"]
    assert [d.excluded_from_ranking for d in days] == [False, True]


def test_lead_labels() -> None:
    assert lead_labels([0, 6, 12]) == ["0\u20136 h", "6\u201312 h", "12+ h"]


def test_wind_regime_terciles() -> None:
    df = aligned([1000.0] * 6, [0.0] * 6, rows_per_day=2)
    df["actual_mw"] = [1, 1, 5, 5, 9, 9]
    tags = wind_regime(df)
    assert tags.tolist() == ["calm", "calm", "moderate", "moderate", "windy", "windy"]
    assert wind_regime(df.iloc[:2]).tolist() == ["n/a", "n/a"]
    assert [g.key for g in metrics_by(df, "regime")] == ["calm", "moderate", "windy"]


def test_weekday_and_hour_keys() -> None:
    df = aligned([1000.0] * 4, [10.0] * 4, day=date(2026, 1, 10))  # a Saturday
    assert [g.key for g in metrics_by(df, "weekday")] == ["Sat"]
    assert [g.key for g in metrics_by(df, "hour")] == ["00:00", "01:00"]
