"""Plain-English findings computed from the metrics. No number here is hard-coded:
every sentence is assembled from results, and its wording follows the sign and
size of what was measured."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.margin import MIN_HISTORY_DAYS, MarginRecommendation
from app.domain.metrics import GroupMetrics, MetricsResult


@dataclass(frozen=True)
class Finding:
    id: str
    title: str
    body: str
    value: float | None
    unit: str
    interval: tuple[float, float] | None
    link: str  # frontend route that shows the evidence


def _mw(x: float) -> str:
    return f"{x:,.0f} MW"


def _gw(x: float) -> str:
    return f"{x / 1000:,.1f} GW"


@dataclass(frozen=True)
class SweepPoint:
    cutoff: str
    vintage: str | None
    mae_mw: float | None


def build_findings(
    summary: MetricsResult,
    regimes: list[GroupMetrics],
    rec: MarginRecommendation,
    sweep: list[SweepPoint],
    cutoff_label: str,
) -> list[Finding]:
    out: list[Finding] = []
    iv = summary.intervals or {}

    if summary.bias_mw is not None and summary.n:
        lo, hi = iv.get("bias_mw", (None, None))
        sure = lo is not None and hi is not None and (lo > 0 or hi < 0)
        direction = "above" if summary.bias_mw > 0 else "below"
        consequence = (
            "so buying against it leaves the desk short more often than long"
            if summary.bias_mw > 0
            else "so buying against it leaves the desk long more often than short"
        )
        out.append(
            Finding(
                id="bias",
                title="The forecast is systematically biased"
                if sure
                else "No clear bias at this sample size",
                body=(
                    f"At the {cutoff_label} cutoff the forecast ran on average "
                    f"{_mw(abs(summary.bias_mw))} {direction} actual wind, {consequence}."
                    + ("" if sure else " The 95 % interval includes zero.")
                ),
                value=summary.bias_mw,
                unit="MW",
                interval=iv.get("bias_mw"),
                link="/accuracy#bias",
            )
        )

    named = {g.key: g for g in regimes if not g.low_n and g.metrics.bias_mw is not None}
    if "calm" in named and "windy" in named:
        calm, windy = named["calm"].metrics, named["windy"].metrics
        assert calm.bias_mw is not None and windy.bias_mw is not None
        worse = "windy" if abs(windy.bias_mw) > abs(calm.bias_mw) else "calm"
        out.append(
            Finding(
                id="regime",
                title=f"Errors are largest on {worse} days",
                body=(
                    f"On windy days the bias was {_mw(windy.bias_mw)} (MAE {_mw(windy.mae_mw or 0)}); "
                    f"on calm days {_mw(calm.bias_mw)} (MAE {_mw(calm.mae_mw or 0)}). "
                    "Curtailment of wind farms on the windiest days is one likely cause."
                ),
                value=windy.bias_mw - calm.bias_mw,
                unit="MW",
                interval=None,
                link="/findings#regime",
            )
        )

    if summary.skill_vs_persistence is not None:
        s = summary.skill_vs_persistence
        out.append(
            Finding(
                id="skill",
                title="The forecast beats a naive guess"
                if s > 0
                else "The forecast does not beat a naive guess",
                body=(
                    f"Its error is {abs(s) * 100:.0f} % {'smaller' if s > 0 else 'larger'} than assuming "
                    f"tomorrow repeats today (persistence MAE {_mw(summary.persistence_mae_mw or 0)})."
                ),
                value=s,
                unit="ratio",
                interval=iv.get("skill_vs_persistence"),
                link="/accuracy",
            )
        )

    current = next((p for p in sweep if p.cutoff == cutoff_label[:5]), None)
    later = [p for p in sweep if current and p.cutoff > current.cutoff and p.mae_mw is not None]
    if current and current.mae_mw is not None and later:
        nxt = min(later, key=lambda p: p.cutoff)
        assert nxt.mae_mw is not None
        gain = current.mae_mw - nxt.mae_mw
        pct = 100 * gain / current.mae_mw
        out.append(
            Finding(
                id="cutoff",
                title="Deciding later barely helps"
                if abs(pct) < 5
                else "Deciding later changes accuracy",
                body=(
                    f"Waiting from {current.cutoff} to {nxt.cutoff} switches to the {nxt.vintage} vintage "
                    f"and changes MAE by {_mw(-gain)} ({-pct:+.1f} %)."
                ),
                value=-gain,
                unit="MW",
                interval=None,
                link="/cutoff",
            )
        )

    flat_wf = rec.by("walk_forward", "flat")
    cond_wf = rec.by("walk_forward", "conditional")
    if rec.margin_mw is not None:
        q = round(rec.quantile * 100)
        honest = (
            f"but {flat_wf.coverage_pct:.1f} % when each day's margin is set only from days "
            "already known at its cutoff."
            if flat_wf.coverage_pct is not None
            else "but the window is too short for an out-of-sample check "
            f"(needs {MIN_HISTORY_DAYS} days of history), so treat it as optimistic."
        )
        out.append(
            Finding(
                id="margin",
                title=f"A P{q} margin of {_gw(rec.margin_mw)}",
                body=(
                    f"Buying against forecast minus {_mw(rec.margin_mw)} of wind would have covered "
                    f"{q} % of half-hours in hindsight, {honest}"
                ),
                value=rec.margin_mw,
                unit="MW",
                interval=iv.get("p90_mw") if q == 90 else None,
                link="/#margin",
            )
        )
        if (
            cond_wf.coverage_pct is not None
            and flat_wf.coverage_pct is not None
            and flat_wf.over_procured_mwh > 0
        ):
            saving = 100 * (1 - cond_wf.over_procured_mwh / flat_wf.over_procured_mwh)
            similar = abs(cond_wf.coverage_pct - flat_wf.coverage_pct) <= 1.0
            out.append(
                Finding(
                    id="smart-margin",
                    title=(
                        f"A smarter margin cuts over-buying by {saving:.0f} %"
                        if similar and saving > 0
                        else "A level-dependent margin is not a clear win here"
                    ),
                    body=(
                        f"Varying the margin with the forecast level gave {cond_wf.coverage_pct:.1f} % "
                        f"coverage (flat: {flat_wf.coverage_pct:.1f} %) with "
                        f"{cond_wf.over_procured_mwh / 1000:,.0f} GWh over-procured "
                        f"(flat: {flat_wf.over_procured_mwh / 1000:,.0f} GWh), out of sample."
                    ),
                    value=saving,
                    unit="%",
                    interval=None,
                    link="/findings#policies",
                )
            )
    return out
