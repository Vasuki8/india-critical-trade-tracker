const fmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const compactFmt = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });
const unitValueFmt = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function usdMillions(v) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return '—';
  const sign = v < 0 ? '-' : '';
  const n = Math.abs(v);
  if (n >= 1000) return `${sign}$${fmt.format(n / 1000)}B`;
  return `${sign}$${fmt.format(n)}M`;
}

function pct(v) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${fmt.format(v)}%`;
}

function physicalQuantity(metric) {
  if (!metric || metric.status !== 'ok' || metric.quantity === null || metric.quantity === undefined) return '—';
  return `${compactFmt.format(metric.quantity)} ${metric.quantity_unit || ''}`.trim();
}

function impliedUnitValue(metric) {
  if (!metric || metric.status !== 'ok' || metric.unit_value_usd_per_source_unit === null || metric.unit_value_usd_per_source_unit === undefined) return '—';
  return `$${unitValueFmt.format(metric.unit_value_usd_per_source_unit)}/${metric.quantity_unit || 'unit'}`;
}

function quantityAvailability(metric) {
  if (!metric) return null;
  const units = metric.component_units || metric.source_quantity_units || [];
  const unitText = units.length ? ` (${units.join(' + ')})` : '';
  if (metric.status === 'mixed_quantity_units') {
    return `Mixed physical units${unitText} · aggregate unavailable`;
  }
  if (metric.status === 'rollup_disabled') {
    return `HS8 quantities kept separate${unitText} · aggregate unavailable`;
  }
  return null;
}

async function loadJSON(path) {
  const res = await fetch(path, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

function mappingClass(status) {
  return /needs|sensitive|partial/i.test(status) ? 'mapping review' : 'mapping';
}

function riskClass(risk) {
  return ['high', 'moderate', 'low'].includes(risk) ? `risk ${risk}` : 'risk';
}

function quantityBlock(metrics) {
  const aggregate = metrics?.unit_values?.aggregate || {};
  const rows = [];

  const appendTrade = (label, metric) => {
    if (metric?.status === 'ok') {
      rows.push(`
        <div class="quantity-row" title="TradeStat quantity is used directly in the displayed source unit before implied unit-value calculation.">
          <span>${label} quantity <strong>${escapeHTML(physicalQuantity(metric))}</strong></span>
          <span>Implied ${label.toLowerCase()} unit <strong>${escapeHTML(impliedUnitValue(metric))}</strong></span>
        </div>`);
      return;
    }
    const availability = quantityAvailability(metric);
    if (availability) {
      rows.push(`
        <div class="quantity-row availability" title="Exact HS8 quantities remain available in the source observations; incompatible physical units are never summed.">
          <span>${label} quantity <strong>${escapeHTML(availability)}</strong></span>
        </div>`);
    }
  };

  appendTrade('Import', aggregate.import);
  appendTrade('Export', aggregate.export);
  return rows.join('');
}

function escapeHTML(value) {
  return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

function uiIcon(name) {
  return `<svg class="icon" aria-hidden="true"><use href="#icon-${name}"/></svg>`;
}

const viewLabels = { overview: 'Overview', commodities: 'Commodities', sources: 'Data & methodology' };
let currentView = null;

function navigateTracker(view, { updateHash = true, focus = true } = {}) {
  if (!Object.hasOwn(viewLabels, view)) return;
  if (updateHash && location.hash !== `#${view}`) history.pushState(null, '', `#${view}`);
  if (currentView === view) return;
  currentView = view;
  document.querySelectorAll('[data-page]').forEach(page => { page.hidden = page.dataset.page !== view; });
  document.querySelectorAll('.primary-nav [data-view]').forEach(link => {
    if (link.dataset.view === view) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  document.querySelector('#view-label').textContent = viewLabels[view];
  document.title = `${viewLabels[view]} · India Trade`;
  if (focus) {
    const heading = document.querySelector(`#${view}-view h1`);
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  window.dispatchEvent(new CustomEvent('tracker:viewchange', { detail: { view } }));
}
window.navigateTracker = navigateTracker;

document.addEventListener('click', event => {
  const link = event.target.closest('a[href^="#"]');
  if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
  const view = link.getAttribute('href').slice(1);
  if (!Object.hasOwn(viewLabels, view)) return;
  event.preventDefault();
  navigateTracker(view);
});
window.addEventListener('hashchange', () => {
  const view = location.hash.slice(1);
  // Back from the first navigation returns to the original URL with no hash.
  if (view === 'main-content') return;
  navigateTracker(Object.hasOwn(viewLabels, view) ? view : 'overview', { updateHash: false });
});
navigateTracker(Object.hasOwn(viewLabels, location.hash.slice(1)) ? location.hash.slice(1) : 'overview', { updateHash: false, focus: false });

function bindCommodityIntelligenceButtons() {
  document.querySelectorAll('.intelligence-button').forEach(button => {
    button.addEventListener('click', () => {
      window.openCommodityIntelligence?.(button.dataset.commodityId, button.dataset.commodityName);
    });
  });
}

function selectCommodities(master, dashboard, filters) {
  const metricsById = new Map((dashboard.commodities || []).map(item => [item.id, item]));
  const q = filters.query.trim().toLowerCase();
  const items = master.commodities.filter(c => {
    const text = `${c.name} ${c.category} ${c.hs_codes.join(' ')}`.toLowerCase();
    const m = metricsById.get(c.id);
    return (!q || text.includes(q)) && (!filters.category || c.category === filters.category)
      && (!filters.risk || m?.dependency?.risk === filters.risk);
  });
  const sortValue = c => {
    const m = metricsById.get(c.id);
    const value = filters.sort === 'dependency' ? m?.dependency?.score : m?.[filters.sort];
    return typeof value === 'number' && Number.isFinite(value) ? value : -Infinity;
  };
  items.sort((a, b) => {
    if (filters.sort !== 'name') {
      const difference = sortValue(b) - sortValue(a);
      if (!Number.isNaN(difference) && difference !== 0) return difference;
    }
    return a.name.localeCompare(b.name);
  });
  return { items, metricsById };
}

function renderCommodities(master, dashboard) {
  const grid = document.querySelector('#commodity-grid');
  const filters = {
    query: document.querySelector('#search').value,
    category: document.querySelector('#category').value,
    risk: document.querySelector('#risk-filter').value,
    sort: document.querySelector('#sort').value,
  };
  const { items, metricsById } = selectCommodities(master, dashboard, filters);
  grid.innerHTML = items.map(c => {
    const m = metricsById.get(c.id);
    const dependency = m?.dependency || {};
    const topSupplier = m?.supplier_concentration?.top_partners?.[0];
    const risk = ['high', 'moderate', 'low'].includes(dependency.risk) ? dependency.risk : null;
    const supplierShare = typeof topSupplier?.share_pct === 'number' ? topSupplier.share_pct : null;
    const dataBlock = m ? `
      <div class="trade-stats">
        <div class="trade-stat import-stat"><span>Imports</span><strong>${usdMillions(m.imports)}</strong></div>
        <div class="trade-stat export-stat"><span>Exports</span><strong>${usdMillions(m.exports)}</strong></div>
        <div class="trade-stat"><span>Balance</span><strong>${usdMillions(m.balance)}</strong></div>
      </div>
      <div class="growth-row"><span>Import YoY <strong>${pct(m.import_yoy_pct)}</strong></span><span>Export YoY <strong>${pct(m.export_yoy_pct)}</strong></span></div>
      <div class="commodity-foot"><span class="${riskClass(risk)}">${risk ? `${risk[0].toUpperCase()}${risk.slice(1)} dependency` : 'Dependency unavailable'}</span><span class="dependency-score">Score <strong>${escapeHTML(dependency.score ?? '—')}</strong><span> / 100</span></span></div>
      <div class="supplier-signal"><div><span>Top supplier</span><strong>${escapeHTML(topSupplier?.partner_country || 'Unavailable')}${supplierShare !== null ? ` · ${fmt.format(supplierShare)}%` : ''}</strong></div>${supplierShare !== null ? `<div class="supplier-track" aria-hidden="true"><i style="width:${Math.max(0, Math.min(supplierShare, 100))}%"></i></div>` : ''}</div>
      <details class="commodity-details"><summary>HS mapping, YTD & quantities</summary><div class="hs">HS ${c.hs_codes.map(code => `<code>${escapeHTML(code)}</code>`).join('')}</div><span class="${mappingClass(c.mapping_status)}">${escapeHTML(c.mapping_status.replaceAll('_', ' '))}</span><div class="growth-row"><span>YTD imports <strong>${usdMillions(m.ytd_imports)}</strong></span><span>YTD exports <strong>${usdMillions(m.ytd_exports)}</strong></span></div>${quantityBlock(m)}<p class="card-period">Reporting month: ${escapeHTML(periodLabel(m.period || dashboard.as_of))}</p></details>
      <button class="intelligence-button" type="button" data-commodity-id="${escapeHTML(c.id)}" data-commodity-name="${escapeHTML(c.name)}" aria-label="Explore ${escapeHTML(c.name)} intelligence">Explore intelligence ${uiIcon('arrow')}</button>`
      : `<div class="empty-data">Awaiting validated official trade data.</div><div class="hs">HS ${c.hs_codes.map(code => `<code>${escapeHTML(code)}</code>`).join('')}</div><span class="${mappingClass(c.mapping_status)}">${escapeHTML(c.mapping_status.replaceAll('_', ' '))}</span>`;
    return `<article class="card commodity-card"><div class="commodity-top"><span class="commodity-symbol">${uiIcon('box')}</span><div><div class="commodity-category">${escapeHTML(c.category)}</div><h2 class="commodity-name">${escapeHTML(c.name)}</h2></div></div>${dataBlock}</article>`;
  }).join('') || `<div class="card empty-state">${uiIcon('search')}<h2>No commodities found</h2><p>Try another name or HS code, or reset the filters to see the full watchlist.</p><button type="button" class="ghost-button" id="empty-reset">Reset all filters</button></div>`;
  grid.setAttribute('aria-busy', 'false');
  document.querySelector('#visible-count').textContent = `${items.length} of ${master.commodities.length} commodities · ${periodLabel(dashboard.as_of)}`;
  document.querySelector('#reset-filters').hidden = !(filters.query || filters.category || filters.risk || filters.sort !== 'imports');
  document.querySelector('#empty-reset')?.addEventListener('click', () => resetFilters(master, dashboard));
  bindCommodityIntelligenceButtons();
}

function resetFilters(master, dashboard) {
  document.querySelector('#search').value = '';
  document.querySelector('#category').value = '';
  document.querySelector('#risk-filter').value = '';
  document.querySelector('#sort').value = 'imports';
  renderCommodities(master, dashboard);
  document.querySelector('#search').focus();
}

function initFilters(master, dashboard) {
  const categories = [...new Set(master.commodities.map(c => c.category))].sort();
  document.querySelector('#category').innerHTML = '<option value="">All categories</option>' + categories.map(c => `<option value="${escapeHTML(c)}">${escapeHTML(c)}</option>`).join('');
  document.querySelector('#search').oninput = () => renderCommodities(master, dashboard);
  ['category', 'risk-filter', 'sort'].forEach(id => {
    document.querySelector(`#${id}`).onchange = () => renderCommodities(master, dashboard);
  });
  document.querySelector('#reset-filters').onclick = () => resetFilters(master, dashboard);
}

function renderSource(status) {
  document.querySelector('#source-data-available').textContent = status.data_available || '—';
  document.querySelector('#source-updated').textContent = status.last_updated || '—';
  document.querySelector('#source-final').textContent = status.final_through || '—';
  document.querySelector('#source-revised').textContent = status.revised_final_through || '—';
  const sourceCheck = document.querySelector('#source-check');
  sourceCheck.textContent = status.fetch_status === 'ok' ? 'Last check successful' : (status.fetch_status || 'Unavailable').replaceAll('_', ' ');
  sourceCheck.className = `coverage-badge ${status.fetch_status === 'ok' ? 'complete' : 'partial'}`;
  const checkDate = status.checked_at ? new Date(status.checked_at) : null;
  document.querySelector('#source-checked-at').textContent = checkDate && !Number.isNaN(checkDate.getTime())
    ? `${new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }).format(checkDate)} UTC` : '—';
  document.querySelector('#source-warning').textContent = status.classification_warning || 'No source warning reported.';
}

async function main() {
  const fatal = document.querySelector('#fatal');
  fatal.hidden = true;
  const [masterResult, dashboardResult, sourceResult] = await Promise.allSettled([
    loadJSON('data/commodities.json'), loadJSON('data/dashboard.json'), loadJSON('data/source_status.json'),
  ]);
  if (sourceResult.status === 'fulfilled') renderSource(sourceResult.value);
  else {
    renderSource({ fetch_status: 'Source status unavailable', classification_warning: 'Source notices could not be loaded. Check the official source before comparing classification-sensitive periods.' });
  }
  try {
    if (masterResult.status !== 'fulfilled' || dashboardResult.status !== 'fulfilled') throw new Error('The latest dashboard could not be retrieved.');
    const master = masterResult.value;
    const dashboard = dashboardResult.value;
    document.querySelector('#commodity-count').textContent = master.commodities.length;
    document.querySelector('#nav-count').textContent = master.commodities.length;
    document.querySelector('#imports').textContent = usdMillions(dashboard.summary.imports);
    document.querySelector('#exports').textContent = usdMillions(dashboard.summary.exports);
    document.querySelector('#balance').textContent = usdMillions(dashboard.summary.balance);
    document.querySelector('#balance').style.color = dashboard.summary.balance >= 0 ? 'var(--positive)' : 'var(--negative)';
    document.querySelector('#imports-foot').innerHTML = `<strong>${pct(dashboard.summary.import_yoy_pct)}</strong> vs. same month last year<span class="metric-secondary">YTD ${usdMillions(dashboard.summary.ytd_imports)}</span>`;
    document.querySelector('#exports-foot').innerHTML = `<strong>${pct(dashboard.summary.export_yoy_pct)}</strong> vs. same month last year<span class="metric-secondary">YTD ${usdMillions(dashboard.summary.ytd_exports)}</span>`;
    document.querySelector('#balance-foot').innerHTML = `${dashboard.summary.balance === null || dashboard.summary.balance === undefined ? 'Balance unavailable' : dashboard.summary.balance < 0 ? 'Net import deficit' : dashboard.summary.balance > 0 ? 'Net export surplus' : 'Balanced trade'}<span class="metric-secondary">YTD ${usdMillions(dashboard.summary.ytd_balance)}</span>`;
    const observed = dashboard.summary.observed_commodity_count ?? dashboard.commodities.length;
    document.querySelector('#coverage-foot').innerHTML = `<strong>${observed} / ${master.commodities.length}</strong> with monthly observations<span class="metric-secondary">${new Set(master.commodities.map(c => c.category)).size} strategic categories</span>`;
    document.querySelector('#as-of').textContent = periodLabel(dashboard.as_of) || 'Awaiting data';
    document.querySelector('#snapshot-period').textContent = periodLabel(dashboard.as_of);
    window.trackerDashboard = dashboard;
    window.renderPortfolioHistory?.(dashboard);
    initFilters(master, dashboard);
    renderCommodities(master, dashboard);
  } catch (err) {
    fatal.hidden = false;
    fatal.innerHTML = `The tracker could not load its data. Please retry or check your connection. <button type="button" class="ghost-button" id="retry-data">Retry loading</button>`;
    document.querySelector('#retry-data').onclick = main;
    document.querySelector('#as-of').textContent = 'Unavailable';
    document.querySelector('#snapshot-period').textContent = 'Unavailable';
    document.querySelector('#commodity-grid').setAttribute('aria-busy', 'false');
    document.querySelector('#commodity-grid').innerHTML = '<div class="card empty-state"><h2>Commodity data unavailable</h2><p>Use Retry loading above to try again.</p></div>';
    document.querySelector('#visible-count').textContent = 'Data unavailable';
    document.querySelector('#portfolio-history-chart').innerHTML = '<div class="intel-empty">History could not be loaded.</div>';
    console.error('Tracker load failed:', err);
  }
}
// Shared chart/date helpers are loaded by the following scripts. Wait for all
// deferred scripts before starting requests, even when JSON is locally cached.
document.addEventListener('DOMContentLoaded', main, { once: true });
