const fmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const compactFmt = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });
const unitValueFmt = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function usdMillions(v) {
  if (v === null || v === undefined) return '—';
  const sign = v < 0 ? '-' : '';
  const n = Math.abs(v);
  if (n >= 1000) return `${sign}$${fmt.format(n / 1000)}B`;
  return `${sign}$${fmt.format(n)}M`;
}

function pct(v) {
  if (v === null || v === undefined) return '—';
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
  const imports = aggregate.import;
  const exports = aggregate.export;
  const rows = [];

  if (imports?.status === 'ok') {
    rows.push(`
      <div class="quantity-row" title="TradeStat quantity is used directly in the displayed source unit before implied unit-value calculation.">
        <span>Import quantity <strong>${physicalQuantity(imports)}</strong></span>
        <span>Implied import unit <strong>${impliedUnitValue(imports)}</strong></span>
      </div>`);
  }
  if (exports?.status === 'ok') {
    rows.push(`
      <div class="quantity-row" title="TradeStat quantity is used directly in the displayed source unit before implied unit-value calculation.">
        <span>Export quantity <strong>${physicalQuantity(exports)}</strong></span>
        <span>Implied export unit <strong>${impliedUnitValue(exports)}</strong></span>
      </div>`);
  }

  return rows.join('');
}

function bindCommodityIntelligenceButtons() {
  document.querySelectorAll('.intelligence-button').forEach(button => {
    button.addEventListener('click', () => {
      if (typeof window.openCommodityIntelligence === 'function') {
        window.openCommodityIntelligence(button.dataset.commodityId, button.dataset.commodityName);
      }
    });
  });
}

function renderCommodities(master, dashboard) {
  const grid = document.querySelector('#commodity-grid');
  const q = document.querySelector('#search').value.trim().toLowerCase();
  const category = document.querySelector('#category').value;
  const metricsById = new Map((dashboard.commodities || []).map(item => [item.id, item]));
  const items = master.commodities.filter(c => {
    const text = `${c.name} ${c.category} ${c.hs_codes.join(' ')}`.toLowerCase();
    return (!q || text.includes(q)) && (!category || c.category === category);
  });

  grid.innerHTML = items.map(c => {
    const m = metricsById.get(c.id);
    const dependency = m?.dependency || {};
    const topSupplier = m?.supplier_concentration?.top_partners?.[0];
    const dataBlock = m ? `
      <div class="trade-stats">
        <div class="trade-stat"><span>Imports</span><strong>${usdMillions(m.imports)}</strong></div>
        <div class="trade-stat"><span>Exports</span><strong>${usdMillions(m.exports)}</strong></div>
        <div class="trade-stat"><span>Balance</span><strong>${usdMillions(m.balance)}</strong></div>
      </div>
      <div class="growth-row">
        <span>Import YoY <strong>${pct(m.import_yoy_pct)}</strong></span>
        <span>Export YoY <strong>${pct(m.export_yoy_pct)}</strong></span>
      </div>
      <div class="growth-row">
        <span>YTD imports <strong>${usdMillions(m.ytd_imports)}</strong></span>
        <span>YTD exports <strong>${usdMillions(m.ytd_exports)}</strong></span>
      </div>
      ${quantityBlock(m)}
      <div class="commodity-foot">
        <span class="${riskClass(dependency.risk)}">${dependency.score ?? '—'} dependency · ${dependency.risk || 'n/a'}</span>
        <span>${topSupplier ? `Top supplier: ${topSupplier.partner_country} ${topSupplier.share_pct}%` : 'Supplier data unavailable'}</span>
      </div>
      <button class="intelligence-button" type="button" data-commodity-id="${c.id}" data-commodity-name="${c.name}">Explore intelligence</button>` : '<div class="empty-data">Trade series: awaiting validated official ingestion</div>';

    return `
      <article class="card commodity-card">
        <div class="commodity-name">${c.name}</div>
        <div class="commodity-category">${c.category}</div>
        <div class="hs">HS ${c.hs_codes.map(code => `<code>${code}</code>`).join('')}</div>
        <span class="${mappingClass(c.mapping_status)}">${c.mapping_status.replaceAll('_', ' ')}</span>
        ${dataBlock}
      </article>
    `;
  }).join('');
  document.querySelector('#visible-count').textContent = items.length;
  bindCommodityIntelligenceButtons();
}

function initFilters(master, dashboard) {
  const categories = [...new Set(master.commodities.map(c => c.category))].sort();
  document.querySelector('#category').innerHTML = '<option value="">All categories</option>' + categories.map(c => `<option>${c}</option>`).join('');
  document.querySelector('#search').addEventListener('input', () => renderCommodities(master, dashboard));
  document.querySelector('#category').addEventListener('change', () => renderCommodities(master, dashboard));
}

function renderSource(status) {
  document.querySelector('#source-data-available').textContent = status.data_available || '—';
  document.querySelector('#source-updated').textContent = status.last_updated || '—';
  document.querySelector('#source-final').textContent = status.final_through || '—';
  document.querySelector('#source-revised').textContent = status.revised_final_through || '—';
  document.querySelector('#source-check').textContent = status.fetch_status || '—';
  document.querySelector('#source-warning').textContent = status.classification_warning || 'No source warning reported.';
}

async function main() {
  try {
    const [master, dashboard, source] = await Promise.all([
      loadJSON('data/commodities.json'),
      loadJSON('data/dashboard.json'),
      loadJSON('data/source_status.json')
    ]);

    document.querySelector('#commodity-count').textContent = master.commodities.length;
    document.querySelector('#visible-count').textContent = master.commodities.length;
    document.querySelector('#imports').textContent = usdMillions(dashboard.summary.imports);
    document.querySelector('#exports').textContent = usdMillions(dashboard.summary.exports);
    document.querySelector('#balance').textContent = usdMillions(dashboard.summary.balance);
    document.querySelector('#imports-foot').textContent = `YoY ${pct(dashboard.summary.import_yoy_pct)} · YTD ${usdMillions(dashboard.summary.ytd_imports)} · watched HS universe`;
    document.querySelector('#exports-foot').textContent = `YoY ${pct(dashboard.summary.export_yoy_pct)} · YTD ${usdMillions(dashboard.summary.ytd_exports)} · overlap-adjusted`;
    document.querySelector('#balance-foot').textContent = `YTD balance ${usdMillions(dashboard.summary.ytd_balance)} · exports minus imports`;
    document.querySelector('#as-of').textContent = dashboard.as_of || 'Awaiting first ingestion';
    initFilters(master, dashboard);
    renderCommodities(master, dashboard);
    renderSource(source);
  } catch (err) {
    document.querySelector('#fatal').hidden = false;
    document.querySelector('#fatal').textContent = `Unable to load tracker data: ${err.message}`;
  }
}

main();
