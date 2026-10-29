import clsx from 'clsx'
import type { ButtonHTMLAttributes, ReactNode } from 'react'

export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  id,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  id?: string
}) {
  return (
    <section
      id={id}
      className={clsx('border-border bg-surface min-w-0 rounded-xl border p-4', className)}
      aria-label={typeof title === 'string' ? title : undefined}
    >
      {(title || actions) && (
        <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold tracking-tight">{title}</h2>}
            {subtitle && <p className="text-muted mt-0.5 text-xs">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={clsx('skeleton rounded-md', className)} />
}

export function Button({
  className,
  variant = 'ghost',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'ghost' | 'solid' }) {
  return (
    <button
      type="button"
      className={clsx(
        'inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors disabled:opacity-40',
        variant === 'solid'
          ? 'bg-text text-bg hover:opacity-90'
          : 'border-border text-text hover:bg-surface-2 border',
        className,
      )}
      {...props}
    />
  )
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: 'neutral' | 'ok' | 'warn'
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium',
        tone === 'ok' && 'border-ok/40 text-ok',
        tone === 'warn' && 'border-warn/50 text-warn',
        tone === 'neutral' && 'border-border text-muted',
      )}
    >
      {children}
    </span>
  )
}

export const selectClass =
  'border-border bg-surface text-text h-8 rounded-md border px-2 text-xs focus-visible:outline-2'
