"""Response models for the analytics endpoints. Units are in field names."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class MetricsOut(BaseModel):
    n: int = Field(description="Half-hours with both forecast and actual")
    n_expected: int
    n_days: int
    n_independent: int = Field(description="Distinct forecast values (hourly WINDFOR)")
    completeness: float | None
    mean_actual_mw: float | None
    mean_forecast_mw: float | None
    mae_mw: float | None
    rmse_mw: float | None
    bias_mw: float | None = Field(description="mean(forecast - actual); positive = over-forecast")
    nmae_mean_pct: float | None
    nmae_capacity_pct: float | None
    wmape_pct: float | None
    correlation: float | None
    r2: float | None
    error_quantiles_mw: dict[str, float | None]
    hit_rate_mw_pct: float | None
    hit_rate_pct_pct: float | None
    persistence_mae_mw: float | None
    skill_vs_persistence: float | None
    intervals: dict[str, tuple[float, float]] | None = Field(
        default=None, description="95 % day-block bootstrap intervals; null below 5 days"
    )


class GroupOut(BaseModel):
    key: str
    metrics: MetricsOut
    low_n: bool = Field(description="n < 30: treat with caution")
    excluded_from_ranking: bool


class SeriesPoint(BaseModel):
    start_time: datetime
    actual_mw: float | None
    forecast_mw: float | None
    error_mw: float | None
    band_low_mw: float | None = Field(description="forecast - P90 error: likely floor for actual")
    band_high_mw: float | None = Field(description="forecast - P10 error: likely ceiling")
    publish_time: datetime | None = Field(description="Vintage used (as-of the cutoff)")
    lead_time_h: float | None
    stale: bool


class Band(BaseModel):
    low_quantile: float
    high_quantile: float
    error_low_mw: float
    error_high_mw: float
    basis: Literal["in_sample_window"] = "in_sample_window"


class SeriesOut(BaseModel):
    resolution: Literal["30m", "1h", "1d"]
    points: list[SeriesPoint]
    band: Band | None
    vintages_used: list[datetime]
    gaps: int = Field(description="Half-hours missing an actual or a forecast")
    stale_periods: int


class HistogramOut(BaseModel):
    edges: list[float]
    counts: list[int]
    quantiles: dict[str, float]
    mean: float | None
    n: int
    unit: Literal["MW", "%"]


class CalibrationBucketOut(BaseModel):
    bucket: str
    n: int
    inside_in_sample_pct: float | None
    inside_walk_forward_pct: float | None
    n_walk_forward: int
    low_n: bool


class CalibrationOut(BaseModel):
    nominal_pct: float
    buckets: list[CalibrationBucketOut]


class SweepRow(BaseModel):
    cutoff: str
    days_before: int
    vintages_used: list[str] = Field(description="UTC publish times (HH:MM) of the vintages used")
    n: int
    completeness: float | None
    mae_mw: float | None
    bias_mw: float | None
    p90_error_mw: float | None
    skill_vs_persistence: float | None
    mean_vintage_age_h: float | None
    walk_forward_coverage_pct: float | None
    walk_forward_over_procured_mwh: float | None
    conditional_over_procured_mwh: float | None


class BacktestOut(BaseModel):
    policy: Literal["none", "flat", "conditional"]
    evaluation: Literal["in_sample", "walk_forward"]
    quantile: float
    n: int
    n_days: int
    days_skipped: int
    coverage_pct: float | None
    mean_margin_mw: float | None
    over_procured_mwh: float
    shortfall_mwh: float


class DayMarginOut(BaseModel):
    delivery_date: date
    history_days: int
    mean_margin_mw: float
    coverage_pct: float


class PlanRow(BaseModel):
    start_time: datetime
    period: int
    forecast_mw: float | None
    margin_mw: float | None
    wind_to_plan_mw: float | None = Field(description="forecast - margin: wind to rely on")
    wind_to_plan_mwh: float | None


class PlanOut(BaseModel):
    delivery_date: date
    policy: Literal["none", "flat", "conditional"]
    margin_basis: Literal["walk_forward", "window", "none"]
    history_days: int
    publish_time: datetime | None
    rows: list[PlanRow]
    forecast_total_mwh: float | None
    wind_to_plan_total_mwh: float | None


class MarginOut(BaseModel):
    quantile: float
    margin_mw: float | None
    margin_mwh_per_period: float | None
    recommendation: str
    in_sample: list[BacktestOut]
    walk_forward: list[BacktestOut]
    walk_forward_days: list[DayMarginOut]
    plan: PlanOut | None


class VintagePoint(BaseModel):
    start_time: datetime
    forecast_mw: float


class VintageOut(BaseModel):
    publish_time: datetime
    n_points: int
    full_day: bool
    mean_mw: float
    mae_vs_actual_mw: float | None
    after_cutoff: bool
    selected: bool
    points: list[VintagePoint]


class ActualPoint(BaseModel):
    start_time: datetime
    actual_mw: float


class DayVintagesOut(BaseModel):
    delivery_date: date
    cutoff: datetime
    selected_publish_time: datetime | None
    vintages: list[VintageOut]
    actuals: list[ActualPoint]
    revision_vintages: int
    revision_hours: int
    revision_range_mw: float | None
    revision_step_mw: float | None
    nearest_date_with_data: date | None = Field(
        default=None, description="Set when this day has no vintages"
    )


class ReplayPoint(BaseModel):
    start_time: datetime
    forecast_mw: float | None
    margin_mw: float | None
    wind_to_plan_mw: float | None


class RevealPoint(BaseModel):
    start_time: datetime
    actual_mw: float | None
    error_mw: float | None
    covered: bool | None = Field(description="error <= margin")


class ReplayOut(BaseModel):
    decision_date: date
    delivery_date: date
    cutoff: datetime
    publish_time: datetime | None = Field(description="Vintage on screen at the cutoff")
    vintage_age_h: float | None
    margin_mw: float | None = Field(description="Walk-forward margin knowable at the cutoff")
    history_days: int
    known: list[ReplayPoint] = Field(description="Only what was published by the cutoff")
    recent_actuals: list[ActualPoint] = Field(
        description="Actuals published in the 24 h to the cutoff"
    )
    reveal: list[RevealPoint] = Field(description="What happened next. Hide until revealed")
    reveal_mae_mw: float | None
    reveal_coverage_pct: float | None
    previous_decision: date | None
    next_decision: date | None


class FindingOut(BaseModel):
    id: str
    title: str
    body: str
    value: float | None
    unit: str
    interval: tuple[float, float] | None
    link: str
