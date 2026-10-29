import { motion, useReducedMotion } from 'motion/react'
import { useMemo, useState } from 'react'
import { DayChart } from '../components/charts/DayChart'
import { VintageStrip } from '../components/charts/VintageStrip'
import { KpiTile } from '../components/kpi/KpiTile'
import { PlanTable } from '../components/tables/PlanTable'
import { Badge, Card, Skeleton, selectClass } from '../components/ui'
import { useDayVintages, useMargin, useSeries } from '../features/queries'
import { useView } from '../features/view'
import {
  formatDeliveryDate,
  formatGWh,
  formatHours,
  formatMW,
  formatPct,
  formatUkTime,
  ukDateOf,
} from '../lib/format'

const pct = (v: number | null | undefined) => formatPct(v == null ? v : v * 100, 0)

export default function Dashboard() {
  const { params, update, scope, summary, day } = useView()
  const series = useSeries(scope)
  const margin = useMargin(scope, day, params.policy)
  const vintages = useDayVintages(scope, day)
  const [preview, setPreview] = useState<string | null>(null)
  const reduce = useReducedMotion()

  const m = summary.data?.data
  const plan = margin.data?.data.plan
  const v = vintages.data?.data

  const dayPoints = useMemo(
    () => (series.data?.data.points ?? []).filter((p) => day && ukDateOf(p.start_time) === day),
    [series.data, day],
  )
  const dayComplete = dayPoints.length
    ? dayPoints.filter((p) => p.actual_mw != null && p.forecast_mw != null).length / dayPoints.length
    : null
  const dayMargins = plan?.rows.map((r) => r.margin_mw).filter((x): x is number => x != null) ?? []
  const meanMargin = dayMargins.length ? dayMargins.reduce((a, b) => a + b, 0) / dayMargins.length : null
  const marginMwh = dayMargins.reduce((a, b) => a + b * 0.5, 0)
  const ageH =
    v?.selected_publish_time != null ? (Date.parse(v.cutoff) - Date.parse(v.selected_publish_time)) / 3.6e6 : null

  const previewVintage = v?.vintages.find((x) => x.publish_time === preview)
  const previewMap = useMemo(
    () => (previewVintage ? new Map(previewVintage.points.map((p) => [p.start_time, p.forecast_mw])) : undefined),
    [previewVintage],
  )
  const iv = m?.intervals ?? undefined
  const loading = summary.isPending

  const tiles = [
    <KpiTile
      key="fc"
      label="Wind forecast for the day"
      value={plan?.forecast_total_mwh}
      format={(x) => formatGWh(x)}
      hint="Sum of the as-of forecast over the delivery day (MW × 0.5 h)."
      loading={margin.isPending}
      detail={<>Plan on {formatGWh(plan?.wind_to_plan_total_mwh)} after the margin</>}
    />,
    <KpiTile
      key="mae"
      label="Typical miss (MAE)"
      value={m?.mae_mw}
      format={formatMW}
      hint="Mean absolute error of the forecast at this cutoff over the whole window."
      loading={loading}
      detail={iv?.mae_mw ? <>95 % CI {formatMW(iv.mae_mw[0]).replace(' MW', '')}–{formatMW(iv.mae_mw[1])}</> : 'window average'}
    />,
    <KpiTile
      key="margin"
      label={`P${Math.round((margin.data?.data.quantile ?? 0.9) * 100)} safety margin`}
      value={meanMargin}
      format={formatMW}
      hint="Wind to hold back from the forecast for this day: the error quantile, fitted only on days known before the cutoff."
      loading={margin.isPending}
      detail={<>{formatGWh(marginMwh)} over the day · bias {formatMW(m?.bias_mw)}</>}
    />,
    <KpiTile
      key="skill"
      label="Skill vs persistence"
      value={m?.skill_vs_persistence}
      format={pct}
      hint="1 − MAE(forecast) / MAE(yesterday's actual, same period). Above 0 means the forecast adds value."
      loading={loading}
      detail={
        iv?.skill_vs_persistence ? (
          <>95 % CI {pct(iv.skill_vs_persistence[0])}–{pct(iv.skill_vs_persistence[1])}</>
        ) : (
          'better than a naive guess'
        )
      }
    />,
    <KpiTile
      key="age"
      label="Forecast age at cutoff"
      value={ageH}
      format={formatHours}
      hint="Time between the vintage's publication and the decision cutoff."
      loading={vintages.isPending}
      badge={ageH != null && ageH > 24 ? <Badge tone="warn">stale</Badge> : null}
      detail={v?.selected_publish_time ? <>Published {formatUkTime(v.selected_publish_time)}</> : 'No vintage before cutoff'}
    />,
    <KpiTile
      key="complete"
      label="Completeness"
      value={dayComplete == null ? null : dayComplete * 100}
      format={(x) => formatPct(x, 0)}
      hint="Share of the day's half-hours with both a forecast and an actual."
      loading={series.isPending}
      badge={dayComplete != null && dayComplete < 1 ? <Badge tone="warn">gaps</Badge> : <Badge tone="ok">complete</Badge>}
      detail={<>Window {formatPct((summary.data?.meta.completeness ?? 0) * 100, 0)}</>}
    />,
  ]

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{day ? formatDeliveryDate(day) : 'Decision dashboard'}</h1>
          <p className="text-muted text-sm">
            What the desk saw at {params.cutoff} UK the day before, and what happened.
          </p>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {tiles.map((t, i) => (
          <motion.div
            key={i}
            initial={reduce ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.04, duration: 0.18 }}
          >
            {t}
          </motion.div>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-12">
        <Card
          className="xl:col-span-8"
          title="Forecast vs actual"
          subtitle="Half-hourly MW, UK time. The band is where actual wind landed relative to the forecast in 80 % of the window's half-hours."
        >
          {series.isPending ? (
            <Skeleton className="h-80 w-full" />
          ) : series.isError ? (
            <p role="alert" className="text-sm">Could not load the series: {series.error.message}</p>
          ) : dayPoints.length ? (
            <DayChart
              points={dayPoints}
              preview={previewMap}
              previewLabel={previewVintage ? `Vintage ${formatUkTime(previewVintage.publish_time)}` : undefined}
            />
          ) : (
            <p className="text-muted text-sm">No data for this day.</p>
          )}
        </Card>

        <Card
          className="xl:col-span-4"
          title="What to buy"
          id="margin"
          actions={
            <select
              aria-label="Margin policy"
              className={selectClass}
              value={params.policy}
              onChange={(e) => update({ policy: e.target.value })}
            >
              <option value="flat">Flat P90 margin</option>
              <option value="conditional">Level-dependent margin</option>
              <option value="none">No margin</option>
            </select>
          }
        >
          {margin.isPending || !plan ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-64 w-full" />
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {meanMargin != null && (
                <p className="text-sm leading-snug">
                  <span className="font-semibold">For this day:</span> hold back{' '}
                  <span className="num">{formatMW(meanMargin)}</span> of the forecast
                  {plan.margin_basis === 'walk_forward'
                    ? `, learned from the ${plan.history_days} days known before the cutoff.`
                    : '.'}
                </p>
              )}
              <p className="text-muted text-xs leading-snug">
                <span className="font-medium">Across the window:</span> {margin.data?.data.recommendation}
              </p>
              <PlanTable plan={plan} />
            </div>
          )}
        </Card>
      </div>

      <Card
        title="How the forecast for this day evolved"
        subtitle="Every vintage, oldest first, on one scale; faint line = actual. Click one to overlay it on the chart."
      >
        {vintages.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : v && v.vintages.length ? (
          <>
            <VintageStrip vintages={v.vintages} actuals={v.actuals} preview={preview} onPreview={setPreview} />
            {v.revision_range_mw != null && (
              <p className="text-muted mt-2 text-xs">
                Before the cutoff, the {v.revision_vintages} latest vintages moved the day's mean forecast by up to{' '}
                <span className="num text-text">{formatMW(v.revision_range_mw)}</span> (compared on the{' '}
                {v.revision_hours} hours they all cover).
              </p>
            )}
          </>
        ) : (
          <p className="text-muted text-sm">
            No vintages for this day.
            {v?.nearest_date_with_data && (
              <>
                {' '}
                <button type="button" className="underline" onClick={() => update({ day: v.nearest_date_with_data! })}>
                  Go to {v.nearest_date_with_data}
                </button>
              </>
            )}
          </p>
        )}
      </Card>
    </div>
  )
}
