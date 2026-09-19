const intelligenceState = {
  data: null,
  commodityId: null,
  monthByPeriod: new Map(),
  countrySeries: new Map(),
  countries: [],
  requestId: 0,
  controller: null,
  returnFocus: null,
  cache: new Map(),
};

const intelligencePeriodFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
});

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function periodLabel(period) {
  if (calendarMonthNumber(period) === null) return period || '—';
  const [year, month] = period.split('-').map(Number);
  return intelligencePeriodFormatter.format(new Date(Date.UTC(year, month - 1, 1)));
}

// Values are stored in USD millions. Missing values must stay missing on charts.
function finiteTradeValue(value) {
  if (!['number', 'string'].includes(typeof value) || (typeof value === 'string' && !value.trim())) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function calendarMonthNumber(period) {
  if (!/^\d{4}-\d{2}$/.test(period || '')) return null;
  const [year, month] = period.split('-').map(Number);
  return month >= 1 && month <= 12 ? year * 12 + month - 1 : null;
}

function calendarPeriod(number) {
  return `${Math.floor(number / 12)}-${String(number % 12 + 1).padStart(2, '0')}`;
}

function rangeMonths(months, range) {
  if (!['12', '36', '60'].includes(String(range)) || !months.length) return months;
  const latest = calendarMonthNumber(months.at(-1).period);
  if (latest === null) return months;
  const first = latest - Number(range) + 1;
  return months.filter(row => {
    const month = calendarMonthNumber(row.period);
    return month !== null && month >= first && month <= latest;
  });
}

function chartCalendarRows(rows, gaps = []) {
  const byPeriod = new Map(rows.filter(row => calendarMonthNumber(row.period) !== null).map(row => [row.period, row]));
  const periods = [...byPeriod.keys()].sort();
  if (!periods.length) return [];
  const gapNotes = new Map(gaps.map(gap => [gap.period, gap.note]));
  const first = calendarMonthNumber(periods[0]);
  const last = calendarMonthNumber(periods.at(-1));
  const calendar = [];
  for (let month = first; month <= last; month += 1) {
    const period = calendarPeriod(month);
    calendar.push(byPeriod.get(period) || {
      period, imports: null, exports: null, chartMissing: true,
      coverage_note: gapNotes.get(period) || 'No observation was reported for this month. This gap is not zero trade.',
    });
  }
  return calendar;
}

function seriesPath(values, width, height, padding, maxValue) {
  const inset = typeof padding === 'number'
    ? { left: padding, right: padding, top: padding, bottom: padding }
    : padding;
  const usableWidth = width - inset.left - inset.right;
  const usableHeight = height - inset.top - inset.bottom;
  const commands = [];
  let connected = false;
  values.forEach((value, index) => {
    const number = finiteTradeValue(value);
    if (number === null) {
      connected = false;
      return;
    }
    const x = inset.left + (values.length === 1 ? usableWidth / 2 : index / (values.length - 1) * usableWidth);
    const y = inset.top + usableHeight - number / maxValue * usableHeight;
    commands.push(`${connected ? 'L' : 'M'} ${x.toFixed(1)} ${y.toFixed(1)}`);
    connected = true;
  });
  return commands.join(' ');
}

function rowCoverageNote(row, values = []) {
  if (row.chartMissing) return row.coverage_note;
  const notes = [];
  if (row.coverage_status === 'partial' || row.status === 'partial') {
    const observed = row.observed_commodity_count;
    const expected = row.expected_commodity_count;
    notes.push(Number.isFinite(observed) && Number.isFinite(expected)
      ? `Partial coverage: ${observed} of ${expected} commodity groups reported.`
      : 'Partial coverage: totals include only available observations.');
    if (row.missing_commodities?.length) {
      notes.push(`Missing: ${row.missing_commodities.map(name => name.replaceAll('_', ' ')).join(', ')}.`);
    }
  }
  if (values.some(value => finiteTradeValue(value) === null)) notes.push('An unavailable value is shown as a gap, not zero.');
  return notes.join(' ');
}

const chartCleanup = new WeakMap();
const chartReadoutFormatter = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

function chartValueLabel(value) {
  const number = finiteTradeValue(value);
  if (number === null) return 'Unavailable';
  const amount = Math.abs(number);
  const sign = number < 0 ? '−' : '';
  if (amount >= 1000) return `${sign}$${chartReadoutFormatter.format(amount / 1000)}B`;
  return `${sign}$${chartReadoutFormatter.format(amount)}M`;
}

function renderLineChart(targetId, rows, series, options = {}) {
  const target = document.getElementById(targetId);
  if (!target) return;
  chartCleanup.get(target)?.();
  const calendar = chartCalendarRows(rows, options.gaps);
  if (!calendar.length) {
    target.innerHTML = '<div class="intel-empty">No observations for this selection.</div>';
    return;
  }

  const targetWidth = target.clientWidth - (parseFloat(getComputedStyle(target).paddingLeft) || 0) - (parseFloat(getComputedStyle(target).paddingRight) || 0);
  const width = Math.max(240, Math.round(targetWidth) || 800);
  const height = width < 520 ? 248 : 290;
  const padding = { left: 56, right: 18, top: 23, bottom: 35 };
  const usableWidth = width - padding.left - padding.right;
  const usableHeight = height - padding.top - padding.bottom;
  const values = series.map(item => calendar.map(row => finiteTradeValue(item.value(row))));
  const maxObserved = Math.max(0, ...values.flat().filter(value => value !== null));
  const roughStep = (maxObserved || 1) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const step = ([1, 2, 2.5, 5, 10].find(number => number * magnitude >= roughStep) || 10) * magnitude;
  const maxValue = Math.ceil((maxObserved || 1) / step) * step;
  const xFor = index => padding.left + (calendar.length === 1 ? usableWidth / 2 : index / (calendar.length - 1) * usableWidth);
  const yFor = value => padding.top + usableHeight - value / maxValue * usableHeight;
  const gridLines = [];
  for (let tick = 0; tick <= maxValue + step / 2; tick += step) {
    const y = yFor(tick);
    gridLines.push(`<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" class="chart-grid-line" /><text x="${padding.left - 10}" y="${y + 4}" text-anchor="end" class="chart-axis-label">${esc(chartValueLabel(tick))}</text>`);
  }
  const paths = series.map((item, index) => `<path d="${seriesPath(values[index], width, height, padding, maxValue)}" class="chart-line ${esc(item.className)}" />`).join('');
  const labelCount = width >= 680 ? 5 : 3;
  const labelIndexes = [...new Set(Array.from({ length: labelCount }, (_, index) => Math.round(index / (labelCount - 1) * (calendar.length - 1))))];
  const labels = labelIndexes.map(index => `<text x="${xFor(index)}" y="${height - 8}" text-anchor="${index === 0 ? 'start' : index === calendar.length - 1 ? 'end' : 'middle'}" class="chart-axis-label">${esc(periodLabel(calendar[index].period))}</text>`).join('');
  const missingMonths = calendar.filter(row => row.chartMissing).length;
  const partialMonths = calendar.filter(row => row.coverage_status === 'partial' || row.status === 'partial').length;
  const invalidMonths = calendar.filter((row, index) => !row.chartMissing && values.some(item => item[index] === null)).length;
  const coverageMessages = [];
  if (missingMonths) coverageMessages.push(`${missingMonths} unreported month${missingMonths === 1 ? '' : 's'} shown as ${missingMonths === 1 ? 'a gap' : 'gaps'}.`);
  if (partialMonths) coverageMessages.push(`${partialMonths} month${partialMonths === 1 ? ' has' : 's have'} partial coverage; totals use available observations.`);
  if (invalidMonths) coverageMessages.push(`${invalidMonths} month${invalidMonths === 1 ? ' has an unavailable value' : 's have unavailable values'}.`);
  const chartLabel = options.label || 'Monthly imports and exports';
  target.innerHTML = `
    <div class="chart-frame" tabindex="0" role="slider" aria-label="${esc(chartLabel)}: reporting month" aria-orientation="horizontal" aria-valuemin="1" aria-valuemax="${calendar.length}" aria-valuenow="${calendar.length}" aria-describedby="${targetId}-help">
      <svg class="intel-chart" viewBox="0 0 ${width} ${height}" aria-hidden="true">
        <text x="${padding.left}" y="12" class="chart-axis-label">USD</text>
        ${gridLines.join('')}${paths}${labels}
        <line class="chart-cursor" x1="0" x2="0" y1="${padding.top}" y2="${height - padding.bottom}" />
        ${series.map((item, index) => `<circle class="chart-point" data-series="${index}" r="4" style="fill:var(${item.className === 'exports-line' ? '--export' : '--accent'})" />`).join('')}
      </svg>
    </div>
    <div class="chart-legend">${series.map(item => `<span class="legend-item"><i class="${esc(item.className)}" aria-hidden="true"></i>${esc(item.label)}</span>`).join('')}</div>
    <div class="chart-readout">
      <span class="chart-readout-period"></span>
      ${series.map((item, index) => `<span class="chart-readout-item"><span>${esc(item.label)}</span><strong class="chart-readout-value" data-series="${index}"></strong></span>`).join('')}
    </div>
    <p class="chart-coverage-note" data-month-coverage hidden></p>
    <p class="chart-range-label">${esc(periodLabel(calendar[0].period))} – ${esc(periodLabel(calendar.at(-1).period))} · ${calendar.length - missingMonths} reported month${calendar.length - missingMonths === 1 ? '' : 's'}</p>
    ${coverageMessages.length ? `<p class="chart-coverage-note">${esc(coverageMessages.join(' '))}</p>` : ''}
    <p class="chart-help" id="${targetId}-help">Hover or touch to inspect a month. Focus the chart and use ← / → to move, or Home / End. ${esc(options.note || '')}</p>
  `;
  const frame = target.querySelector('.chart-frame');
  const svg = target.querySelector('svg');
  const cursor = target.querySelector('.chart-cursor');
  const points = [...target.querySelectorAll('.chart-point')];
  const readoutValues = [...target.querySelectorAll('.chart-readout-value')];
  const period = target.querySelector('.chart-readout-period');
  const note = target.querySelector('[data-month-coverage]');
  let activeIndex = -1;
  let pointerFrame = 0;
  let pointerX = null;
  const updateReadout = index => {
    index = Math.max(0, Math.min(calendar.length - 1, index));
    if (index === activeIndex) return;
    activeIndex = index;
    const row = calendar[index];
    const label = periodLabel(row.period);
    period.textContent = label;
    const currentValues = values.map(items => items[index]);
    const coverage = rowCoverageNote(row, currentValues);
    note.textContent = coverage;
    note.hidden = !coverage;
    cursor.setAttribute('x1', xFor(index));
    cursor.setAttribute('x2', xFor(index));
    currentValues.forEach((value, seriesIndex) => {
      readoutValues[seriesIndex].textContent = chartValueLabel(value);
      points[seriesIndex].style.display = value === null ? 'none' : '';
      if (value !== null) {
        points[seriesIndex].setAttribute('cx', xFor(index));
        points[seriesIndex].setAttribute('cy', yFor(value));
      }
    });
    frame.setAttribute('aria-valuenow', index + 1);
    frame.setAttribute('aria-valuetext', `${label}. ${series.map((item, seriesIndex) => `${item.label}: ${chartValueLabel(currentValues[seriesIndex])}`).join('. ')}.${coverage ? ` ${coverage}` : ''}`);
  };
  const selectPointer = event => {
    if (event.pointerType === 'touch' && event.type === 'pointermove') return;
    pointerX = event.clientX;
    if (pointerFrame) return;
    pointerFrame = requestAnimationFrame(() => {
      pointerFrame = 0;
      const rect = svg.getBoundingClientRect();
      if (!rect.width) return;
      const localX = (pointerX - rect.left) / rect.width * width;
      updateReadout(Math.round((localX - padding.left) / usableWidth * (calendar.length - 1)));
    });
  };
  frame.addEventListener('pointermove', selectPointer);
  frame.addEventListener('pointerdown', selectPointer);
  frame.addEventListener('keydown', event => {
    const changes = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1, PageUp: 12, PageDown: -12 };
    if (Object.hasOwn(changes, event.key)) {
      event.preventDefault();
      updateReadout(activeIndex + changes[event.key]);
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      updateReadout(event.key === 'Home' ? 0 : calendar.length - 1);
    }
  });
  const savedIndex = options.activePeriod ? calendar.findIndex(row => row.period === options.activePeriod) : -1;
  updateReadout(savedIndex >= 0 ? savedIndex : calendar.length - 1);

  let resizeFrame = 0;
  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(() => {
    const nextWidth = target.clientWidth - (parseFloat(getComputedStyle(target).paddingLeft) || 0) - (parseFloat(getComputedStyle(target).paddingRight) || 0);
    if (nextWidth < 1 || Math.abs(Math.max(240, Math.round(nextWidth)) - width) < 2 || resizeFrame) return;
    resizeFrame = requestAnimationFrame(() => {
      resizeFrame = 0;
      const wasFocused = document.activeElement === frame;
      renderLineChart(targetId, rows, series, { ...options, activePeriod: calendar[activeIndex]?.period });
      if (wasFocused) target.querySelector('.chart-frame')?.focus({ preventScroll: true });
    });
  }) : null;
  observer?.observe(target);
  chartCleanup.set(target, () => {
    observer?.disconnect();
    cancelAnimationFrame(pointerFrame);
    cancelAnimationFrame(resizeFrame);
  });
}

function partnerShare(row, total) {
  const reported = finiteTradeValue(row?.share_pct);
  if (reported !== null) return reported;
  const value = row ? finiteTradeValue(row.value) : 0;
  const denominator = finiteTradeValue(total);
  return value !== null && denominator > 0 ? Math.round(value / denominator * 10000) / 100 : null;
}

function shareLabel(value) {
  return finiteTradeValue(value) === null ? '—' : `${chartReadoutFormatter.format(Number(value))}%`;
}

function tradeTotal(months, key) {
  const values = months.map(row => finiteTradeValue(row[key])).filter(value => value !== null);
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
}

function aggregatePartners(months, key) {
  const totals = new Map();
  months.forEach(month => {
    (month[key] || []).forEach(row => {
      const value = finiteTradeValue(row.value);
      if (value !== null) totals.set(row.partner_country, (totals.get(row.partner_country) || 0) + value);
    });
  });
  return [...totals.entries()]
    .map(([partner_country, value]) => ({ partner_country, value }))
    .sort((a, b) => b.value - a.value);
}

function buildIntelligenceIndexes(data) {
  const months = data.monthly || [];
  const monthByPeriod = new Map();
  const countryTotals = new Map();
  const countrySeries = new Map();
  // A partner absent from a complete monthly country table has no reported value.
  // An unavailable monthly table/total stays null, and absent calendar months stay gaps.
  const emptyCountryMonth = month => ({
    period: month.period,
    imports: Array.isArray(month.imports_by_country) && finiteTradeValue(month.imports) !== null ? 0 : null,
    exports: Array.isArray(month.exports_by_country) && finiteTradeValue(month.exports) !== null ? 0 : null,
    coverage_status: month.coverage_status,
    status: month.status,
  });
  months.forEach((month, monthIndex) => {
    monthByPeriod.set(month.period, month);
    const visit = (rows, key) => {
      (rows || []).forEach(row => {
        const country = row.partner_country;
        if (!country) return;
        const value = finiteTradeValue(row.value);
        countryTotals.set(country, (countryTotals.get(country) || 0) + (value ?? 0));
        let series = countrySeries.get(country);
        if (!series) {
          series = months.map(emptyCountryMonth);
          countrySeries.set(country, series);
        }
        series[monthIndex][key] = value;
      });
    };
    visit(month.imports_by_country, 'imports');
    visit(month.exports_by_country, 'exports');
  });
  intelligenceState.monthByPeriod = monthByPeriod;
  intelligenceState.countrySeries = countrySeries;
  intelligenceState.countries = [...countryTotals.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([country]) => country);
}

function renderOverall(data) {
  const months = data.monthly || [];
  const latest = months.at(-1) || {};
  const totalImports = tradeTotal(months, 'imports');
  const totalExports = tradeTotal(months, 'exports');
  const balance = totalImports === null || totalExports === null ? null : totalExports - totalImports;
  const topAllTime = aggregatePartners(months, 'imports_by_country')[0];
  const peakImport = months.filter(month => finiteTradeValue(month.imports) !== null)
    .reduce((best, month) => !best || Number(month.imports) > Number(best.imports) ? month : best, null);
  const dependency = latest.dependency || {};
  const supplier = (latest.imports_by_country || [])[0];
  const fullRange = `${periodLabel(data.coverage?.first_period)} – ${periodLabel(data.coverage?.last_period)}`;
  const gapCount = data.coverage?.history_gaps?.length || 0;
  const coverage = `${months.length} observed months${gapCount ? ` · ${gapCount} classification gap${gapCount === 1 ? '' : 's'}` : ''}`;
  document.querySelector('#intel-overall-kpis').innerHTML = `
    <article class="intel-kpi"><span>Whole-history imports</span><strong>${usdMillions(totalImports)}</strong><small>${esc(fullRange)}</small></article>
    <article class="intel-kpi"><span>Whole-history exports</span><strong>${usdMillions(totalExports)}</strong><small>${esc(coverage)}</small></article>
    <article class="intel-kpi"><span>Whole-history balance</span><strong>${usdMillions(balance)}</strong><small>Exports minus imports · observed data</small></article>
    <article class="intel-kpi"><span>Latest dependency</span><strong>${esc(dependency.score ?? '—')}<small>/ 100</small></strong><small>${esc(dependency.risk || 'not available')} · ${esc(periodLabel(latest.period))}</small></article>
  `;
  document.querySelector('#intel-insights').innerHTML = `
    <div class="insight-card"><span>Peak import month · all history</span><strong>${peakImport ? esc(periodLabel(peakImport.period)) : '—'}</strong><small>${peakImport ? usdMillions(peakImport.imports) : '—'}</small></div>
    <div class="insight-card"><span>Latest top supplier</span><strong>${esc(supplier?.partner_country || '—')}</strong><small>${shareLabel(partnerShare(supplier, latest.imports))} of ${esc(periodLabel(latest.period))} imports</small></div>
    <div class="insight-card"><span>Largest supplier · all history</span><strong>${esc(topAllTime?.partner_country || '—')}</strong><small>${topAllTime ? usdMillions(topAllTime.value) : '—'}</small></div>
    <div class="insight-card"><span>Latest supplier HHI</span><strong>${esc(latest.supplier_concentration?.hhi ?? '—')}</strong><small>Higher means more concentrated</small></div>
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
  ], { gaps: data.coverage?.history_gaps, label: `${data.commodity?.name || 'Commodity'} monthly trade` });
}

function countryRows(month) {
  const imports = new Map((month.imports_by_country || []).map(row => [row.partner_country, row]));
  const exports = new Map((month.exports_by_country || []).map(row => [row.partner_country, row]));
  const countries = new Set([...imports.keys(), ...exports.keys()]);
  const valueFor = (map, key, country) => map.has(country)
    ? finiteTradeValue(map.get(country).value)
    : Array.isArray(month[`${key}_by_country`]) && finiteTradeValue(month[key]) !== null ? 0 : null;
  return [...countries].map(country => ({
    country,
    importValue: valueFor(imports, 'imports', country),
    importShare: partnerShare(imports.get(country), month.imports),
    exportValue: valueFor(exports, 'exports', country),
    exportShare: partnerShare(exports.get(country), month.exports),
  })).sort((a, b) => (b.importValue ?? -1) - (a.importValue ?? -1) || (b.exportValue ?? -1) - (a.exportValue ?? -1));
}

function intelligenceQuantityContext(month, trade, commodityId, dashboard = window.trackerDashboard) {
  const metric = month.unit_values?.aggregate?.[trade];
  const availability = typeof quantityAvailability === 'function' ? quantityAvailability(metric) : null;
  if (availability) return availability;
  if (metric?.status === 'ok') return '';

  // Compact v2 intelligence can omit unavailable-reason metadata. Recover only a
  // reason from the matching dashboard snapshot, never a positive quantity or unit
  // value. Both USD totals and the commodity/month must agree so source revisions
  // or a newer dashboard cannot lend current quantity context to historical data.
  if ((!metric || metric.status === 'not_available') && dashboard?.as_of === month.period && commodityId) {
    const latest = dashboard.commodities?.find(row => row.id === commodityId);
    const totalsMatch = latest && ['imports', 'exports'].every(key => {
      const observed = finiteTradeValue(month[key]);
      return observed !== null && observed === finiteTradeValue(latest[key]);
    });
    if (totalsMatch && (!latest.period || latest.period === month.period)) {
      const sourceMetric = latest.unit_values?.aggregate?.[trade];
      const reason = typeof quantityAvailability === 'function' ? quantityAvailability(sourceMetric) : null;
      if (reason && sourceMetric?.status !== 'ok') return reason;
    }
  }
  return 'Validated quantity unavailable for this month.';
}

function renderMonthDetail() {
  const data = intelligenceState.data;
  if (!data) return;
  const period = document.querySelector('#intel-month').value;
  const month = intelligenceState.monthByPeriod.get(period);
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
      <td>${shareLabel(row.importShare)}</td>
      <td>${usdMillions(row.exportValue)}</td>
      <td>${shareLabel(row.exportShare)}</td>
    </tr>
  `).join('') || '<tr><td colspan="5">No partner-country rows available.</td></tr>';

  const top = (month.imports_by_country || []).slice(0, 10);
  const max = Math.max(...top.map(row => Number(row.value || 0)), 1);
  document.querySelector('#intel-supplier-bars').innerHTML = top.map(row => `
    <div class="country-bar-row">
      <span>${esc(row.partner_country)}</span>
      <div class="country-bar-track"><i style="width:${Math.max((Number(row.value || 0) / max) * 100, 0)}%"></i></div>
      <strong>${shareLabel(partnerShare(row, month.imports))}</strong>
    </div>
  `).join('') || '<div class="intel-empty">No supplier data for this month.</div>';

  const quantity = month.unit_values?.aggregate || {};
  const quantityTrade = (label, trade) => {
    const metric = quantity[trade];
    const context = intelligenceQuantityContext(month, trade, data.commodity?.id || intelligenceState.commodityId);
    return `
      <div><span>${label} quantity</span><strong>${esc(physicalQuantity(metric))}</strong>${context ? `<small class="table-subtext">${esc(context)}</small>` : ''}</div>
      <div><span>Implied ${label.toLowerCase()} unit value</span><strong>${esc(impliedUnitValue(metric))}</strong><small class="table-subtext">${metric?.status === 'ok' ? 'Trade value divided by physical quantity.' : 'Requires compatible, validated quantities.'}</small></div>
    `;
  };
  document.querySelector('#intel-unit-values').innerHTML = quantityTrade('Import', 'import') + quantityTrade('Export', 'export');
}

function renderCountryHistory() {
  const data = intelligenceState.data;
  if (!data) return;
  const country = document.querySelector('#intel-country').value;
  const rows = intelligenceState.countrySeries.get(country) || [];
  renderLineChart('intel-country-chart', rows, [
    { label: `${country} imports`, className: 'imports-line', value: row => row.imports },
    { label: `${country} exports`, className: 'exports-line', value: row => row.exports },
  ], { gaps: data.coverage?.history_gaps, label: `${country} monthly trade`, note: 'A zero means no partner value was reported for that observed month.' });
}

function renderAnnual(data) {
  document.querySelector('#intel-annual-table-body').innerHTML = (data.annual || []).slice().reverse().map(row => {
    const supplier = row.top_import_partners?.[0] || row.supplier_concentration?.top_partners?.[0];
    const partial = row.months_observed !== 12 || row.coverage_status === 'partial';
    return `
      <tr>
        <td>${esc(row.year)}${partial ? '<small class="table-subtext">Partial year</small>' : ''}</td>
        <td>${esc(row.months_observed)} / 12</td>
        <td>${usdMillions(row.imports)}</td>
        <td>${usdMillions(row.exports)}</td>
        <td>${usdMillions(row.balance)}</td>
        <td>${esc(supplier?.partner_country || '—')}</td>
        <td>${shareLabel(supplier?.share_pct)}</td>
        <td>${esc(row.supplier_concentration?.hhi ?? '—')}</td>
      </tr>`;
  }).join('') || '<tr><td colspan="8">No annual observations available.</td></tr>';
}

function renderGaps(data) {
  const gaps = data.coverage?.history_gaps || [];
  const target = document.querySelector('#intel-gaps');
  target.hidden = gaps.length === 0;
  target.innerHTML = gaps.map(gap => `<strong>${esc(periodLabel(gap.period))}</strong> — ${esc(gap.note)}`).join('<br>');
}

function initializeIntelligenceControls(data) {
  const month = document.querySelector('#intel-month');
  month.innerHTML = (data.monthly || []).slice().reverse().map(row => `<option value="${esc(row.period)}">${esc(periodLabel(row.period))}</option>`).join('');
  month.value = data.monthly.at(-1)?.period || '';
  month.disabled = !data.monthly.length;
  const country = document.querySelector('#intel-country');
  country.innerHTML = intelligenceState.countries.map(name => `<option value="${esc(name)}">${esc(name)}</option>`).join('') || '<option value="">No partners reported</option>';
  country.disabled = !intelligenceState.countries.length;
  month.onchange = renderMonthDetail;
  country.onchange = renderCountryHistory;
  const range = document.querySelector('#intel-range');
  range.onchange = renderTrend;
  range.value = 'all';
}

async function openCommodityIntelligence(commodityId, commodityName) {
  const section = document.querySelector('#intelligence-section');
  const body = document.querySelector('#intel-body');
  const status = document.querySelector('#intel-status');
  const title = document.querySelector('#intel-title');
  if (!section || !body) return;
  const active = document.activeElement;
  if (active && !section.contains(active)) intelligenceState.returnFocus = active;
  intelligenceState.controller?.abort();
  const requestId = ++intelligenceState.requestId;
  const controller = new AbortController();
  intelligenceState.controller = controller;
  intelligenceState.commodityId = commodityId;
  intelligenceState.data = null;
  window.navigateTracker?.('critical');
  const browser = document.querySelector('#commodity-browser');
  if (browser) browser.hidden = true;
  section.hidden = false;
  section.setAttribute('aria-busy', 'true');
  title.textContent = commodityName || commodityId;
  document.querySelector('#intel-subtitle').textContent = 'Historical trade, suppliers, and country-level detail';
  body.hidden = true;
  if (status) {
    status.hidden = false;
    status.className = 'intel-loading';
    status.innerHTML = '<span class="intel-loading-spinner" aria-hidden="true"></span><span>Loading commodity intelligence…</span>';
  }
  title.tabIndex = -1;
  title.focus({ preventScroll: true });
  section.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });

  try {
    let data = intelligenceState.cache.get(commodityId);
    if (!data) {
      const response = await fetch(`data/intelligence/${encodeURIComponent(commodityId)}.json`, { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      data = await response.json();
      if (!Array.isArray(data.monthly)) throw new Error('Invalid commodity data');
    }
    if (requestId !== intelligenceState.requestId || controller.signal.aborted || section.hidden) return;
    intelligenceState.cache.delete(commodityId);
    intelligenceState.cache.set(commodityId, data);
    if (intelligenceState.cache.size > 3) intelligenceState.cache.delete(intelligenceState.cache.keys().next().value);
    intelligenceState.data = data;
    buildIntelligenceIndexes(data);
    title.textContent = data.commodity?.name || commodityName || commodityId;
    document.querySelector('#intel-subtitle').textContent = [
      data.commodity?.category,
      `${periodLabel(data.coverage?.first_period)} – ${periodLabel(data.coverage?.last_period)}`,
      `${data.coverage?.months_observed ?? data.monthly.length} observed months`,
    ].filter(Boolean).join(' · ');
    initializeIntelligenceControls(data);
    renderOverall(data);
    renderMonthDetail();
    renderAnnual(data);
    renderGaps(data);
    body.hidden = false;
    renderTrend();
    renderCountryHistory();
    if (status) {
      status.hidden = true;
      status.textContent = '';
    }
    section.setAttribute('aria-busy', 'false');
  } catch (error) {
    if (error.name === 'AbortError' || requestId !== intelligenceState.requestId || section.hidden) return;
    section.setAttribute('aria-busy', 'false');
    document.querySelector('#intel-subtitle').textContent = 'Commodity intelligence is temporarily unavailable.';
    if (status) {
      status.hidden = false;
      status.className = 'intel-empty';
      status.innerHTML = '<p>We could not load this commodity. Please try again.</p><button type="button" class="ghost-button">Try again</button>';
      status.querySelector('button').addEventListener('click', () => openCommodityIntelligence(commodityId, commodityName));
    }
  } finally {
    if (requestId === intelligenceState.requestId) intelligenceState.controller = null;
  }
}

function closeCommodityIntelligence() {
  intelligenceState.requestId += 1;
  intelligenceState.controller?.abort();
  intelligenceState.controller = null;
  const section = document.querySelector('#intelligence-section');
  if (!section) return;
  section.hidden = true;
  section.setAttribute('aria-busy', 'false');
  const browser = document.querySelector('#commodity-browser');
  if (browser) browser.hidden = false;
  const status = document.querySelector('#intel-status');
  if (status) status.hidden = true;
  const trigger = intelligenceState.returnFocus;
  const fallback = [...document.querySelectorAll('.intelligence-button')]
    .find(button => button.dataset.commodityId === intelligenceState.commodityId);
  const returnTo = trigger?.isConnected && !trigger.closest('[hidden]') && trigger !== document.body ? trigger : fallback || document.querySelector('#search');
  returnTo?.focus();
}

window.openCommodityIntelligence = openCommodityIntelligence;
window.closeCommodityIntelligence = closeCommodityIntelligence;
document.querySelector('#intel-close')?.addEventListener('click', closeCommodityIntelligence);
document.querySelector('#intelligence-section')?.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !event.defaultPrevented) {
    event.preventDefault();
    closeCommodityIntelligence();
  }
});
