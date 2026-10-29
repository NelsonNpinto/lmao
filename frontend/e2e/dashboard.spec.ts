import { expect, test } from '@playwright/test'

test('dashboard: changing the cutoff changes the vintage and the KPIs', async ({ page }) => {
  await page.goto('/?day=2026-01-15')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Thu 15 Jan 2026')

  const mae = page.getByLabel(/^Typical miss \(MAE\):/)
  await expect(mae).toHaveText('2,042 MW')
  await expect(page.getByText(/vintage\s+14 Jan, 07:30 UK/)).toBeVisible()

  await page.getByLabel('Cutoff', { exact: true }).selectOption('11:00')
  await expect(page).toHaveURL(/cutoff=11%3A00|cutoff=11:00/)
  await expect(page.getByText(/vintage\s+14 Jan, 09:30 UK/)).toBeVisible()
  await expect(mae).toHaveText('2,016 MW')

  // Times are UK time even though this browser runs in Asia/Kolkata.
  await page.getByRole('button', { name: 'Show as table' }).click()
  await expect(page.getByRole('row').nth(1)).toContainText('00:00')
})

test('day explorer: keyboard steps between days', async ({ page }) => {
  await page.goto('/days/2026-01-21')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Wed 21 Jan 2026')
  await expect(page.getByText('used', { exact: true }).first()).toBeVisible()
  await page.keyboard.press(']')
  await expect(page).toHaveURL(/\/days\/2026-01-22/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Thu 22 Jan 2026')
  await page.keyboard.press('[')
  await expect(page).toHaveURL(/\/days\/2026-01-21/)
})

test('a malformed shared link falls back to defaults with one notice', async ({ page }) => {
  await page.goto('/?cutoff=9am&policy=conditional')
  await expect(page.getByText(/Ignored an invalid link parameter \(cutoff\)/)).toBeVisible()
  await expect(page).toHaveURL(/^[^?]*\?policy=conditional$/)
  await expect(page.getByLabel('Margin policy')).toHaveValue('conditional')
})

test('every page renders without a crash', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  for (const [path, heading] of [
    ['/accuracy', 'Forecast accuracy'],
    ['/cutoff', 'When should we decide?'],
    ['/replay?day=2026-01-21', 'Replay'],
    ['/findings', 'What the data says'],
    ['/data', 'Data and methods'],
  ] as const) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(heading)
  }
  expect(errors).toEqual([])
})
