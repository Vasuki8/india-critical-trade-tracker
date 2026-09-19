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
const national = read('data/national/dashboard.json');
const nationalSnapshot = period => read(`data/national/months/${period}.json`);
const nationalRowKey = row => String(row.code ?? row.name);
const nationalPeriods = national.monthly.map(row => row.period).sort();
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
  await expect(target.locator('#critical-as-of')).not.toHaveText(/Loading|Unavailable/);
  await expect(target.locator('.commodity-card')).toHaveCount(master.commodities.length);
  await expect(target.locator('#national-month')).toHaveValue(national.as_of);
  await expect(target.locator('#national-status')).toHaveAttribute('data-state', 'ready');
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

async function bounded(promise, message) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(message)), 15000);
    })]);
  } finally { clearTimeout(timer); }
}

async function openCommodity(id, target = page) {
  await view('critical', target);
  const button = target.locator(`.intelligence-button[data-commodity-id="${id}"]`);
  await button.click();
  await expect(target.locator('#intel-body')).toBeVisible();
  await expect(target.locator('#intel-title')).toHaveText(master.commodities.find(item => item.id === id).name);
}

function periodLabel(period) {
  return new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
    .format(new Date(`${period}-01T00:00:00Z`));
}

async function assertNationalMonth(period, target = page) {
  const snapshot = nationalSnapshot(period);
  await expect(target.locator('#national-month')).toHaveValue(period);
  await expect(target.locator('#national-status')).toHaveAttribute('data-state', 'ready');
  await expect(target.locator('#national-snapshot-period')).toContainText(periodLabel(period));
  const expected = await target.evaluate(summary => ({
    imports: usdMillions(summary.imports), exports: usdMillions(summary.exports),
    balance: usdMillions(summary.exports - summary.imports),
    total: usdMillions(summary.exports + summary.imports),
  }), snapshot.summary);
  await expect(target.locator('#national-imports')).toHaveText(expected.imports);
  await expect(target.locator('#national-exports')).toHaveText(expected.exports);
  await expect(target.locator('#national-balance')).toHaveText(expected.balance);
  await expect(target.locator('#national-total-trade')).toHaveText(expected.total);
  for (const [kind, field] of [['chapter', 'chapters'], ['partner', 'partners']]) {
    const rows = target.locator(`#national-${kind}-table-body tr[data-code]`);
    await expect(rows).toHaveCount(snapshot[field].length);
    const renderedKeys = await rows.evaluateAll(items => items.map(item => item.dataset.code));
    assert.deepEqual([...renderedKeys].sort(), snapshot[field].map(nationalRowKey).sort(), `${period} ${field} must match that month's complete source table`);
    const leading = [...snapshot[field]].sort((a, b) => (b.imports ?? -1) - (a.imports ?? -1))[0];
    const formatted = await target.evaluate(item => [usdMillions(item.imports), usdMillions(item.exports)], leading);
    const leadingIndex = renderedKeys.indexOf(nationalRowKey(leading));
    assert(leadingIndex >= 0, 'The leading source row must be present');
    const leadingRow = rows.nth(leadingIndex);
    await expect(leadingRow).toContainText(leading.name);
    if (kind === 'partner' && leading.code == null) await expect(leadingRow).not.toContainText('Source code');
    for (const value of formatted) await expect(leadingRow).toContainText(value);
  }
  return snapshot;
}

// CSV names can contain commas or escaped quotes; parse cells before checking values.
function parseCSV(text) {
  const rows = [];
  let row = [], cell = '', quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') { cell += '"'; index += 1; }
      else quoted = !quoted;
    } else if (char === ',' && !quoted) { row.push(cell); cell = ''; }
    else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && text[index + 1] === '\n') index += 1;
      row.push(cell); rows.push(row); row = []; cell = '';
    } else cell += char;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
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
    await check('national merchandise totals and the critical watchlist retain their own data scope', async () => {
      assert.equal(national.scope, 'merchandise');
      const snapshot = await assertNationalMonth(national.as_of);
      assert.notEqual(snapshot.summary.imports, dashboard.summary.imports, 'National imports must come from national observations');
      assert.notEqual(snapshot.summary.exports, dashboard.summary.exports, 'National exports must come from national observations');
      await expect(page.locator('#overview-view')).toContainText(/merchandise|goods/i);
      assert(snapshot.chapters.length > master.commodities.length, 'The general explorer must cover the full merchandise classification');
      await view('partners');
      await screenshot('desktop-partners');
      await view('critical');
      await screenshot('desktop-critical');
      const watched = await page.evaluate(summary => [usdMillions(summary.imports), usdMillions(summary.exports)], dashboard.summary);
      await expect(page.locator('#imports')).toHaveText(watched[0]);
      await expect(page.locator('#exports')).toHaveText(watched[1]);
      await expect(page.locator('#critical-view')).toContainText(/watchlist|watched|critical/i);
    });
    await check('reporting month updates national metrics and both complete breakdowns', async () => {
      assert(nationalPeriods.length > 2, 'General trade needs historical reporting months');
      const historicalPeriod = nationalPeriods[Math.max(0, nationalPeriods.length - 13)];
      assert.notEqual(historicalPeriod, national.as_of);
      await view('overview');
      await page.locator('#national-month').selectOption(historicalPeriod);
      await assertNationalMonth(historicalPeriod);
      await view('commodities');
      await expect(page.locator('#national-chapter-table-body tr[data-code]').first()).toBeVisible();
      await view('partners');
      await expect(page.locator('#national-partner-table-body tr[data-code]').first()).toBeVisible();
      await page.locator('#national-month').selectOption(national.as_of);
      await assertNationalMonth(national.as_of);
    });
    await check('historical partner YTD source warnings preserve monthly values and expose exact differences', async () => {
      const sourceWarnings = national.reconciliation_warnings.filter(warning => warning.kind === 'partners');
      assert(sourceWarnings.length > 0, 'The recorded historical source discrepancies must remain available for inspection');
      const warningKey = warning => `${warning.period}|${warning.trade_type}|${warning.field}`;
      const uniqueWarnings = new Map(sourceWarnings.map(warning => [warningKey(warning), warning]));
      const affectedPeriods = new Set(sourceWarnings.map(warning => warning.period));
      const warnedPeriod = [...affectedPeriods].sort()[0];
      const snapshotWarnings = nationalSnapshot(warnedPeriod).provenance.reconciliation_warnings.filter(warning => warning.kind === 'partners');
      assert(snapshotWarnings.length > 0, 'The selected reporting month must retain its source discrepancy metadata');
      await view('overview');
      await page.locator('#national-month').selectOption(warnedPeriod);
      await assertNationalMonth(warnedPeriod);
      const note = page.locator('#national-reconciliation-note');
      for (const name of ['overview', 'commodities', 'partners']) {
        await view(name);
        await expect(note).toBeVisible();
        await expect(note).toContainText(periodLabel(warnedPeriod));
        await expect(note).toContainText('YTD');
      }
      await view('critical');
      await expect(note).toBeHidden();
      await view('sources');
      await expect(note).toBeHidden();
      await expect(page.locator('#national-reconciliation-summary')).toHaveText(new RegExp(`^${affectedPeriods.size} reporting month`));
      const details = page.locator('#national-reconciliation-details');
      await expect(details).toBeVisible();
      await details.locator('summary').click();
      const rows = page.locator('#national-reconciliation-table-body tr');
      await expect(rows).toHaveCount(uniqueWarnings.size);
      const rendered = await rows.evaluateAll(items => items.map(row => {
        const cells = [...row.cells];
        return {
          key: `${row.dataset.period}|${row.dataset.trade}|${row.dataset.field}`,
          cells: cells.slice(0, 5).map(cell => cell.textContent.trim()),
          difference: [...cells[5].childNodes].filter(node => node.nodeType === Node.TEXT_NODE).map(node => node.textContent).join('').trim(),
          tolerance: cells[5].querySelector('small')?.textContent.trim(),
        };
      }));
      const renderedByKey = new Map(rendered.map(row => [row.key, row]));
      assert.deepEqual([...renderedByKey.keys()].sort(), [...uniqueWarnings.keys()].sort(), 'Every source discrepancy must appear exactly once');
      const format = new Intl.NumberFormat('en-US', { maximumFractionDigits: 6 });
      for (const [key, warning] of uniqueWarnings) {
        const row = renderedByKey.get(key);
        const flow = ['import', 'imports'].includes(warning.trade_type) ? 'Imports' : 'Exports';
        const field = warning.field === 'cumulative_previous_year_value' ? 'Prior-year YTD' : 'Current-year YTD';
        assert.deepEqual(row.cells, [periodLabel(warning.period), flow, field, format.format(warning.reported_total), format.format(warning.sum_of_rows)]);
        assert.equal(row.difference, format.format(warning.difference), 'The signed source difference must retain its published precision');
        assert.equal(row.tolerance, `Rounding tolerance: ±${format.format(warning.rounding_tolerance)}`);
      }
      await page.locator('#national-reconciliation-title').scrollIntoViewIfNeeded();
      await screenshot('desktop-source-reconciliation');
      await view('overview');
      const cleanPeriod = [...nationalPeriods].reverse().find(period => !(nationalSnapshot(period).provenance?.reconciliation_warnings || []).some(warning => warning.kind === 'partners'));
      assert(cleanPeriod, 'A clean reporting month must be available to check that warnings clear');
      await page.locator('#national-month').selectOption(cleanPeriod);
      await assertNationalMonth(cleanPeriod);
      await expect(note).toBeHidden();
      if (cleanPeriod !== national.as_of) {
        await page.locator('#national-month').selectOption(national.as_of);
        await assertNationalMonth(national.as_of);
        await expect(note).toBeVisible();
      }
    });
    await check('general commodity and partner search, flow, sorting, empty state and CSV use source rows', async () => {
      const snapshot = nationalSnapshot(national.as_of);
      for (const [kind, field, nameHeader, codeHeader] of [
        ['chapter', 'chapters', 'Commodity chapter', 'HS chapter'],
        ['partner', 'partners', 'Trade partner', 'Partner code'],
      ]) {
        await view(kind === 'chapter' ? 'commodities' : 'partners');
        const rows = page.locator(`#national-${kind}-table-body tr[data-code]`);
        const search = page.locator(`#national-${kind}-search`);
        const sort = page.locator(`#national-${kind}-sort`);
        const flow = page.locator(`#national-${kind}-flow`);
        const reset = page.locator(`#national-${kind}-reset`);
        const table = page.locator(`#national-${kind}-table-body`).locator('..');
        await expect(rows).toHaveCount(snapshot[field].length);
        await sort.selectOption('exports');
        let firstCode = await rows.first().getAttribute('data-code');
        assert.equal(snapshot[field].find(item => nationalRowKey(item) === firstCode).exports,
          Math.max(...snapshot[field].map(item => item.exports ?? -Infinity)), `${field} must sort by actual exports`);
        await flow.selectOption('imports');
        await expect(sort).toHaveValue('imports');
        await expect(table.locator('thead')).toContainText(/imports/i);
        await expect(table.locator('thead')).not.toContainText(/exports/i);
        await expect(rows).toHaveCount(snapshot[field].length);
        await flow.selectOption('exports');
        await expect(sort).toHaveValue('exports');
        await expect(table.locator('thead')).toContainText(/exports/i);
        await expect(table.locator('thead')).not.toContainText(/imports/i);
        await search.fill('no-such-trade-record-xyz');
        await expect(rows).toHaveCount(0);
        await expect(page.locator(`#national-${kind}-results`)).toContainText(/0|no/i);
        await reset.click();
        await expect(search).toHaveValue('');
        await expect(flow).toHaveValue('both');
        await expect(sort).toHaveValue('imports');
        await expect(rows).toHaveCount(snapshot[field].length);
        firstCode = await rows.first().getAttribute('data-code');
        assert.equal(snapshot[field].find(item => nationalRowKey(item) === firstCode).imports,
          Math.max(...snapshot[field].map(item => item.imports ?? -Infinity)), `${field} reset must restore highest imports`);
        const hasBothFlows = item => item.name && item.imports > 0 && item.exports > 0;
        const sample = (kind === 'partner' && snapshot[field].find(item => item.code == null && hasBothFlows(item)))
          || snapshot[field].find(hasBothFlows);
        assert(sample, `${field} needs a source row with trade in both directions`);
        await search.fill(sample.name);
        const filtered = snapshot[field].filter(item => `${item.code ?? ''} ${item.name}`.toLowerCase().includes(sample.name.toLowerCase()));
        await expect(rows).toHaveCount(filtered.length);
        const downloaded = page.waitForEvent('download');
        await page.locator(`#national-${kind}-download`).click();
        const download = await downloaded;
        assert.equal(download.suggestedFilename(), `india-merchandise-${field}-${national.as_of}.csv`);
        const csv = parseCSV(fs.readFileSync(await download.path(), 'utf8').replace(/^\uFEFF/, ''));
        assert.equal(csv.length, filtered.length + 1, 'CSV must include exactly the filtered source rows and one header');
        const headers = csv[0];
        assert(headers.includes('Imports (USD million)') && headers.includes('Exports (USD million)'), 'CSV must retain exact units');
        for (const cells of csv.slice(1)) {
          const record = Object.fromEntries(headers.map((header, index) => [header, cells[index]]));
          const item = filtered.find(candidate => candidate.name === record[nameHeader] && String(candidate.code ?? '') === record[codeHeader]);
          assert(item, 'Every CSV row must come from the active filter');
          assert.equal(record['Reporting month'], national.as_of);
          assert.equal(record[nameHeader], item.name);
          assert.equal(record[codeHeader], String(item.code ?? ''), 'Unreported source codes must stay blank');
          for (const [header, fieldName] of [['Imports (USD million)', 'imports'], ['Exports (USD million)', 'exports']]) {
            if (item[fieldName] === null) assert.equal(record[header], '', 'Missing trade must remain an empty CSV cell');
            else assert.equal(Number(record[header]), item[fieldName], 'CSV must preserve the underlying amount, without display rounding');
          }
        }
        await reset.click();
      }
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
      await delayedPage.route('**/assets/js/intelligence.js*', async route => {
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
      await expect(delayedPage.locator('#national-history-chart .chart-frame')).toBeVisible();
      await delayedPage.close();
    });
    await check('critical commodity search, combined filters, empty state, reset and sorting', async () => {
      await view('critical');
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
        for (const name of ['overview', 'commodities', 'partners', 'critical', 'sources']) {
          await view(name);
          const extent = await page.evaluate(() => ({ actual: document.documentElement.scrollWidth, viewport: window.innerWidth }));
          assert(extent.actual <= extent.viewport + 1, `${name} overflows at ${width}px: ${JSON.stringify(extent)}`);
          if (width === 390) await screenshot(`mobile-${name}`, page, ['overview', 'sources'].includes(name));
        }
      }
    });
    await check('small nonzero trade values never disappear into rounded zero millions', async () => {
      const values = await page.evaluate(() => [usdMillions(.04), usdMillions(-.04), usdMillions(0), usdMillions(null)]);
      assert.deepEqual(values, ['$40K', '-$40K', '$0M', '—']);
    });
    await check('national history follows the selected reporting month and keyboard range', async () => {
      await view('overview');
      const historicalPeriod = nationalPeriods.at(-2);
      await page.locator('#national-month').selectOption(historicalPeriod);
      await assertNationalMonth(historicalPeriod);
      await page.locator('#national-range').selectOption('12');
      await chartKeyboard('national-history-chart');
      const chart = page.locator('#national-history-chart');
      const lastMonth = Number(historicalPeriod.slice(0, 4)) * 12 + Number(historicalPeriod.slice(5));
      const firstMonth = Number(nationalPeriods[0].slice(0, 4)) * 12 + Number(nationalPeriods[0].slice(5));
      await expect(chart.locator('.chart-frame')).toHaveAttribute('aria-valuemax', String(Math.min(12, lastMonth - firstMonth + 1)));
      await expect(chart.locator('.chart-readout-period')).toHaveText(periodLabel(historicalPeriod));
      const selected = nationalSnapshot(historicalPeriod);
      // Chart inspection keeps two decimal places; headline KPI cards use one.
      const expected = await page.evaluate(summary => [chartValueLabel(summary.imports), chartValueLabel(summary.exports)], selected.summary);
      assert.deepEqual(await chart.locator('.chart-readout-value').allTextContents(), expected);
      await page.locator('#national-month').selectOption(national.as_of);
      await assertNationalMonth(national.as_of);
      await page.locator('#national-range').selectOption('36');
    });
    await check('portfolio chart keyboard and selected-range totals work together', async () => {
      await view('critical');
      await page.locator('#critical-portfolio > summary').click();
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
      await page.locator('#intel-month').selectOption('2018-01');
      await expect(page.locator('#intel-unit-values')).toContainText('Validated quantity unavailable for this month.');
      await expect(page.locator('#intel-unit-values')).not.toContainText(/mixed physical units/i);
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
      await racePage.goto(`${baseURL}#critical`);
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
      await bounded(requestArrived, 'Intelligence request did not start');
      await expect(racePage.locator('#intel-body')).toBeHidden();
      await racePage.locator('#intel-close').click();
      await expect(racePage.locator('#intelligence-section')).toBeHidden();
      await openCommodity('natural_gas_lng', racePage);
      release();
      await bounded(requestDelivered, 'Delayed intelligence request did not settle');
      await expect(racePage.locator('#intel-title')).toHaveText('Natural Gas / LNG');
      await expect(racePage.locator('#intel-body')).toBeVisible();
      await racePage.unroute('**/data/intelligence/crude_oil.json');
      await racePage.close();
    });
    await check('switching reporting months cannot restore a delayed national snapshot', async () => {
      const racePage = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
      monitor(racePage);
      await racePage.goto(baseURL);
      await ready(racePage);
      const delayedPeriod = nationalPeriods.at(-2);
      const finalPeriod = nationalPeriods.at(-3);
      const routePattern = `**/data/national/months/${delayedPeriod}.json`;
      let release, arrived, delivered;
      const requestArrived = new Promise(resolve => { arrived = resolve; });
      const requestReleased = new Promise(resolve => { release = resolve; });
      const requestDelivered = new Promise(resolve => { delivered = resolve; });
      await racePage.route(routePattern, async route => {
        arrived();
        await requestReleased;
        try { await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(nationalSnapshot(delayedPeriod)) }); }
        catch { /* Cancelling the previous month's request is a correct result. */ }
        delivered();
      });
      await racePage.locator('#national-month').selectOption(delayedPeriod);
      await bounded(requestArrived, 'Delayed national request did not start');
      await expect(racePage.locator('#national-status')).toHaveAttribute('data-state', 'loading');
      await expect(racePage.locator('#national-status')).toBeVisible();
      await expect(racePage.locator('#national-imports')).toBeHidden();
      await racePage.locator('#national-month').selectOption(finalPeriod);
      await assertNationalMonth(finalPeriod, racePage);
      release();
      await bounded(requestDelivered, 'Delayed national request did not settle');
      await assertNationalMonth(finalPeriod, racePage);
      await racePage.unroute(routePattern);
      await racePage.close();
    });
    await check('a failed month shows an explicit retry and recovers the same reporting month', async () => {
      const retryPage = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
      const failedPeriod = nationalPeriods.at(-2);
      const failedURL = new URL(`data/national/months/${failedPeriod}.json`, baseURL).href;
      const routePattern = `**/data/national/months/${failedPeriod}.json`;
      let injectingFailure = false, injectedRequests = 0, expectedHttpLogs = 0, expectedAppLogs = 0;
      retryPage.setDefaultTimeout(15000);
      retryPage.on('pageerror', error => failures.push(error.message));
      retryPage.on('console', message => {
        if (message.type() !== 'error') return;
        // Exempt only this injected response and its exact application diagnostic.
        // A 503 for any other URL, or another application error, still fails the suite.
        const text = message.text();
        const location = message.location().url;
        if (injectingFailure && expectedHttpLogs === 0 && location === failedURL && /^Failed to load resource:.*\b503\b/.test(text)) {
          expectedHttpLogs += 1;
        } else if (injectingFailure && expectedAppLogs === 0 && /\/assets\/js\/national\.js(?:\?|$)/.test(location)
          && text.startsWith(`National merchandise detail could not load: Error: Reporting month ${failedPeriod}: HTTP 503`)) {
          expectedAppLogs += 1;
        } else failures.push(text);
      });
      await retryPage.goto(baseURL);
      await ready(retryPage);
      injectingFailure = true;
      await retryPage.route(routePattern, route => {
        injectedRequests += 1;
        return route.fulfill({ status: 503, contentType: 'text/plain', body: 'Temporary test failure' });
      }, { times: 1 });
      await retryPage.locator('#national-month').selectOption(failedPeriod);
      await expect(retryPage.locator('#national-status')).toHaveAttribute('data-state', 'error');
      await expect(retryPage.locator('#national-status')).toBeVisible();
      await expect(retryPage.locator('#national-imports')).toBeHidden();
      await expect(retryPage.locator('#national-retry')).toBeVisible();
      await expect(retryPage.locator('#national-month')).toHaveValue(failedPeriod);
      await expect.poll(() => expectedAppLogs).toBe(1);
      assert.equal(injectedRequests, 1);
      injectingFailure = false;
      await retryPage.unroute(routePattern);
      await retryPage.locator('#national-retry').click();
      await assertNationalMonth(failedPeriod, retryPage);
      await retryPage.close();
    });
    await check('mobile touch can inspect both chart series without page overflow', async () => {
      const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, reducedMotion: 'reduce' });
      monitor(mobile);
      await mobile.goto(`${baseURL}#critical`);
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
