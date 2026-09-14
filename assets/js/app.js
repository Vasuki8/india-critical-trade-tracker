const fmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });

function usdMillions(v) {
  if (v === null || v === undefined) return '—';
  const sign = v < 0 ? '-' : '';
  const n = Math.abs(v);
  if (n >= 1000) return `${sign}$${fmt.format(n / 1000)}B`;
  return `${sign}$${fmt.format(n)}M`;
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
      <div class="commodity-foot">
        <span class="${riskClass(dependency.risk)}">${dependency.score ?? '—'} dependency · ${dependency.risk || 'n/a'}</span>
        <span>${topSupplier ? `Top supplier: ${topSupplier.partner_country} ${topSupplier.share_pct}%` : 'Supplier data unavailable'}</span>
      </div>` : '<div class="empty-data">Trade series: awaiting validated official ingestion</div>';

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
