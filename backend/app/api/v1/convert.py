"""Turn pandas / domain values into JSON-safe Python (NaN, NaT -> None)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas as pd

from app.domain.metrics import GroupMetrics, MetricsResult
from app.schemas.analytics import GroupOut, MetricsOut


def nn(v: Any) -> Any:
    """None for NaN/NaT/pd.NA; plain Python scalars otherwise."""
    if v is None or v is pd.NaT or v is pd.NA:
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if hasattr(v, "item") and not isinstance(v, datetime):
        return nn(v.item())
    return v


def records(df: pd.DataFrame, cols: list[str]) -> list[dict[str, Any]]:
    return [
        {c: nn(v) for c, v in zip(cols, row, strict=True)}
        for row in df[cols].itertuples(index=False)
    ]


def metrics_out(m: MetricsResult) -> MetricsOut:
    return MetricsOut.model_validate(m.as_dict())


def group_out(g: GroupMetrics) -> GroupOut:
    return GroupOut(
        key=g.key,
        metrics=metrics_out(g.metrics),
        low_n=g.low_n,
        excluded_from_ranking=g.excluded_from_ranking,
    )
