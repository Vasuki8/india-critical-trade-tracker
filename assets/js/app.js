const fmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });

function valueOrDash(v, suffix = '') {
  return v === null || v === undefined ? '—' : `${fmt.format(v)}${suffix}`;
}

async function loadJSON(path) {
  const res = await fetch(path, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

function mappingClass(status) {
  return /needs|sensitive|partial/i.test(status) ? 'mapping review' : 'mapping';
}

function renderCommodities(master) {
  const grid = document.querySelector('#commodity-grid');
  const q = document.querySelector('#search').value.trim().toLowerCase();
  const category = document.querySelector('#category').value;
  const items = master.commodities.filter(c => {
    const text = `${c.name} ${c.category} ${c.hs_codes.join(' ')}`.toLowerCase();
    return (!q || text.includes(q)) && (!category || c.category === category);
  });

  grid.innerHTML = items.map(c => `
    <article class="card commodity-card">
      <div class="commodity-name">${c.name}</div>
      <div class="commodity-category">${c.category}</div>
      <div class="hs">HS ${c.hs_codes.map(code => `<code>${code}</code>`).join('')}</div>
      <span class="${mappingClass(c.mapping_status)}">${c.mapping_status.replaceAll('_', ' ')}</span>
      <div class="empty-data">Trade series: awaiting first official ingestion</div>
    </article>
  `).join('');
  document.querySelector('#visible-count').textContent = items.length;
}

function initFilters(master) {
  const categories = [...new Set(master.commodities.map(c => c.category))].sort();
  document.querySelector('#category').innerHTML = '<option value="">All categories</option>' + categories.map(c => `<option>${c}</option>`).join('');
  document.querySelector('#search').addEventListener('input', () => renderCommodities(master));
  document.querySelector('#category').addEventListener('change', () => renderCommodities(master));
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
    document.querySelector('#imports').textContent = valueOrDash(dashboard.summary.imports);
    document.querySelector('#exports').textContent = valueOrDash(dashboard.summary.exports);
    document.querySelector('#balance').textContent = valueOrDash(dashboard.summary.balance);
    document.querySelector('#as-of').textContent = dashboard.as_of || 'Awaiting first ingestion';
    initFilters(master);
    renderCommodities(master);
    renderSource(source);
  } catch (err) {
    document.querySelector('#fatal').hidden = false;
    document.querySelector('#fatal').textContent = `Unable to load tracker data: ${err.message}`;
  }
}

main();
