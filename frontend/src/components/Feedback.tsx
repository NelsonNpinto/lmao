import { CloudOff, Info, Loader2, TriangleAlert, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useMeta } from '../features/queries'
import { formatUkTime } from '../lib/format'
import { useSnapshot } from '../lib/snapshot'
import { useToasts } from '../lib/stores'

export function Toaster() {
  const { toasts, dismiss } = useToasts()
  return (
    <div className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="border-border bg-surface pointer-events-auto flex items-start gap-2 rounded-lg border p-3 text-sm shadow-lg"
          >
            {t.tone === 'info' ? (
              <Info className="text-muted mt-0.5 size-4 shrink-0" aria-hidden />
            ) : (
              <TriangleAlert className="text-warn mt-0.5 size-4 shrink-0" aria-hidden />
            )}
            <span className="flex-1">{t.message}</span>
            <button type="button" aria-label="Dismiss" onClick={() => dismiss(t.id)} className="text-muted hover:text-text">
              <X className="size-4" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}

/** Offline detection and the free-tier "waking the server" state (Break #20). */
export function StatusBanners() {
  const [online, setOnline] = useState(() => navigator.onLine)
  const meta = useMeta()
  const [slow, setSlow] = useState(false)
  const snapshot = useSnapshot()
  const qc = useQueryClient()

  useEffect(() => {
    const on = () => setOnline(true)
    const off = () => setOnline(false)
    window.addEventListener('online', on)
    window.addEventListener('offline', off)
    return () => {
      window.removeEventListener('online', on)
      window.removeEventListener('offline', off)
    }
  }, [])

  useEffect(() => {
    if (!meta.isPending) return
    const t = setTimeout(() => setSlow(true), 2500)
    return () => clearTimeout(t)
  }, [meta.isPending])

  if (snapshot.active)
    return (
      <Banner icon={<CloudOff className="text-warn size-4" aria-hidden />}>
        Offline snapshot: read-only January data saved {formatUkTime(snapshot.generatedAt)}, default 09:00 cutoff.
        {snapshot.reason === 'api-unreachable' && (
          <>
            {' '}The live API is unreachable.{' '}
            <button
              type="button"
              className="underline"
              onClick={() => {
                snapshot.deactivate()
                void qc.resetQueries()
              }}
            >
              Try live again
            </button>
          </>
        )}
      </Banner>
    )
  if (!online)
    return (
      <Banner icon={<CloudOff className="size-4" aria-hidden />}>
        You are offline. Showing the last data loaded; changes will refresh when you reconnect.
      </Banner>
    )
  if (meta.isPending && slow)
    return (
      <Banner icon={<Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />}>
        Waking the server… free-tier hosts sleep when idle; this takes up to 30 s.
      </Banner>
    )
  if (meta.isError)
    return (
      <Banner icon={<TriangleAlert className="text-warn size-4" aria-hidden />}>
        The API is unreachable ({meta.error.message}). Retrying…
      </Banner>
    )
  return null
}

function Banner({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div role="status" className="border-border bg-surface-2 flex items-center gap-2 border-b px-4 py-2 text-sm">
      {icon}
      <span>{children}</span>
    </div>
  )
}
