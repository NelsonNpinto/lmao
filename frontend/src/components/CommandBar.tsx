import { ChevronLeft, ChevronRight, Download, Info, Monitor, Moon, Sun } from 'lucide-react'
import { useState } from 'react'
import { exportUrl, useDayVintages } from '../features/queries'
import { useView } from '../features/view'
import { addDays, formatDeliveryDate, formatUkTime } from '../lib/format'
import { useSnapshot } from '../lib/snapshot'
import { type Theme, useTheme } from '../lib/stores'
import { PRESET_CUTOFFS } from '../lib/url-state'
import { Button, selectClass } from './ui'

export function CutoffSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const isPreset = (PRESET_CUTOFFS as readonly string[]).includes(value)
  const [custom, setCustom] = useState(!isPreset)
  return (
    <div className="flex items-center gap-1.5">
      <label htmlFor="cutoff" className="text-muted text-xs">
        Cutoff
      </label>
      <select
        id="cutoff"
        className={selectClass}
        value={custom ? 'custom' : value}
        onChange={(e) => {
          if (e.target.value === 'custom') return setCustom(true)
          setCustom(false)
          onChange(e.target.value)
        }}
      >
        {PRESET_CUTOFFS.map((c) => (
          <option key={c} value={c}>
            {c} UK, D-1
          </option>
        ))}
        <option value="custom">Custom…</option>
      </select>
      {custom && (
        <input
          aria-label="Custom cutoff (UK time)"
          type="time"
          step={900}
          className={selectClass}
          value={value}
          onChange={(e) => e.target.value && onChange(e.target.value)}
        />
      )}
    </div>
  )
}

const THEMES: { id: Theme; icon: typeof Sun; label: string }[] = [
  { id: 'system', icon: Monitor, label: 'System theme' },
  { id: 'light', icon: Sun, label: 'Light theme' },
  { id: 'dark', icon: Moon, label: 'Dark theme' },
]

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const i = THEMES.findIndex((t) => t.id === theme)
  const current = THEMES[i] ?? THEMES[0]!
  const next = THEMES[(i + 1) % THEMES.length]!
  const Icon = current.icon
  return (
    <Button aria-label={`${current.label}. Switch to ${next.label.toLowerCase()}`} title={current.label} onClick={() => setTheme(next.id)}>
      <Icon className="size-4" aria-hidden />
    </Button>
  )
}

export function CommandBar() {
  const { params, update, scope, meta, first, last, day } = useView()
  const vintages = useDayVintages(scope, day)
  const v = vintages.data?.data
  const snapshot = useSnapshot((st) => st.active)

  return (
    <div className="border-border bg-bg/90 sticky top-0 z-20 flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-2 backdrop-blur">
      <div className="flex items-center gap-1.5 text-xs">
        <span className="text-muted">Window</span>
        <span className="num">
          {first && last ? `${formatDeliveryDate(first, { weekday: false })} – ${formatDeliveryDate(last, { weekday: false })}` : '…'}
        </span>
        <span
          className="text-muted inline-flex cursor-help"
          tabIndex={0}
          role="img"
          aria-label="About the study window"
          title={
            'Default: delivery days 2 Jan to 1 Feb 2026, i.e. the days bought by decisions made on 1-31 January (each decision is for the next day). ' +
            (meta?.clamped ? 'Trimmed to the data available.' : '')
          }
        >
          <Info className="size-3.5" aria-hidden />
        </span>
      </div>

      <div className="flex items-center gap-1" role="group" aria-label="Delivery day">
        <Button aria-label="Previous day" disabled={!day || !first || day <= first} onClick={() => day && update({ day: addDays(day, -1) })}>
          <ChevronLeft className="size-4" aria-hidden />
        </Button>
        <input
          type="date"
          aria-label="Delivery day"
          className={selectClass + ' num'}
          min={first}
          max={last}
          value={day ?? ''}
          onChange={(e) => e.target.value && update({ day: e.target.value })}
        />
        <Button aria-label="Next day" disabled={!day || !last || day >= last} onClick={() => day && update({ day: addDays(day, 1) })}>
          <ChevronRight className="size-4" aria-hidden />
        </Button>
      </div>

      <CutoffSelect value={params.cutoff} onChange={(c) => update({ cutoff: c })} />

      <p className="text-muted min-w-0 text-xs" aria-live="polite">
        {v?.selected_publish_time ? (
          <>
            As of <span className="text-text num">{formatUkTime(v.cutoff)}</span>: vintage{' '}
            <span className="text-text num">{formatUkTime(v.selected_publish_time)}</span>
          </>
        ) : v ? (
          'No vintage was published before this cutoff.'
        ) : null}
      </p>

      <div className="ml-auto flex items-center gap-2">
        {snapshot ? (
          <span className="text-muted text-xs" title="Exports need the live API">
            Export unavailable offline
          </span>
        ) : (
          (['csv', 'xlsx'] as const).map((f) => (
            <a
              key={f}
              className="border-border hover:bg-surface-2 inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium"
              href={exportUrl(scope, f)}
              download
            >
              {f === 'csv' && <Download className="size-3.5" aria-hidden />}
              {f.toUpperCase()}
            </a>
          ))
        )}
        <ThemeToggle />
      </div>
    </div>
  )
}
