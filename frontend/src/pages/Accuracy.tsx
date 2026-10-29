import { useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { TooltipBox } from '../components/charts/ChartTooltip'
import { axis, kTicks } from '../lib/chart-axis'
import { Badge, Button, Card, Skeleton } from '../components/ui'
import {
  useBy,
  useCalibration,
  useErrorDistribution,
  useSeries,
} from '../features/queries'
import { useView } from '../features/view'
import { useChartColors } from '../lib/chart-colors'
import {
  formatMW,
  formatNumber,
  formatPct,
  formatSignedMW,
  formatUkClock,
  ukDateOf,
} from '../lib/format'

const DEFS: [string, string, string][] = [
  ['MAE', 'mean |forecast − actual|', 'typical size of a miss'],
  ['RMSE', '√ mean (forecast − actual)²', 'penalises large misses'],
  ['Bias', 'mean (forecast − actual)', '> 0 means over-forecast: the desk is short'],
  ['nMAE / wMAPE', 'Σ|e| / Σ actual', 'error relative to the wind that blew'],
  ['R²', '1 − Σe² / Σ(a − ā)²', 'share of variation the forecast explains'],
  ['Skill', '1 − MAE / MAE(persistence)', '> 0 means better than "same as yesterday"'],
]

function MetricCards() {
  const { summary } = useView()
  const m = summary.data?.data
  const iv = m?.intervals ?? undefined
  const ci = (k: string, f: (v: number) => string) => {
    const r = iv?.[k]
    return r && r[0] != null && r[1] != null ? `95 % CI ${f(r[0])} – ${f(r[1])}` : null
  }
  const mw = (v: number) => formatNumber(v)
  const cards: [string, string, string | null, string][] = m
    ? [
        ['MAE', formatMW(m.mae_mw), ci('mae_mw', mw), DEFS[0]![1]],
        ['RMSE', formatMW(m.rmse_mw), ci('rmse_mw', mw), DEFS[1]![1]],
        ['Bias', formatSignedMW(m.bias_mw), ci('bias_mw', mw), DEFS[2]![2]],
        ['wMAPE', formatPct(m.wmape_pct), `nMAE vs capacity ${formatPct(m.nmae_capacity_pct)}`, DEFS[3]![1]],
        ['R²', formatNumber(m.r2, 3), `correlation ${formatNumber(m.correlation, 3)}`, DEFS[4]![1]],
        ['P90 error', formatSignedMW(m.error_quantiles_mw.p90), ci('p90_mw', mw), 'error exceeded in only 10 % of half-hours'],
        ['Within ±500 MW', formatPct(m.hit_rate_mw_pct), `within ±10 %: ${formatPct(m.hit_rate_pct_pct)}`, 'share of half-hours'],
        ['Half-hours', formatNumber(m.n), `${m.n_days} days, ${formatNumber(m.n_independent)} independent forecast values`, 'hourly forecast stepped to half-hours'],
      ]
    : []
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {summary.isPending
        ? Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-20" />)
        : cards.map(([label, value, sub, def]) => (
            <div key={label} className="border-border bg-surface rounded-xl border p-3" title={def}>
              <div className="text-muted text-xs">{label}</div>
              <div className="num text-lg font-semibold">{value}</div>
              {sub && <div className="text-muted num text-[11px]">{sub}</div>}
            </div>
          ))}
    </div>
  )
}

function MethodDrawer() {
  return (
    <details className="border-border bg-surface rounded-xl border p-3 text-sm">
      <summary className="cursor-pointer font-medium">How these are calculated</summary>
      <div className="text-muted mt-2 grid gap-2 md:grid-cols-2">
        <p>
          For each delivery half-hour the forecast is the latest WINDFOR vintage published at or before the
          cutoff on D-1 (never a later one). WINDFOR is hourly, so each value covers both half-hours. Error
          e = forecast − actual, in MW.
        </p>
        <dl className="num grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          {DEFS.map(([k, f, why]) => (
            <div key={k} className="contents">
              <dt className="text-text font-medium">{k}</dt>
              <dd>
                {f} <span className="font-sans">· {why}</span>
              </dd>
            </div>
          ))}
        </dl>
        <p className="md:col-span-2">
          95 % intervals resample whole days (1,000 times), because half-hours within a day move together. With
          about a month of data they are wide on purpose. Full derivations and a worked example are in
          docs/METHODOLOGY.md.
        </p>
      </div>
    </details>
  )
}

function ScatterCard() {
  const { scope } = useView()
  const series = useSeries(scope)
  const c = useChartColors()
  const pts = useMemo(
    () =>
      (series.data?.data.points ?? [])
        .filter((p) => p.forecast_mw != null && p.actual_mw != null)
        .map((p) => ({ x: p.forecast_mw!, y: p.actual_mw!, t: p.start_time })),
    [series.data],
  )
  const max = Math.max(1000, ...pts.flatMap((p) => [p.x, p.y]))
  return (
    <Card title="Forecast vs actual" subtitle="Each dot is a half-hour. Below the diagonal = less wind than forecast.">
      {series.isPending ? (
        <Skeleton className="h-72" />
      ) : (
        <div className="h-72" role="img" aria-label={`Scatter of ${pts.length} half-hours, forecast against actual`}>
          <ResponsiveContainer>
            <ScatterChart margin={{ top: 8, right: 12, bottom: 16, left: -4 }} accessibilityLayer={false}>
              <CartesianGrid stroke={c.grid} />
              <XAxis type="number" dataKey="x" domain={[0, max]} tickFormatter={kTicks} {...axis(c.muted, c.border)}
                label={{ value: 'Forecast MW', position: 'insideBottom', offset: -10, fill: c.muted, fontSize: 11 }} />
              <YAxis type="number" dataKey="y" domain={[0, max]} tickFormatter={kTicks} {...axis(c.muted, c.border)} width={44}
                label={{ value: 'Actual MW', angle: -90, position: 'insideLeft', offset: 14, fill: c.muted, fontSize: 11 }} />
              <ReferenceLine segment={[{ x: 0, y: 0 }, { x: max, y: max }]} stroke={c.muted} strokeDasharray="4 3" />
              <Tooltip
                cursor={false}
                content={({ payload }) => {
                  const p = payload?.[0]?.payload as { x: number; y: number; t: string } | undefined
                  return p ? (
                    <TooltipBox
                      title={`${ukDateOf(p.t)} ${formatUkClock(p.t)} UK`}
                      rows={[['Forecast', formatMW(p.x)], ['Actual', formatMW(p.y)], ['Error', formatSignedMW(p.x - p.y)]]}
                    />
                  ) : null
                }}
              />
              <Scatter data={pts} fill={c.actual} fillOpacity={0.35} shape="circle" isAnimationActive={false} />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  )
}

/** Round ticks inside [lo, hi]: every 2,000 MW (or 20 %) including zero. */
function niceTicks(lo: number, hi: number, unit: string): number[] {
  const step = unit === '%' ? 20 : 2000
  const out: number[] = []
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) out.push(t)
  return out
}

function HistogramCard() {
  const { scope } = useView()
  const [norm, setNorm] = useState(false)
  const h = useErrorDistribution(scope, norm)
  const c = useChartColors()
  const d = h.data?.data
  const bins = useMemo(
    () => (d ? d.counts.map((n, i) => ({ mid: (d.edges[i]! + d.edges[i + 1]!) / 2, n })) : []),
    [d],
  )
  const unit = d?.unit ?? 'MW'
  const fmt = (v: number) => (unit === '%' ? `${v.toFixed(0)} %` : kTicks(Math.round(v)))
  return (
    <Card
      title="Signed error distribution"
      subtitle="Right of zero = over-forecast (short). Markers at P10, P50 and P90."
      actions={
        <Button aria-pressed={norm} onClick={() => setNorm((x) => !x)}>
          {norm ? 'Show MW' : 'Show % of mean'}
        </Button>
      }
    >
      {h.isPending || !d ? (
        <Skeleton className="h-72" />
      ) : (
        <div className="h-72" role="img" aria-label={`Histogram of ${d.n} signed errors; P90 ${fmt(d.quantiles.p90 ?? 0)}`}>
          <ResponsiveContainer>
            <BarChart data={bins} barCategoryGap={1} margin={{ top: 16, right: 12, bottom: 0, left: -4 }} accessibilityLayer={false}>
              <CartesianGrid stroke={c.grid} vertical={false} />
              <XAxis dataKey="mid" type="number" domain={['dataMin', 'dataMax']} ticks={niceTicks(d.edges[0]!, d.edges.at(-1)!, unit)} tickFormatter={fmt} {...axis(c.muted, c.border)} />
              <YAxis {...axis(c.muted, c.border)} width={40} />
              <Tooltip
                cursor={{ fill: c.grid }}
                content={({ payload }) => {
                  const p = payload?.[0]?.payload as { mid: number; n: number } | undefined
                  return p ? <TooltipBox title={`around ${fmt(p.mid)}`} rows={[['Half-hours', p.n]]} /> : null
                }}
              />
              <ReferenceLine x={0} stroke={c.text} />
              {(['p10', 'p50', 'p90'] as const).map((q) => (
                <ReferenceLine
                  key={q}
                  x={d.quantiles[q]}
                  stroke={c.muted}
                  strokeDasharray="4 3"
                  label={{ value: q.toUpperCase(), position: 'top', fill: c.muted, fontSize: 11 }}
                />
              ))}
              <Bar dataKey="n" fill={c.muted} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  )
}

function Heatmap() {
  const { scope } = useView()
  const series = useSeries(scope)
  const navigate = useNavigate()
  const { search } = useLocation()
  const { days, grid, max } = useMemo(() => {
    const acc = new Map<string, { s: number; n: number }>()
    const days = new Set<string>()
    for (const p of series.data?.data.points ?? []) {
      if (p.error_mw == null) continue
      const day = ukDateOf(p.start_time)
      const hour = Number(formatUkClock(p.start_time).slice(0, 2))
      days.add(day)
      const k = `${day}|${hour}`
      const a = acc.get(k) ?? { s: 0, n: 0 }
      a.s += Math.abs(p.error_mw)
      a.n += 1
      acc.set(k, a)
    }
    const grid = new Map([...acc].map(([k, v]) => [k, v.s / v.n]))
    return { days: [...days].sort(), grid, max: Math.max(1, ...grid.values()) }
  }, [series.data])

  return (
    <Card
      title="When does it go wrong?"
      subtitle="MAE by delivery day and UK hour. Darker = bigger miss. Click a cell to open that day."
    >
      {series.isPending ? (
        <Skeleton className="h-96" />
      ) : (
        <div className="overflow-x-auto">
          <div className="grid min-w-[560px] gap-px text-[10px]" style={{ gridTemplateColumns: '64px repeat(24, minmax(0, 1fr))' }}>
            <span />
            {Array.from({ length: 24 }, (_, h) => (
              <span key={h} className="text-muted num text-center">
                {h % 3 === 0 ? String(h).padStart(2, '0') : ''}
              </span>
            ))}
            {days.map((d) => (
              <div key={d} className="contents">
                <span className="text-muted num pr-1 text-right">{d.slice(5)}</span>
                {Array.from({ length: 24 }, (_, h) => {
                  const v = grid.get(`${d}|${h}`)
                  const pct = v == null ? 0 : Math.round(15 + (85 * v) / max)
                  return (
                    <button
                      key={h}
                      type="button"
                      className="h-3.5 rounded-[2px] focus-visible:outline-1"
                      style={{
                        background:
                          v == null
                            ? 'var(--surface-2)'
                            : `color-mix(in oklab, var(--error-pos) ${pct}%, var(--surface))`,
                      }}
                      title={`${d} ${String(h).padStart(2, '0')}:00 UK · MAE ${formatMW(v)}`}
                      aria-label={`${d} ${h}:00, MAE ${formatMW(v)}`}
                      onClick={() => {
                        const sp = new URLSearchParams(search)
                        sp.set('day', d)
                        navigate({ pathname: '/', search: `?${sp}` })
                      }}
                    />
                  )
                })}
              </div>
            ))}
          </div>
          <div className="text-muted mt-2 flex items-center gap-2 text-[11px]">
            <span>0 MW</span>
            <span
              className="h-2 w-32 rounded"
              style={{ background: 'linear-gradient(90deg, color-mix(in oklab, var(--error-pos) 15%, var(--surface)), var(--error-pos))' }}
            />
            <span className="num">{formatMW(max)}</span>
          </div>
        </div>
      )}
    </Card>
  )
}

function BiasCard() {
  const { scope } = useView()
  const by = useBy(scope, 'day')
  const c = useChartColors()
  const rows = useMemo(() => {
    const g = by.data?.data ?? []
    return g.map((d, i) => {
      const win = g.slice(Math.max(0, i - 6), i + 1).map((x) => x.metrics.bias_mw).filter((x): x is number => x != null)
      return {
        day: d.key,
        bias: d.metrics.bias_mw,
        rolling: win.length === Math.min(7, i + 1) && win.length >= 7 ? win.reduce((a, b) => a + b, 0) / win.length : null,
        excluded: d.excluded_from_ranking,
      }
    })
  }, [by.data])
  return (
    <Card id="bias" title="Daily bias" subtitle="Mean (forecast − actual) per day. Above zero: over-forecast, the desk was short. Line: 7-day rolling mean.">
      {by.isPending ? (
        <Skeleton className="h-64" />
      ) : (
        <div className="h-64" role="img" aria-label="Daily bias bars with 7-day rolling mean">
          <ResponsiveContainer>
            <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -4 }} accessibilityLayer={false}>
              <CartesianGrid stroke={c.grid} vertical={false} />
              <XAxis dataKey="day" tickFormatter={(d: string) => d.slice(8)} {...axis(c.muted, c.border)} interval={2} />
              <YAxis tickFormatter={kTicks} {...axis(c.muted, c.border)} width={44} />
              <ReferenceLine y={0} stroke={c.text} />
              <Tooltip
                cursor={{ fill: c.grid }}
                content={({ payload }) => {
                  const p = payload?.[0]?.payload as (typeof rows)[number] | undefined
                  return p ? (
                    <TooltipBox
                      title={p.day}
                      rows={[
                        ['Bias', formatSignedMW(p.bias)],
                        ['7-day mean', formatSignedMW(p.rolling)],
                        ...(p.excluded ? [['Note', 'under 90 % complete'] as [string, string]] : []),
                      ]}
                    />
                  ) : null
                }}
              />
              <Bar dataKey="bias" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                {rows.map((r) => (
                  <Cell key={r.day} fill={(r.bias ?? 0) >= 0 ? c['error-pos'] : c['error-neg']} fillOpacity={r.excluded ? 0.35 : 1} />
                ))}
              </Bar>
              <Line dataKey="rolling" stroke={c.text} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  )
}

function LeadTimeCard() {
  const { scope } = useView()
  const by = useBy(scope, 'lead_time')
  const cal = useCalibration(scope)
  const c = useChartColors()
  const rows = (by.data?.data ?? []).map((g) => ({ key: g.key, mae: g.metrics.mae_mw, bias: g.metrics.bias_mw, n: g.metrics.n, low: g.low_n }))
  const calRows = (cal.data?.data.buckets ?? []).map((b) => ({
    key: b.bucket,
    in_sample: b.inside_in_sample_pct,
    walk_forward: b.inside_walk_forward_pct,
  }))
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Error by lead time" subtitle="Hours between publication and the delivery period. With a fixed cutoff, longer lead also means later in the day.">
        {by.isPending ? (
          <Skeleton className="h-64" />
        ) : (
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -4 }} accessibilityLayer={false}>
                <CartesianGrid stroke={c.grid} vertical={false} />
                <XAxis dataKey="key" {...axis(c.muted, c.border)} />
                <YAxis tickFormatter={kTicks} {...axis(c.muted, c.border)} width={44} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Tooltip
                  cursor={{ fill: c.grid }}
                  content={({ payload }) => {
                    const p = payload?.[0]?.payload as (typeof rows)[number] | undefined
                    return p ? (
                      <TooltipBox title={p.key} rows={[['MAE', formatMW(p.mae)], ['Bias', formatSignedMW(p.bias)], ['n', `${p.n}${p.low ? ' (low)' : ''}`]]} />
                    ) : null
                  }}
                />
                <Bar dataKey="mae" name="MAE" fill={c.muted} radius={[3, 3, 0, 0]} isAnimationActive={false}>
                  {rows.map((r) => <Cell key={r.key} fillOpacity={r.low ? 0.35 : 1} />)}
                </Bar>
                <Bar dataKey="bias" name="Bias" fill={c['error-pos']} radius={[3, 3, 0, 0]} isAnimationActive={false}>
                  {rows.map((r) => <Cell key={r.key} fillOpacity={r.low ? 0.35 : 1} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        {rows.some((r) => r.low) && <p className="text-muted mt-1 text-xs">Faded buckets have fewer than 30 half-hours.</p>}
      </Card>
      <Card
        title="Is the band honest?"
        subtitle={`Share of actuals inside the P10–P90 band; it should be ${formatPct(cal.data?.data.nominal_pct ?? 80, 0)}. Walk-forward uses only earlier days.`}
      >
        {cal.isPending ? (
          <Skeleton className="h-64" />
        ) : (
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={calRows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }} accessibilityLayer={false}>
                <CartesianGrid stroke={c.grid} vertical={false} />
                <XAxis dataKey="key" {...axis(c.muted, c.border)} />
                <YAxis domain={[0, 100]} unit="%" {...axis(c.muted, c.border)} width={48} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <ReferenceLine y={cal.data?.data.nominal_pct ?? 80} stroke={c.text} strokeDasharray="4 3" label={{ value: 'target', position: 'right', fill: c.muted, fontSize: 11 }} />
                <Tooltip cursor={{ fill: c.grid }} content={({ payload, label }) => (payload?.length ? (
                  <TooltipBox title={label} rows={payload.map((p) => [p.name, formatPct(p.value as number)])} />
                ) : null)} />
                <Bar dataKey="in_sample" name="In-sample" fill={c.muted} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                <Bar dataKey="walk_forward" name="Walk-forward" fill={c.forecast} radius={[3, 3, 0, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>
    </div>
  )
}

export default function Accuracy() {
  const { params } = useView()
  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-lg font-semibold tracking-tight">Forecast accuracy</h1>
        <p className="text-muted text-sm">
          The whole window at the {params.cutoff} UK cutoff. <Badge>as-of forecast, never a later vintage</Badge>
        </p>
      </header>
      <MetricCards />
      <MethodDrawer />
      <div className="grid gap-4 lg:grid-cols-2">
        <ScatterCard />
        <HistogramCard />
      </div>
      <Heatmap />
      <BiasCard />
      <LeadTimeCard />
    </div>
  )
}
