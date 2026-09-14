const intelligenceState = {
  data: null,
  commodityId: null,
};

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function periodLabel(period) {
  if (!period || !/^\d{4}-\d{2}$/.test(period)) return period || '—';
  const [year, month] = period.split('-').map(Number);
  return new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric' }).format(new Date(Date.UTC(year, month - 1, 1)));
}

function rangeMonths(months, range) {
  if (range === '12') return months.slice(-12);
  if (range === '36') return months.slice(-36);
  if (range === '60') return months.slice(-60);
  return months;
}

function seriesPath(values, width, height, padding, maxValue) {
  const usableWidth = width - padding * 2;
  const usableHeight = height - padding * 2;
  if (!values.length) return '';
  return values.map((value, index) => {
    const x = padding + (values.length === 1 ? usableWidth / 2 : (index / (values.length - 1)) * usableWidth);
    const y = padding + usableHeight - ((Number(value) || 0) / maxValue) * usableHeight;
    return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(' ');
}

function renderLineChart(targetId, rows, series) {
  const target = document.querySelector(`#${targetId}`);
  if (!target) return;
  if (!rows.length) {
    target.innerHTML = '<div class="intel-empty">No observations for this selection.</div>';
    return;
  }

  const width = 900;
  const height = 300;
  const padding = 34;
  const allValues = series.flatMap(item => rows.map(row => Number(item.value(row)) || 0));
  const maxValue = Math.max(...allValues, 1);
  const gridLines = [0, .25, .5, .75, 1].map(fraction => {
    const y = padding + (height - padding * 2) * (1 - fraction);
    return `<line x1="${padding}" y1="${y}" x2="${width - padding}" y2="${y}" class="chart-grid-line" />`;
  }).join('');
  const paths = series.map(item => {
    const values = rows.map(row => item.value(row));
    return `<path d="${seriesPath(values, width, height, padding, maxValue)}" class="chart-line ${item.className}" />`;
  }).join('');

  const labelIndexes = [...new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1])];
  const labels = labelIndexes.map(index => {
    const x = padding + (rows.length === 1 ? (width - padding * 2) / 2 : (index / (rows.length - 1)) * (width - padding * 2));
    return `<text x="${x}" y="${height - 8}" text-anchor="middle" class="chart-axis-label">${esc(rows[index].period)}</text>`;
  }).join('');

  target.innerHTML = `
    <svg class="intel-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Historical trade chart">
      ${gridLines}${paths}${labels}
    </svg>
    <div class="chart-legend">${series.map(item => `<span class="legend-item"><i class="${item.className}"></i>${esc(item.label)}</span>`).join('')}</div>
  `;
}

function aggregatePartners(months, key) {
  const totals = new Map();
  months.forEach(month => {
    (month[key] || []).forEach(row => {
      totals.set(row.partner_country, (totals.get(row.partner_country) || 0) + Number(row.value || 0));
    });
  });
  return [...totals.entries()]
    .map(([partner_country, value]) => ({ partner_country, value }))
    .sort((a, b) => b.value - a.value);
}

function renderOverall(data) {
  const months = data.monthly || [];
  const latest = months.at(-1) || {};
  const totalImports = months.reduce((sum, month) => sum + Number(month.imports || 0), 0);
  const totalExports = months.reduce((sum, month) => sum + Number(month.exports || 0), 0);
  const topAllTime = aggregatePartners(months, 'imports_by_country')[0];
  const peakImport = months.reduce((best, month) => !best || Number(month.imports || 0) > Number(best.imports || 0) ? month : best, null);
  const dependency = latest.dependency || {};
  const supplier = latest.supplier_concentration?.top_partners?.[0];

  document.querySelector('#intel-overall-kpis').innerHTML = `
    <article class="intel-kpi"><span>Historical imports</span><strong>${usdMillions(totalImports)}</strong><small>${esc(data.coverage.first_period)} → ${esc(data.coverage.last_period)}</small></article>
    <article class="intel-kpi"><span>Historical exports</span><strong>${usdMillions(totalExports)}</strong><small>Observed months: ${months.length}</small></article>
    <article class="intel-kpi"><span>Historical net balance</span><strong>${usdMillions(totalExports - totalImports)}</strong><small>Exports minus imports</small></article>
    <article class="intel-kpi"><span>Latest dependency</span><strong>${dependency.score ?? '—'}</strong><small>${esc(dependency.risk || 'not available')}</small></article>
  `;

  document.querySelector('#intel-insights').innerHTML = `
    <div class="insight-card"><span>Peak import month</span><strong>${peakImport ? periodLabel(peakImport.period) : '—'}</strong><small>${peakImport ? usdMillions(peakImport.imports) : '—'}</small></div>
    <div class="insight-card"><span>Latest top supplier</span><strong>${esc(supplier?.partner_country || '—')}</strong><small>${supplier?.share_pct ?? '—'}% of latest imports</small></div>
    <div class="insight-card"><span>Largest supplier over history</span><strong>${esc(topAllTime?.partner_country || '—')}</strong><small>${topAllTime ? usdMillions(topAllTime.value) : '—'}</small></div>
    <div class="insight-card"><span>Latest supplier HHI</span><strong>${latest.supplier_concentration?.hhi ?? '—'}</strong><small>Higher means more concentrated</small></div>
  `;
}

function renderTrend() {
  const data = intelligenceState.data;
  if (!data) return;
  const range = document.querySelector('#intel-range').value;
  const months = rangeMonths(data.monthly || [], range);
  renderLineChart('intel-trade-chart', months, [
    { label: 'Imports', className: 'imports-line', value: row => row.imports },
    { label: 'Exports', className: 'exports-line', value: row => row.exports },
  ]);
}

function countryRows(month) {
  const imports = new Map((month.imports_by_country || []).map(row => [row.partner_country, row]));
  const exports = new Map((month.exports_by_country || []).map(row => [row.partner_country, row]));
  const countries = new Set([...imports.keys(), ...exports.keys()]);
  return [...countries].map(country => ({
    country,
    importValue: imports.get(country)?.value || 0,
    importShare: imports.get(country)?.share_pct,
    exportValue: exports.get(country)?.value || 0,
    exportShare: exports.get(country)?.share_pct,
  })).sort((a, b) => b.importValue - a.importValue || b.exportValue - a.exportValue);
}

function renderMonthDetail() {
  const data = intelligenceState.data;
  if (!data) return;
  const period = document.querySelector('#intel-month').value;
  const month = (data.monthly || []).find(item => item.period === period);
  if (!month) return;

  document.querySelector('#intel-month-summary').innerHTML = `
    <div><span>Imports</span><strong>${usdMillions(month.imports)}</strong></div>
    <div><span>Exports</span><strong>${usdMillions(month.exports)}</strong></div>
    <div><span>Balance</span><strong>${usdMillions(month.balance)}</strong></div>
    <div><span>Import YoY</span><strong>${pct(month.import_yoy_pct)}</strong></div>
  `;

  const rows = countryRows(month);
  document.querySelector('#intel-country-table-body').innerHTML = rows.map(row => `
    <tr>
      <td>${esc(row.country)}</td>
      <td>${usdMillions(row.importValue)}</td>
      <td>${row.importShare === null || row.importShare === undefined ? '—' : `${row.importShare}%`}</td>
      <td>${usdMillions(row.exportValue)}</td>
      <td>${row.exportShare === null || row.exportShare === undefined ? '—' : `${row.exportShare}%`}</td>
    </tr>
  `).join('') || '<tr><td colspan="5">No partner-country rows available.</td></tr>';

  const top = (month.imports_by_country || []).slice(0, 10);
  const max = Math.max(...top.map(row => Number(row.value || 0)), 1);
  document.querySelector('#intel-supplier-bars').innerHTML = top.map(row => `
    <div class="country-bar-row">
      <span>${esc(row.partner_country)}</span>
      <div class="country-bar-track"><i style="width:${Math.max((Number(row.value || 0) / max) * 100, 1)}%"></i></div>
      <strong>${row.share_pct ?? '—'}%</strong>
    </div>
  `).join('') || '<div class="intel-empty">No supplier data for this month.</div>';

  const quantity = month.unit_values?.aggregate || {};
  const importUnit = quantity.import;
  const exportUnit = quantity.export;
  document.querySelector('#intel-unit-values').innerHTML = `
    <div><span>Import quantity</span><strong>${physicalQuantity(importUnit)}</strong></div>
    <div><span>Implied import unit</span><strong>${impliedUnitValue(importUnit)}</strong></div>
    <div><span>Export quantity</span><strong>${physicalQuantity(exportUnit)}</strong></div>
    <div><span>Implied export unit</span><strong>${impliedUnitValue(exportUnit)}</strong></div>
  `;
}

function allCountries(data) {
  const totals = new Map();
  (data.monthly || []).forEach(month => {
    [...(month.imports_by_country || []), ...(month.exports_by_country || [])].forEach(row => {
      totals.set(row.partner_country, (totals.get(row.partner_country) || 0) + Number(row.value || 0));
    });
  });
  return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([country]) => country);
}

function renderCountryHistory() {
  const data = intelligenceState.data;
  if (!data) return;
  const country = document.querySelector('#intel-country').value;
  const rows = (data.monthly || []).map(month => {
    const importRow = (month.imports_by_country || []).find(row => row.partner_country === country);
    const exportRow = (month.exports_by_country || []).find(row => row.partner_country === country);
    return {
      period: month.period,
      imports: importRow?.value || 0,
      exports: exportRow?.value || 0,
    };
  });
  renderLineChart('intel-country-chart', rows, [
    { label: `${country} imports`, className: 'imports-line', value: row => row.imports },
    { label: `${country} exports`, className: 'exports-line', value: row => row.exports },
  ]);
}

function renderAnnual(data) {
  document.querySelector('#intel-annual-table-body').innerHTML = (data.annual || []).slice().reverse().map(row => {
    const supplier = row.top_import_partners?.[0];
    return `
      <tr>
        <td>${esc(row.year)}</td>
        <td>${row.months_observed}</td>
        <td>${usdMillions(row.imports)}</td>
        <td>${usdMillions(row.exports)}</td>
        <td>${usdMillions(row.balance)}</td>
        <td>${esc(supplier?.partner_country || '—')}</td>
        <td>${supplier?.share_pct ?? '—'}%</td>
        <td>${row.supplier_concentration?.hhi ?? '—'}</td>
      </tr>`;
  }).join('');
}

function renderGaps(data) {
  const gaps = data.coverage?.history_gaps || [];
  const target = document.querySelector('#intel-gaps');
  target.hidden = gaps.length === 0;
  target.innerHTML = gaps.map(gap => `<strong>${esc(gap.period)}</strong> — ${esc(gap.note)}`).join('<br>');
}

function initializeIntelligenceControls(data) {
  const month = document.querySelector('#intel-month');
  month.innerHTML = (data.monthly || []).slice().reverse().map(row => `<option value="${esc(row.period)}">${esc(periodLabel(row.period))}</option>`).join('');
  month.value = data.monthly.at(-1)?.period || '';

  const countries = allCountries(data);
  const country = document.querySelector('#intel-country');
  country.innerHTML = countries.map(name => `<option value="${esc(name)}">${esc(name)}</option>`).join('');

  month.onchange = renderMonthDetail;
  country.onchange = renderCountryHistory;
  document.querySelector('#intel-range').onchange = renderTrend;
}

async function openCommodityIntelligence(commodityId, commodityName) {
  const section = document.querySelector('#intelligence-section');
  const body = document.querySelector('#intel-body');
  section.hidden = false;
  document.querySelector('#intel-title').textContent = commodityName || commodityId;
  document.querySelector('#intel-subtitle').textContent = 'Loading historical country and trade intelligence…';
  body.hidden = true;
  section.scrollIntoView({ behavior: 'smooth', block: 'start' });

  try {
    const data = await loadJSON(`data/intelligence/${commodityId}.json`);
    intelligenceState.data = data;
    intelligenceState.commodityId = commodityId;
    document.querySelector('#intel-title').textContent = data.commodity?.name || commodityName || commodityId;
    document.querySelector('#intel-subtitle').textContent = `${data.commodity?.category || ''} · ${data.coverage?.first_period || '—'} to ${data.coverage?.last_period || '—'} · ${data.coverage?.months_observed || 0} observed months`;
    initializeIntelligenceControls(data);
    renderOverall(data);
    renderTrend();
    renderMonthDetail();
    renderCountryHistory();
    renderAnnual(data);
    renderGaps(data);
    body.hidden = false;
  } catch (err) {
    document.querySelector('#intel-subtitle').textContent = `Unable to load commodity intelligence: ${err.message}`;
  }
}

window.openCommodityIntelligence = openCommodityIntelligence;

document.querySelector('#intel-close')?.addEventListener('click', () => {
  document.querySelector('#intelligence-section').hidden = true;
});
