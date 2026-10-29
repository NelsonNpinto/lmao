import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'
import { Navigate, useLocation, useNavigate, useParams } from 'react-router'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { TooltipBox } from '../components/charts/ChartTooltip'
import { axis, kTicks } from '../lib/chart-axis'
import { Badge, Button, Card, Skeleton } from '../components/ui'
import { useDayVintages, useSeries } from '../features/queries'
import { useView } from '../features/view'
import { useChartColors } from '../lib/chart-colors'
import {
  addDays,
  formatDeliveryDate,
  formatHours,
  formatMW,
  formatSignedMW,
  formatUkClock,
  formatUkTime,
  ukDateOf,
} from '../lib/format'

function Timeline({
  pubs,
  cutoff,
  selected,
}: {
  pubs: { t: string; after: boolean }[]
  cutoff: string
  selected: string | null
}) {
  const c = useChartColors()
  if (!pubs.length) return null
  const times = [...pubs.map((p) => Date.parse(p.t)), Date.parse(cutoff)]
  const t0 = Math.min(...times)
  const t1 = Math.max(...times)
  const x = (t: string) => 2 + ((Date.parse(t) - t0) / Math.max(1, t1 - t0)) * 96
  return (
    <div>
      <svg viewBox="0 0 100 14" className="h-12 w-full" preserveAspectRatio="none" role="img" aria-label={`${pubs.length} publications; cutoff ${formatUkTime(cutoff)}`}>
        <line x1="1" x2="99" y1="7" y2="7" stroke={c.border} strokeWidth="0.4" />
        <line x1={x(cutoff)} x2={x(cutoff)} y1="1" y2="13" stroke={c.text} strokeWidth="0.4" strokeDasharray="1 0.6" />
        {pubs.map((p) => (
          <circle
            key={p.t}
            cx={x(p.t)}
            cy="7"
            r={p.t === selected ? 1.6 : 1}
            fill={p.t === selected ? c.forecast : p.after ? 'none' : c.muted}
            stroke={p.after ? c.muted : 'none'}
            strokeWidth="0.3"
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      <div className="text-muted num flex justify-between text-[11px]">
        <span>{formatUkTime(pubs[0]!.t)}</span>
        <span className="text-text">cutoff {formatUkTime(cutoff)}</span>
        <span>{formatUkTime(pubs.at(-1)!.t)}</span>
      </div>
    </div>
  )
}

export default function DayExplorer() {
  const { date } = useParams()
  const { scope, first, last, day: viewDay, params, update } = useView()
  const navigate = useNavigate()
  const { search } = useLocation()
  const vintages = useDayVintages(scope, date)
  const series = useSeries(scope)
  const c = useChartColors()
  const v = vintages.data?.data

  const go = (d: string) => {
    const sp = new URLSearchParams(search)
    sp.set('day', d)
    navigate({ pathname: `/days/${d}`, search: `?${sp}` })
  }

  // On arrival the route's date wins and is written to ?day (so the command bar
  // shows it); after that the command bar's day picker drives the route.
  const arrived = useRef(false)
  useEffect(() => {
    if (!date) return
    if (!arrived.current) {
      arrived.current = true
      if (params.day !== date) update({ day: date }, { replace: true })
      return
    }
    if (params.day && params.day !== date) {
      navigate({ pathname: `/days/${params.day}`, search }, { replace: true })
    }
  }, [params.day, date, navigate, search, update])
  const prev = date && first && date > first ? addDays(date, -1) : null
  const next = date && last && date < last ? addDays(date, 1) : null

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && ['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return
      if ((e.key === '[' || e.key === 'j') && prev) go(prev)
      if ((e.key === ']' || e.key === 'k') && next) go(next)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const { rows, keys } = useMemo(() => {
    if (!v) return { rows: [], keys: [] as { key: string; t: string; after: boolean; selected: boolean; age: number }[] }
    const byHour = new Map<string, Record<string, number | string>>()
    const n = v.vintages.length
    const keys = v.vintages.map((vt, i) => ({
      key: `v${i}`,
      t: vt.publish_time,
      after: vt.after_cutoff,
      selected: vt.selected,
      age: n > 1 ? i / (n - 1) : 1,
    }))
    v.vintages.forEach((vt, i) =>
      vt.points.forEach((p) => {
        const r = byHour.get(p.start_time) ?? { t: p.start_time }
        r[`v${i}`] = p.forecast_mw
        byHour.set(p.start_time, r)
      }),
    )
    const actualH = new Map<string, number[]>()
    v.actuals.forEach((a) => {
      const h = a.start_time.slice(0, 14) + '00:00Z'
      actualH.set(h, [...(actualH.get(h) ?? []), a.actual_mw])
    })
    actualH.forEach((vals, h) => {
      const r = byHour.get(h) ?? { t: h }
      r.actual = vals.reduce((a, b) => a + b, 0) / vals.length
      byHour.set(h, r)
    })
    return { rows: [...byHour.values()].sort((a, b) => String(a.t).localeCompare(String(b.t))), keys }
  }, [v])

  const dayPoints = (series.data?.data.points ?? []).filter((p) => date && ukDateOf(p.start_time) === date)

  if (!date) return viewDay ? <Navigate to={{ pathname: `/days/${viewDay}`, search }} replace /> : <Skeleton className="h-96" />

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{formatDeliveryDate(date)}</h1>
          <p className="text-muted text-sm">
            Every forecast published for this day, converging on what happened. Keys: <kbd className="num">[</kbd>{' '}
            previous, <kbd className="num">]</kbd> next.
          </p>
        </div>
        <div className="flex gap-2">
          <Button disabled={!prev} onClick={() => prev && go(prev)} aria-label="Previous day (shortcut [)">
            <ChevronLeft className="size-4" aria-hidden /> Prev
          </Button>
          <Button disabled={!next} onClick={() => next && go(next)} aria-label="Next day (shortcut ])">
            Next <ChevronRight className="size-4" aria-hidden />
          </Button>
        </div>
      </header>

      <Card
        title="Forecast fan"
        subtitle="Hourly. Orange: the vintage used at the cutoff. Gray: earlier vintages, fainter when older. Dashed: published after the cutoff (not knowable when buying)."
        actions={
          v?.revision_range_mw != null ? <Badge>revised by up to {formatMW(v.revision_range_mw)} before cutoff</Badge> : null
        }
      >
        {vintages.isPending ? (
          <Skeleton className="h-80" />
        ) : !v?.vintages.length ? (
          <p className="text-sm">
            No vintages for this day.{' '}
            {v?.nearest_date_with_data && (
              <button type="button" className="underline" onClick={() => go(v.nearest_date_with_data!)}>
                Go to {v.nearest_date_with_data}
              </button>
            )}
          </p>
        ) : (
          <>
            <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Legend">
              <li className="flex items-center gap-1.5"><span className="bg-actual inline-block h-1 w-4 rounded" /> Actual (hourly mean)</li>
              <li className="flex items-center gap-1.5"><span className="bg-forecast inline-block h-0.5 w-4 rounded" /> Vintage used</li>
              <li className="flex items-center gap-1.5"><span className="bg-muted inline-block h-0.5 w-4 rounded" /> Earlier vintages</li>
              <li className="flex items-center gap-1.5"><span className="border-muted inline-block w-4 border-t-2 border-dashed" /> After cutoff</li>
            </ul>
            <div className="h-80" role="img" aria-label={`${keys.length} forecast vintages for ${date} and the actual`}>
              <ResponsiveContainer>
                <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -8 }} accessibilityLayer={false}>
                  <CartesianGrid stroke={c.grid} vertical={false} />
                  <XAxis dataKey="t" tickFormatter={(t: string) => formatUkClock(t)} interval={2} {...axis(c.muted, c.border)} />
                  <YAxis tickFormatter={kTicks} domain={[0, 'auto']} {...axis(c.muted, c.border)} width={44} />
                  <Tooltip
                    content={({ payload, label }) => {
                      if (!payload?.length) return null
                      const row = payload[0]!.payload as Record<string, number>
                      const used = keys.find((k) => k.selected)
                      return (
                        <TooltipBox
                          title={`${formatUkClock(String(label))} UK`}
                          rows={[
                            ['Actual', formatMW(row.actual)],
                            ['Used vintage', formatMW(used ? row[used.key] : null)],
                            ['Vintages here', keys.filter((k) => row[k.key] != null).length],
                          ]}
                        />
                      )
                    }}
                  />
                  {keys
                    .filter((k) => !k.selected)
                    .map((k) => (
                      <Line
                        key={k.key}
                        dataKey={k.key}
                        stroke={c.muted}
                        strokeOpacity={k.after ? 0.6 : 0.2 + 0.6 * k.age}
                        strokeDasharray={k.after ? '4 3' : undefined}
                        strokeWidth={1.25}
                        dot={false}
                        connectNulls={false}
                        isAnimationActive={false}
                      />
                    ))}
                  {keys
                    .filter((k) => k.selected)
                    .map((k) => (
                      <Line key={k.key} dataKey={k.key} stroke={c.forecast} strokeWidth={2.5} dot={false} isAnimationActive={false} />
                    ))}
                  <Line dataKey="actual" stroke={c.actual} strokeWidth={3} dot={false} connectNulls={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-7" title="Publication timeline" subtitle="Each dot is a vintage covering this day; the line is the decision cutoff.">
          {v && (
            <Timeline pubs={v.vintages.map((x) => ({ t: x.publish_time, after: x.after_cutoff }))} cutoff={v.cutoff} selected={v.selected_publish_time ?? null} />
          )}
          {v && (
            <table className="num mt-3 w-full text-right text-xs">
              <thead className="text-muted">
                <tr>
                  <th scope="col" className="text-left font-medium">Published (UK)</th>
                  <th scope="col" className="font-medium">Hours</th>
                  <th scope="col" className="font-medium">Mean</th>
                  <th scope="col" className="font-medium">MAE vs actual</th>
                </tr>
              </thead>
              <tbody>
                {v.vintages.map((x) => (
                  <tr key={x.publish_time} className={x.selected ? 'font-semibold' : x.after_cutoff ? 'text-muted' : ''}>
                    <th scope="row" className="text-left font-normal">
                      {formatUkTime(x.publish_time)} {x.selected && <Badge tone="ok">used</Badge>}
                    </th>
                    <td>{x.n_points}{x.full_day ? '' : ' (partial)'}</td>
                    <td>{formatMW(x.mean_mw)}</td>
                    <td>{formatMW(x.mae_vs_actual_mw)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card className="lg:col-span-5" title="Half-hours" subtitle="As-of forecast at the cutoff vs actual.">
          {series.isPending ? (
            <Skeleton className="h-80" />
          ) : (
            <div className="max-h-[26rem] overflow-auto">
              <table className="num w-full text-right text-xs">
                <thead className="bg-surface text-muted sticky top-0">
                  <tr>
                    <th scope="col" className="py-1 text-left font-medium">UK</th>
                    <th scope="col" className="font-medium">Forecast</th>
                    <th scope="col" className="font-medium">Actual</th>
                    <th scope="col" className="font-medium">Error</th>
                    <th scope="col" className="font-medium">Lead</th>
                  </tr>
                </thead>
                <tbody>
                  {dayPoints.map((p) => (
                    <tr key={p.start_time} className="border-border border-t">
                      <th scope="row" className="py-0.5 text-left font-normal">{formatUkClock(p.start_time)}</th>
                      <td>{formatMW(p.forecast_mw).replace(' MW', '')}</td>
                      <td>{formatMW(p.actual_mw).replace(' MW', '')}</td>
                      <td>{formatSignedMW(p.error_mw).replace(' MW', '')}</td>
                      <td>{formatHours(p.lead_time_h)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
