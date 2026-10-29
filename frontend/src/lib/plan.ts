import type { Schemas } from './api/client'
import { formatUkClock } from './format'

type Plan = Schemas['PlanOut']

const HEADERS = ['Period', 'UK time', 'Forecast MW', 'Margin MW', 'Wind to plan MW', 'Wind to plan MWh']

/** Raw values (unrounded) for the desk's own spreadsheet. */
export function planToRows(plan: Plan): (string | number)[][] {
  return plan.rows.map((r) => [
    r.period,
    formatUkClock(r.start_time),
    r.forecast_mw ?? '',
    r.margin_mw ?? '',
    r.wind_to_plan_mw ?? '',
    r.wind_to_plan_mwh ?? '',
  ])
}

export function toDelimited(plan: Plan, sep: ',' | '\t'): string {
  return [HEADERS, ...planToRows(plan)].map((r) => r.join(sep)).join('\n') + '\n'
}
