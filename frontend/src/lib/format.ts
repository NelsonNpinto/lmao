/**
 * The single place numbers and times are formatted for display (Break #15).
 * Values are rounded only here, never in data or exports. Times always render
 * in UK time and say so, whatever the browser's timezone (Break #9).
 */

export const UK_TZ = 'Europe/London'
export const EM_DASH = '—'

const fmt = (digits: number) =>
  new Intl.NumberFormat('en-GB', { maximumFractionDigits: digits, minimumFractionDigits: digits })

const ok = (v: number | null | undefined): v is number => v != null && Number.isFinite(v)

export function formatNumber(v: number | null | undefined, digits = 0): string {
  return ok(v) ? fmt(digits).format(v) : EM_DASH
}

export function formatMW(v: number | null | undefined): string {
  return ok(v) ? `${fmt(0).format(v)} MW` : EM_DASH
}

export function formatSignedMW(v: number | null | undefined): string {
  if (!ok(v)) return EM_DASH
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${fmt(0).format(Math.abs(v))} MW`
}

export function formatGWh(mwh: number | null | undefined, digits = 1): string {
  return ok(mwh) ? `${fmt(digits).format(mwh / 1000)} GWh` : EM_DASH
}

export function formatPct(v: number | null | undefined, digits = 1): string {
  return ok(v) ? `${fmt(digits).format(v)} %` : EM_DASH
}

export function formatHours(v: number | null | undefined): string {
  return ok(v) ? `${fmt(1).format(v)} h` : EM_DASH
}

const ukDateTime = new Intl.DateTimeFormat('en-GB', {
  timeZone: UK_TZ,
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})
const ukClock = new Intl.DateTimeFormat('en-GB', {
  timeZone: UK_TZ,
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

/** "04 Jan, 07:30 UK" */
export function formatUkTime(iso: string | null | undefined): string {
  return iso ? `${ukDateTime.format(new Date(iso))} UK` : EM_DASH
}

/** "07:30" in UK time (unlabelled, for axes and tables under a "UK time" header). */
export function formatUkClock(iso: string): string {
  return ukClock.format(new Date(iso))
}

const dateParts = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'UTC',
  weekday: 'short',
  day: '2-digit',
  month: 'short',
  year: 'numeric',
})

/** "Thu 15 Jan 2026" (or "15 Jan 2026") for a plain YYYY-MM-DD delivery date. */
export function formatDeliveryDate(day: string, opts: { weekday?: boolean } = {}): string {
  const [y, m, d] = day.split('-').map(Number)
  const parts = Object.fromEntries(
    dateParts.formatToParts(new Date(Date.UTC(y!, m! - 1, d!))).map((p) => [p.type, p.value]),
  )
  const core = `${parts.day} ${parts.month} ${parts.year}`
  return opts.weekday === false ? core : `${parts.weekday} ${core}`
}

/** Pure calendar arithmetic on YYYY-MM-DD strings. */
export function addDays(day: string, n: number): string {
  const [y, m, d] = day.split('-').map(Number)
  return new Date(Date.UTC(y!, m! - 1, d! + n)).toISOString().slice(0, 10)
}

/** UK delivery date (YYYY-MM-DD) of a UTC instant. */
export function ukDateOf(iso: string): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: UK_TZ }).format(new Date(iso))
}
