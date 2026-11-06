import { test, expect } from '@playwright/test';

const SHOTS = 'E:/claurvie/playwright-reports/screenshots';

test('Mobile: dashboard renders without horizontal scroll, hamburger menu opens/closes/navigates', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/07-mobile-dashboard.png`, fullPage: true });

  const [scrollWidth, clientWidth] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    document.documentElement.clientWidth,
  ]);
  expect(scrollWidth, 'mobile dashboard should not cause horizontal scroll').toBeLessThanOrEqual(clientWidth + 1);

  // The desktop sidebar is `hidden lg:flex` -- present in the DOM but not
  // visible at this viewport.
  await expect(page.locator('aside').first()).toBeHidden();

  await page.getByRole('button', { name: 'Open navigation menu' }).click();
  await page.screenshot({ path: `${SHOTS}/08-mobile-sidebar-open.png`, fullPage: true });
  await expect(page.getByRole('link', { name: 'Submissions', exact: true })).toBeVisible();

  await page.getByRole('link', { name: 'Submissions', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Submissions' })).toBeVisible();
  // The off-canvas panel should auto-close after navigating.
  await expect(page.getByRole('button', { name: 'Close navigation menu' })).toBeHidden();

  const [sw2, cw2] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(sw2).toBeLessThanOrEqual(cw2 + 1);
});
