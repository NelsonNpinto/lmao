import { Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { NAV } from '../app/nav'
import { useView } from '../features/view'
import { parseDayQuery } from '../lib/day-query'
import { addDays } from '../lib/format'
import { useTheme } from '../lib/stores'
import { PRESET_CUTOFFS } from '../lib/url-state'

interface Item {
  id: string
  label: string
  hint: string
  run: () => void
}

/** Cmd/Ctrl+K: jump to pages and days, switch cutoff or theme. */
export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const navigate = useNavigate()
  const { search } = useLocation()
  const { update, first, last, day } = useView()
  const { setTheme } = useTheme()
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((o) => !o)
        setQ('')
        setActive(0)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (open) input.current?.focus()
  }, [open])

  const items = useMemo<Item[]>(() => {
    const close = (f: () => void) => () => {
      f()
      setOpen(false)
    }
    const all: Item[] = [
      ...NAV.map((n) => ({
        id: `nav${n.to}`,
        label: n.label,
        hint: 'Page',
        run: close(() => navigate({ pathname: n.to, search })),
      })),
      ...PRESET_CUTOFFS.map((c) => ({
        id: `cutoff${c}`,
        label: `Cutoff ${c} UK`,
        hint: 'Cutoff',
        run: close(() => update({ cutoff: c })),
      })),
      ...(['light', 'dark', 'system'] as const).map((t) => ({
        id: `theme-${t}`,
        label: `Theme: ${t}`,
        hint: 'Theme',
        run: close(() => setTheme(t)),
      })),
      { id: 'refresh', label: 'Refresh data from Elexon', hint: 'Action', run: close(() => navigate({ pathname: '/data', search })) },
    ]
    if (day) {
      all.push(
        { id: 'prev', label: `Previous day (${addDays(day, -1)})`, hint: 'Day', run: close(() => update({ day: addDays(day, -1) })) },
        { id: 'next', label: `Next day (${addDays(day, 1)})`, hint: 'Day', run: close(() => update({ day: addDays(day, 1) })) },
      )
    }
    const year = Number((first ?? '2026').slice(0, 4))
    const target = parseDayQuery(q, year)
    const inWindow = target && (!first || target >= first) && (!last || target <= last)
    const filtered = all.filter((i) => i.label.toLowerCase().includes(q.trim().toLowerCase()))
    return target && inWindow
      ? [
          {
            id: 'day',
            label: `Open ${target} in the day explorer`,
            hint: 'Day',
            run: close(() => {
              const sp = new URLSearchParams(search)
              sp.set('day', target)
              navigate({ pathname: `/days/${target}`, search: `?${sp}` })
            }),
          },
          ...filtered,
        ]
      : filtered
  }, [q, navigate, search, update, setTheme, day, first, last])

  if (!open) return null
  const choose = (i: number) => items[i]?.run()

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[15vh]" onMouseDown={() => setOpen(false)}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="border-border bg-surface w-full max-w-lg overflow-hidden rounded-xl border shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="border-border flex items-center gap-2 border-b px-3">
          <Search className="text-muted size-4" aria-hidden />
          <input
            ref={input}
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={items[active] ? `pal-${items[active]!.id}` : undefined}
            className="h-11 flex-1 bg-transparent text-sm outline-none"
            placeholder="Go to a page, a day (15 Jan), a cutoff…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              setActive(0)
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') setActive((a) => Math.min(items.length - 1, a + 1))
              else if (e.key === 'ArrowUp') setActive((a) => Math.max(0, a - 1))
              else if (e.key === 'Enter') choose(active)
              else if (e.key === 'Escape') setOpen(false)
              else return
              e.preventDefault()
            }}
          />
          <kbd className="text-muted text-[10px]">esc</kbd>
        </div>
        <ul id="palette-list" role="listbox" className="max-h-80 overflow-auto p-1">
          {items.length === 0 && <li className="text-muted px-3 py-2 text-sm">Nothing matches.</li>}
          {items.map((it, i) => (
            <li
              key={it.id}
              id={`pal-${it.id}`}
              role="option"
              aria-selected={i === active}
              className={`flex cursor-pointer items-center justify-between rounded-md px-3 py-2 text-sm ${i === active ? 'bg-surface-2' : ''}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => choose(i)}
            >
              <span>{it.label}</span>
              <span className="text-muted text-[11px]">{it.hint}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
