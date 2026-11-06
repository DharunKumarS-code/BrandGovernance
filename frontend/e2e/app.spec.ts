import { test, expect, type Page } from '@playwright/test';
import path from 'path';

const SHOTS = 'E:/claurvie/playwright-reports/screenshots';
const FIXTURE_PDF = path.resolve('E:/claurvie/playwright-reports/fixtures/test-guideline.pdf');

async function actAs(page: Page, namePattern: RegExp) {
  // The "Acting as" <select> isn't programmatically associated with its
  // <label> (no htmlFor/id) -- found during this test pass, see the final
  // report. Falling back to a positional locator: the second <select>
  // inside the (desktop) sidebar <aside>.
  const userSelect = page.locator('aside select').nth(1);
  const optionValue = await userSelect.locator('option').filter({ hasText: namePattern }).first().getAttribute('value');
  if (!optionValue) throw new Error(`actAs: no "Acting as" option matched ${namePattern}`);
  await userSelect.selectOption(optionValue);
  await page.waitForTimeout(300); // let the header/context switch settle
}

async function createAndSubmit(page: Page, title: string, content: string): Promise<string> {
  await page.goto('/submissions/new');
  await page.getByPlaceholder(/Nova Buds Pro/).fill(title);
  await page.getByPlaceholder(/Write or paste/).fill(content);
  await page.getByRole('button', { name: 'Submit for Review' }).click();
  await page.waitForURL(/\/submissions\/[a-f0-9]{24}$/, { timeout: 10_000 });
  return page.url().split('/submissions/')[1];
}

test.describe.serial('Clarivue AI end-to-end (desktop)', () => {
  let submissionApprove: string;
  let submissionChanges: string;
  let submissionReject: string;

  test('1. Dashboard loads with summary cards and Refresh works', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await expect(page.getByText('Total').first()).toBeVisible();
    await expect(page.getByText('Open Issues Detected')).toBeVisible();
    await expect(page.getByText('Review Overview')).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/01-dashboard.png`, fullPage: true });

    const refreshBtn = page.getByRole('button', { name: /Refresh/ });
    await refreshBtn.click();
    // The refresh can complete faster than a polled assertion can catch
    // the transient "Refreshing..." label (a genuinely good sign -- it's
    // a local backend), so don't assert on that moment. Confirm the
    // button is back to its normal, enabled state afterward instead.
    await expect(refreshBtn).toBeEnabled({ timeout: 10_000 });
    await expect(page.getByText('Total').first()).toBeVisible();
  });

  test('2. Sidebar navigation reaches every page with no horizontal scroll', async ({ page }) => {
    await page.goto('/');
    const stops: [string, string][] = [
      ['Guideline Documents', 'Guideline Documents'],
      ['Brand Facts', 'Brand Facts'],
      ['Terminology', 'Terminology'],
      ['Claim Policies', 'Claim Policies'],
      ['Logos & Colours', 'Logos & Colours'],
      ['Submissions', 'Submissions'],
      ['Dashboard', 'Dashboard'],
    ];
    for (const [navLabel, heading] of stops) {
      await page.getByRole('link', { name: navLabel, exact: true }).click();
      await expect(page.getByRole('heading', { name: heading })).toBeVisible();
      const [scrollWidth, clientWidth] = await page.evaluate(() => [
        document.documentElement.scrollWidth,
        document.documentElement.clientWidth,
      ]);
      expect(scrollWidth, `${navLabel} should not cause horizontal scroll`).toBeLessThanOrEqual(clientWidth + 1);
    }
  });

  test('3. Brand Guidelines: page loads and PDF upload works', async ({ page }) => {
    await page.goto('/guidelines');
    await expect(page.getByRole('heading', { name: 'Guideline Documents' })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/04-guidelines-before-upload.png`, fullPage: true });

    await page.locator('input[type="file"]').setInputFiles(FIXTURE_PDF);
    await page.getByRole('button', { name: 'Upload' }).click();
    await expect(page.getByText(/Uploaded ".*" successfully/)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('test-guideline.pdf').first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/04-guidelines-after-upload.png`, fullPage: true });
  });

  test('4. Brand Facts page loads', async ({ page }) => {
    await page.goto('/facts');
    await expect(page.getByRole('heading', { name: 'Brand Facts' })).toBeVisible();
    // Not hardcoded to the original seed.py fixtures -- the live demo org's
    // brand facts have since been customised (now "Kinetra Pulse Run 3"),
    // so assert against whatever the table actually shows instead of a
    // stale assumption.
    await expect(page.locator('table tbody tr').first()).toBeVisible();
  });

  test('5. Terminology page loads', async ({ page }) => {
    await page.goto('/terminology');
    await expect(page.getByRole('heading', { name: 'Terminology' })).toBeVisible();
  });

  test('6. Claim Policies page loads', async ({ page }) => {
    await page.goto('/claim-policies');
    await expect(page.getByRole('heading', { name: 'Claim Policies' })).toBeVisible();
  });

  test('7. Brand Assets page loads', async ({ page }) => {
    await page.goto('/assets');
    await expect(page.getByRole('heading', { name: 'Logos & Colours' })).toBeVisible();
  });

  test('8. New Submission: create three test ads as the creator', async ({ page }) => {
    await page.goto('/');
    await actAs(page, /Priya Nair/);

    await page.goto('/submissions/new');
    await page.screenshot({ path: `${SHOTS}/03-new-submission.png`, fullPage: true });

    // Content matched to the CURRENT live demo org's governance data
    // (brand facts/terminology/claim policies were customised to
    // "Kinetra Pulse Run 3" at some point -- discovered mid-run, see the
    // final report -- so the original Nova Electronics seed assumptions
    // don't hold any more).
    submissionApprove = await createAndSubmit(
      page,
      'Playwright Test Ad - Approve Path',
      'The Kinetra Pulse Run 3 is the lightest running shoe in its class, weighing just 245 grams.',
    );
    submissionChanges = await createAndSubmit(
      page,
      'Playwright Test Ad - Changes Requested Path',
      'Introducing the Kinetra Pulse Run 3 with incredible Flex Core cushioning.',
    );
    submissionReject = await createAndSubmit(
      page,
      'Playwright Test Ad - Reject Path',
      'The #1 running shoe on the market, guaranteed to improve your time.',
    );

    expect(submissionApprove).toMatch(/^[a-f0-9]{24}$/);
    expect(submissionChanges).toMatch(/^[a-f0-9]{24}$/);
    expect(submissionReject).toMatch(/^[a-f0-9]{24}$/);
  });

  test('9. Submission details: AI analysis, findings, evidence and suggestion', async ({ page }) => {
    await page.goto(`/submissions/${submissionApprove}`);
    await expect(page.getByRole('button', { name: 'Analyze Submission' })).toBeVisible();

    // Real Gemini call -- generous timeout.
    await page.getByRole('button', { name: 'Analyze Submission' }).click();
    await expect(page.getByText(/Analysis complete/)).toBeVisible({ timeout: 40_000 });
    await page.screenshot({ path: `${SHOTS}/05-ai-findings.png`, fullPage: true });

    const expandButtons = page.getByRole('button', { name: /View evidence/ });
    const findingCount = await expandButtons.count();
    expect(findingCount, "the planted 'lightest' claim should produce at least one finding").toBeGreaterThan(0);

    await expandButtons.first().click();
    await expect(page.getByText(/Evidence/).first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/05-ai-findings-evidence.png`, fullPage: true });

    const generateBtn = page.getByRole('button', { name: 'Generate suggestion' });
    if (await generateBtn.count() > 0) {
      await generateBtn.first().click();
      // "Suggested Correction" is rendered unconditionally once a
      // correction exists, whether or not the model produced an actual
      // replacement span -- more robust than matching specific wording,
      // which varies with what the LLM actually said.
      await expect(page.getByText('Suggested Correction')).toBeVisible({ timeout: 20_000 });
      await page.screenshot({ path: `${SHOTS}/05-ai-findings-suggestion.png`, fullPage: true });
    }
  });

  test('10. Reviewer workflow: approve', async ({ page }) => {
    await page.goto('/');
    await actAs(page, /Jordan Lee/);
    await page.goto(`/submissions/${submissionApprove}`);
    await expect(page.getByRole('heading', { name: 'Review Decision' })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/06-reviewer-workflow.png`, fullPage: true });

    await page.getByPlaceholder(/Review comment/).fill('Looks compliant overall, approving.');
    await page.getByRole('button', { name: 'Approve' }).click();
    await expect(page.getByText('Submission approved.')).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: `${SHOTS}/06-reviewer-approved.png`, fullPage: true });
  });

  test('11. Reviewer workflow: request changes, creator resubmits, reviewer approves', async ({ page }) => {
    await page.goto('/');
    await actAs(page, /Jordan Lee/);
    await page.goto(`/submissions/${submissionChanges}`);
    await page.getByPlaceholder(/Review comment/).fill("Please use 'FlexCore foam' -- 'Flex Core' is a restricted variant.");
    await page.getByRole('button', { name: 'Request Changes' }).click();
    await expect(page.getByText(/Changes requested/)).toBeVisible({ timeout: 10_000 });

    await actAs(page, /Priya Nair/);
    await page.goto(`/submissions/${submissionChanges}`);
    await page.getByRole('button', { name: 'Edit content' }).click();
    await page.locator('textarea').fill('Introducing the Kinetra Pulse Run 3 with incredible FlexCore foam cushioning.');
    await page.getByRole('button', { name: 'Save as New Revision' }).click();
    await expect(page.getByText(/New revision created/)).toBeVisible({ timeout: 10_000 });
    await page.getByRole('button', { name: 'Submit' }).click();
    await expect(page.getByText('Submission submitted.')).toBeVisible({ timeout: 10_000 });

    await actAs(page, /Jordan Lee/);
    await page.goto(`/submissions/${submissionChanges}`);
    await page.getByPlaceholder(/Review comment/).fill('Fixed, approving now.');
    await page.getByRole('button', { name: 'Approve' }).click();
    await expect(page.getByText('Submission approved.')).toBeVisible({ timeout: 10_000 });
  });

  test('12. Reviewer workflow: reject', async ({ page }) => {
    await page.goto('/');
    await actAs(page, /Jordan Lee/);
    await page.goto(`/submissions/${submissionReject}`);
    await page.getByPlaceholder(/Review comment/).fill('Unsupported superlative claim and a banned guarantee.');
    await page.getByRole('button', { name: 'Reject' }).click();
    await expect(page.getByText('Submission rejected.')).toBeVisible({ timeout: 10_000 });
  });
});
