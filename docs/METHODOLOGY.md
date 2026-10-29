# Methodology

Every number WindSight shows is computed by the pure functions in `backend/app/domain/` from the raw Elexon rows in the database. This document defines each one, works one example by hand, and gives January 2026 results you can reproduce with:

```bash
cd backend && uv run python -m app.cli report --cutoff 07:00 --cutoff 09:00 --cutoff 11:00 --cutoff 23:00
```

## 1. Data

| Dataset | Elexon stream | Resolution | Stored as |
|---|---|---|---|
| Actual wind outturn | `FUELHH`, `fuelType=WIND` | half-hourly, MW averaged over the period | `wind_actual`, one row per half-hour |
| Wind forecast | `WINDFOR` | **hourly**, about 8 publications (vintages) a day, 2–3 days ahead | `wind_forecast`, one row per (target hour, vintage) |

All timestamps are stored and processed in UTC. UK local time is used in exactly two places: deciding which delivery day a half-hour belongs to, and turning a cutoff such as "09:00 on D-1" into a UTC instant for that specific day (so it stays correct across BST).

Energy: a half-hour at *x* MW is *x* × 0.5 MWh.

## 2. As-of forecast selection

For delivery day *D* and cutoff rule (*t*, *n*) — local time *t* on *D − n*:

    cutoff(D) = UK-local(D − n, t) → UTC
    forecast(h) = generation of the vintage with the greatest publish_time ≤ cutoff(D), for target hour h in D

- `publish_time == cutoff` counts as available.
- If no vintage exists at or before the cutoff, the forecast is **null**. A later vintage is never substituted. A hypothesis property test checks this against a brute-force search on random data, and mutating the selection to look ahead fails 7 tests.
- Implementation: `pandas.merge_asof(left=targets sorted by cutoff, right=vintages sorted by publish_time, by="start_time", direction="backward")` in `domain/vintage.py`.
- `lead_time_h = start_time − publish_time`; `vintage_age_h = cutoff − publish_time`. A vintage older than 24 h at the cutoff is still used but flagged `stale`.
- **Hourly to half-hourly.** The selected hourly value at HH:00 applies as a step to HH:00 and HH:30. Nothing is interpolated. Metrics are computed over half-hours (1,488 in the default window), and `n_independent` (744) counts the distinct forecast values behind them.

With the observed publication times (02:30, 04:30, 07:30, 09:30, 11:30, 15:30, 18:30, 22:30 UTC), a **09:00 cutoff selects the 07:30 vintage**. The 09:30 vintage misses it by 30 minutes.

Horizon: a vintage published on day *X* reaches 21:00 UTC on *X* + 2. Every D-1 cutoff therefore covers all of *D*, but **a D-2 cutoff leaves D's last two hours without a forecast**. Those half-hours count against completeness.

## 3. Alignment

`domain/align.py` builds one row per half-hour of the delivery window. The grid comes from UK day boundaries, so clock-change days have 46 or 50 rows. Actuals and the selected forecast are **left-joined** onto the grid, so a gap stays visible as `has_actual = False` or `has_forecast = False` instead of disappearing in an inner join. Metrics use only rows where both are present. `completeness = n / n_expected`.

Signed error, in MW:

    e = forecast − actual

**Positive error = over-forecast**: less wind arrived than planned, so the desk is short and buys at intraday or balancing prices. Negative error means the desk was long.

## 4. Metrics

Over the *n* half-hours with both a forecast *f* and an actual *a*:

| Metric | Formula | Undefined (returned as `null`) when |
|---|---|---|
| MAE (MW) | mean \|e\| | n = 0 |
| RMSE (MW) | √ mean e² | n = 0 |
| Bias / MBE (MW) | mean e | n = 0 |
| nMAE, mean basis (%) | 100 · MAE / mean a | mean a = 0 |
| nMAE, capacity basis (%) | 100 · MAE / installed capacity (config, default 30 GW) | capacity unset |
| wMAPE (%) | 100 · Σ\|e\| / Σa | Σa = 0 |
| Correlation | Pearson r(f, a) | n < 2 or zero variance |
| R² | 1 − Σe² / Σ(a − ā)² | Σ(a − ā)² = 0 |
| Error quantiles (MW) | P5, P10, P25, P50, P75, P90, P95 of e (linear interpolation) | n = 0 |
| Hit rate, MW band (%) | 100 · share with \|e\| ≤ 500 MW | n = 0 |
| Hit rate, % band (%) | 100 · share with \|e\| ≤ 10 % · a | n = 0 |
| Persistence MAE (MW) | mean \|p − a\|, where p = actual at the same settlement period on the previous day | no persistence value |
| Skill vs persistence | 1 − MAE_forecast / MAE_persistence, both over the half-hours where persistence exists | persistence MAE = 0 |

Plain MAPE is deliberately not offered: it divides by actual wind, which is near zero on calm nights.

**Breakdowns** (`metrics_by`): by delivery day, hour of day (UK), weekday, lead-time bucket (default 0–6, 6–12, 12–24, 24–36, 36+ h, half-open), and wind regime (each day tagged calm / moderate / windy by tercile of its mean actual). Buckets with n < 30 are flagged `low_n`. Days under 90 % completeness are flagged `excluded_from_ranking`.

**Confidence intervals.** Half-hours within a day are strongly autocorrelated, so they are not independent observations. Intervals come from a **day-block bootstrap**: resample whole delivery days with replacement, 1,000 times, fixed seed, and take the 2.5th and 97.5th percentiles. Intervals are skipped below 5 days.

### Worked example (the unit-test fixture)

Ten half-hours, five hourly forecast values:

| a (MW) | 1000 | 1200 | 800 | 0 | 500 | 1500 | 2000 | 900 | 1100 | 700 |
|---|---|---|---|---|---|---|---|---|---|---|
| e (MW) | 100 | −200 | 50 | 0 | 300 | −100 | 250 | −50 | 0 | 150 |
| persistence error (MW) | 200 | −200 | 100 | 0 | −300 | 300 | 500 | −100 | 100 | 200 |

- Σ\|e\| = 1,200, so **MAE = 120**. Σe² = 240,000, so **RMSE = √24,000 = 154.9193**. Σe = 500, so **bias = 50**.
- Σa = 9,700 and ā = 970, so **nMAE = wMAPE = 1,200 / 9,700 = 12.3711 %**. On a 30 GW capacity basis, **0.4 %**.
- Σ(a − ā)² = 2,681,000, so **R² = 1 − 240,000 / 2,681,000 = 0.910481**.
- Sorted e = [−200, −100, −50, 0, 0, 50, 100, 150, 250, 300]. P90 sits at position 0.9 × 9 = 8.1, so **P90 = 250 + 0.1 × 50 = 255**. **P50 = 25**, **P10 = −110**.
- \|e\| ≤ 100 MW for 6 of 10 half-hours, so **hit rate = 60 %**. \|e\| ≤ 5 % · a for 2 of 10, so **20 %**.
- Persistence MAE = 2,000 / 10 = 200, so **skill = 1 − 120 / 200 = 0.4**.

`tests/unit/test_metrics.py::test_hand_computed_values` asserts each of these to 4 decimal places.

## 5. Procurement margin

The desk plans on `forecast − margin` MW of wind. A half-hour is **covered** when the actual wind is at least that, i.e. `e ≤ margin`.

| Quantity | Formula |
|---|---|
| Flat margin at confidence q | q-quantile of e over the training half-hours (default q = 0.90) |
| Coverage (%) | 100 · share of half-hours with e ≤ margin |
| Over-procured (MWh) | Σ max(0, margin − e) × 0.5: bought, then not needed |
| Shortfall (MWh) | Σ max(0, e − margin) × 0.5: still short after the margin |

Policies (`domain/margin.py`):

- **none**: margin 0, i.e. buy against the raw forecast.
- **flat**: one margin for every half-hour.
- **conditional**: a separate q-quantile of e within each tercile of the forecast level. Bin edges come from the training data. A bin with fewer than 30 training half-hours falls back to the flat margin.

Evaluations:

- **In-sample**: fit on the whole window, score on the same window. This is optimistic by construction and shown for reference only.
- **Walk-forward (no look-ahead)**: for each delivery day D, fit only on days whose actuals were **fully published before D's cutoff**. Day X's last half-hour is published at the end of X, so X is usable only if end(X) ≤ cutoff(D). At a 09:00 D-1 cutoff that means D-2 and earlier, because D-1 is still in progress. The training window expands over time. Days with fewer than 7 usable history days are skipped and counted (8 of 31 in January). A synthetic-drift test confirms that walk-forward exposes the under-coverage that in-sample hides.

Worked example (unit test): errors 1, 2, …, 100 MW. P90 = 90.1 MW, coverage = 90 %, over-procured = Σ(90.1 − e) for e ≤ 90, × 0.5 = **2,007 MWh**, shortfall = Σ(e − 90.1) for e ≥ 91, × 0.5 = **27 MWh**.

## 6. Vintage evolution and revision signal

For one delivery day (`domain/evolution.py`):

- Every vintage that covers the day, with its point count, mean and MAE against the hourly-mean actual.
- Whether each vintage was published after the cutoff, and which vintage was selected.
- Two revision measures over the vintages published in the 48 h up to the cutoff, compared on the hours all of them cover: the **range** (max − min of their means) and the **mean step** between consecutive vintages.

## 7. January 2026 results

Delivery days 2 Jan – 1 Feb 2026, 1,488 half-hours, 100 % complete. 95 % day-block bootstrap intervals in brackets.

| Cutoff (UK, D-1) | Vintage used | MAE (MW) | Bias (MW) | P90 margin (MW) | Skill vs persistence |
|---|---|---|---|---|---|
| 07:00 | 04:30 | 2,020 | +1,671 | 4,177 | 0.49 |
| **09:00** | **07:30** | **2,042** [1,642–2,485] | **+1,748** [1,234–2,291] | **4,140** [3,115–5,355] | **0.49** [0.33–0.61] |
| 11:00 | 09:30 | 2,016 | +1,730 | 4,172 | 0.49 |
| 23:00 | 22:30 | 1,830 | +1,603 | 3,637 | 0.54 |

At 09:00: RMSE 2,509 MW, nMAE / wMAPE 18.1 %, correlation 0.93, R² 0.645. Persistence MAE is 3,980 MW. Only 11.3 % of half-hours fall within ±500 MW, and 27.8 % within ±10 %.

Margin backtest at 09:00, q = 0.90. Walk-forward covers 23 days.

| Policy | In-sample coverage | Walk-forward coverage | Walk-forward mean margin | Walk-forward over-procured | Walk-forward shortfall |
|---|---|---|---|---|---|
| none | 15.3 % | 15.3 % | 0 MW | 75 GWh | 1,106 GWh |
| flat P90 | 90.0 % | **85.2 %** | 4,061 MW | 1,331 GWh | 120 GWh |
| conditional P90 | 89.9 % | **85.1 %** | 3,633 MW | **1,114 GWh (−16 %)** | 139 GWh |

Error by wind regime (09:00): calm MAE 1,707 / bias +1,065 MW; moderate 1,876 / +1,742; windy **2,576 / +2,505**.

### What the numbers say

1. **The public forecast runs high.** Bias is +1.75 GW at 09:00, and the 95 % interval excludes zero, so this is not noise. The over-forecast is worst on windy days (+2.5 GW against +1.1 GW on calm days), consistent with wind curtailment or with WINDFOR covering wind farms that FUELHH does not meter. Either way, a desk buying against the raw forecast is short in 85 % of half-hours.
2. **The forecast still earns its keep.** It halves the error of naive persistence (skill 0.49).
3. **Deciding later barely helps.** Moving from 09:00 to 11:00 switches to the 09:30 vintage and improves MAE by 26 MW (about 1 %). Only an evening decision (22:30 vintage) helps materially (−10 % MAE), and that is after the auction.
4. **The P90 margin under-covers out of sample** (85 % rather than 90 %). The in-sample figure is optimistic because error levels shift through the month.
5. **A conditional margin buys the same protection more cheaply.** It reaches the same 85 % walk-forward coverage with 16 % less over-procurement at 09:00. The gain does not hold at every cutoff: at 23:00 it trades 5 points of coverage for less over-buying. This is reported as a candidate improvement, not a settled one.

Caveats: 31 days is a small, autocorrelated sample; the intervals above are wide on purpose. Lead-time buckets are confounded with hour of day, because with a fixed cutoff a longer lead time means a later hour of D. Read the hour-of-day breakdown alongside them.

## 8. Reproducing a number without the app

```python
import pandas as pd, sqlite3
con = sqlite3.connect("data/windsight.db")
a = pd.read_sql("select start_time, generation_mw from wind_actual", con, parse_dates=["start_time"])
f = pd.read_sql("select start_time, publish_time, generation_mw from wind_forecast", con,
                parse_dates=["start_time", "publish_time"])
for df in (a, f):
    for c in df.columns:
        if c != "generation_mw":
            df[c] = df[c].dt.tz_localize("UTC")
# January is GMT, so 09:00 UK on D-1 is 09:00 UTC on D-1.
f["cutoff"] = f["start_time"].dt.floor("D") - pd.Timedelta(hours=15)
sel = (f[f.publish_time <= f.cutoff].sort_values("publish_time")
       .groupby("start_time").tail(1).set_index("start_time")["generation_mw"])
a["forecast"] = a["start_time"].dt.floor("h").map(sel)
w = a[(a.start_time >= "2026-01-02") & (a.start_time < "2026-02-02")]
e = w.forecast - w.generation_mw
print(round(e.abs().mean()), round(e.mean()), round(e.quantile(0.9)))   # 2042 1748 4140
```
