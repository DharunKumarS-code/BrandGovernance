import { test, expect } from '@playwright/test';
import path from 'path';

// Reuses the tiny PNG fixture pattern from the backend's own colour-analysis
// tests -- a plain solid-colour PNG is enough to prove the upload/display
// path works end-to-end.
test('New Submission: image upload renders as a blob URL and revokes it on navigation', async ({ page }) => {
  await page.addInitScript(() => {
    const originalRevoke = URL.revokeObjectURL.bind(URL);
    Object.defineProperty(window, '__revokedBlobUrls', { value: [] });
    URL.revokeObjectURL = (url: string) => {
      (window as unknown as { __revokedBlobUrls: string[] }).__revokedBlobUrls.push(url);
      originalRevoke(url);
    };
  });
  await page.goto('/submissions/new');
  await page.getByPlaceholder(/Nova Buds Pro/).fill('Visual Test Ad');

  const fixture = path.resolve(__dirname, 'fixtures', 'test-image.png');
  await page.locator('input[type="file"][accept*="image"]').setInputFiles(fixture);
  await page.getByRole('button', { name: 'Upload Image' }).click();

  await page.waitForURL(/\/submissions\/[a-f0-9]{24}$/, { timeout: 10_000 });
  await expect(page.getByRole('heading', { name: 'Visual Test Ad' })).toBeVisible();
  const image = page.locator('img[alt="Visual Test Ad"]');
  await expect(image).toBeVisible();
  await expect(image).toHaveAttribute('src', /^blob:/);
  const blobUrl = await image.getAttribute('src');
  await expect(page).not.toHaveURL(/image=/);
  await page.getByRole('link', { name: /Back to submissions/ }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __revokedBlobUrls: string[] }).__revokedBlobUrls)).toContain(blobUrl);

  await page.evaluate(() => localStorage.setItem('clarivue_access_token', 'expired-test-token'));
  await page.getByRole('row').filter({ hasText: 'Visual Test Ad' }).getByRole('link', { name: 'View' }).click();
  await expect(page.getByRole('img', { name: 'Visual Test Ad' })).toContainText('Image unavailable');
  await expect.poll(() => page.evaluate(() => localStorage.getItem('clarivue_access_token'))).toBeNull();
});
