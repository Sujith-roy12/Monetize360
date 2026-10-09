const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(require.resolve('playwright', {paths: [path.join(__dirname, '../frontend')]}));
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(process.argv[2] || 'http://127.0.0.1:5173');
    await page.getByText('Engine online', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Pricing studio', exact: true }).click();
    await page.getByLabel('Pricing product').selectOption('car_rental_standard');
    const response = page.waitForResponse(r => r.url().endsWith('/api/pricing/calculate') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Calculate price', exact: true }).click();
    const result = await (await response).json();
    assert.equal(Number(result.final_price), 14900);
    await page.getByText('Decision #' + result.decision_id, { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Decision history', exact: true }).click();
    await page.getByRole('button', { name: 'Replay', exact: true }).first().click();
    await page.getByText('Replay matched the original price and full trace.', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('Browser smoke passed: live calculate, rendered result, history, replay.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
