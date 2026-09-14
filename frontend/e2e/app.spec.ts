import { test, expect, type Page } from '@playwright/test'

// End-to-end against the real June deliveries: the UI must show corrected numbers
// and surface every planted defect, not just render.

const browserErrors: string[] = []

test.beforeEach(async ({ page }) => {
  browserErrors.length = 0
  page.on('pageerror', error => browserErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') browserErrors.push(message.text()) })
  await page.goto('/')
})

test.afterEach(() => {
  expect(browserErrors, 'no JavaScript or console errors').toEqual([])
})

const openTab = (page: Page, tabName: string) => page.getByRole('button', { name: tabName, exact: true }).click()

const healthRow = (page: Page, platform: string, weekLabel: string) =>
  page.locator('tr.h-row').filter({ hasText: platform }).filter({ hasText: weekLabel })

const usdToNumber = (text: string) => Number(text.replace(/[^0-9.]/g, ''))

test('overview lists the defects found in each platform', async ({ page }) => {
  await expect(page.getByText('Numbers you can trust.')).toBeVisible()
  await expect(page.locator('.ov-plat-card')).toHaveCount(3)
  await expect(page.getByText(/06-08 spend reported in cents/)).toBeVisible()
})

test('metrics show June spend with the Meta cents week corrected', async ({ page }) => {
  await openTab(page, 'Metrics')
  const totalSpendCard = page.locator('.kpi-card').filter({ hasText: 'Total Spend' })
  await expect(totalSpendCard.locator('.kpi-value')).toHaveText('$54,277.30')
  await expect(totalSpendCard).toContainText('13 campaigns')
  await expect(page.locator('tr.cam-row')).toHaveCount(13)
})

test('platform filter narrows campaigns and totals', async ({ page }) => {
  await openTab(page, 'Metrics')
  await expect(page.locator('tr.cam-row')).toHaveCount(13)
  await page.locator('.filters select').selectOption('Google Ads')
  await expect(page.locator('tr.cam-row')).toHaveCount(5)
  await expect(page.locator('.kpi-card').filter({ hasText: 'Total Spend' }).locator('.kpi-value')).toHaveText('$27,954.50')
})

test('spend traces back to source files and the rules applied to them', async ({ page }) => {
  await openTab(page, 'Metrics')
  await page.locator('tr.cam-row').filter({ hasText: 'Summer Sale' }).locator('.td-spend').click()

  const weekRows = page.locator('.trace-tbl tbody tr[class^="trace-row-"]')
  await expect(weekRows).toHaveCount(5)
  const centsWeek = weekRows.filter({ hasText: 'meta_ads_2026-06-08.csv' })
  await expect(centsWeek).toContainText('WARN')
  const centsWeekSpend = usdToNumber(await centsWeek.locator('.trace-spend').last().innerText())
  const nextWeekSpend  = usdToNumber(await weekRows.filter({ hasText: 'meta_ads_2026-06-15.csv' }).locator('.trace-spend').last().innerText())
  expect(centsWeekSpend).toBeLessThan(3 * nextWeekSpend)

  await expect(page.locator('.trace-rules')).toContainText('spend_usd: taken as USD')
  await expect(page.locator('.trace-lineage').filter({ hasText: 'Spend looks reported in cents' })).toHaveCount(1)
  // a table grows to fit its content, so measure the scroll container around the campaign table instead
  const traceFitsOnScreen = await page.locator('.tbl-wrap').evaluate(container => container.scrollWidth <= container.clientWidth)
  expect(traceFitsOnScreen, 'lineage text must not push the numeric columns off-screen').toBe(true)
})

test('data health summarizes every delivery slot', async ({ page }) => {
  await openTab(page, 'Data Health')
  await expect(page.locator('tr.h-row')).toHaveCount(15)
  await expect(page.locator('.hs-pass .h-stat-count')).toHaveText('7')
  await expect(page.locator('.hs-warn .h-stat-count')).toHaveText('7')
  await expect(page.locator('.hs-fail .h-stat-count')).toHaveText('1')
  await expect(healthRow(page, 'LinkedIn Ads', 'Jun 22, 2026')).toContainText('- missing -')
  await expect(healthRow(page, 'Google Ads', 'Jun 15, 2026')).toContainText('WARN')
  await expect(healthRow(page, 'Google Ads', 'Jun 1, 2026')).toContainText('35 / 43')
})

test('check report lists the exact affected lines', async ({ page }) => {
  await openTab(page, 'Data Health')

  await healthRow(page, 'Meta Ads', 'Jun 1, 2026').click()
  const checkReport = page.locator('.checks-row')
  await expect(checkReport).toContainText('35 rows received · 34 loaded · 1 excluded')
  await expect(checkReport).toContainText("line 23: App Install Push '06/31/2026' is not a valid date")
  await expect(checkReport).toContainText("line 12: 'brand awareness q2' -> 'Brand Awareness Q2'")
  await expect(checkReport).toContainText('App Install Push 2026-06-01')

  await healthRow(page, 'Meta Ads', 'Jun 8, 2026').click()
  await expect(checkReport).toContainText('Spend looks reported in cents')
  await expect(checkReport).toContainText('$480,070.00 -> $4,800.70')
})

test('re-ingest is idempotent from the UI', async ({ page }) => {
  await openTab(page, 'Data Health')
  const reingestButton = page.getByRole('button', { name: /Re-ingest/ })
  await reingestButton.click()
  await expect(reingestButton).toHaveText('↻ Re-ingest')
  await expect(page.locator('.error')).toHaveCount(0)
  await expect(page.locator('.hs-warn .h-stat-count')).toHaveText('7')
  await expect(page.locator('tr.h-row')).toHaveCount(15)
})
