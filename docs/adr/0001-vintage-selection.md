# ADR 0001: As-of vintage selection at query time

- Status: accepted
- Date: 2026-10-28

## Context

NESO publishes WINDFOR about eight times a day. Each publication (vintage) forecasts roughly the next 2–3 days at hourly resolution, so one delivery hour has about 20 vintages. The procurement desk buys day-ahead at a cutoff on D-1, so the forecast that matters is the one the desk could see at that cutoff, not the most recent one ever published. Picking a later vintage would make the forecast look more accurate than it was when the decision was made (look-ahead bias).

## Decision

1. **Store every vintage.** `wind_forecast` is keyed on `(start_time, publish_time)` and is never collapsed by `start_time`.
2. **Select at query time.** For each delivery hour `t` on day D, the selected forecast is the row with the greatest `publish_time` such that `publish_time <= cutoff(D)`, where `cutoff(D)` is the configured UK local time on `D - cutoff_days_before`, converted to UTC for that specific day.
3. **Vectorised.** Selection uses `pandas.merge_asof(direction="backward")` per delivery day's cutoff, not a Python loop.
4. **Never a later vintage.** If no vintage satisfies the condition, the period's forecast is null and coverage drops. It does not fall back to a later vintage. A hypothesis property test enforces this.
5. **Resolution.** WINDFOR is hourly, so the selected hourly value is applied as a step to both half-hours before aligning with half-hourly FUELHH actuals (see DECISIONS.md D3).
6. **Diagnostics.** Each selected row carries `lead_time_h = start_time − publish_time` and `vintage_age_h = cutoff − publish_time`. A vintage more than 24 h old is still used but flagged as stale.

## Consequences

- Changing the cutoff in the UI changes which vintage is used, and the UI displays the selected `publish_time` as proof.
- Because there are about 20k rows per month, query-time selection is cheap. Results are still cached by `(window, cutoff, data_version)`.
- The cutoff sweep is effectively discrete. With the observed schedule, any cutoff from 07:30 to 09:29 UTC selects the same 07:30 vintage.
