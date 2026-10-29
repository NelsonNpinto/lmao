import { expect, test } from '@playwright/test'

test('API down: the app falls back to the static snapshot (Break #20)', async ({ page }) => {
  // Only the API: a glob like **/api/** would also block Vite's /src/lib/api/ modules.
  await page.route(/\/api\/v1\//, (route) => route.abort('connectionrefused'))
  await page.goto('/?day=2026-01-15')
  await expect(page.getByText(/Offline snapshot: read-only January data/)).toBeVisible({ timeout: 15_000 })
  await expect(page.getByLabel(/^Typical miss \(MAE\):/)).toHaveText('2,042 MW')
  await expect(page.getByText(/plan on the forecast minus 4,140 MW/)).toBeVisible()

  // A view outside the snapshot says so instead of failing silently.
  await page.getByLabel('Cutoff', { exact: true }).selectOption('11:00')
  await expect(page.getByText(/Not in the offline snapshot/).first()).toBeVisible()
})
