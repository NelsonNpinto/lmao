import { parseParams } from './url-state'

const parse = (q: string) => parseParams(new URLSearchParams(q))

describe('parseParams', () => {
  it('fills defaults when the URL is empty', () => {
    expect(parse('')).toEqual({
      params: { from: undefined, to: undefined, day: undefined, cutoff: '09:00', policy: 'flat' },
      invalid: [],
    })
  })

  it('keeps valid values', () => {
    const { params, invalid } = parse('from=2026-01-02&to=2026-02-02&day=2026-01-15&cutoff=11:00&policy=conditional')
    expect(invalid).toEqual([])
    expect(params).toEqual({
      from: '2026-01-02',
      to: '2026-02-02',
      day: '2026-01-15',
      cutoff: '11:00',
      policy: 'conditional',
    })
  })

  it('drops malformed values and reports them (Break #23)', () => {
    const { params, invalid } = parse('cutoff=9am&day=2026-13-45&policy=yolo&from=yesterday')
    expect(params.cutoff).toBe('09:00')
    expect(params.day).toBeUndefined()
    expect(params.policy).toBe('flat')
    expect(invalid.sort()).toEqual(['cutoff', 'day', 'from', 'policy'])
  })

  it('rejects an inverted window', () => {
    const { params, invalid } = parse('from=2026-02-01&to=2026-01-01')
    expect(params.from).toBeUndefined()
    expect(params.to).toBeUndefined()
    expect(invalid).toEqual(['from', 'to'])
  })

  it('rejects out-of-range clock times', () => {
    expect(parse('cutoff=24:00').invalid).toEqual(['cutoff'])
    expect(parse('cutoff=23:59').params.cutoff).toBe('23:59')
  })
})

describe('parseDayQuery', async () => {
  const { parseDayQuery } = await import('./day-query')
  it('understands ISO, "15 jan" and "15/01"', () => {
    expect(parseDayQuery('2026-01-15', 2026)).toBe('2026-01-15')
    expect(parseDayQuery('15 Jan', 2026)).toBe('2026-01-15')
    expect(parseDayQuery('3 feb', 2026)).toBe('2026-02-03')
    expect(parseDayQuery('15/01', 2026)).toBe('2026-01-15')
    expect(parseDayQuery('accuracy', 2026)).toBeNull()
  })
})

describe('snapshotKey', async () => {
  const { snapshotKey } = await import('./snapshot')
  it('sorts and decodes params so the backend generator and the client agree', () => {
    expect(snapshotKey('http://h/api/v1/series?cutoff=09%3A00')).toBe('/api/v1/series?cutoff=09:00')
    expect(snapshotKey('http://h/api/v1/metrics/cutoff-sweep?days_before=1&cutoff=09:00&cutoffs=00%3A00%2C01%3A00')).toBe(
      '/api/v1/metrics/cutoff-sweep?cutoff=09:00&cutoffs=00:00,01:00&days_before=1',
    )
    expect(snapshotKey('http://h/api/v1/meta')).toBe('/api/v1/meta')
  })
})
