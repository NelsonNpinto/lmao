import { expect, test } from '@playwright/test'

test('dashboard fits a phone screen without horizontal scrolling', async ({ page }) => {
  await page.goto('/?day=2026-01-15')
  await expect(page.getByLabel(/^Typical miss \(MAE\):/)).toHaveText('2,042 MW')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
