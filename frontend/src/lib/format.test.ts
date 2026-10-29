import {
  addDays,
  formatDeliveryDate,
  formatMW,
  formatPct,
  formatSignedMW,
  formatUkTime,
  ukDateOf,
} from './format'

describe('format', () => {
  it('formats MW with grouping and unit', () => {
    expect(formatMW(12345.6)).toBe('12,346 MW')
  })

  it('renders an em dash for null, NaN and Infinity', () => {
    expect(formatMW(null)).toBe('—')
    expect(formatMW(Number.NaN)).toBe('—')
    expect(formatPct(Number.POSITIVE_INFINITY)).toBe('—')
  })

  it('shows UK time even when the browser runs in IST', () => {
    // Browser-local (IST, UTC+5:30) would read 13:00 for 07:30Z.
    expect(new Date('2026-01-04T07:30:00Z').getHours()).toBe(13)
    // 07:30Z in January is 07:30 UK (GMT), 13:00 in India.
    expect(formatUkTime('2026-01-04T07:30:00Z')).toBe('04 Jan, 07:30 UK')
    // 07:30Z in June is 08:30 UK (BST).
    expect(formatUkTime('2026-06-04T07:30:00Z')).toBe('04 Jun, 08:30 UK')
  })
})

describe('date helpers', () => {
  it('does pure calendar arithmetic across month ends', () => {
    expect(addDays('2026-01-31', 1)).toBe('2026-02-01')
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28')
  })

  it('maps UTC instants to UK delivery dates, not browser-local ones', () => {
    // 20:00Z on 15 Jan is already 16 Jan in India but still 15 Jan in the UK.
    expect(ukDateOf('2026-01-15T20:00:00Z')).toBe('2026-01-15')
    // 23:30Z on 31 May is 1 Jun 00:30 BST.
    expect(ukDateOf('2026-05-31T23:30:00Z')).toBe('2026-06-01')
  })

  it('formats signed MW and delivery dates', () => {
    expect(formatSignedMW(1559)).toBe('+1,559 MW')
    expect(formatSignedMW(-387)).toBe('−387 MW')
    expect(formatDeliveryDate('2026-01-15')).toBe('Thu 15 Jan 2026')
    expect(formatDeliveryDate('2026-01-15', { weekday: false })).toBe('15 Jan 2026')
  })
})
