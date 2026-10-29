const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']

/** "2026-01-15", "15 jan", "15/01" -> ISO date within the window's year. */
export function parseDayQuery(q: string, year: number): string | null {
  const s = q.trim().toLowerCase()
  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (m) return `${m[1]}-${m[2]}-${m[3]}`
  m = s.match(/^(\d{1,2})\s*([a-z]{3})/)
  if (m && MONTHS.includes(m[2]!)) return `${year}-${String(MONTHS.indexOf(m[2]!) + 1).padStart(2, '0')}-${m[1]!.padStart(2, '0')}`
  m = s.match(/^(\d{1,2})\/(\d{1,2})$/)
  if (m) return `${year}-${m[2]!.padStart(2, '0')}-${m[1]!.padStart(2, '0')}`
  return null
}
