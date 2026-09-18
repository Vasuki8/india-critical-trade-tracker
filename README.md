# India Critical Commodity Trade Tracker

A live tracker for India's strategically important commodity imports and exports, built around official Department of Commerce TradeStat / DGCI&S MEIDB data and published as a static GitHub Pages site.

## Current build

The tracker covers **23 critical commodity groups** and carries official monthly USD data through **June 2026**. The baseline USD archive spans the TradeStat monthly lower bound of **January 2018 through June 2026**: **102 calendar months** and **2,345 commodity-month history rows**.

The site has two complementary analytical layers:

- a compact **consolidated portfolio dashboard** for the full watched commodity universe; and
- a lazy-loaded **commodity intelligence drill-down** for each commodity, generated deterministically from stored observations.

The portfolio view includes monthly and annual imports/exports, trade balance, cumulative totals, peak import month, coverage status, supplier concentration and validated physical-quantity context where available.

The commodity intelligence view adds:

- month-by-month imports, exports and balance;
- every reported partner country for a selected month;
- historical trends for any selected supplier/export destination;
- annual totals and supplier concentration;
- top supplier share and HHI;
- dependency indicators;
- quantity and implied unit-value context where physically valid; and
- explicit classification-transition warnings instead of treating missing classification coverage as zero trade.

## Quantity coverage

TradeStat physical quantity is queried only at **ITC-HS8**. Monetary and physical definitions are versioned separately so a broad validated USD series can coexist with an exact HS8 quantity mapping.

Six commodity groups currently have validated HS8 quantity mappings:

| Commodity | Quantity mapping | Rollup | Historical state |
| --- | --- | --- | --- |
| Crude Oil | period-specific HS8 children of `2709` | compatible mass units may roll up | complete from Jan 2018, excluding Feb 2022 transition |
| Natural Gas / LNG | `27111100`, `27112100` | same as monetary HS8 mapping | complete from Jan 2018 |
| Lithium & Compounds | `28252000`, `28369100` | same as monetary HS8 mapping | complete from Jan 2018 |
| Rare Earths | exact HS8 children of `2846` | compatible mass units may roll up | complete from Jan 2018 |
| Solar Cells / Modules | period-specific exact HS8 mapping | same as monetary mapping | complete from Jan 2018, excluding Feb 2022 transition |
| Electric Accumulators / Batteries | exact period-specific HS8 children of `8507` | **disabled** because units are mixed | recovery/backfill in progress |

The tracker only declares `history_complete_from` after the required archive has been fetched, generated data rebuilt, and validation succeeds. An enabled quantity mapping therefore does **not** automatically mean historical quantity coverage is complete.

### Classification-aware quantity series

**Crude Oil** quantity mapping:

- through January 2022: `27090000`
- February 2022: intentional transition gap
- from March 2022: `27090010`, `27090090`

**Solar PV** mapping:

- through January 2022: `85414011`, `85414012`
- February 2022: intentional transition gap
- from March 2022: `85414200`, `85414300`

**Batteries** quantity mapping:

- through January 2022: `85071000`, `85072000`, `85073000`, `85074000`, `85075000`, `85076000`, `85078000`, `85079010`, `85079090`
- February 2022: intentional transition gap
- from March 2022: `85071000`, `85072000`, `85073000`, `85075000`, `85076000`, `85078000`, `85079010`, `85079090`

The February 2022 gaps are deliberate because ITC(HS) 2022 took effect during that month. The tracker does not fabricate a single-month bridge across a mid-month classification change.

### Quantity units and unit values

MEIDB quantity values are used directly in the displayed source unit. The verified quantity selector is code `2`, and the quantity scale is **1**.

Equivalent mass units are normalized conservatively before aggregation, for example:

- `TON`, `TONNE`, `MT` → `KGS` using ×1,000
- `GMS`, `GRAM` → `KGS` using ×0.001
- `KGS` remains `KGS`

Unrelated unit families are never combined.

Batteries are the important example: accumulator lines are reported in `NOS`, while parts such as `85079010` and `85079090` are reported in `KGS`. Therefore the full `8507` physical quantity is **not** summed and no parent-level implied unit value is fabricated. Raw HS8 quantities remain available with provenance and the dashboard explicitly reports that the aggregate is unavailable because the physical units are mixed.

The derivation engine also supports validated **multi-parent monetary mappings**. Each exact quantity child must belong to exactly one monetary parent, every parent must have at least one child, and all positive quantities must resolve to one compatible canonical unit before an aggregate unit value is calculated.

A non-writing live probe is available for evaluating prospective quantity mappings before they are enabled:

```powershell
uv run python scripts/probe_quantity_units.py --hs-code 26050000 --period 2018-01 --period 2026-06 --trade-type both --require-canonical-unit KGS
```

## Data architecture

### Canonical observations

Current observations live at:

```text
data/observations/YYYY-MM/<commodity>.<value_type>.json
```

Canonical observation files retain full source provenance, including:

- period and trade direction;
- HS code and active mapping;
- value type / selector code;
- partner-country rows;
- source unit for quantity reports;
- source URL and report date;
- retrieval timestamp; and
- checksum.

### Dashboard payload

`data/dashboard.json` is the eagerly loaded portfolio payload. It is written as compact JSON to reduce transfer and parsing overhead while retaining the same browser contract.

### Commodity intelligence

Deep country/month intelligence is generated into one file per commodity:

```text
data/intelligence/<commodity>.json
```

The intelligence layer uses the compact v2 generated schema and omits redundant monthly fields that can be derived from the canonical archive. The homepage does not load all commodity intelligence at startup; it fetches one commodity file only when **Explore intelligence** is opened.

The browser pre-indexes month/country series after that file is loaded so interactive country/month selections do not repeatedly rescan the full payload.

Rebuild generated data with:

```powershell
uv run python scripts/build_dashboard.py
uv run python scripts/build_revision_summary.py
uv run python scripts/build_intelligence.py
```

## Derived analytics

The tracker derives:

- imports, exports and trade balance;
- monthly YoY and calendar-year YTD values;
- top suppliers / destinations and supplier concentration;
- a transparent dependency score;
- physical quantity and implied USD per canonical physical unit when valid;
- monthly and annual commodity histories;
- consolidated portfolio history; and
- revision summaries when official data changes semantically.

Parent/child monetary HS mappings are deduplicated using a shortest-prefix union so chapter/heading overlap cannot inflate portfolio totals.

## Revision-aware observations

Before replacing a current observation, the ingester computes a deterministic semantic fingerprint. Fetch-time-only fields such as `retrieved_at` and `report_date` are excluded from revision identity.

Fingerprint hashing streams canonical JSON tokens directly into SHA-256, preserving the historical hash contract without allocating a complete filtered copy plus a second full canonical JSON string.

If a refetched observation is semantically unchanged, the current file is left untouched. If official values, rows, mappings, units, totals, checksums or other semantic content changes, the previous document is archived at:

```text
data/revisions/YYYY-MM/<commodity>.<value_type>/<fingerprint>.json
```

The daily source watcher and historical backfills share the same writer, so the revision contract is consistent across both paths.

## Source monitoring and automation

### Shared data-writer lock

All workflows that can commit TradeStat-derived data serialize on the GitHub Actions concurrency group:

```text
tradestat-data-writer
```

This prevents the daily source watcher, historical backfills and controlled bootstrap/repair jobs from overwriting each other's data commits.

The one-time Crude Oil, Rare Earths and Batteries bootstrap workflows are **manual-only**. Editing their YAML no longer automatically restarts an expensive historical ingestion.

### Daily source watch

`.github/workflows/source-watch.yml`:

1. checks official TradeStat release metadata;
2. compares latest stored observations with active mappings/provenance;
3. performs only stale/latest ingestion plus bounded Revised-Final refreshes;
4. archives genuine semantic revisions;
5. rebuilds dashboard, revision summary and intelligence data;
6. runs data validation, Python tests and frontend JavaScript syntax checks; and
7. commits validated generated data back to `main`.

Timestamp-only checks remain no-ops.

### Historical backfill

`.github/workflows/backfill.yml` provides controlled resumable backfills for USD, quantity, or both. Existing complete observations are skipped automatically.

Backfill eligibility checks include:

- active period-specific mapping;
- requested import/export coverage;
- value type;
- stored observation status;
- quantity selector code `2`; and
- direct quantity scale `1`.

The monthly lower bound is January 2018. Safety limits keep broad historical runs bounded; targeted commodity/quantity repairs can use larger windows.

### Validation

`.github/workflows/validate.yml` checks:

- commodity-master structure and mapping quality;
- generated dashboard/history consistency;
- commodity intelligence rebuild/synchronization;
- Python tests; and
- JavaScript syntax for the homepage, portfolio and intelligence code.

GitHub Actions dependencies are pinned to immutable commit SHAs using Node-24-compatible action releases.

## Interface and navigation

The responsive interface uses a light color scheme with teal imports and violet exports. Three URL-addressable views keep the workspace compact:

- **Overview** (`#overview`): latest reporting-month metrics, overlap-adjusted portfolio history, range-specific statistics, and an expandable annual table.
- **Commodities** (`#commodities`): search by name, HS code, or category; filter by category and dependency; sort by imports, exports, dependency, or name. Each card keeps its HS mapping, YTD figures, and validated quantity context in an expandable disclosure. The detail workspace retains monthly and country history, concentration, quantities, and annual tables.
- **Data & methodology** (`#sources`): source availability, last source update, final/revised-final periods, monitor check timestamp in UTC, classification notice, and explanations of portfolio coverage, units, and dependency scoring.

The headline reporting month is distinct from the source update and monitor check timestamps. A successful source check is labeled as the last check, rather than implying continuous live availability. Source-status retrieval failure does not block available trade data.

Historical charts show a USD value axis and a shared period readout for imports and exports. Pointer/touch selection and keyboard arrow keys, Home, and End inspect observations. Imports use a solid line and exports a dashed line so color is not the only distinction. Missing calendar months break the plotted line; partial coverage is explained alongside the chart and table. Selecting a portfolio range updates the chart, cumulative statistics, peak, and annual rows together.

Navigation works with direct links and browser history. Controls have labels and visible keyboard focus; intelligence loading can be closed, stale responses cannot replace the active commodity, and closing returns focus to the originating card. Reduced-motion preferences are respected. Wide tables scroll within their labeled regions on small screens.

## Frontend performance

The static site remains optimized for a growing archive:

- commodity intelligence is lazy-loaded;
- dashboard and intelligence generated JSON are compact;
- repeated country/month scans are pre-indexed;
- inactive navigation views are hidden;
- opaque cards avoid costly backdrop blur and use compact shadows;
- commodity cards use `content-visibility: auto` with intrinsic-size fallbacks; and
- chart/table paints are isolated while section geometry remains stable when navigating.

The interface uses native HTML, CSS, and JavaScript without a runtime framework, external font, or chart dependency. Browser checks and viewport screenshots run separately from the existing data-validation workflow.

## Verified TradeStat MEIDB contracts

The live MEIDB commodity-all-countries forms were verified in September 2026:

| Value type | Selector code |
| --- | ---: |
| US $ Million | `1` |
| Quantity | `2` |
| ₹ Crore | `3` |

The client validates this contract before submitting ingestion requests. If the form mapping changes, ingestion fails instead of silently storing the wrong measure.

## Data integrity rules

- Quantity ingestion requires an active validated HS8 mapping.
- Broad/review-sensitive mappings are not silently promoted to quantity mappings.
- Required import/export request failures block normal observation persistence unless partial persistence is explicitly authorized.
- Classification-transition months are represented as coverage gaps, not zero trade.
- Quantity-only observations cannot advance the headline dashboard `as_of` month.
- Generated intelligence must match canonical dashboard periods and classification gaps.
- Parent-heading quantity rollup is explicit opt-in and requires complete, unambiguous child coverage.
- Incompatible physical units are never summed.
- Historical completeness is declared only after the configured archive passes validation.
- The April 2026 TradeStat ITC-HS reallocation/unit warning remains a classification guardrail.

## Local setup with uv

```powershell
uv sync --dev
uv run python scripts/build_dashboard.py
uv run python scripts/build_revision_summary.py
uv run python scripts/build_intelligence.py
uv run python scripts/validate_data.py
uv run pytest -q
uv run python -m http.server 8000
```

Then open `http://localhost:8000`.

## Ingest official data

Check source status:

```powershell
uv run python scripts/check_source.py
```

Latest USD observations:

```powershell
uv run python scripts/ingest_tradestat.py --latest --trade-type both --value-type usd --year-type calendar
```

Latest physical quantity observations for eligible groups:

```powershell
uv run python scripts/ingest_tradestat.py --latest --trade-type both --value-type quantity --year-type calendar
```

One commodity / one period:

```powershell
uv run python scripts/ingest_tradestat.py --period 2026-06 --commodity natural_gas_lng --trade-type both --value-type quantity
```

Dry-run a historical batch:

```powershell
uv run python scripts/backfill_tradestat.py --start-period 2018-01 --end-period 2018-12 --value-type usd --trade-type both --dry-run
```

## Repository structure

```text
.
├── .github/workflows/
│   ├── backfill.yml
│   ├── bootstrap-batteries-quantity.yml
│   ├── bootstrap-crude-oil-quantity.yml
│   ├── bootstrap-rare-earth-quantity.yml
│   ├── source-watch.yml
│   └── validate.yml
├── assets/
│   ├── css/
│   │   ├── intelligence.css
│   │   ├── performance.css
│   │   └── styles.css
│   └── js/
│       ├── app.js
│       ├── intelligence.js
│       └── portfolio.js
├── data/
│   ├── commodities.json
│   ├── dashboard.json
│   ├── revision_summary.json
│   ├── source_status.json
│   ├── intelligence/<commodity>.json
│   ├── observations/YYYY-MM/*.json
│   └── revisions/YYYY-MM/<commodity>.<value_type>/*.json
├── scripts/
│   ├── backfill_tradestat.py
│   ├── build_dashboard.py
│   ├── build_intelligence.py
│   ├── build_revision_summary.py
│   ├── check_source.py
│   ├── ingest_tradestat.py
│   ├── probe_quantity_units.py
│   └── validate_data.py
├── src/tracker/
│   ├── aggregation.py
│   ├── dashboard.py
│   ├── derived.py
│   ├── intelligence.py
│   ├── mapping_quality.py
│   ├── releases.py
│   ├── tradestat.py
│   └── validation.py
├── tests/
├── index.html
└── pyproject.toml
```

## Dependency score

The dependency score is deliberately transparent:

- **60%** — net-import reliance
- **25%** — top supplier share
- **15%** — supplier HHI concentration

It is a ranking signal for the watched universe, not a claim about official national strategic-risk policy.

## Publication

GitHub Pages is enabled for the repository. Commits to `main` trigger the Pages deployment flow so static code and generated data move together.

## Next priorities

1. Finish and validate the Batteries 2018-present quantity archive recovery.
2. Extend exact-HS8 quantity coverage only where classification stability and physical-unit compatibility are independently verified.
3. Continue revalidating Final/Revised-Final TradeStat history and archiving genuine source revisions.
4. Promote broad HS2/4/6 commodity definitions to precise HS8 mappings where economically meaningful.
5. Expand cross-commodity and supplier-country intelligence without increasing initial-page payload or scroll cost.
