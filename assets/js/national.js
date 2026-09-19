// National merchandise is an independent, complete scope. The critical
// watchlist's overlapping HS groups never supply the national headline totals.
const nationalState = {
  manifest: null,
  monthly: [],
  period: null,
  detail: null,
  phase: 'loading',
  requestId: 0,
  controller: null,
  cache: new Map(),
};
const nationalViews = new Set(['overview', 'commodities', 'partners']);
const nationalNumber = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });
const nationalReconciliationNumber = new Intl.NumberFormat('en-US', { maximumFractionDigits: 6 });

function nationalActiveView() {
  return document.querySelector('[data-page]:not([hidden])')?.dataset.page || 'overview';
}

function syncNationalNavigation() {
  const view = nationalActiveView();
  const isGeneral = nationalViews.has(view);
  document.querySelector('#national-month-control').hidden = !isGeneral;
  document.querySelector('#critical-status').hidden = view !== 'critical';
  document.querySelector('#source-context').hidden = view !== 'sources';
  document.querySelector('#national-status').hidden = !isGeneral || nationalState.phase === 'ready';
  document.querySelector('#national-reconciliation-note').hidden = !isGeneral || nationalState.phase !== 'ready' || !nationalReconciliationWarnings(nationalState.detail).length;
}

function nationalReconciliationWarnings(detail) {
  const warnings = detail?.provenance?.reconciliation_warnings;
  return Array.isArray(warnings) ? warnings.filter(warning => warning.kind === 'partners') : [];
}

function renderNationalReconciliation(detail) {
  const target = document.querySelector('#national-reconciliation-note');
  const warnings = nationalReconciliationWarnings(detail);
  target.innerHTML = warnings.length
    ? `${uiIcon('info')}<div><strong>Partner YTD source note · ${escapeHTML(periodLabel(detail.period))}</strong><p>The source’s cumulative partner rows differ from its reported total for this month. Monthly trade figures and the reported national totals reconcile. <a href="#sources">Inspect the source differences</a>.</p></div>`
    : '';
}

function renderNationalReconciliationHistory(manifest) {
  const warnings = Array.isArray(manifest.reconciliation_warnings)
    ? manifest.reconciliation_warnings.filter(warning => warning.kind === 'partners') : [];
  const unique = new Map(warnings.map(warning => [`${warning.period}|${warning.trade_type}|${warning.field}`, warning]));
  const rows = [...unique.values()].sort((a, b) => String(b.period).localeCompare(String(a.period))
    || String(a.trade_type).localeCompare(String(b.trade_type)) || String(a.field).localeCompare(String(b.field)));
  const periods = new Set(rows.map(warning => warning.period));
  document.querySelector('#national-reconciliation-summary').textContent = periods.size
    ? `${periods.size} reporting month${periods.size === 1 ? ' has' : 's have'} discrepancies between the source’s cumulative partner rows and its reported totals. Monthly trade figures and national totals reconcile. The original source figures are preserved; the affected months are identified when selected.`
    : 'No cumulative partner discrepancies are recorded in the available dashboard history.';
  document.querySelector('#national-reconciliation-details').hidden = !rows.length;
  document.querySelector('#national-reconciliation-table-body').innerHTML = rows.map(warning => {
    const flow = warning.trade_type === 'import' || warning.trade_type === 'imports' ? 'Imports'
      : warning.trade_type === 'export' || warning.trade_type === 'exports' ? 'Exports' : warning.trade_type;
    const field = warning.field === 'cumulative_previous_year_value' ? 'Prior-year YTD'
      : warning.field === 'cumulative_value' ? 'Current-year YTD' : warning.field;
    const number = value => finiteTradeValue(value) === null ? '—' : nationalReconciliationNumber.format(Number(value));
    return `<tr data-period="${escapeHTML(warning.period)}" data-field="${escapeHTML(warning.field)}" data-trade="${escapeHTML(warning.trade_type)}"><td>${escapeHTML(periodLabel(warning.period))}</td><td>${escapeHTML(flow)}</td><td>${escapeHTML(field)}</td><td>${number(warning.reported_total)}</td><td>${number(warning.sum_of_rows)}</td><td>${number(warning.difference)}<small class="table-subtext">Rounding tolerance: ±${number(warning.rounding_tolerance)}</small></td></tr>`;
  }).join('');
}

function nationalStatus(phase, message) {
  nationalState.phase = phase;
  const target = document.querySelector('#national-status');
  target.dataset.state = phase;
  target.setAttribute('role', phase === 'error' ? 'alert' : 'status');
  target.classList.toggle('national-status-error', phase === 'error');
  target.innerHTML = phase === 'loading'
    ? `<span class="intel-loading-spinner" aria-hidden="true"></span><span>${escapeHTML(message)}</span>`
    : phase === 'error'
      ? `<span>${escapeHTML(message)}</span><button id="national-retry" type="button" class="ghost-button">Retry loading</button>`
      : '';
  document.querySelector('#national-retry')?.addEventListener('click', () => {
    if (nationalState.manifest && nationalState.period) loadNationalMonth(nationalState.period);
    else initNationalDashboard();
  });
  syncNationalNavigation();
}

function nationalAdd(a, b) {
  const first = finiteTradeValue(a);
  const second = finiteTradeValue(b);
  return first === null || second === null ? null : first + second;
}

function nationalBalance(row) {
  const imports = finiteTradeValue(row?.imports);
  const exports = finiteTradeValue(row?.exports);
  return imports === null || exports === null ? null : exports - imports;
}

function nationalShare(value, total) {
  const amount = finiteTradeValue(value);
  const denominator = finiteTradeValue(total);
  return amount === null || denominator === null || denominator <= 0 ? null : amount / denominator * 100;
}

function nationalShareLabel(value) {
  return value === null ? 'Share unavailable' : `${nationalNumber.format(value)}%`;
}

function nationalGrowthLabel(value) {
  return finiteTradeValue(value) === null ? 'Unavailable' : pct(value);
}

function nationalExact(value) {
  const amount = finiteTradeValue(value);
  return amount === null ? 'Unavailable' : `${nationalNumber.format(amount)} USD million`;
}

function nationalYearOnYear(current, previous) {
  const latest = finiteTradeValue(current);
  const earlier = finiteTradeValue(previous);
  return latest === null || earlier === null || earlier === 0 ? null : (latest / earlier - 1) * 100;
}

function renderNationalSummary(detail) {
  const summary = detail.summary;
  const balance = nationalBalance(summary);
  const total = nationalAdd(summary.imports, summary.exports);
  const previousPeriod = calendarPeriod(calendarMonthNumber(detail.period) - 12);
  const previous = nationalState.monthly.find(row => row.period === previousPeriod);
  const totalYoy = Object.hasOwn(summary, 'total_trade_yoy_pct')
    ? finiteTradeValue(summary.total_trade_yoy_pct)
    : nationalYearOnYear(total, nationalAdd(previous?.imports, previous?.exports));
  const ytdBalance = nationalBalance({ imports: summary.ytd_imports, exports: summary.ytd_exports });
  const ytdTotal = nationalAdd(summary.ytd_imports, summary.ytd_exports);
  const setAmount = (id, value) => {
    const target = document.getElementById(id);
    target.textContent = usdMillions(value);
    target.title = nationalExact(value);
  };
  setAmount('national-imports', summary.imports);
  setAmount('national-exports', summary.exports);
  setAmount('national-balance', balance);
  setAmount('national-total-trade', total);
  document.querySelector('#national-balance').style.color = balance === null ? 'var(--text)' : balance < 0 ? 'var(--negative)' : 'var(--positive)';
  document.querySelector('#national-imports-foot').innerHTML = `<strong>${nationalGrowthLabel(summary.import_yoy_pct)}</strong> YoY<span class="metric-secondary">YTD ${usdMillions(summary.ytd_imports)}</span>`;
  document.querySelector('#national-exports-foot').innerHTML = `<strong>${nationalGrowthLabel(summary.export_yoy_pct)}</strong> YoY<span class="metric-secondary">YTD ${usdMillions(summary.ytd_exports)}</span>`;
  document.querySelector('#national-balance-foot').innerHTML = `${balance === null ? 'Balance unavailable' : balance < 0 ? 'Merchandise trade deficit' : balance > 0 ? 'Merchandise trade surplus' : 'Balanced merchandise trade'}<span class="metric-secondary">YTD ${usdMillions(ytdBalance)}</span>`;
  document.querySelector('#national-total-trade-foot').innerHTML = `<strong>${nationalGrowthLabel(totalYoy)}</strong> YoY<span class="metric-secondary">YTD ${usdMillions(ytdTotal)} · imports + exports</span>`;
  document.querySelector('#national-yoy-note').textContent = finiteTradeValue(summary.import_yoy_pct) === null || finiteTradeValue(summary.export_yoy_pct) === null
    ? 'YoY is unavailable where the prior-year comparison is missing or zero.'
    : 'YoY compares the same month a year earlier.';
  document.querySelector('#national-snapshot-period').textContent = periodLabel(detail.period);
  document.querySelectorAll('[data-national-period]').forEach(node => { node.textContent = periodLabel(detail.period); });
}

function nationalRowKey(row) {
  return String(row.code ?? row.name);
}

function nationalFilteredRows(kind) {
  const rows = nationalState.detail?.[kind === 'chapter' ? 'chapters' : 'partners'] || [];
  const query = document.querySelector(`#national-${kind}-search`).value.trim().toLocaleLowerCase();
  const sort = document.querySelector(`#national-${kind}-sort`).value;
  const valueFor = row => sort === 'trade' ? nationalAdd(row.imports, row.exports)
    : sort === 'balance' ? nationalBalance(row) : finiteTradeValue(row[sort]);
  return rows.filter(row => !query || `${row.code ?? ''} ${row.name}`.toLocaleLowerCase().includes(query)).slice().sort((a, b) => {
    if (sort === 'name') return String(a.name).localeCompare(String(b.name));
    if (sort === 'code') return String(a.code).localeCompare(String(b.code), 'en', { numeric: true });
    const av = valueFor(a);
    const bv = valueFor(b);
    if (av === null && bv !== null) return 1;
    if (bv === null && av !== null) return -1;
    if (av !== null && bv !== null && av !== bv) return bv - av;
    return String(a.name).localeCompare(String(b.name));
  });
}

function renderNationalTable(kind) {
  const detail = nationalState.detail;
  if (!detail) return;
  const allRows = detail[kind === 'chapter' ? 'chapters' : 'partners'];
  const rows = nationalFilteredRows(kind);
  const flow = document.querySelector(`#national-${kind}-flow`).value;
  const label = kind === 'chapter' ? 'Commodity chapter' : 'Trade partner';
  const flows = flow === 'both' ? ['imports', 'exports'] : [flow];
  const amountCell = (row, direction) => {
    const share = nationalShare(row[direction], detail.summary[direction]);
    return `<td class="national-value ${direction}" title="${escapeHTML(nationalExact(row[direction]))}"><strong>${usdMillions(row[direction])}</strong><small>${nationalShareLabel(share)} of India’s ${direction}</small></td>`;
  };
  const flowHeaders = flows.map(direction => `<th scope="col">${direction === 'imports' ? 'Imports' : 'Exports'}<span>Value · national share</span></th><th scope="col">${direction === 'imports' ? 'Import' : 'Export'} YoY</th>`).join('');
  const balanceHeader = flow === 'both' ? '<th scope="col">Balance<span>Exports − imports</span></th>' : '';
  document.querySelector(`#national-${kind}-table-head`).innerHTML = `<tr><th scope="col">${label}</th>${flowHeaders}${balanceHeader}</tr>`;
  const columns = flow === 'both' ? 6 : 3;
  document.querySelector(`#national-${kind}-table-body`).innerHTML = rows.map(row => {
    const balance = nationalBalance(row);
    const code = kind === 'chapter' ? `HS ${row.code}` : row.code == null ? '' : `Source code ${row.code}`;
    return `<tr data-code="${escapeHTML(nationalRowKey(row))}"><th scope="row"><strong>${escapeHTML(row.name)}</strong>${code ? `<small>${escapeHTML(code)}</small>` : ''}</th>${flows.map(direction => `${amountCell(row, direction)}<td>${nationalGrowthLabel(row[direction === 'imports' ? 'import_yoy_pct' : 'export_yoy_pct'])}</td>`).join('')}${flow === 'both' ? `<td class="national-balance ${balance === null ? '' : balance < 0 ? 'deficit' : 'surplus'}" title="${escapeHTML(nationalExact(balance))}">${usdMillions(balance)}</td>` : ''}</tr>`;
  }).join('') || `<tr><td class="national-empty-row" colspan="${columns}"><strong>No ${kind === 'chapter' ? 'chapters' : 'partners'} found</strong><span>Try another name or code, or reset the filters.</span><button type="button" class="ghost-button" data-national-empty-reset="${kind}">Reset filters</button></td></tr>`;
  document.querySelector(`#national-${kind}-table`).classList.toggle('national-single-flow', flow !== 'both');
  document.querySelector(`#national-${kind}-results`).textContent = `${rows.length} of ${allRows.length} ${kind === 'chapter' ? 'chapters' : 'partners'} · ${periodLabel(detail.period)}`;
  document.querySelector(`#national-${kind}-coverage`).textContent = `${allRows.length} reported ${kind === 'chapter' ? 'HS chapters' : 'partners'}`;
  document.querySelector(`#national-${kind}-caption`).textContent = `${label}s, India merchandise ${flow === 'both' ? 'imports and exports' : flow}, ${periodLabel(detail.period)}, values in USD`;
  document.querySelector(`#national-${kind}-reset`).hidden = !document.querySelector(`#national-${kind}-search`).value && flow === 'both' && document.querySelector(`#national-${kind}-sort`).value === 'imports';
  document.querySelector(`#national-${kind}-download`).disabled = rows.length === 0;
  document.querySelector(`[data-national-empty-reset="${kind}"]`)?.addEventListener('click', () => resetNationalFilters(kind));
}

function resetNationalFilters(kind) {
  document.querySelector(`#national-${kind}-search`).value = '';
  document.querySelector(`#national-${kind}-flow`).value = 'both';
  document.querySelector(`#national-${kind}-sort`).value = 'imports';
  renderNationalTable(kind);
  document.querySelector(`#national-${kind}-search`).focus();
}

function renderNationalRanking(targetId, rows, flow, kind, total) {
  const ranked = rows.filter(row => finiteTradeValue(row[flow]) !== null && Number(row[flow]) > 0)
    .slice().sort((a, b) => Number(b[flow]) - Number(a[flow]) || String(a.name).localeCompare(String(b.name))).slice(0, 5);
  document.getElementById(targetId).innerHTML = ranked.map((row, index) => {
    const share = nationalShare(row[flow], total);
    return `<button class="national-ranking-row ${flow}" type="button" data-national-explore="${kind}" data-national-code="${escapeHTML(nationalRowKey(row))}" aria-label="Explore ${escapeHTML(row.name)}"><span class="national-rank">${index + 1}</span><span class="national-rank-content"><span class="national-rank-name">${kind === 'chapter' ? `<small>HS ${escapeHTML(row.code)}</small>` : ''}${escapeHTML(row.name)}</span><span class="national-rank-track" aria-hidden="true"><i style="width:${Math.min(100, Math.max(0, share || 0))}%"></i></span></span><span class="national-rank-value"><strong>${usdMillions(row[flow])}</strong><small>${nationalShareLabel(share)}</small></span></button>`;
  }).join('') || '<div class="intel-empty">No positive trade values reported for this month.</div>';
}

function renderNationalRankings(detail) {
  ['imports', 'exports'].forEach(flow => {
    const direction = flow === 'imports' ? 'import' : 'export';
    renderNationalRanking(`national-top-${direction}-chapters`, detail.chapters, flow, 'chapter', detail.summary[flow]);
    renderNationalRanking(`national-top-${direction}-partners`, detail.partners, flow, 'partner', detail.summary[flow]);
  });
}

function renderNationalHistory() {
  const period = nationalState.period;
  const history = nationalState.monthly.filter(row => !period || row.period <= period);
  const rows = rangeMonths(history, document.querySelector('#national-range').value);
  renderLineChart('national-history-chart', rows, [
    { label: 'Imports', className: 'imports-line', value: row => row.imports },
    { label: 'Exports', className: 'exports-line', value: row => row.exports },
  ], { label: 'India merchandise monthly imports and exports' });
  const annual = portfolioAnnualRows(rows).reverse();
  document.querySelector('#national-annual-table-body').innerHTML = annual.map(row => `<tr><td>${escapeHTML(row.year)}</td><td>${row.months} / 12</td><td>${usdMillions(row.imports)}</td><td>${usdMillions(row.exports)}</td><td>${usdMillions(row.balance)}</td><td><span class="coverage-badge ${row.coverage}">${escapeHTML(row.coverageLabel)}</span>${row.coverageNote ? `<small class="table-subtext">${escapeHTML(row.coverageNote)}</small>` : ''}</td></tr>`).join('') || '<tr><td colspan="6">No observations for the selected range.</td></tr>';
}

function nationalCsvCell(value) {
  if (value === null || value === undefined) return '""';
  // Numeric values, including negative trade balances, remain numeric. Source
  // labels are quoted and guarded against spreadsheet formula interpretation.
  let text = typeof value === 'number' ? String(value) : String(value);
  if (typeof value !== 'number' && /^[\s\uFEFF]*[=+\-@\t\r\n]/u.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadNationalCsv(kind) {
  const detail = nationalState.detail;
  if (!detail || nationalState.phase !== 'ready') return;
  const rows = nationalFilteredRows(kind);
  const headers = ['Reporting month', kind === 'chapter' ? 'HS chapter' : 'Partner code', kind === 'chapter' ? 'Commodity chapter' : 'Trade partner', 'Imports (USD million)', 'Exports (USD million)', 'Balance (USD million)', 'Import share (%)', 'Export share (%)', 'Import YoY (%)', 'Export YoY (%)'];
  const records = rows.map(row => [detail.period, row.code == null ? null : String(row.code), row.name, finiteTradeValue(row.imports), finiteTradeValue(row.exports), nationalBalance(row), nationalShare(row.imports, detail.summary.imports), nationalShare(row.exports, detail.summary.exports), finiteTradeValue(row.import_yoy_pct), finiteTradeValue(row.export_yoy_pct)]);
  const csv = '\uFEFF' + [headers, ...records].map(row => row.map(nationalCsvCell).join(',')).join('\r\n') + '\r\n';
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `india-merchandise-${kind === 'chapter' ? 'chapters' : 'partners'}-${detail.period}.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function validateNationalDetail(detail, period) {
  if (!detail || detail.period !== period || !detail.summary || !Array.isArray(detail.chapters) || !Array.isArray(detail.partners)) throw new Error('The reporting-month file has an unexpected format.');
  if (detail.scope && detail.scope !== 'merchandise') throw new Error('The reporting-month scope is not merchandise.');
  for (const kind of ['chapters', 'partners']) {
    const codes = new Set();
    detail[kind].forEach(row => {
      if ((kind === 'chapters' && row.code == null) || typeof row.name !== 'string' || codes.has(nationalRowKey(row))) throw new Error(`Invalid ${kind} records in reporting-month data.`);
      codes.add(nationalRowKey(row));
    });
  }
  return detail;
}

async function loadNationalMonth(period) {
  if (!nationalState.monthly.some(row => row.period === period)) return;
  nationalState.controller?.abort();
  const requestId = ++nationalState.requestId;
  const controller = new AbortController();
  nationalState.controller = controller;
  nationalState.period = period;
  nationalState.detail = null;
  document.querySelector('#national-month').value = period;
  document.querySelectorAll('.national-month-content').forEach(node => { node.hidden = true; node.setAttribute('aria-busy', 'true'); });
  nationalStatus('loading', `Loading merchandise details for ${periodLabel(period)}…`);
  renderNationalHistory();
  try {
    let detail = nationalState.cache.get(period);
    if (!detail) {
      const response = await fetch(`data/national/months/${period}.json`, { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error(`Reporting month ${period}: HTTP ${response.status}`);
      detail = validateNationalDetail(await response.json(), period);
    }
    if (requestId !== nationalState.requestId || controller.signal.aborted) return;
    nationalState.cache.delete(period);
    nationalState.cache.set(period, detail);
    while (nationalState.cache.size > 6) nationalState.cache.delete(nationalState.cache.keys().next().value);
    nationalState.detail = detail;
    renderNationalSummary(detail);
    renderNationalReconciliation(detail);
    renderNationalRankings(detail);
    renderNationalTable('chapter');
    renderNationalTable('partner');
    document.querySelectorAll('.national-month-content').forEach(node => { node.hidden = false; node.setAttribute('aria-busy', 'false'); });
    document.querySelector('#national-nav-count').textContent = detail.chapters.length;
    nationalStatus('ready', '');
    window.dispatchEvent(new CustomEvent('tracker:nationalchange', { detail: { period } }));
  } catch (error) {
    if (requestId !== nationalState.requestId || error.name === 'AbortError') return;
    nationalStatus('error', `The merchandise details for ${periodLabel(period)} could not be loaded. Retry, or choose another reporting month.`);
    document.querySelectorAll('.national-month-content').forEach(node => node.setAttribute('aria-busy', 'false'));
    console.error('National merchandise detail could not load:', error);
  }
}

async function initNationalDashboard() {
  nationalStatus('loading', 'Loading official merchandise trade data…');
  try {
    const manifest = await loadJSON('data/national/dashboard.json');
    if (manifest.scope !== 'merchandise' || !Array.isArray(manifest.monthly) || !manifest.monthly.length) throw new Error('The national dashboard does not contain merchandise history.');
    const monthly = manifest.monthly.filter(row => calendarMonthNumber(row.period) !== null).slice().sort((a, b) => a.period.localeCompare(b.period));
    if (!monthly.length) throw new Error('No valid monthly periods are available.');
    nationalState.manifest = manifest;
    nationalState.monthly = monthly;
    renderNationalReconciliationHistory(manifest);
    const month = document.querySelector('#national-month');
    month.innerHTML = monthly.slice().reverse().map(row => `<option value="${escapeHTML(row.period)}">${escapeHTML(periodLabel(row.period))}</option>`).join('');
    month.disabled = false;
    const latest = monthly.some(row => row.period === manifest.as_of) ? manifest.as_of : monthly.at(-1).period;
    document.querySelector('#national-source-history').textContent = `${periodLabel(monthly[0].period)} – ${periodLabel(monthly.at(-1).period)} · ${monthly.length} months`;
    const coverage = manifest.coverage || {};
    const chapterCount = coverage.chapter_count ?? coverage.latest_chapter_count;
    const partnerCount = coverage.partner_count ?? coverage.latest_partner_count;
    document.querySelector('#national-source-coverage').textContent = chapterCount && partnerCount
      ? `${chapterCount} HS chapters · ${partnerCount} partners · ${periodLabel(latest)}`
      : `National totals, chapters & partners · ${periodLabel(latest)}`;
    const sourceNote = typeof coverage.note === 'string' ? coverage.note : typeof manifest.source?.note === 'string' ? manifest.source.note : null;
    if (sourceNote) document.querySelector('#national-source-note').textContent = sourceNote;
    await loadNationalMonth(latest);
  } catch (error) {
    nationalStatus('error', 'The national merchandise dashboard could not be loaded. Retry to retrieve the official data.');
    document.querySelector('#national-month').disabled = true;
    document.querySelector('#national-month').innerHTML = '<option>Unavailable</option>';
    document.querySelector('#national-history-chart').innerHTML = '<div class="intel-empty">National history is unavailable until the data loads.</div>';
    document.querySelector('#national-source-history').textContent = 'National dashboard unavailable';
    document.querySelector('#national-source-coverage').textContent = 'Could not load coverage';
    document.querySelector('#national-reconciliation-summary').textContent = 'Source reconciliation checks could not be loaded.';
    console.error('National merchandise dashboard could not load:', error);
  }
}

function bindNationalControls() {
  document.querySelector('#national-month').addEventListener('change', event => loadNationalMonth(event.target.value));
  document.querySelector('#national-range').addEventListener('change', renderNationalHistory);
  ['chapter', 'partner'].forEach(kind => {
    document.querySelector(`#national-${kind}-search`).addEventListener('input', () => renderNationalTable(kind));
    document.querySelector(`#national-${kind}-sort`).addEventListener('change', () => renderNationalTable(kind));
    document.querySelector(`#national-${kind}-flow`).addEventListener('change', event => {
      if (event.target.value !== 'both') document.querySelector(`#national-${kind}-sort`).value = event.target.value;
      renderNationalTable(kind);
    });
    document.querySelector(`#national-${kind}-reset`).addEventListener('click', () => resetNationalFilters(kind));
    document.querySelector(`#national-${kind}-download`).addEventListener('click', () => downloadNationalCsv(kind));
  });
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-national-explore]');
    if (!button || !nationalState.detail) return;
    const kind = button.dataset.nationalExplore;
    const row = nationalState.detail[kind === 'chapter' ? 'chapters' : 'partners'].find(item => nationalRowKey(item) === button.dataset.nationalCode);
    if (!row) return;
    document.querySelector(`#national-${kind}-search`).value = row.name;
    document.querySelector(`#national-${kind}-flow`).value = 'both';
    document.querySelector(`#national-${kind}-sort`).value = button.classList.contains('exports') ? 'exports' : 'imports';
    renderNationalTable(kind);
    window.navigateTracker(kind === 'chapter' ? 'commodities' : 'partners');
  });
  window.addEventListener('tracker:viewchange', syncNationalNavigation);
  syncNationalNavigation();
  initNationalDashboard();
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bindNationalControls, { once: true });
else bindNationalControls();
