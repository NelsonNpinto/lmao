import { test } from '@playwright/test'

// Run with `npm run screenshots` (excluded from the smoke run). Writes docs/screenshots/*.png.
const OUT = '../docs/screenshots'

const shots: [string, string, 'dark' | 'light'][] = [
  ['dashboard', '/?day=2026-01-21', 'dark'],
  ['accuracy', '/accuracy', 'dark'],
  ['cutoff', '/cutoff', 'dark'],
  ['day-explorer', '/days/2026-01-21', 'dark'],
  ['replay', '/replay?day=2026-01-21', 'dark'],
  ['findings', '/findings', 'light'],
]

for (const [name, path, scheme] of shots) {
  test(`@screenshots ${name}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
    await page.setViewportSize({ width: 1440, height: 960 })
    await page.goto(path)
    await page.getByRole('heading', { level: 1 }).waitFor()
    if (name === 'replay') await page.getByRole('button', { name: 'Reveal' }).click()
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(800)
    await page.screenshot({ path: `${OUT}/${name}.png` })
  })
}
