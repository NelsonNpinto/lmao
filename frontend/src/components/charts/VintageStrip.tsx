import clsx from 'clsx'
import { useMemo } from 'react'
import type { Schemas } from '../../lib/api/client'
import { useChartColors } from '../../lib/chart-colors'
import { formatMW, formatUkTime } from '../../lib/format'

type Vintage = Schemas['VintageOut']
type ActualPoint = Schemas['ActualPoint']

const W = 132
const H = 40

/**
 * Small multiples: every vintage that forecast this day, oldest first, each
 * against the same scale with the actual as a faint reference. The one used at
 * the cutoff is marked; later ones (unknowable at decision time) are dimmed.
 */
export function VintageStrip({
  vintages,
  actuals,
  preview,
  onPreview,
}: {
  vintages: Vintage[]
  actuals: ActualPoint[]
  preview: string | null
  onPreview: (publishTime: string | null) => void
}) {
  const c = useChartColors()
  const scale = useMemo(() => {
    const times = [...vintages.flatMap((v) => v.points.map((p) => Date.parse(p.start_time))), ...actuals.map((a) => Date.parse(a.start_time))]
    const vals = [...vintages.flatMap((v) => v.points.map((p) => p.forecast_mw)), ...actuals.map((a) => a.actual_mw)]
    const t0 = Math.min(...times)
    const t1 = Math.max(...times)
    const v1 = Math.max(...vals, 1)
    const x = (t: string) => ((Date.parse(t) - t0) / Math.max(1, t1 - t0)) * (W - 4) + 2
    const y = (v: number) => H - 3 - (v / v1) * (H - 6)
    return { x, y }
  }, [vintages, actuals])

  const actualPath = actuals.map((a, i) => `${i ? 'L' : 'M'}${scale.x(a.start_time).toFixed(1)},${scale.y(a.actual_mw).toFixed(1)}`).join('')

  return (
    <ol className="flex gap-2 overflow-x-auto pb-1" aria-label="Forecast vintages for this day">
      {vintages.map((v) => {
        const path = v.points.map((p, i) => `${i ? 'L' : 'M'}${scale.x(p.start_time).toFixed(1)},${scale.y(p.forecast_mw).toFixed(1)}`).join('')
        const isPreview = preview === v.publish_time
        return (
          <li key={v.publish_time} className="shrink-0">
            <button
              type="button"
              onClick={() => onPreview(isPreview ? null : v.publish_time)}
              aria-pressed={isPreview}
              className={clsx(
                'flex w-[150px] flex-col gap-1 rounded-lg border p-2 text-left text-[11px] transition-colors',
                v.selected ? 'border-forecast' : 'border-border',
                isPreview && 'bg-surface-2',
                v.after_cutoff && 'opacity-60',
              )}
              title={`Vintage published ${formatUkTime(v.publish_time)}. Mean ${formatMW(v.mean_mw)}; MAE vs actual ${formatMW(v.mae_vs_actual_mw)}.`}
            >
              <span className="flex items-center justify-between gap-1">
                <span className="num">{formatUkTime(v.publish_time).replace(' UK', '')}</span>
                {v.selected ? (
                  <span className="text-forecast font-semibold">used</span>
                ) : v.after_cutoff ? (
                  <span className="text-muted">after cutoff</span>
                ) : null}
              </span>
              <svg width={W} height={H} aria-hidden>
                <path d={actualPath} fill="none" stroke={c.actual} strokeOpacity={0.35} strokeWidth={1.5} />
                <path d={path} fill="none" stroke={v.selected ? c.forecast : c.muted} strokeWidth={2} />
              </svg>
              <span className="text-muted num">MAE {formatMW(v.mae_vs_actual_mw)}</span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}
