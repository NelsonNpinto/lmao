import { Check, ClipboardCopy, Download } from 'lucide-react'
import { useState } from 'react'
import type { Schemas } from '../../lib/api/client'
import { formatGWh, formatNumber, formatUkClock } from '../../lib/format'
import { toDelimited } from '../../lib/plan'
import { Button } from '../ui'

type Plan = Schemas['PlanOut']

const BASIS: Record<Plan['margin_basis'], string> = {
  walk_forward: 'margin set only from days known before this cutoff',
  window: 'too little earlier history: margin from the whole window (optimistic)',
  none: 'no margin applied',
}

export function PlanTable({ plan }: { plan: Plan }) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    await navigator.clipboard.writeText(toDelimited(plan, '\t'))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  const download = () => {
    const blob = new Blob([toDelimited(plan, ',')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `windsight_plan_${plan.delivery_date}_${plan.policy}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="flex min-h-0 flex-col gap-2">
      <p className="text-muted text-[11px]">
        {BASIS[plan.margin_basis]}
        {plan.margin_basis === 'walk_forward' && ` (${plan.history_days} days)`}.
      </p>
      <div className="max-h-[22rem] overflow-auto rounded-md border border-[var(--border)]">
        <table className="num w-full text-right text-xs">
          <caption className="sr-only">Per-period wind to plan on for {plan.delivery_date}</caption>
          <thead className="bg-surface-2 text-muted sticky top-0">
            <tr>
              <th scope="col" className="px-2 py-1.5 text-left font-medium">UK</th>
              <th scope="col" className="px-2 font-medium">Forecast</th>
              <th scope="col" className="px-2 font-medium">Margin</th>
              <th scope="col" className="px-2 font-medium">Plan on</th>
            </tr>
          </thead>
          <tbody>
            {plan.rows.map((r) => (
              <tr key={r.start_time} className="border-border border-t">
                <th scope="row" className="px-2 py-0.5 text-left font-normal">
                  {formatUkClock(r.start_time)}
                </th>
                <td className="px-2">{formatNumber(r.forecast_mw)}</td>
                <td className="text-muted px-2">{formatNumber(r.margin_mw)}</td>
                <td className="px-2 font-medium">{formatNumber(r.wind_to_plan_mw)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot className="bg-surface-2 sticky bottom-0">
            <tr>
              <th scope="row" className="px-2 py-1.5 text-left font-medium">Day</th>
              <td className="px-2">{formatGWh(plan.forecast_total_mwh)}</td>
              <td className="px-2" />
              <td className="px-2 font-semibold">{formatGWh(plan.wind_to_plan_total_mwh)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="text-muted text-[11px]">All values MW averaged over the half-hour; day totals in GWh.</p>
      <div className="flex gap-2">
        <Button onClick={copy} aria-label="Copy plan as tab-separated values">
          {copied ? <Check className="size-3.5" aria-hidden /> : <ClipboardCopy className="size-3.5" aria-hidden />}
          {copied ? 'Copied' : 'Copy'}
        </Button>
        <Button onClick={download}>
          <Download className="size-3.5" aria-hidden /> CSV
        </Button>
      </div>
    </div>
  )
}
