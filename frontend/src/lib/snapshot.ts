/**
 * Static snapshot fallback (Break #20): if the API cannot be reached, or the
 * build sets VITE_STATIC_SNAPSHOT=true, requests are answered from JSON files
 * saved by `python -m app.cli snapshot` for the default view. Read-only: any
 * request outside the snapshot gets a clear 404, writes get 503.
 */
import { create } from 'zustand'

interface Manifest {
  generated_at: string
  cutoff: string
  window: [string, string]
  entries: Record<string, string>
}

interface SnapshotState {
  active: boolean
  reason: 'forced' | 'api-unreachable' | null
  generatedAt: string | null
  activate: (reason: 'forced' | 'api-unreachable') => void
  deactivate: () => void
}

export const FORCED = import.meta.env.VITE_STATIC_SNAPSHOT === 'true'

export const useSnapshot = create<SnapshotState>((set) => ({
  active: FORCED,
  reason: FORCED ? 'forced' : null,
  generatedAt: null,
  activate: (reason) => set({ active: true, reason }),
  deactivate: () => set({ active: false, reason: null }),
}))

/** Must match backend app.cli.snapshot_key: path + '?' + sorted, decoded params. */
export function snapshotKey(url: string): string {
  const u = new URL(url, 'http://x')
  const params = [...u.searchParams.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
  const q = params.map(([k, v]) => `${k}=${v}`).join('&')
  return q ? `${u.pathname}?${q}` : u.pathname
}

let manifest: Promise<Manifest | null> | null = null

export function loadManifest(): Promise<Manifest | null> {
  manifest ??= fetch('/snapshot/manifest.json')
    .then((r) => (r.ok ? (r.json() as Promise<Manifest>) : null))
    .then((m) => {
      if (m) useSnapshot.setState({ generatedAt: m.generated_at })
      return m
    })
    .catch(() => null)
  return manifest
}

const problem = (status: number, detail: string) =>
  new Response(JSON.stringify({ type: 'about:blank', title: 'Offline snapshot', status, detail }), {
    status,
    headers: { 'Content-Type': 'application/problem+json' },
  })

export async function snapshotFetch(request: Request): Promise<Response> {
  if (request.method !== 'GET') return problem(503, 'The offline snapshot is read-only.')
  const m = await loadManifest()
  if (!m) return problem(503, 'The API is unreachable and no offline snapshot is available.')
  const file = m.entries[snapshotKey(request.url)]
  if (!file)
    return problem(
      404,
      `Not in the offline snapshot, which covers the ${m.cutoff} UK cutoff over the default window.`,
    )
  const r = await fetch(`/snapshot/${file}`, { signal: request.signal })
  return new Response(await r.text(), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

/** Probe the API once at start-up; switch to the snapshot if it is not there within 8 s. */
export async function probeApi(baseUrl: string, onFallback: () => void): Promise<void> {
  if (useSnapshot.getState().active) return
  try {
    const r = await fetch(`${baseUrl}/api/v1/health`, { signal: AbortSignal.timeout(8000) })
    if (r.ok) return
  } catch {
    /* fall through */
  }
  if (await loadManifest()) {
    useSnapshot.getState().activate('api-unreachable')
    onFallback()
  }
}
