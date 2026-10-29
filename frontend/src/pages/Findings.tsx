import { ArrowRight } from 'lucide-react'
import { Link, useLocation } from 'react-router'
import { Card, Skeleton } from '../components/ui'
import { useBy, useFindings, useMargin } from '../features/queries'
import { useView } from '../features/view'
import { formatGWh, formatMW, formatNumber, formatPct, formatSignedMW } from '../lib/format'

const POLICY_LABEL = { none: 'No margin', flat: 'Flat P90', conditional: 'Level-dependent P90' } as const

const ROADMAP: [string, string, string][] = [
  ['Bias correction', 'Subtract the rolling bias by lead time and wind regime.', 'January data already loaded'],
  ['Calibrated uncertainty', 'Quantile regression or conformal intervals on level, lead and hour: margins that shrink on easy days.', '3+ months of history'],
  ['Vintage-aware model', 'Gradient boosting on the last few vintages and their revisions.', '6–12 months of vintages'],
  ['Weather-informed model', 'Add hub-height wind from numerical weather prediction.', 'NWP feed, licence check'],
  ['Demand and residual', 'Forecast demand with the same harness; output the volume to buy.', 'Elexon demand data'],
  ['Price-aware margin', 'Optimise against asymmetric short/long costs instead of a fixed quantile.', 'Imbalance and intraday prices'],
  ['Grounded assistant', 'Answer desk questions by calling this API, showing every call.', 'This pilot'],
]

function fmtValue(v: number | null, unit: string) {
  if (v == null) return '—'
  if (unit === 'MW') return formatSignedMW(v)
  if (unit === '%') return formatPct(v, 0)
  if (unit === 'ratio') return formatPct(v * 100, 0)
  return formatNumber(v)
}

export default function Findings() {
  const { scope, params, day } = useView()
  const { search } = useLocation()
  const findings = useFindings(scope)
  const regimes = useBy(scope, 'regime')
  const margin = useMargin(scope, day, params.policy)
  const m = margin.data?.data

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-lg font-semibold tracking-tight">What the data says</h1>
        <p className="text-muted text-sm">
          Computed from the window at the {params.cutoff} UK cutoff; every number links to the chart that shows it.
        </p>
      </header>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {findings.isPending
          ? Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-40" />)
          : findings.data?.data.map((f) => (
              <Card key={f.id} id={f.id}>
                <div className="flex h-full flex-col gap-2">
                  <h2 className="font-semibold leading-snug">{f.title}</h2>
                  <p className="num text-2xl font-semibold">{fmtValue(f.value, f.unit)}</p>
                  {f.interval && (
                    <p className="text-muted num text-xs">
                      95 % CI {fmtValue(f.interval[0] ?? null, f.unit)} to {fmtValue(f.interval[1] ?? null, f.unit)}
                    </p>
                  )}
                  <p className="text-muted flex-1 text-sm leading-snug">{f.body}</p>
                  <Link className="text-text inline-flex items-center gap-1 text-xs font-medium hover:underline" to={{ pathname: f.link.split('#')[0] || '/', search, hash: f.link.split('#')[1] }}>
                    See the evidence <ArrowRight className="size-3" aria-hidden />
                  </Link>
                </div>
              </Card>
            ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card id="policies" title="Buying policies compared" subtitle="Same January data. Walk-forward: each day's margin learned only from days known before its cutoff.">
          {!m ? (
            <Skeleton className="h-40" />
          ) : (
            <div className="overflow-x-auto">
              <table className="num w-full text-right text-xs">
                <thead className="text-muted">
                  <tr>
                    <th scope="col" className="text-left font-medium">Policy</th>
                    <th scope="col" className="font-medium">Coverage (in-sample)</th>
                    <th scope="col" className="font-medium">Coverage (walk-fwd)</th>
                    <th scope="col" className="font-medium">Mean margin</th>
                    <th scope="col" className="font-medium">Over-bought</th>
                    <th scope="col" className="font-medium">Still short</th>
                  </tr>
                </thead>
                <tbody>
                  {m.walk_forward.map((wf) => {
                    const ins = m.in_sample.find((x) => x.policy === wf.policy)
                    return (
                      <tr key={wf.policy} className="border-border border-t">
                        <th scope="row" className="py-1 text-left font-normal">{POLICY_LABEL[wf.policy]}</th>
                        <td>{formatPct(ins?.coverage_pct)}</td>
                        <td className="font-semibold">{formatPct(wf.coverage_pct)}</td>
                        <td>{formatMW(wf.mean_margin_mw)}</td>
                        <td>{formatGWh(wf.over_procured_mwh, 0)}</td>
                        <td>{formatGWh(wf.shortfall_mwh, 0)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <p className="text-muted mt-2 text-xs">
                Walk-forward covers {m.walk_forward[0]?.n_days ?? 0} days; the first{' '}
                {m.walk_forward[0]?.days_skipped ?? 0} lacked a week of usable history.
              </p>
            </div>
          )}
        </Card>

        <Card id="regime" title="Wind regime" subtitle="Days split into thirds by actual mean wind.">
          {regimes.isPending ? (
            <Skeleton className="h-40" />
          ) : (
            <table className="num w-full text-right text-xs">
              <thead className="text-muted">
                <tr>
                  <th scope="col" className="text-left font-medium">Regime</th>
                  <th scope="col" className="font-medium">Days</th>
                  <th scope="col" className="font-medium">Mean actual</th>
                  <th scope="col" className="font-medium">MAE</th>
                  <th scope="col" className="font-medium">Bias</th>
                  <th scope="col" className="font-medium">P90 error</th>
                </tr>
              </thead>
              <tbody>
                {regimes.data?.data.map((g) => (
                  <tr key={g.key} className="border-border border-t">
                    <th scope="row" className="py-1 text-left font-normal capitalize">{g.key}</th>
                    <td>{g.metrics.n_days}</td>
                    <td>{formatMW(g.metrics.mean_actual_mw)}</td>
                    <td>{formatMW(g.metrics.mae_mw)}</td>
                    <td>{formatSignedMW(g.metrics.bias_mw)}</td>
                    <td>{formatMW(g.metrics.error_quantiles_mw.p90)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <Card title="Roadmap: from measuring the forecast to improving it" subtitle="Not built in the pilot. Each step plugs into the same walk-forward harness and ships only if it beats the raw forecast out of sample.">
        <ol className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {ROADMAP.map(([t, d, need], i) => (
            <li key={t} className="bg-surface-2 rounded-lg p-3 text-sm">
              <div className="text-muted num text-xs">Step {i + 1}</div>
              <div className="font-semibold">{t}</div>
              <p className="text-muted mt-1 text-xs leading-snug">{d}</p>
              <p className="mt-1 text-[11px]">Needs: {need}</p>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  )
}
