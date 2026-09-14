function portfolioAnnualRows(months) {
  const grouped = new Map();
  (months || []).forEach(month => {
    const year = String(month.period || '').slice(0, 4);
    if (!year) return;
    if (!grouped.has(year)) grouped.set(year, []);
    grouped.get(year).push(month);
  });
  return [...grouped.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([year, rows]) => {
    const imports = rows.reduce((sum, row) => sum + Number(row.imports || 0), 0);
    const exports = rows.reduce((sum, row) => sum + Number(row.exports || 0), 0);
    const partial = rows.some(row => row.coverage_status === 'partial');
    return {
      year,
      months: rows.length,
      imports,
      exports,
      balance: exports - imports,
      coverage: partial || rows.length !== 12 ? 'partial' : 'complete',
    };
  });
}

function renderPortfolioHistory(dashboard) {
  const months = dashboard?.monthly || [];
  if (!months.length) return;
  const rangeControl = document.querySelector('#portfolio-range');
  const range = rangeControl?.value || 'all';
  const visible = rangeMonths(months, range);
  renderLineChart('portfolio-history-chart', visible, [
    { label: 'Portfolio imports', className: 'imports-line', value: row => row.imports },
    { label: 'Portfolio exports', className: 'exports-line', value: row => row.exports },
  ]);

  const totalImports = months.reduce((sum, row) => sum + Number(row.imports || 0), 0);
  const totalExports = months.reduce((sum, row) => sum + Number(row.exports || 0), 0);
  const peak = months.reduce((best, row) => !best || Number(row.imports || 0) > Number(best.imports || 0) ? row : best, null);
  const partialMonths = months.filter(row => row.coverage_status === 'partial').length;
  document.querySelector('#portfolio-history-kpis').innerHTML = `
    <article class="intel-kpi"><span>Observed history</span><strong>${months.length} months</strong><small>${esc(months[0].period)} → ${esc(months.at(-1).period)}</small></article>
    <article class="intel-kpi"><span>Cumulative imports</span><strong>${usdMillions(totalImports)}</strong><small>Watched HS universe</small></article>
    <article class="intel-kpi"><span>Cumulative exports</span><strong>${usdMillions(totalExports)}</strong><small>Overlap-adjusted portfolio</small></article>
    <article class="intel-kpi"><span>Peak import month</span><strong>${peak ? periodLabel(peak.period) : '—'}</strong><small>${peak ? usdMillions(peak.imports) : '—'} · ${partialMonths} partial-coverage month${partialMonths === 1 ? '' : 's'}</small></article>
  `;

  const annual = portfolioAnnualRows(months).reverse();
  document.querySelector('#portfolio-annual-table-body').innerHTML = annual.map(row => `
    <tr>
      <td>${esc(row.year)}</td>
      <td>${row.months}</td>
      <td>${usdMillions(row.imports)}</td>
      <td>${usdMillions(row.exports)}</td>
      <td>${usdMillions(row.balance)}</td>
      <td><span class="coverage-badge ${row.coverage}">${esc(row.coverage)}</span></td>
    </tr>
  `).join('');

  if (rangeControl && !rangeControl.dataset.bound) {
    rangeControl.addEventListener('change', () => renderPortfolioHistory(window.trackerDashboard));
    rangeControl.dataset.bound = 'true';
  }
}

window.renderPortfolioHistory = renderPortfolioHistory;
if (window.trackerDashboard) renderPortfolioHistory(window.trackerDashboard);
