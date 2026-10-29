/**
 * The URL is the source of truth for window, cutoff, day and policy, so every
 * view is a shareable link and the back button works. Params are validated
 * with zod; anything malformed is dropped, the URL is repaired in place and a
 * single toast explains it (Break #23).
 */
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router'
import { z } from 'zod'
import { useToasts } from './stores'

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/).refine((s) => !Number.isNaN(Date.parse(s)))
const hhmm = z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/)

export const paramSchemas = {
  from: isoDate,
  to: isoDate,
  day: isoDate,
  cutoff: hhmm,
  policy: z.enum(['none', 'flat', 'conditional']),
} as const

export type ParamKey = keyof typeof paramSchemas
export const DEFAULT_CUTOFF = '09:00'
export const PRESET_CUTOFFS = ['07:00', '09:00', '11:00'] as const

export interface ViewParams {
  from?: string
  to?: string
  day?: string
  cutoff: string
  policy: 'none' | 'flat' | 'conditional'
}

/** Pure parser: valid params plus the names of the ones that were rejected. */
export function parseParams(sp: URLSearchParams): { params: ViewParams; invalid: ParamKey[] } {
  const invalid: ParamKey[] = []
  const pick = <K extends ParamKey>(k: K): z.infer<(typeof paramSchemas)[K]> | undefined => {
    const raw = sp.get(k)
    if (raw == null || raw === '') return undefined
    const r = paramSchemas[k].safeParse(raw)
    if (!r.success) invalid.push(k)
    return r.success ? (r.data as z.infer<(typeof paramSchemas)[K]>) : undefined
  }
  let from = pick('from')
  let to = pick('to')
  if (from && to && from >= to) {
    invalid.push('from', 'to')
    from = to = undefined
  }
  const params: ViewParams = {
    from,
    to,
    day: pick('day'),
    cutoff: pick('cutoff') ?? DEFAULT_CUTOFF,
    policy: pick('policy') ?? 'flat',
  }
  return { params, invalid }
}

export function useViewParams() {
  const [sp, setSp] = useSearchParams()
  const { params, invalid } = useMemo(() => parseParams(sp), [sp])
  const push = useToasts((s) => s.push)
  const warned = useRef(false)

  useEffect(() => {
    if (!invalid.length) return
    const next = new URLSearchParams(sp)
    invalid.forEach((k) => next.delete(k))
    setSp(next, { replace: true })
    if (!warned.current) {
      warned.current = true
      push(`Ignored an invalid link parameter (${[...new Set(invalid)].join(', ')}); using defaults.`, 'warn')
    }
  }, [invalid, sp, setSp, push])

  const update = useCallback(
    (patch: Partial<Record<ParamKey, string | undefined>>, opts?: { replace?: boolean }) => {
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev)
          for (const [k, v] of Object.entries(patch)) {
            if (v == null || v === '') next.delete(k)
            else next.set(k, v)
          }
          return next
        },
        { replace: opts?.replace },
      )
    },
    [setSp],
  )

  return { params, update }
}
