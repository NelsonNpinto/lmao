import { animate, useReducedMotion } from 'motion/react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { EM_DASH } from '../../lib/format'
import { Skeleton } from '../ui'

/** Counts up to ``value`` on change; renders the final value at once with reduced motion. */
export function AnimatedNumber({
  value,
  format,
}: {
  value: number | null | undefined
  format: (v: number | null | undefined) => string
}) {
  const reduce = useReducedMotion()
  const [shown, setShown] = useState<number | null | undefined>(value)
  const prev = useRef<number | null | undefined>(value)

  useEffect(() => {
    const from = prev.current
    prev.current = value
    if (reduce || value == null || from == null || !Number.isFinite(from)) {
      setShown(value)
      return
    }
    const controls = animate(from, value, {
      duration: 0.6,
      ease: 'easeOut',
      onUpdate: (v) => setShown(v),
    })
    return () => controls.stop()
  }, [value, reduce])

  return <>{shown == null ? EM_DASH : format(shown)}</>
}

export function KpiTile({
  label,
  value,
  format,
  hint,
  detail,
  loading,
  badge,
}: {
  label: string
  value: number | null | undefined
  format: (v: number | null | undefined) => string
  hint: string
  detail?: ReactNode
  loading?: boolean
  badge?: ReactNode
}) {
  return (
    <div className="border-border bg-surface flex min-w-0 flex-col gap-1 rounded-xl border p-3.5" title={hint}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-muted text-xs leading-tight font-medium">{label}</span>
        {badge}
      </div>
      {loading ? (
        <Skeleton className="h-7 w-28" />
      ) : (
        <span className="num text-xl font-semibold tracking-tight" aria-label={`${label}: ${format(value)}`}>
          <AnimatedNumber value={value} format={format} />
        </span>
      )}
      <span className="text-muted text-[11px] leading-snug">{loading ? <Skeleton className="h-3 w-36" /> : detail}</span>
    </div>
  )
}
