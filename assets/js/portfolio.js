function portfolioAnnualRows(months) {
  const grouped = new Map();
  (months || []).forEach(month => {
    const year = String(month.period || '').slice(0, 4);
    if (!year) return;
    if (!grouped.has(year)) grouped.set(year, []);
    grouped.get(year).push(month);
  });
  return [...grouped.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([year, rows]) => {
    const imports = tradeTotal(rows, 'imports');
    const exports = tradeTotal(rows, 'exports');
    const partialMonths = rows.filter(row => row.coverage_status === 'partial').length;
    const unavailableMonths = rows.filter(row => finiteTradeValue(row.imports) === null || finiteTradeValue(row.exports) === null).length;
    const count = new Set(rows.map(row => row.period)).size;
    const notes = [];
    if (count !== 12) notes.push(`${count} of 12 calendar months in this selection.`);
    if (partialMonths) notes.push(`${partialMonths} month${partialMonths === 1 ? ' has' : 's have'} incomplete commodity coverage.`);
    if (unavailableMonths) notes.push(`${unavailableMonths} month${unavailableMonths === 1 ? ' has' : 's have'} unavailable trade values; totals use reported values.`);
    return {
      year,
      months: count,
      imports,
      exports,
      balance: imports === null || exports === null ? null : exports - imports,
      coverage: partialMonths || unavailableMonths || count !== 12 ? 'partial' : 'complete',
      coverageLabel: partialMonths || unavailableMonths ? 'Partial coverage' : count === 12 ? 'Full year' : 'Partial year',
      coverageNote: notes.join(' '),
    };
  });
}

function renderPortfolioHistory(dashboard) {
  const months = dashboard?.monthly || [];
  const rangeControl = document.querySelector('#portfolio-range');
  const range = rangeControl?.value || 'all';
  const visible = rangeMonths(months, range);
  renderLineChart('portfolio-history-chart', visible, [
    { label: 'Imports', className: 'imports-line', value: row => row.imports },
    { label: 'Exports', className: 'exports-line', value: row => row.exports },
  ], { label: 'Portfolio monthly imports and exports' });

  const kpis = document.querySelector('#portfolio-history-kpis');
  const annualBody = document.querySelector('#portfolio-annual-table-body');
  if (!visible.length) {
    if (kpis) kpis.innerHTML = '';
    if (annualBody) annualBody.innerHTML = '<tr><td colspan="6">No observations for this selection.</td></tr>';
    return;
  }
  const totalImports = tradeTotal(visible, 'imports');
  const totalExports = tradeTotal(visible, 'exports');
  const peak = visible.filter(row => finiteTradeValue(row.imports) !== null)
    .reduce((best, row) => !best || Number(row.imports) > Number(best.imports) ? row : best, null);
  const partialMonths = visible.filter(row => row.coverage_status === 'partial').length;
  const unavailableMonths = visible.filter(row => finiteTradeValue(row.imports) === null || finiteTradeValue(row.exports) === null).length;
  const calendarCount = calendarMonthNumber(visible.at(-1).period) - calendarMonthNumber(visible[0].period) + 1;
  const missingMonths = calendarCount - visible.length;
  const coverage = [
    partialMonths ? `${partialMonths} partial-coverage month${partialMonths === 1 ? '' : 's'}` : '',
    missingMonths > 0 ? `${missingMonths} unreported month${missingMonths === 1 ? '' : 's'}` : '',
    unavailableMonths ? `${unavailableMonths} month${unavailableMonths === 1 ? '' : 's'} with unavailable values` : '',
  ].filter(Boolean).join(' · ');
  if (kpis) kpis.innerHTML = `
    <article class="intel-kpi"><span>Selected range</span><strong>${visible.length} months</strong><small>${esc(periodLabel(visible[0].period))} – ${esc(periodLabel(visible.at(-1).period))}</small></article>
    <article class="intel-kpi"><span>Imports in selected range</span><strong>${usdMillions(totalImports)}</strong><small>${esc(coverage || 'Observed portfolio totals')}</small></article>
    <article class="intel-kpi"><span>Exports in selected range</span><strong>${usdMillions(totalExports)}</strong><small>Overlapping HS headings counted once</small></article>
    <article class="intel-kpi"><span>Peak import month in range</span><strong>${peak ? esc(periodLabel(peak.period)) : '—'}</strong><small>${peak ? usdMillions(peak.imports) : '—'}${peak?.coverage_status === 'partial' ? ' · Partial coverage' : ''}</small></article>
  `;

  const annual = portfolioAnnualRows(visible).reverse();
  if (annualBody) annualBody.innerHTML = annual.map(row => `
    <tr>
      <td>${esc(row.year)}</td>
      <td>${row.months} / 12</td>
      <td>${usdMillions(row.imports)}</td>
      <td>${usdMillions(row.exports)}</td>
      <td>${usdMillions(row.balance)}</td>
      <td><span class="coverage-badge ${row.coverage}">${esc(row.coverageLabel)}</span>${row.coverageNote ? `<small class="table-subtext">${esc(row.coverageNote)}</small>` : ''}</td>
    </tr>
  `).join('');

  if (rangeControl && !rangeControl.dataset.bound) {
    rangeControl.addEventListener('change', () => renderPortfolioHistory(window.trackerDashboard));
    rangeControl.dataset.bound = 'true';
  }
}

window.renderPortfolioHistory = renderPortfolioHistory;
if (window.trackerDashboard) renderPortfolioHistory(window.trackerDashboard);
