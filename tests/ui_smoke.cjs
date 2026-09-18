/* Run against the static server: node tests/ui_smoke.cjs.
   With the Codex runtime, set NODE_PATH=$CODEX_PRIMARY_RUNTIME_NODE_MODULES.
   Screenshots are review artifacts; assertions cover behavior and data meaning. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const expect = require('playwright/test').expect.configure({ timeout: 15000 });

const root = path.join(__dirname, '..');
const read = file => JSON.parse(fs.readFileSync(path.join(root, file), 'utf8'));
const master = read('data/commodities.json');
const dashboard = read('data/dashboard.json');
const source = read('data/source_status.json');
const baseURL = process.env.UI_BASE_URL || 'http://127.0.0.1:8000/';
const artifacts = path.resolve(process.env.UI_ARTIFACTS || path.join(root, 'ui-artifacts'));
const failures = [];
const checks = [];
let page;

function monitor(target) {
  target.setDefaultTimeout(15000);
  target.on('pageerror', error => failures.push(error.message));
  target.on('console', message => {
    if (message.type() === 'error') failures.push(message.text());
  });
}

async function ready(target) {
  await expect(target.locator('#as-of')).not.toHaveText(/Loading|Unavailable/);
  await expect(target.locator('.commodity-card')).toHaveCount(master.commodities.length);
}

async function view(name, target = page) {
  await target.locator(`.primary-nav [data-view="${name}"]`).click();
  await expect(target.locator(`#${name}-view`)).toBeVisible();
}

async function screenshot(name, target = page, fullPage = false) {
  await target.screenshot({ path: path.join(artifacts, `${name}.png`), fullPage });
}

async function check(name, action) {
  await action();
  checks.push(name);
  console.log(`PASS ${name}`);
}

async function openCommodity(id, target = page) {
  await view('commodities', target);
  const button = target.locator(`.intelligence-button[data-commodity-id="${id}"]`);
  await button.click();
  await expect(target.locator('#intel-body')).toBeVisible();
  await expect(target.locator('#intel-title')).toHaveText(master.commodities.find(item => item.id === id).name);
}

async function chartKeyboard(targetId, target = page) {
  const chart = target.locator(`#${targetId}`);
  const slider = chart.locator('.chart-frame[role="slider"]');
  await expect(slider).toBeVisible();
  const max = Number(await slider.getAttribute('aria-valuemax'));
  assert(max > 1, `${targetId} should contain monthly observations`);
  await slider.press('Home');
  await expect(slider).toHaveAttribute('aria-valuenow', '1');
  const first = await chart.locator('.chart-readout-period').textContent();
  await slider.press('End');
  await expect(slider).toHaveAttribute('aria-valuenow', String(max));
  await expect(chart.locator('.chart-readout-period')).not.toHaveText(first);
  await expect(chart.locator('.chart-readout-value')).toHaveCount(2);
  for (const value of await chart.locator('.chart-readout-value').allTextContents()) {
    assert(value.includes('$'), `${targetId} must show a USD value for both latest series`);
  }
  await slider.press('ArrowLeft');
  await expect(slider).toHaveAttribute('aria-valuenow', String(max - 1));
  await slider.press('ArrowRight');
  await expect(slider).toHaveAttribute('aria-valuenow', String(max));
}

async function waitForServer() {
  for (let attempt = 0; attempt < 40; attempt++) {
    try { if ((await fetch(baseURL)).ok) return; } catch { /* Server may still be starting. */ }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Static server did not become ready at ${baseURL}`);
}

(async () => {
  fs.mkdirSync(artifacts, { recursive: true });
  await waitForServer();
  const browser = await chromium.launch({ headless: true });
  try {
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    monitor(page);
    await page.goto(baseURL);
    await ready(page);
    await screenshot('desktop-overview', page, true);
    await check('navigation restores the initial overview with browser Back', async () => {
      await view('commodities');
      await screenshot('desktop-commodities');
      await page.goBack();
      await expect(page.locator('#overview-view')).toBeVisible();
      await expect(page.locator('.primary-nav [data-view="overview"]')).toHaveAttribute('aria-current', 'page');
    });
    await check('source deep link shows separate release and monitor dates', async () => {
      await page.goto(`${baseURL}#sources`);
      await ready(page);
      await expect(page.locator('#sources-view')).toBeVisible();
      await expect(page.locator('#source-data-available')).toHaveText(source.data_available);
      await expect(page.locator('#source-final')).toHaveText(source.final_through);
      await expect(page.locator('#source-revised')).toHaveText(source.revised_final_through);
      await expect(page.locator('#source-checked-at')).toContainText('UTC');
      await expect(page.locator('#source-warning')).toHaveText(source.classification_warning);
      await screenshot('desktop-methodology', page, true);
    });
    await check('fast data still loads when the shared intelligence script arrives late', async () => {
      const delayedPage = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
      monitor(delayedPage);
      await delayedPage.route('**/assets/js/intelligence.js', async route => {
        await new Promise(resolve => setTimeout(resolve, 500));
        await route.continue();
      });
      await delayedPage.route(/\/data\/(commodities|dashboard|source_status)\.json$/, route => {
        const file = new URL(route.request().url()).pathname.split('/').at(-1);
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(read(`data/${file}`)) });
      });
      await delayedPage.goto(baseURL);
      await ready(delayedPage);
      await expect(delayedPage.locator('#fatal')).toBeHidden();
      await expect(delayedPage.locator('#portfolio-history-chart .chart-frame')).toBeVisible();
      await delayedPage.close();
    });
    await check('search, combined filters, empty state, reset and sorting', async () => {
      await view('commodities');
      await page.locator('#search').fill('2709');
      await expect(page.locator('.commodity-card')).toHaveCount(1);
      await expect(page.locator('.commodity-name')).toHaveText('Crude Oil');
      await page.locator('#category').selectOption('Clean Energy');
      await expect(page.locator('.empty-state')).toContainText('No commodities found');
      await page.locator('#empty-reset').click();
      await expect(page.locator('.commodity-card')).toHaveCount(master.commodities.length);
      await expect(page.locator('#search')).toBeFocused();
      await page.locator('#risk-filter').selectOption('high');
      await expect(page.locator('.commodity-card')).toHaveCount(dashboard.commodities.filter(item => item.dependency?.risk === 'high').length);
      await page.locator('#risk-filter').selectOption('');
      await page.locator('#sort').selectOption('exports');
      const topExport = [...dashboard.commodities].sort((a, b) => b.exports - a.exports)[0].name;
      await expect(page.locator('.commodity-name').first()).toHaveText(topExport);
      await page.locator('#sort').selectOption('dependency');
      const topDependency = [...dashboard.commodities].sort((a, b) => b.dependency.score - a.dependency.score)[0].name;
      await expect(page.locator('.commodity-name').first()).toHaveText(topDependency);
      await page.locator('#reset-filters').click();
      await expect(page.locator('#sort')).toHaveValue('imports');
      await expect(page.locator('#reset-filters')).toBeHidden();
    });
    await check('page layouts stay within the viewport at mobile, tablet and desktop widths', async () => {
      for (const width of [320, 390, 768, 1440]) {
        await page.setViewportSize({ width, height: width < 600 ? 844 : 1000 });
        for (const name of ['overview', 'commodities', 'sources']) {
          await view(name);
          const extent = await page.evaluate(() => ({ actual: document.documentElement.scrollWidth, viewport: window.innerWidth }));
          assert(extent.actual <= extent.viewport + 1, `${name} overflows at ${width}px: ${JSON.stringify(extent)}`);
          if (width === 390) await screenshot(`mobile-${name}`, page, name !== 'commodities');
        }
      }
    });
    await check('portfolio chart keyboard and selected-range totals work together', async () => {
      await view('overview');
      await chartKeyboard('portfolio-history-chart');
      await page.locator('#portfolio-range').selectOption('12');
      await expect(page.locator('#portfolio-history-kpis')).toContainText('12 months');
      await expect(page.locator('#portfolio-history-chart .chart-frame')).toHaveAttribute('aria-valuemax', '12');
      const annualRows = page.locator('#portfolio-annual-table-body tr');
      const years = new Set(dashboard.monthly.slice(-12).map(row => row.period.slice(0, 4)));
      await expect(annualRows).toHaveCount(years.size);
      await page.locator('#portfolio-range').selectOption('all');
    });
    await check('commodity detail restores focus and exposes both historical charts', async () => {
      await openCommodity('crude_oil');
      await expect(page.locator('#commodity-browser')).toBeHidden();
      await chartKeyboard('intel-trade-chart');
      await chartKeyboard('intel-country-chart');
      await page.locator('#intel-title').scrollIntoViewIfNeeded();
      await screenshot('desktop-intelligence');
      await page.locator('#intel-month').selectOption({ index: 1 });
      await expect(page.locator('#intel-country-table-body tr').first()).toBeVisible();
      await page.locator('#intel-country').selectOption({ index: 1 });
      await chartKeyboard('intel-country-chart');
      await page.locator('#intel-close').click();
      await expect(page.locator('#commodity-browser')).toBeVisible();
      await expect(page.locator('.intelligence-button[data-commodity-id="crude_oil"]')).toBeFocused();
    });
    await check('mixed battery quantities remain explicitly unavailable', async () => {
      await openCommodity('batteries');
      await expect(page.locator('#intel-unit-values')).toContainText(/mixed physical units/i);
      await expect(page.locator('#intel-unit-values')).toContainText('KGS');
      await expect(page.locator('#intel-unit-values')).toContainText('NOS');
      await page.locator('#intel-close').click();
    });
    await check('classification gaps remain missing rather than zero trade', async () => {
      await openCommodity('solar_pv');
      await page.locator('#intel-range').selectOption('all');
      const chart = page.locator('#intel-trade-chart');
      const slider = chart.locator('.chart-frame');
      await slider.press('Home');
      const solar = read('data/intelligence/solar_pv.json');
      const first = solar.monthly[0].period.split('-').map(Number);
      const gap = solar.coverage.history_gaps.find(row => row.period === '2022-02');
      assert(gap, 'The solar classification gap fixture must exist');
      const steps = (2022 - first[0]) * 12 + 2 - first[1];
      for (let i = 0; i < steps; i++) await slider.press('ArrowRight');
      await expect(chart.locator('.chart-readout-period')).toContainText('Feb 2022');
      for (const value of await chart.locator('.chart-readout-value').allTextContents()) assert.equal(value, 'Unavailable');
      await expect(chart.locator('[data-month-coverage]')).toContainText(/gap|missing|unavailable/i);
      await page.locator('#intel-close').click();
    });
    await check('closing a loading detail and switching commodities cannot restore stale data', async () => {
      // A fresh page ensures the bounded in-memory commodity cache cannot bypass this request.
      const racePage = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
      monitor(racePage);
      await racePage.goto(`${baseURL}#commodities`);
      await ready(racePage);
      const delayed = read('data/intelligence/crude_oil.json');
      let release;
      let arrived;
      let delivered;
      const requestArrived = new Promise(resolve => { arrived = resolve; });
      const requestReleased = new Promise(resolve => { release = resolve; });
      const requestDelivered = new Promise(resolve => { delivered = resolve; });
      await racePage.route('**/data/intelligence/crude_oil.json', async route => {
        arrived();
        await requestReleased;
        try { await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(delayed) }); }
        catch { /* Aborting the stale request is also a successful outcome. */ }
        delivered();
      });
      await racePage.locator('.intelligence-button[data-commodity-id="crude_oil"]').click();
      await Promise.race([requestArrived, new Promise((_, reject) => setTimeout(() => reject(new Error('Intelligence request did not start')), 5000))]);
      await expect(racePage.locator('#intel-body')).toBeHidden();
      await racePage.locator('#intel-close').click();
      await expect(racePage.locator('#intelligence-section')).toBeHidden();
      await openCommodity('natural_gas_lng', racePage);
      release();
      await Promise.race([requestDelivered, new Promise((_, reject) => setTimeout(() => reject(new Error('Delayed intelligence request did not settle')), 15000))]);
      await expect(racePage.locator('#intel-title')).toHaveText('Natural Gas / LNG');
      await expect(racePage.locator('#intel-body')).toBeVisible();
      await racePage.unroute('**/data/intelligence/crude_oil.json');
      await racePage.close();
    });
    await check('mobile touch can inspect both chart series without page overflow', async () => {
      const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, reducedMotion: 'reduce' });
      monitor(mobile);
      await mobile.goto(`${baseURL}#commodities`);
      await ready(mobile);
      await openCommodity('crude_oil', mobile);
      const slider = mobile.locator('#intel-trade-chart .chart-frame');
      await slider.scrollIntoViewIfNeeded();
      const before = await slider.getAttribute('aria-valuenow');
      await slider.tap();
      await expect(slider).not.toHaveAttribute('aria-valuenow', before);
      await expect(mobile.locator('#intel-trade-chart .chart-readout-value')).toHaveCount(2);
      const extent = await mobile.evaluate(() => ({ actual: document.documentElement.scrollWidth, viewport: window.innerWidth }));
      assert(extent.actual <= extent.viewport + 1, `Mobile intelligence overflow: ${JSON.stringify(extent)}`);
      await mobile.locator('#intel-title').scrollIntoViewIfNeeded();
      await screenshot('mobile-intelligence', mobile);
      await mobile.close();
    });
    assert.deepEqual(failures, [], 'No browser exceptions or console errors are expected');
    console.log(`Completed ${checks.length} browser smoke checks.`);
  } catch (error) {
    if (page && !page.isClosed()) await screenshot('failure', page).catch(() => {});
    throw error;
  } finally {
    fs.writeFileSync(path.join(artifacts, 'checks.json'), JSON.stringify({ checks, browserErrors: failures }, null, 2));
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
