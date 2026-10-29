import { useReducedMotion } from 'motion/react'
import { type KeyboardEvent, useMemo, useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts'
import { useChartColors } from '../../lib/chart-colors'
import { formatHours, formatMW, formatSignedMW, formatUkClock } from '../../lib/format'

export interface DayPoint {
  start_time: string
  actual_mw: number | null
  forecast_mw: number | null
  error_mw: number | null
  band_low_mw: number | null
  band_high_mw: number | null
  lead_time_h: number | null
}

interface Row extends DayPoint {
  label: string
  band: [number, number] | null
  preview: number | null
}

const kTicks = (v: number) => (v === 0 ? '0' : `${Math.round(v / 1000)}k`)

/**
 * One delivery day: as-of forecast (hourly, drawn as steps), actual, the
 * historical P10-P90 band, and optionally another vintage for comparison.
 * Gaps stay gaps (connectNulls=false, Break #21). Hover or arrow keys move a
 * readout; a table view is one click away.
 */
export function DayChart({
  points,
  preview,
  previewLabel,
}: {
  points: DayPoint[]
  preview?: Map<string, number>
  previewLabel?: string
}) {
  const reduce = useReducedMotion()
  const c = useChartColors()
  const rows: Row[] = useMemo(
    () =>
      points.map((p) => {
        const hour = p.start_time.slice(0, 14) + '00:00Z'
        return {
          ...p,
          label: formatUkClock(p.start_time),
          band: p.band_low_mw != null && p.band_high_mw != null ? [p.band_low_mw, p.band_high_mw] : null,
          preview: preview?.get(hour) ?? null,
        }
      }),
    [points, preview],
  )
  const [active, setActive] = useState<number | null>(null)
  const [table, setTable] = useState(false)
  const idx = active ?? rows.length - 1
  const a = rows[idx]
  const gaps = rows.filter((r) => r.actual_mw == null || r.forecast_mw == null).length

  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight') setActive(Math.min(rows.length - 1, (active ?? -1) + 1))
    else if (e.key === 'ArrowLeft') setActive(Math.max(0, (active ?? rows.length) - 1))
    else if (e.key === 'Home') setActive(0)
    else if (e.key === 'End') setActive(rows.length - 1)
    else return
    e.preventDefault()
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-xs">
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1" aria-label="Legend">
          <li className="flex items-center gap-1.5">
            <span className="bg-forecast inline-block h-0.5 w-4 rounded" aria-hidden /> Forecast (as of cutoff, hourly)
          </li>
          <li className="flex items-center gap-1.5">
            <span className="bg-actual inline-block h-0.5 w-4 rounded" aria-hidden /> Actual
          </li>
          <li className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-4 rounded-sm" style={{ background: 'var(--band)' }} aria-hidden />
            P10–P90 historical error band
          </li>
          {previewLabel && (
            <li className="flex items-center gap-1.5">
              <span className="border-muted inline-block w-4 border-t-2 border-dashed" aria-hidden /> {previewLabel}
            </li>
          )}
        </ul>
        <button
          type="button"
          className="text-muted hover:text-text underline-offset-2 hover:underline"
          onClick={() => setTable((t) => !t)}
          aria-pressed={table}
        >
          {table ? 'Show chart' : 'Show as table'}
        </button>
      </div>

      {a && (
        <div className="bg-surface-2 num mb-2 grid grid-cols-2 gap-x-4 gap-y-0.5 rounded-md px-3 py-1.5 text-xs sm:grid-cols-5" aria-live="polite">
          <span>
            <span className="text-muted">Period </span>
            {a.label} UK
          </span>
          <span>
            <span className="text-muted">Forecast </span>
            {formatMW(a.forecast_mw)}
          </span>
          <span>
            <span className="text-muted">Actual </span>
            {formatMW(a.actual_mw)}
          </span>
          <span>
            <span className="text-muted">Error </span>
            {formatSignedMW(a.error_mw)}
          </span>
          <span>
            <span className="text-muted">Lead </span>
            {formatHours(a.lead_time_h)}
          </span>
        </div>
      )}

      {table ? (
        <div className="max-h-80 overflow-auto">
          <table className="num w-full text-right text-xs">
            <thead className="bg-surface text-muted sticky top-0">
              <tr>
                <th className="py-1 text-left font-medium">UK time</th>
                <th className="font-medium">Forecast MW</th>
                <th className="font-medium">Actual MW</th>
                <th className="font-medium">Error MW</th>
                <th className="font-medium">Band MW</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.start_time} className="border-border border-t">
                  <td className="py-0.5 text-left">{r.label}</td>
                  <td>{formatMW(r.forecast_mw).replace(' MW', '')}</td>
                  <td>{formatMW(r.actual_mw).replace(' MW', '')}</td>
                  <td>{formatSignedMW(r.error_mw).replace(' MW', '')}</td>
                  <td>
                    {r.band ? `${Math.round(r.band[0]).toLocaleString('en-GB')}–${Math.round(r.band[1]).toLocaleString('en-GB')}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div
          tabIndex={0}
          role="img"
          aria-label={`Forecast and actual wind for the day, ${rows.length} half-hours${gaps ? `, ${gaps} with missing data` : ''}. Use arrow keys to step through periods.`}
          onKeyDown={onKey}
          className="h-72 w-full sm:h-80"
        >
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={rows}
              accessibilityLayer={false} // the wrapper is the single focus stop with its own keys
              margin={{ top: 8, right: 8, bottom: 0, left: -8 }}
              onMouseMove={(s) => {
                const i = Number(s?.activeTooltipIndex)
                if (Number.isFinite(i)) setActive(i)
              }}
              onMouseLeave={() => setActive(null)}
            >
              <CartesianGrid stroke={c.grid} vertical={false} />
              <XAxis
                dataKey="label"
                interval={5}
                tick={{ fill: c.muted, fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: c.border }}
              />
              <YAxis
                tickFormatter={kTicks}
                tick={{ fill: c.muted, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={44}
                domain={[0, 'auto']}
              />
              <Area
                dataKey="band"
                stroke="none"
                fill={c.band}
                connectNulls={false}
                isAnimationActive={!reduce}
              />
              {preview && (
                <Line
                  dataKey="preview"
                  type="stepAfter"
                  stroke={c.muted}
                  strokeWidth={2}
                  strokeDasharray="4 3"
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={!reduce}
                />
              )}
              <Line
                dataKey="forecast_mw"
                type="stepAfter"
                stroke={c.forecast}
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={!reduce}
              />
              <Line
                dataKey="actual_mw"
                type="linear"
                stroke={c.actual}
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={!reduce}
              />
              {a && <ReferenceLine x={a.label} stroke={c.muted} strokeDasharray="2 2" />}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
      {gaps > 0 && (
        <p className="text-warn mt-2 text-xs" role="note">
          {gaps} half-hour{gaps === 1 ? '' : 's'} missing an actual or a forecast; shown as gaps, not interpolated.
        </p>
      )}
    </div>
  )
}
