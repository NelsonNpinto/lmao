import type { ReactNode } from 'react'

/** Themed tooltip body for Recharts' `content` prop: text tokens only, never series colours. */
export function TooltipBox({ title, rows }: { title: ReactNode; rows: [ReactNode, ReactNode][] }) {
  return (
    <div className="border-border bg-surface num rounded-md border px-2.5 py-1.5 text-xs shadow-lg">
      <div className="mb-0.5 font-medium">{title}</div>
      {rows.map(([k, v], i) => (
        <div key={i} className="flex justify-between gap-4">
          <span className="text-muted">{k}</span>
          <span>{v}</span>
        </div>
      ))}
    </div>
  )
}
