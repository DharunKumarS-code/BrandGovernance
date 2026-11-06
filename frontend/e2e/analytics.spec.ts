import { test, expect } from '@playwright/test';

test('Analytics: reachable from sidebar and renders without error', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Analytics', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Analytics' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Guideline Coverage' })).toBeVisible();
  const [scrollWidth, clientWidth] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1);
});
