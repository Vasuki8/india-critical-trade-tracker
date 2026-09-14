# India Critical Commodity Trade Tracker

A live tracker for India's strategically important commodity imports and exports, built around official Department of Commerce TradeStat / DGCI&S MEIDB data and published as a static GitHub Pages site.

## Current build

The tracker covers **23 critical commodity groups** and currently carries official monthly data through **June 2026**. The ingestion layer preserves partner-country detail and source provenance, then derives:

- imports, exports and trade balance
- monthly YoY change and calendar-year YTD values
- top suppliers / export destinations and concentration
- a transparent dependency score
- physical quantity and implied USD per source unit for validated HS8 mappings
- monthly commodity history from stored observations

The source monitor checks TradeStat daily. Heavy ingestion runs only when the official release changes, a stored mapping becomes stale, or a quantity observation needs contract/provenance refresh.

## Verified TradeStat MEIDB contracts

### Values selector

The live MEIDB commodity-all-countries forms were verified on **14 September 2026**. Both import and export forms use:

| Value type | Selector code |
| --- | ---: |
| US $ Million | `1` |
| Quantity | `2` |
| ₹ Crore | `3` |

The client validates this live selector contract before submitting an ingestion request. If TradeStat changes the form mapping, ingestion fails loudly rather than silently storing one measure as another.

### Quantity units

TradeStat exposes physical quantity only at **HS8** in this workflow. For the MEIDB quantity endpoint, returned values are already expressed in the displayed source unit (for example `KGS` or `NOS`), so the tracker uses a quantity scale of **1**. No additional thousand-unit multiplier is applied.

Implied unit values are calculated only when:

- the monetary and quantity observations match on period, trade direction and HS8 code;
- the quantity report carries the verified selector code `2`;
- the source quantity unit is present; and
- quantity is positive.

Validated quantity-capable groups currently include:

- **Lithium & Compounds** — `28252000`, `28369100` (`KGS`)
- **Natural Gas / LNG** — `27111100`, `27112100` (`KGS`)
- **Solar Cells / Modules** — `85414200`, `85414300` (`NOS`)

Solar cell and module unit values are kept at HS8 level because a bare photovoltaic cell and a completed module/panel are not economically comparable units.

## Data integrity rules

- Every stored report retains period, trade type, HS code, value type, selector code, partner-country rows, source URL, report date, retrieval timestamp and checksum.
- Quantity ingestion is rejected unless the active mapping is HS8.
- Mappings marked `needs`, `partial` or `sensitive` are skipped by automatic ingestion until reviewed.
- A commodity observation is not written if one of its required import/export requests fails, unless partial persistence is explicitly allowed.
- Dashboard portfolio totals deduplicate parent/child HS mappings using a shortest-prefix union, preventing double counting such as HS 85 plus HS 8541/8517.
- Stored observations are automatically refreshed when their active HS mapping differs from the commodity master or the period's classification era.
- Quantity observations are refreshed when selector provenance or direct-unit scale metadata is stale.
- Quantity-only months cannot advance the dashboard's headline `as_of` period.
- The April 2026 TradeStat ITC-HS reallocation/unit warning remains a classification guardrail.

### Classification-aware series

Solar PV is explicitly versioned around the ITC(HS) 2022 change:

- through **January 2022**: `85414011`, `85414012`
- **February 2022**: transition month intentionally not auto-stitched
- from **March 2022**: `85414200`, `85414300`

This prevents the history layer from pretending the current solar codes existed unchanged across the classification transition.

## Automation

### Daily source watch

`.github/workflows/source-watch.yml`:

1. checks the official TradeStat release state;
2. compares stored observations with current HS mappings and quantity provenance;
3. fetches only the USD and/or quantity layers that are actually stale;
4. rebuilds `data/dashboard.json`;
5. validates the commodity master and runs the full test suite; and
6. commits official-data changes back to `main`.

### Validation

`.github/workflows/validate.yml` runs on pushes and pull requests and checks:

- commodity-master validation;
- Python tests; and
- dashboard JavaScript syntax with `node --check`.

### Historical backfill

A controlled workflow is available at `.github/workflows/backfill.yml`. It is intentionally separate from the lightweight daily updater.

The backfill is **resumable**. Before any request, `scripts/backfill_tradestat.py` checks each period/commodity observation for:

- active period-specific HS mapping;
- requested import/export coverage;
- value type;
- successful stored status; and
- for quantity, selector code `2` plus direct-unit scale `1`.

Current observations are skipped automatically. Missing, incomplete or stale observations are fetched. This lets interrupted or partially completed backfills be rerun without repeating every official-site request.

Safety limits remain in place: all-commodity USD runs are limited to 12 months per workflow run; single-commodity or quantity runs may cover up to 36 months.

You can preview a local backfill without network writes:

```powershell
uv run python scripts/backfill_tradestat.py --start-period 2025-01 --end-period 2025-12 --value-type usd --trade-type both --dry-run
```

Run the same resumable batch:

```powershell
uv run python scripts/backfill_tradestat.py --start-period 2025-01 --end-period 2025-12 --value-type usd --trade-type both
```

## Local setup with uv

```powershell
uv sync --dev
uv run python scripts/validate_data.py
uv run pytest -q
uv run python -m http.server 8000
```

Then open `http://localhost:8000`.

## Ingest official data

Check the official source:

```powershell
uv run python scripts/check_source.py
```

Latest USD observations:

```powershell
uv run python scripts/ingest_tradestat.py --latest --trade-type both --value-type usd --year-type calendar
```

Latest physical quantity observations for eligible HS8 groups:

```powershell
uv run python scripts/ingest_tradestat.py --latest --trade-type both --value-type quantity --year-type calendar
```

One commodity and one period:

```powershell
uv run python scripts/ingest_tradestat.py --period 2026-06 --commodity natural_gas_lng --trade-type both --value-type quantity
```

Rebuild the static dashboard JSON from stored observations:

```powershell
uv run python scripts/build_dashboard.py
```

## Repository structure

```text
.
├── .github/workflows/
│   ├── backfill.yml
│   ├── source-watch.yml
│   └── validate.yml
├── assets/
│   ├── css/styles.css
│   └── js/app.js
├── data/
│   ├── commodities.json
│   ├── dashboard.json
│   ├── source_status.json
│   └── observations/YYYY-MM/*.json
├── scripts/
│   ├── backfill_tradestat.py
│   ├── build_dashboard.py
│   ├── check_source.py
│   ├── ingest_tradestat.py
│   └── validate_data.py
├── src/tracker/
│   ├── aggregation.py
│   ├── dashboard.py
│   ├── derived.py
│   ├── tradestat.py
│   └── validation.py
├── tests/
├── index.html
└── pyproject.toml
```

## Dependency score

The model is deliberately transparent:

- **60%** — net-import reliance
- **25%** — top supplier share
- **15%** — supplier HHI concentration

The score is intended for ranking watched commodities, not as a claim about national strategic-risk policy.

## Publication

GitHub Pages is enabled for the repository. Updates committed to `main` trigger the repository's Pages build/deployment flow, so the static site and its generated dashboard data move together.

## Next build priorities

1. Backfill monthly USD history from 2018 in bounded resumable batches.
2. Backfill HS8 quantity history for validated quantity-capable groups and calculate historical implied unit values.
3. Add interactive historical charts and country drill-downs from the stored monthly history.
4. Separate first-release and revised observations so revisions can be measured rather than silently replacing prior values.
5. Continue promoting broad HS2/4/6 commodity groups to validated HS8 definitions where an exact, stable mapping is economically meaningful.
