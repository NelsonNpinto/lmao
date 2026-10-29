/**
 * Server state. Every hook passes TanStack Query's AbortSignal through, so a
 * superseded request (fast cutoff changes) is cancelled, and keeps the
 * previous data on screen while the next loads: no flicker (Break #22).
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, unwrap } from '../lib/api/client'

export interface Scope {
  from?: string
  to?: string
  cutoff: string
}

const query = (s: Scope) => ({
  ...(s.from ? { from: s.from } : {}),
  ...(s.to ? { to: s.to } : {}),
  cutoff: s.cutoff,
})

const common = { placeholderData: keepPreviousData, staleTime: 5 * 60_000 } as const

export function useMeta() {
  return useQuery({
    queryKey: ['meta'],
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/v1/meta', { signal })),
    staleTime: 30_000,
    retry: 4,
    retryDelay: (n) => Math.min(1000 * 2 ** n, 8000),
  })
}

export function useSummary(s: Scope) {
  return useQuery({
    queryKey: ['summary', s],
    queryFn: async ({ signal }) =>
      unwrap(await api.GET('/api/v1/metrics/summary', { params: { query: query(s) }, signal })),
    ...common,
  })
}

export function useSeries(s: Scope) {
  return useQuery({
    queryKey: ['series', s],
    queryFn: async ({ signal }) =>
      unwrap(await api.GET('/api/v1/series', { params: { query: query(s) }, signal })),
    ...common,
  })
}

export function useMargin(s: Scope, day: string | undefined, policy: 'none' | 'flat' | 'conditional') {
  return useQuery({
    queryKey: ['margin', s, day, policy],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/procurement/margin', {
          params: { query: { ...query(s), policy, ...(day ? { day } : {}) } },
          signal,
        }),
      ),
    enabled: Boolean(day),
    ...common,
  })
}

export function useDayVintages(s: Scope, day: string | undefined) {
  return useQuery({
    queryKey: ['vintages', s.cutoff, day],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/days/{delivery_date}/vintages', {
          params: { path: { delivery_date: day! }, query: { cutoff: s.cutoff } },
          signal,
        }),
      ),
    enabled: Boolean(day),
    ...common,
  })
}

export function exportUrl(s: Scope, format: 'csv' | 'xlsx' | 'json'): string {
  const base = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''
  const q = new URLSearchParams({ ...query(s), format })
  return `${base}/api/v1/export?${q}`
}

export type Dimension = 'day' | 'hour' | 'weekday' | 'lead_time' | 'regime'

export function useBy(s: Scope, dimension: Dimension) {
  return useQuery({
    queryKey: ['by', dimension, s],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/metrics/by/{dimension}', {
          params: { path: { dimension }, query: query(s) },
          signal,
        }),
      ),
    ...common,
  })
}

export function useErrorDistribution(s: Scope, normalise: boolean) {
  return useQuery({
    queryKey: ['hist', s, normalise],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/metrics/error-distribution', {
          params: { query: { ...query(s), bins: 40, normalise } },
          signal,
        }),
      ),
    ...common,
  })
}

export function useCalibration(s: Scope) {
  return useQuery({
    queryKey: ['calibration', s],
    queryFn: async ({ signal }) =>
      unwrap(await api.GET('/api/v1/metrics/calibration', { params: { query: query(s) }, signal })),
    ...common,
  })
}

export const HOURLY_CUTOFFS = Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, '0')}:00`)

export function useCutoffSweep(s: Scope, daysBefore: 1 | 2) {
  return useQuery({
    queryKey: ['sweep', s.from, s.to, daysBefore],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/metrics/cutoff-sweep', {
          params: {
            query: {
              ...query(s),
              days_before: daysBefore,
              cutoffs: HOURLY_CUTOFFS.join(','),
            },
          },
          signal,
        }),
      ),
    ...common,
  })
}

export function useFindings(s: Scope) {
  return useQuery({
    queryKey: ['findings', s],
    queryFn: async ({ signal }) =>
      unwrap(await api.GET('/api/v1/findings', { params: { query: query(s) }, signal })),
    ...common,
  })
}

export function useReplay(s: Scope, decisionDate: string | undefined) {
  return useQuery({
    queryKey: ['replay', s, decisionDate],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/replay/{decision_date}', {
          params: { path: { decision_date: decisionDate! }, query: query(s) },
          signal,
        }),
      ),
    enabled: Boolean(decisionDate),
    ...common,
  })
}

export function useIngestRuns(poll: boolean) {
  return useQuery({
    queryKey: ['ingest-runs'],
    queryFn: async ({ signal }) =>
      unwrap(await api.GET('/api/v1/ingest/runs', { params: { query: { limit: 20 } }, signal })),
    refetchInterval: poll ? 1000 : false,
  })
}
