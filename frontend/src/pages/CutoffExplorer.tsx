import { useDeferredValue, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { TooltipBox } from '../components/charts/ChartTooltip'
import { axis, kTicks } from '../lib/chart-axis'
import { AnimatedNumber } from '../components/kpi/KpiTile'
import { Card, Skeleton, selectClass } from '../components/ui'
import { useCutoffSweep } from '../features/queries'
import { useView } from '../features/view'
import { useChartColors } from '../lib/chart-colors'
import { formatGWh, formatHours, formatMW, formatPct, formatSignedMW } from '../lib/format'
import type { Schemas } from '../lib/api/client'

type Row = Schemas['SweepRow']
const hourOf = (c: string) => Number(c.slice(0, 2))
// GB day-ahead auctions (EPEX ~09:20, N2EX ~10:50 UK) close in this window.
const GATE = [9 + 20 / 60, 11] as const

function Mini({
  rows,
  dataKey,
  title,
  format,
  selected,
  zero,
}: {
  rows: Row[]
  dataKey: keyof Row
  title: string
  format: (v: number | null | undefined) => string
  selected: number
  zero?: boolean
}) {
  const c = useChartColors()
  const data = rows.map((r) => ({ h: hourOf(r.cutoff), v: r[dataKey] as number | null, vintage: r.vintages_used[0] }))
  return (
    <Card title={title}>
      <div className="h-44" role="img" aria-label={`${title} by cutoff hour`}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -8 }} accessibilityLayer={false}>
            <CartesianGrid stroke={c.grid} vertical={false} />
            <ReferenceArea x1={GATE[0]} x2={GATE[1]} fill={c.muted} fillOpacity={0.12} />
            <XAxis type="number" dataKey="h" domain={[0, 23]} ticks={[0, 3, 6, 9, 12, 15, 18, 21]} tickFormatter={(h: number) => `${String(h).padStart(2, '0')}:00`} {...axis(c.muted, c.border)} />
            <YAxis tickFormatter={(v: number) => (dataKey === 'walk_forward_coverage_pct' ? `${v}%` : kTicks(v))} domain={zero ? [0, 'auto'] : ['auto', 'auto']} {...axis(c.muted, c.border)} width={46} />
            <Tooltip
              content={({ payload }) => {
                const p = payload?.[0]?.payload as (typeof data)[number] | undefined
                return p ? (
                  <TooltipBox title={`${String(p.h).padStart(2, '0')}:00 UK cutoff`} rows={[[title, format(p.v)], ['Vintage', `${p.vintage ?? '—'} UTC`]]} />
                ) : null
              }}
            />
            <ReferenceLine x={selected} stroke={c.text} strokeDasharray="3 3" />
            <Line type="stepAfter" dataKey="v" stroke={c.forecast} strokeWidth={2} dot={{ r: 2.5, fill: c.forecast }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}

export default function CutoffExplorer() {
  const { scope, params, update } = useView()
  const [daysBefore, setDaysBefore] = useState<1 | 2>(1)
  const sweep = useCutoffSweep(scope, daysBefore)
  const [hour, setHour] = useState(() => hourOf(params.cutoff))
  const shown = useDeferredValue(hour) // keeps the slider at 60 fps while charts redraw
  const rows = useMemo(() => sweep.data?.data ?? [], [sweep.data])
  const sel = rows.find((r) => hourOf(r.cutoff) === shown)
  const base = rows.find((r) => r.cutoff === '09:00')

  const commit = (h: number) => update({ cutoff: `${String(h).padStart(2, '0')}:00` }, { replace: true })

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-lg font-semibold tracking-tight">When should we decide?</h1>
        <p className="text-muted text-sm">
          Accuracy and the margin it implies, for every hourly decision time. The shaded band is the GB day-ahead
          auction gate-closure window (about 09:20–11:00 UK): decisions after it are not tradeable day-ahead.
        </p>
      </header>

      <Card>
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex min-w-[260px] flex-1 items-center gap-3 text-sm">
            <span className="text-muted whitespace-nowrap">Cutoff</span>
            <input
              type="range"
              min={0}
              max={23}
              step={1}
              value={hour}
              onChange={(e) => setHour(Number(e.target.value))}
              onPointerUp={() => commit(hour)}
              onKeyUp={() => commit(hour)}
              className="accent-[var(--forecast)] flex-1"
              aria-valuetext={`${String(hour).padStart(2, '0')}:00 UK`}
            />
            <span className="num w-14 text-right font-semibold">{String(hour).padStart(2, '0')}:00</span>
          </label>
          <label className="flex items-center gap-2 text-xs">
            <span className="text-muted">Decision day</span>
            <select className={selectClass} value={daysBefore} onChange={(e) => setDaysBefore(Number(e.target.value) as 1 | 2)}>
              <option value={1}>D-1</option>
              <option value={2}>D-2</option>
            </select>
          </label>
        </div>

        {sweep.isPending ? (
          <Skeleton className="mt-4 h-16" />
        ) : sel ? (
          <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5" aria-live="polite">
            {[
              ['Vintage used', sel.vintages_used.map((v) => `${v} UTC`).join(', ') || '—', null],
              ['MAE', <AnimatedNumber key="m" value={sel.mae_mw} format={formatMW} />, base && sel.mae_mw != null && base.mae_mw != null ? `${formatSignedMW(sel.mae_mw - base.mae_mw)} vs 09:00` : null],
              ['P90 margin', <AnimatedNumber key="p" value={sel.p90_error_mw} format={formatMW} />, base && sel.p90_error_mw != null && base.p90_error_mw != null ? `${formatSignedMW(sel.p90_error_mw - base.p90_error_mw)} vs 09:00` : null],
              ['Walk-forward coverage', formatPct(sel.walk_forward_coverage_pct), 'target 90 %'],
              ['Over-procured (flat)', formatGWh(sel.walk_forward_over_procured_mwh, 0), `forecast age ${formatHours(sel.mean_vintage_age_h)}`],
            ].map(([label, value, sub], i) => (
              <div key={i} className="bg-surface-2 rounded-lg p-3">
                <div className="text-muted text-xs">{label}</div>
                <div className="num text-base font-semibold">{value}</div>
                {sub && <div className="text-muted num text-[11px]">{sub}</div>}
              </div>
            ))}
          </div>
        ) : null}
      </Card>

      {sweep.isPending ? (
        <div className="grid gap-4 md:grid-cols-2">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-56" />)}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <Mini rows={rows} dataKey="mae_mw" title="MAE (MW)" format={formatMW} selected={shown} zero />
          <Mini rows={rows} dataKey="bias_mw" title="Bias (MW)" format={formatSignedMW} selected={shown} />
          <Mini rows={rows} dataKey="p90_error_mw" title="P90 margin (MW)" format={formatMW} selected={shown} zero />
          <Mini rows={rows} dataKey="walk_forward_coverage_pct" title="Walk-forward coverage of the P90 margin (%)" format={(v) => formatPct(v)} selected={shown} />
        </div>
      )}

      <Card title="All cutoffs" subtitle="Each row selects the latest vintage published by that time on the decision day.">
        <div className="overflow-x-auto">
          <table className="num w-full text-right text-xs">
            <thead className="text-muted">
              <tr>
                <th scope="col" className="py-1 text-left font-medium">Cutoff UK</th>
                <th scope="col" className="font-medium">Vintage (UTC)</th>
                <th scope="col" className="font-medium">MAE</th>
                <th scope="col" className="font-medium">Bias</th>
                <th scope="col" className="font-medium">P90 margin</th>
                <th scope="col" className="font-medium">Skill</th>
                <th scope="col" className="font-medium">WF coverage</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.cutoff}
                  className={hourOf(r.cutoff) === shown ? 'bg-surface-2 font-semibold' : 'border-border border-t'}
                >
                  <th scope="row" className="py-0.5 text-left font-normal">
                    <button type="button" className="hover:underline" onClick={() => { setHour(hourOf(r.cutoff)); commit(hourOf(r.cutoff)) }}>
                      {r.cutoff}
                    </button>
                  </th>
                  <td>{r.vintages_used.join(', ') || '—'}</td>
                  <td>{formatMW(r.mae_mw)}</td>
                  <td>{formatSignedMW(r.bias_mw)}</td>
                  <td>{formatMW(r.p90_error_mw)}</td>
                  <td>{formatPct(r.skill_vs_persistence == null ? null : r.skill_vs_persistence * 100, 0)}</td>
                  <td>{formatPct(r.walk_forward_coverage_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
