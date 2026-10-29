"""Command line: ``uv run python -m app.cli seed [--refresh] [--from D] [--to D]``."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from app.config import get_settings
from app.db import repositories as repo
from app.db.migrate import upgrade_to_head
from app.db.session import make_engine, make_sessionmaker
from app.domain.align import build_aligned
from app.domain.margin import recommend
from app.domain.metrics import metrics_by, summary
from app.domain.timeutil import local_day_bounds_utc
from app.domain.vintage import CutoffRule
from app.ingest.runner import IngestRequest, IngestRunner
from app.logging import configure_logging
from app.main import http_client_factory


async def seed(delivery_from: date, delivery_to: date, refresh: bool) -> int:
    s = get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(s.database_url)
    await upgrade_to_head(engine)
    sm = make_sessionmaker(engine)
    runner = IngestRunner(sm, http_client_factory(s), concurrency=s.elexon_concurrency)
    run = await runner.run(
        IngestRequest(
            delivery_from=delivery_from,
            delivery_to=delivery_to,
            mode="refresh" if refresh else "read_through",
            forecast_lookback_days=s.forecast_lookback_days,
            chunk_days=s.elexon_chunk_days,
        )
    )
    async with sm() as session:
        cov = await repo.coverage(session)
    cov.pop("last_run")
    await engine.dispose()
    summary = {
        "run_id": run.id,
        "status": run.status,
        "rows_fetched": run.rows_fetched,
        "rows_upserted": run.rows_upserted,
        "rows_rejected": run.rows_rejected,
        "quality": run.quality,
        "coverage": {k: str(v) for k, v in cov.items()},
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if run.status in ("succeeded", "partial") else 1


async def report(day_from: date, day_to: date, cutoffs: list[time]) -> int:
    """Print headline metrics and margin backtests per cutoff (used for METHODOLOGY.md)."""
    s = get_settings()
    engine = make_engine(s.database_url)
    start, _ = local_day_bounds_utc(day_from - timedelta(days=1))
    end, _ = local_day_bounds_utc(day_to)
    async with make_sessionmaker(engine)() as session:
        actuals = await repo.load_actuals_df(session, start, end)
        forecasts = await repo.load_forecasts_df(session, start, end)
    await engine.dispose()

    def r(x: float | None, nd: int = 0) -> float | None:
        return None if x is None else round(x, nd)

    out: dict[str, Any] = {"window": [day_from.isoformat(), day_to.isoformat()], "cutoffs": {}}
    for c in cutoffs:
        al = build_aligned(actuals, forecasts, day_from, day_to, CutoffRule(c))
        m = summary(al, capacity_mw=s.installed_capacity_mw)
        rec = recommend(al, s.margin_quantile)
        out["cutoffs"][c.strftime("%H:%M")] = {
            "vintages_used": sorted(al["publish_time"].dropna().dt.strftime("%H:%M").unique()),
            "n": m.n,
            "n_independent": m.n_independent,
            "completeness": m.completeness,
            "mae_mw": r(m.mae_mw),
            "rmse_mw": r(m.rmse_mw),
            "bias_mw": r(m.bias_mw),
            "nmae_mean_pct": r(m.nmae_mean_pct, 1),
            "wmape_pct": r(m.wmape_pct, 1),
            "correlation": r(m.correlation, 3),
            "r2": r(m.r2, 3),
            "skill_vs_persistence": r(m.skill_vs_persistence, 3),
            "persistence_mae_mw": r(m.persistence_mae_mw),
            "error_quantiles_mw": {k: r(v) for k, v in m.error_quantiles_mw.items()},
            "hit_rate_500mw_pct": r(m.hit_rate_mw_pct, 1),
            "hit_rate_10pct_pct": r(m.hit_rate_pct_pct, 1),
            "intervals_95": {
                k: [round(a), round(b)] if abs(b) > 2 else [round(a, 3), round(b, 3)]
                for k, (a, b) in (m.intervals or {}).items()
            },
            "margin_p90_mw": r(rec.margin_mw),
            "backtests": [
                {
                    "evaluation": b.evaluation,
                    "policy": b.policy,
                    "days": b.n_days,
                    "coverage_pct": r(b.coverage_pct, 1),
                    "mean_margin_mw": r(b.mean_margin_mw),
                    "over_procured_gwh": r(b.over_procured_mwh / 1000, 1),
                    "shortfall_gwh": r(b.shortfall_mwh / 1000, 1),
                }
                for b in rec.in_sample + rec.walk_forward
            ],
            "by_regime": {
                g.key: {
                    "n": g.metrics.n,
                    "mae_mw": r(g.metrics.mae_mw),
                    "bias_mw": r(g.metrics.bias_mw),
                }
                for g in metrics_by(al, "regime")
            },
            "by_lead_time": {
                g.key: {
                    "n": g.metrics.n,
                    "mae_mw": r(g.metrics.mae_mw),
                    "bias_mw": r(g.metrics.bias_mw),
                }
                for g in metrics_by(al, "lead_time", lead_edges=s.lead_time_buckets_h)
            },
        }
    print(json.dumps(out, indent=2, default=str))
    return 0


def snapshot_key(path: str, query: dict[str, str]) -> str:
    """Must match frontend/src/lib/snapshot.ts: path + '?' + sorted, unencoded params."""
    q = "&".join(f"{k}={v}" for k, v in sorted(query.items()))
    return f"{path}?{q}" if q else path


async def snapshot(out_dir: str, cutoff: str = "09:00") -> int:
    """Save every API response the UI requests for the default view, so the
    frontend can run read-only from static files when the API is down (Break #20)."""
    import hashlib
    from pathlib import Path

    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    s = get_settings().model_copy(update={"seed_on_startup": False})
    app = create_app(s)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    entries: dict[str, str] = {}
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://snapshot") as c:

            async def save(path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
                q = query or {}
                r = await c.get(path, params=q)
                r.raise_for_status()
                key = snapshot_key(path, q)
                name = hashlib.sha1(key.encode()).hexdigest()[:16] + ".json"
                (out / name).write_bytes(r.content)
                entries[key] = name
                return r.json()  # type: ignore[no-any-return]

            base = {"cutoff": cutoff}
            summary = await save("/api/v1/metrics/summary", base)
            first = date.fromisoformat(summary["meta"]["window_from"])
            last = date.fromisoformat(summary["meta"]["window_to"])
            days = [first + timedelta(days=i) for i in range((last - first).days)]
            await save("/api/v1/meta")
            await save("/api/v1/series", base)
            await save("/api/v1/findings", base)
            await save("/api/v1/metrics/calibration", base)
            await save("/api/v1/ingest/runs", {"limit": "20"})
            for dim in ("day", "hour", "weekday", "lead_time", "regime"):
                await save(f"/api/v1/metrics/by/{dim}", base)
            for norm in ("false", "true"):
                await save(
                    "/api/v1/metrics/error-distribution", {**base, "bins": "40", "normalise": norm}
                )
            hourly = ",".join(f"{h:02d}:00" for h in range(24))
            await save(
                "/api/v1/metrics/cutoff-sweep", {**base, "days_before": "1", "cutoffs": hourly}
            )
            for d in days:
                iso = d.isoformat()
                await save(f"/api/v1/days/{iso}/vintages", base)
                await save(f"/api/v1/replay/{(d - timedelta(days=1)).isoformat()}", base)
                for policy in ("flat", "conditional", "none"):
                    await save("/api/v1/procurement/margin", {**base, "policy": policy, "day": iso})
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "cutoff": cutoff,
        "window": [first.isoformat(), last.isoformat()],
        "entries": entries,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    size = sum(f.stat().st_size for f in out.glob("*.json"))
    print(f"snapshot: {len(entries)} responses, {size / 1e6:.1f} MB -> {out}")
    return 0


def main() -> None:
    s = get_settings()
    p = argparse.ArgumentParser(prog="windsight")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("seed", help="ingest actuals and forecasts for a delivery window")
    sp.add_argument("--from", dest="d_from", type=date.fromisoformat, default=s.seed_from)
    sp.add_argument(
        "--to", dest="d_to", type=date.fromisoformat, default=s.seed_to, help="exclusive"
    )
    sp.add_argument("--refresh", action="store_true", help="ignore the raw cache, call Elexon")
    rp = sub.add_parser("report", help="print headline metrics for one or more cutoffs")
    rp.add_argument("--from", dest="d_from", type=date.fromisoformat, default=s.study_from)
    rp.add_argument("--to", dest="d_to", type=date.fromisoformat, default=s.study_to)
    rp.add_argument("--cutoff", dest="cutoffs", type=time.fromisoformat, action="append")
    snp = sub.add_parser("snapshot", help="save API responses for the static fallback")
    snp.add_argument("out_dir", nargs="?", default="../frontend/public/snapshot")
    op = sub.add_parser("openapi", help="write the OpenAPI schema to a file")
    op.add_argument("path", nargs="?", default="-")
    args = p.parse_args()
    configure_logging(s.log_level, json=False)
    if args.cmd == "openapi":
        from app.main import create_app

        spec = json.dumps(create_app(s).openapi(), indent=2, sort_keys=True)
        if args.path == "-":
            print(spec)
        else:
            with open(args.path, "w") as fh:
                fh.write(spec + "\n")
        raise SystemExit(0)
    if args.cmd == "snapshot":
        raise SystemExit(asyncio.run(snapshot(args.out_dir)))
    if args.cmd == "report":
        cutoffs = args.cutoffs or [s.cutoff_local]
        raise SystemExit(asyncio.run(report(args.d_from, args.d_to, cutoffs)))
    raise SystemExit(asyncio.run(seed(args.d_from, args.d_to, args.refresh)))


if __name__ == "__main__":
    main()
