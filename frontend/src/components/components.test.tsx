import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MotionConfig } from 'motion/react'
import { useState } from 'react'
import type { Schemas } from '../lib/api/client'
import { formatMW } from '../lib/format'
import { toDelimited } from '../lib/plan'
import { CutoffSelect } from './CommandBar'
import { KpiTile } from './kpi/KpiTile'
import { PlanTable } from './tables/PlanTable'

const plan: Schemas['PlanOut'] = {
  delivery_date: '2026-01-15',
  policy: 'flat',
  margin_basis: 'walk_forward',
  history_days: 12,
  publish_time: '2026-01-14T07:30:00Z',
  forecast_total_mwh: 15834,
  wind_to_plan_total_mwh: 11266.5,
  rows: [
    {
      start_time: '2026-01-15T00:00:00Z',
      period: 1,
      forecast_mw: 15834,
      margin_mw: 4567.5,
      wind_to_plan_mw: 11266.5,
      wind_to_plan_mwh: 5633.25,
    },
    {
      start_time: '2026-01-15T00:30:00Z',
      period: 2,
      forecast_mw: null,
      margin_mw: null,
      wind_to_plan_mw: null,
      wind_to_plan_mwh: null,
    },
  ],
}

describe('KpiTile', () => {
  it('shows the final formatted value under reduced motion', () => {
    render(
      <MotionConfig reducedMotion="always">
        <KpiTile label="Typical miss" value={2041.96} format={formatMW} hint="h" detail="d" />
      </MotionConfig>,
    )
    expect(screen.getByLabelText('Typical miss: 2,042 MW')).toHaveTextContent('2,042 MW')
  })

  it('renders an em dash for a missing value', () => {
    render(<KpiTile label="Skill" value={null} format={formatMW} hint="h" />)
    expect(screen.getByLabelText('Skill: —')).toHaveTextContent('—')
  })
})

describe('PlanTable', () => {
  it('rounds only for display and shows UK times in an IST browser', () => {
    render(<PlanTable plan={plan} />)
    const first = screen.getByRole('row', { name: /00:00/ })
    expect(first).toHaveTextContent('15,834')
    expect(first).toHaveTextContent('4,568')
    expect(first).toHaveTextContent('11,267')
    expect(screen.getByRole('row', { name: /00:30/ })).toHaveTextContent('—')
    expect(screen.getByText(/days\)/)).toHaveTextContent('12 days')
  })

  it('exports raw, unrounded values', () => {
    const tsv = toDelimited(plan, '\t').split('\n')
    expect(tsv[0]).toBe('Period\tUK time\tForecast MW\tMargin MW\tWind to plan MW\tWind to plan MWh')
    expect(tsv[1]).toBe('1\t00:00\t15834\t4567.5\t11266.5\t5633.25')
    expect(tsv[2]).toBe('2\t00:30\t\t\t\t')
  })
})

describe('CutoffSelect', () => {
  function Harness() {
    const [v, setV] = useState('09:00')
    return (
      <>
        <CutoffSelect value={v} onChange={setV} />
        <output>{v}</output>
      </>
    )
  }

  it('switches presets and reveals a custom time input', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.selectOptions(screen.getByLabelText('Cutoff'), '11:00')
    expect(screen.getByRole('status')).toHaveTextContent('11:00')
    expect(screen.queryByLabelText(/Custom cutoff/)).toBeNull()
    await user.selectOptions(screen.getByLabelText('Cutoff'), 'custom')
    expect(screen.getByLabelText(/Custom cutoff/)).toBeInTheDocument()
  })
})
