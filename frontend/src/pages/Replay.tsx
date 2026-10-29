import { Eye, EyeOff, Pause, Play, SkipBack, SkipForward } from 'lucide-react'
import { useReducedMotion } from 'motion/react'
import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { TooltipBox } from '../components/charts/ChartTooltip'
import { axis, kTicks } from '../lib/chart-axis'
import { Badge, Button, Card, Skeleton } from '../components/ui'
import { useReplay } from '../features/queries'
import { useView } from '../features/view'
import { useChartColors } from '../lib/chart-colors'
import {
  addDays,
  formatDeliveryDate,
  formatHours,
  formatMW,
  formatPct,
  formatUkClock,
  formatUkTime,
} from '../lib/format'

function dayList(first?: string, last?: string): string[] {
  if (!first || !last) return []
  const out: string[] = []
  for (let d = first; d <= last; d = addDays(d, 1)) out.push(d)
  return out
}

export default function Replay() {
  const { scope, first, last, day, update, params } = useView()
  const days = useMemo(() => dayList(first, last), [first, last])
  const [revealedFor, setRevealedFor] = useState<string | null>(null)
  const [playing, setPlaying] = useState(false)
  const reduce = useReducedMotion()
  const c = useChartColors()
  const delivery = day
  const decision = delivery ? addDays(delivery, -1) : undefined
  const replay = useReplay(scope, decision)
  const r = replay.data?.data
  const revealed = revealedFor === delivery

  // Play: show the morning, reveal after 1 s, move to the next day after 2 s.
  useEffect(() => {
    if (!playing || !delivery) return
    const t1 = setTimeout(() => setRevealedFor(delivery), 1000)
    const t2 = setTimeout(() => {
      const i = days.indexOf(delivery)
      if (i < 0 || i >= days.length - 1) setPlaying(false)
      else update({ day: days[i + 1] }, { replace: true })
    }, 2000)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [playing, delivery, days, update])

  const rows = useMemo(() => {
    if (!r) return []
    return r.known.map((k, i) => {
      const rev = r.reveal[i]
      return {
        t: k.start_time,
        forecast: k.forecast_mw,
        plan: k.wind_to_plan_mw,
        actual: revealed ? (rev?.actual_mw ?? null) : null,
        miss: revealed && rev?.covered === false ? rev.actual_mw : null,
      }
    })
  }, [r, revealed])

  const idx = delivery ? days.indexOf(delivery) : -1

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-lg font-semibold tracking-tight">Replay</h1>
        <p className="text-muted text-sm">
          Step through decision mornings. Each screen shows only what was published by {params.cutoff} UK on the
          decision day; press Reveal to see what the wind actually did.
        </p>
      </header>

      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <Button aria-label="Previous day" disabled={idx <= 0} onClick={() => update({ day: days[idx - 1] })}>
            <SkipBack className="size-4" aria-hidden />
          </Button>
          <Button variant="solid" onClick={() => setPlaying((p) => !p)} aria-pressed={playing}>
            {playing ? <Pause className="size-4" aria-hidden /> : <Play className="size-4" aria-hidden />}
            {playing ? 'Pause' : 'Play'}
          </Button>
          <Button aria-label="Next day" disabled={idx < 0 || idx >= days.length - 1} onClick={() => update({ day: days[idx + 1] })}>
            <SkipForward className="size-4" aria-hidden />
          </Button>
          <label className="flex min-w-[220px] flex-1 items-center gap-3 text-sm">
            <span className="sr-only">Delivery day</span>
            <input
              type="range"
              min={0}
              max={Math.max(0, days.length - 1)}
              value={Math.max(0, idx)}
              onChange={(e) => update({ day: days[Number(e.target.value)] }, { replace: true })}
              className="flex-1 accent-[var(--forecast)]"
              aria-valuetext={delivery ? formatDeliveryDate(delivery) : ''}
            />
          </label>
          <Button onClick={() => setRevealedFor(revealed ? null : (delivery ?? null))} aria-pressed={revealed}>
            {revealed ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
            {revealed ? 'Hide outcome' : 'Reveal'}
          </Button>
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-12">
        <Card
          className="xl:col-span-8"
          title={delivery ? `Buying for ${formatDeliveryDate(delivery)}` : 'Replay'}
          subtitle={decision ? `Decision morning: ${formatDeliveryDate(decision)}, ${params.cutoff} UK` : undefined}
          actions={revealed ? <Badge tone="warn">outcome revealed</Badge> : <Badge>as known at the cutoff</Badge>}
        >
          {replay.isPending || !r ? (
            <Skeleton className="h-80" />
          ) : (
            <>
              <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Legend">
                <li className="flex items-center gap-1.5"><span className="bg-forecast inline-block h-0.5 w-4" /> Forecast at cutoff</li>
                <li className="flex items-center gap-1.5"><span className="border-text inline-block w-4 border-t-2 border-dashed" /> Plan on (forecast − margin)</li>
                {revealed && <li className="flex items-center gap-1.5"><span className="bg-actual inline-block h-0.5 w-4" /> Actual</li>}
                {revealed && <li className="flex items-center gap-1.5"><span className="bg-error-pos inline-block size-2 rounded-full" /> Short even after margin</li>}
              </ul>
              <div className="h-80" role="img" aria-label={revealed ? `Forecast, plan and actual for ${delivery}` : `Forecast and plan for ${delivery} as known at the cutoff`}>
                <ResponsiveContainer>
                  <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -8 }} accessibilityLayer={false}>
                    <CartesianGrid stroke={c.grid} vertical={false} />
                    <XAxis dataKey="t" tickFormatter={(t: string) => formatUkClock(t)} interval={5} {...axis(c.muted, c.border)} />
                    <YAxis tickFormatter={kTicks} domain={[0, 'auto']} {...axis(c.muted, c.border)} width={44} />
                    <Tooltip
                      content={({ payload, label }) => {
                        const p = payload?.[0]?.payload as (typeof rows)[number] | undefined
                        return p ? (
                          <TooltipBox
                            title={`${formatUkClock(String(label))} UK`}
                            rows={[
                              ['Forecast', formatMW(p.forecast)],
                              ['Plan on', formatMW(p.plan)],
                              ...(revealed ? [['Actual', formatMW(p.actual)] as [string, string]] : []),
                            ]}
                          />
                        ) : null
                      }}
                    />
                    <Line dataKey="forecast" type="stepAfter" stroke={c.forecast} strokeWidth={2} dot={false} isAnimationActive={false} />
                    <Line dataKey="plan" type="stepAfter" stroke={c.text} strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
                    {revealed && (
                      <Line dataKey="actual" stroke={c.actual} strokeWidth={2.5} dot={false} connectNulls={false} isAnimationActive={!reduce} animationDuration={700} />
                    )}
                    {revealed && <Scatter dataKey="miss" fill={c['error-pos']} isAnimationActive={false} />}
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </>
          )}
        </Card>

        <Card className="xl:col-span-4" title="At the cutoff" subtitle="Everything here was knowable when buying.">
          {r ? (
            <dl className="num grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
              <dt className="text-muted font-sans text-xs">Vintage on screen</dt>
              <dd>{formatUkTime(r.publish_time)}</dd>
              <dt className="text-muted font-sans text-xs">Its age</dt>
              <dd>{formatHours(r.vintage_age_h)}</dd>
              <dt className="text-muted font-sans text-xs">P90 margin</dt>
              <dd>{r.margin_mw != null ? formatMW(r.margin_mw) : 'not enough history'}</dd>
              <dt className="text-muted font-sans text-xs">Learned from</dt>
              <dd>{r.history_days} earlier days</dd>
              <dt className="text-muted font-sans text-xs">Last actual known</dt>
              <dd>
                {r.recent_actuals.length
                  ? `${formatMW(r.recent_actuals.at(-1)!.actual_mw)} at ${formatUkClock(r.recent_actuals.at(-1)!.start_time)}`
                  : '—'}
              </dd>
              {revealed && (
                <>
                  <dt className="text-muted col-span-2 mt-2 border-t border-[var(--border)] pt-2 font-sans text-xs font-semibold">
                    What happened
                  </dt>
                  <dt className="text-muted font-sans text-xs">MAE that day</dt>
                  <dd>{formatMW(r.reveal_mae_mw)}</dd>
                  <dt className="text-muted font-sans text-xs">Margin covered</dt>
                  <dd>{formatPct(r.reveal_coverage_pct, 0)} of half-hours</dd>
                </>
              )}
            </dl>
          ) : (
            <Skeleton className="h-48" />
          )}
        </Card>
      </div>
    </div>
  )
}
