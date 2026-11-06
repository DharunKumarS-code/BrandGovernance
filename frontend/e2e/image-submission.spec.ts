import { test, expect } from '@playwright/test';
import path from 'path';

// Reuses the tiny PNG fixture pattern from the backend's own colour-analysis
// tests -- a plain solid-colour PNG is enough to prove the upload/display
// path works end-to-end.
test('New Submission: image upload creates a submission and the image displays on its detail page', async ({ page }) => {
  await page.goto('/submissions/new');
  await page.getByPlaceholder(/Nova Buds Pro/).fill('Visual Test Ad');

  const fixture = path.resolve(__dirname, 'fixtures', 'test-image.png');
  await page.locator('input[type="file"][accept*="image"]').setInputFiles(fixture);
  await page.getByRole('button', { name: 'Upload Image' }).click();

  await page.waitForURL(/\/submissions\/[a-f0-9]{24}$/, { timeout: 10_000 });
  await expect(page.getByRole('heading', { name: 'Visual Test Ad' })).toBeVisible();
  await expect(page.locator('img[alt="Visual Test Ad"]')).toBeVisible();
});
