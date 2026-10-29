import { useEffect, useMemo } from 'react'
import { addDays } from '../lib/format'
import { useToasts } from '../lib/stores'
import { useViewParams } from '../lib/url-state'
import { type Scope, useSummary } from './queries'

/**
 * Resolve the full view from the URL plus what the server says is available:
 * the window actually used (it may be clamped) and the selected delivery day,
 * defaulting to the last day of the window.
 */
export function useView() {
  const { params, update } = useViewParams()
  const scope: Scope = useMemo(
    () => ({ from: params.from, to: params.to, cutoff: params.cutoff }),
    [params.from, params.to, params.cutoff],
  )
  const summary = useSummary(scope)
  const meta = summary.data?.meta
  const first = meta?.window_from ?? undefined
  const last = meta?.window_to ? addDays(meta.window_to, -1) : undefined
  const push = useToasts((s) => s.push)

  const outside = Boolean(params.day && first && last && (params.day < first || params.day > last))
  const day = params.day && !outside ? params.day : last

  useEffect(() => {
    if (outside && last) {
      push(`${params.day} is outside the data window; showing ${last}.`, 'warn')
      update({ day: last }, { replace: true })
    }
  }, [outside, last, params.day, push, update])

  return { params, update, scope, summary, meta, first, last, day }
}
