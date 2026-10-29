from datetime import date, time

import pandas as pd
import pytest

from app.domain.evolution import vintage_evolution
from app.domain.vintage import CutoffRule

DAY = date(2026, 1, 10)


def vintage(published: str, value: float, hours: int = 24) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "start_time": pd.date_range("2026-01-10T00:00Z", periods=hours, freq="h"),
            "publish_time": pd.Timestamp(published),
            "generation_mw": value,
        }
    )


def test_evolution_selection_flags_and_revisions() -> None:
    fc = pd.concat(
        [
            vintage("2026-01-08T07:30Z", 9_000.0, hours=22),  # D-2: stops at 21:00Z
            vintage("2026-01-09T02:30Z", 10_000.0),
            vintage("2026-01-09T07:30Z", 10_600.0),
            vintage("2026-01-09T09:30Z", 11_000.0),  # after the 09:00 cutoff
        ]
    )
    actuals = pd.DataFrame(
        {
            "start_time": pd.date_range("2026-01-10T00:00Z", periods=48, freq="30min"),
            "generation_mw": 10_500.0,
        }
    )
    ev = vintage_evolution(fc, actuals, DAY, CutoffRule(time(9)))

    assert ev.selected_publish_time == pd.Timestamp("2026-01-09T07:30Z")
    assert ev.vintages["after_cutoff"].tolist() == [False, False, False, True]
    assert ev.vintages["full_day"].tolist() == [False, True, True, True]
    assert ev.vintages.loc[ev.vintages["selected"], "mae_vs_actual_mw"].item() == pytest.approx(
        100.0
    )
    # Revisions compare the 22 hours all three pre-cutoff vintages share.
    assert ev.revision_vintages == 3 and ev.revision_hours == 22
    assert ev.revision_range_mw == pytest.approx(1_600.0)
    assert ev.revision_step_mw == pytest.approx((1_000 + 600) / 2)
    assert len(ev.points) == 22 + 24 * 3


def test_evolution_empty_day() -> None:
    empty = pd.DataFrame(
        {
            "start_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "publish_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "generation_mw": pd.Series(dtype=float),
        }
    )
    ev = vintage_evolution(empty, empty, DAY, CutoffRule(time(9)))
    assert ev.selected_publish_time is None
    assert ev.vintages.empty and ev.revision_range_mw is None
