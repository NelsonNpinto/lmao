import { useQueryClient } from '@tanstack/react-query'
import { ExternalLink, RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Badge, Button, Card, Skeleton } from '../components/ui'
import { useBy, useIngestRuns, useMeta } from '../features/queries'
import { useView } from '../features/view'
import { api } from '../lib/api/client'
import { formatNumber, formatPct, formatUkTime } from '../lib/format'
import { useToasts } from '../lib/stores'

const TOKEN_KEY = 'windsight-admin-token'

function readToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

function RefreshPanel() {
  const qc = useQueryClient()
  const push = useToasts((s) => s.push)
  const [token, setToken] = useState(readToken)
  const [busy, setBusy] = useState(false)
  const runs = useIngestRuns(busy)
  const latest = runs.data?.data[0]
  const watching = useRef<string | null>(null)

  useEffect(() => {
    if (!busy || !latest || latest.id !== watching.current || latest.status === 'running') return
    setBusy(false)
    watching.current = null
    push(
      `Refresh ${latest.status}: ${formatNumber(latest.rows_upserted)} rows changed, ${formatNumber(latest.rows_rejected)} rejected.`,
      latest.status === 'succeeded' ? 'info' : 'warn',
    )
    void qc.invalidateQueries()
  }, [busy, latest, push, qc])

  const start = async () => {
    try {
      sessionStorage.setItem(TOKEN_KEY, token)
    } catch {
      /* private mode: keep it in memory only */
    }
    const r = await api.POST('/api/v1/ingest/runs', {
      body: { dataset: 'ALL', mode: 'refresh' },
      headers: { 'X-Admin-Token': token },
    })
    if (r.response.status === 202 && r.data) {
      watching.current = r.data.data.id
      setBusy(true)
      void qc.invalidateQueries({ queryKey: ['ingest-runs'] })
    } else if (r.response.status === 409) {
      push('A refresh is already running.', 'warn')
    } else {
      const detail = (r.error as { detail?: string } | undefined)?.detail
      push(`Refresh refused (${r.response.status}): ${detail ?? 'check the admin token'}`, 'error')
    }
  }

  return (
    <Card title="Refresh from Elexon" subtitle="Re-pulls every slice of the seed window from the Insights API; unchanged rows are not rewritten.">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-xs">
          <span className="text-muted">Admin token</span>
          <input
            type="password"
            autoComplete="off"
            className="border-border bg-surface h-8 rounded-md border px-2 text-xs"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </label>
        <Button variant="solid" onClick={start} disabled={busy || !token}>
          <RefreshCw className={busy ? 'size-3.5 animate-spin motion-reduce:animate-none' : 'size-3.5'} aria-hidden />
          {busy ? 'Refreshing…' : 'Refresh'}
        </Button>
      </div>
      {busy && latest?.status === 'running' && (
        <div className="mt-3" aria-live="polite">
          <div className="bg-surface-2 h-2 overflow-hidden rounded-full">
            <div className="bg-forecast h-full transition-[width]" style={{ width: `${Math.round(latest.progress * 100)}%` }} />
          </div>
          <p className="text-muted num mt-1 text-xs">
            {latest.slices_done} of {latest.slices_total} slices · {formatNumber(latest.rows_fetched)} rows fetched
          </p>
        </div>
      )}
    </Card>
  )
}

function Calendar() {
  const { scope } = useView()
  const by = useBy(scope, 'day')
  return (
    <Card title="Coverage" subtitle="Each square is a delivery day: share of half-hours with both a forecast and an actual.">
      {by.isPending ? (
        <Skeleton className="h-28" />
      ) : (
        <>
          <ol className="grid grid-cols-7 gap-1 sm:grid-cols-[repeat(16,minmax(0,1fr))]" aria-label="Coverage by day">
            {by.data?.data.map((d) => {
              const c = d.metrics.completeness ?? 0
              return (
                <li
                  key={d.key}
                  className="num flex aspect-square flex-col items-center justify-center rounded text-[10px]"
                  style={{
                    background: c >= 1 ? 'color-mix(in oklab, var(--ok) 30%, var(--surface))' : c >= 0.9 ? 'color-mix(in oklab, var(--warn) 30%, var(--surface))' : 'var(--surface-2)',
                  }}
                  title={`${d.key}: ${formatPct(c * 100, 0)} complete`}
                  aria-label={`${d.key}: ${formatPct(c * 100, 0)} complete`}
                >
                  <span>{d.key.slice(8)}</span>
                  {c < 1 && <span aria-hidden>{c >= 0.9 ? '!' : '×'}</span>}
                </li>
              )
            })}
          </ol>
          <p className="text-muted mt-2 text-xs">Green: complete. Amber (!): 90–99 %. Gray (×): under 90 %, excluded from daily rankings.</p>
        </>
      )}
    </Card>
  )
}

export default function Data() {
  const meta = useMeta()
  const runs = useIngestRuns(false)
  const cov = meta.data?.data.coverage
  const last = meta.data?.data.last_ingest
  const q = (last?.quality ?? {}) as Record<string, unknown>
  const fuel = (q.FUELHH ?? {}) as Record<string, number>
  const wind = (q.WINDFOR ?? {}) as Record<string, number>

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-lg font-semibold tracking-tight">Data and methods</h1>
        <p className="text-muted text-sm">Where every number comes from, how complete it is, and how to refresh it.</p>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="What is loaded">
          {cov ? (
            <dl className="num grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
              <dt className="text-muted font-sans">Actual half-hours</dt>
              <dd>{formatNumber(cov.actual_rows)}</dd>
              <dt className="text-muted font-sans">Actuals span</dt>
              <dd>{formatUkTime(cov.actual_from)} – {formatUkTime(cov.actual_to)}</dd>
              <dt className="text-muted font-sans">Forecast rows</dt>
              <dd>{formatNumber(cov.forecast_rows)}</dd>
              <dt className="text-muted font-sans">Vintages</dt>
              <dd>{formatNumber(cov.forecast_vintages)}</dd>
              <dt className="text-muted font-sans">Vintages published</dt>
              <dd>{formatUkTime(cov.forecast_published_from)} – {formatUkTime(cov.forecast_published_to)}</dd>
              <dt className="text-muted font-sans">Revised actuals</dt>
              <dd>{cov.actual_revisions}</dd>
            </dl>
          ) : (
            <Skeleton className="h-36" />
          )}
        </Card>
        <Card title="Data quality (last run)">
          {last ? (
            <dl className="num grid grid-cols-3 gap-x-4 gap-y-1.5 text-sm">
              <dt />
              <dd className="text-muted font-sans text-xs">Actuals</dd>
              <dd className="text-muted font-sans text-xs">Forecasts</dd>
              {(['rows_in', 'accepted', 'null_generation', 'negative_generation', 'duplicates'] as const).map((k) => (
                <div key={k} className="contents">
                  <dt className="text-muted font-sans">{k.replace('_', ' ')}</dt>
                  <dd>{formatNumber(fuel[k])}</dd>
                  <dd>{formatNumber(wind[k])}</dd>
                </div>
              ))}
              <dt className="text-muted font-sans">Forecast resolution</dt>
              <dd className="col-span-2">{String(q.forecast_resolution ?? '—')}</dd>
              <dt className="text-muted font-sans">Incomplete days</dt>
              <dd className="col-span-2">{Object.keys((q.incomplete_days ?? {}) as object).length}</dd>
            </dl>
          ) : (
            <Skeleton className="h-36" />
          )}
        </Card>
      </div>

      <Calendar />
      <RefreshPanel />

      <Card title="Ingest runs">
        <div className="overflow-x-auto">
          <table className="num w-full text-right text-xs">
            <thead className="text-muted">
              <tr>
                <th scope="col" className="text-left font-medium">Started (UK)</th>
                <th scope="col" className="text-left font-medium">Status</th>
                <th scope="col" className="font-medium">Mode</th>
                <th scope="col" className="font-medium">Slices</th>
                <th scope="col" className="font-medium">Fetched</th>
                <th scope="col" className="font-medium">Changed</th>
                <th scope="col" className="font-medium">Rejected</th>
              </tr>
            </thead>
            <tbody>
              {runs.data?.data.map((r) => (
                <tr key={r.id} className="border-border border-t" title={r.error ?? undefined}>
                  <th scope="row" className="py-1 text-left font-normal">{formatUkTime(r.started_at)}</th>
                  <td className="text-left">
                    <Badge tone={r.status === 'succeeded' ? 'ok' : r.status === 'running' ? 'neutral' : 'warn'}>{r.status}</Badge>
                  </td>
                  <td>{r.mode}</td>
                  <td>{r.slices_done}/{r.slices_total}</td>
                  <td>{formatNumber(r.rows_fetched)}</td>
                  <td>{formatNumber(r.rows_upserted)}</td>
                  <td>{formatNumber(r.rows_rejected)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Sources">
          <ul className="flex flex-col gap-2 text-sm">
            {[
              ['FUELHH: half-hourly generation outturn by fuel type (WIND)', 'https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream'],
              ['WINDFOR: wind generation forecast, every publication', 'https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream'],
            ].map(([label, href]) => (
              <li key={href}>
                <a className="inline-flex items-center gap-1 hover:underline" href={href} target="_blank" rel="noreferrer">
                  {label} <ExternalLink className="size-3" aria-hidden />
                </a>
              </li>
            ))}
          </ul>
          <p className="text-muted mt-3 text-xs leading-snug">
            Caveats: in very windy periods grid constraints curtail wind farms, so metered output can sit below what
            the wind could have produced, which inflates apparent over-forecast. Both datasets cover metered wind;
            unmetered embedded wind is in neither.
          </p>
        </Card>
        <Card title="Glossary">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
            {[
              ['Vintage', 'One publication of the forecast. About 8 a day, each 2–3 days ahead.'],
              ['Cutoff', 'The time on D-1 by which the desk decides. The forecast used is the latest vintage published by then.'],
              ['Lead time', 'Hours from a vintage’s publication to the half-hour it forecasts.'],
              ['Bias', 'Average of forecast − actual. Positive: the forecast promised more wind than came.'],
              ['Margin', 'Wind held back from the forecast when buying, sized from past errors.'],
              ['Walk-forward', 'Each day judged with a margin learned only from days already known at its cutoff.'],
            ].map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="font-medium">{k}</dt>
                <dd className="text-muted">{v}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>
    </div>
  )
}
