# India Critical Commodity Trade Tracker

A live tracker for India's strategically important commodity imports and exports, built around official Department of Commerce TradeStat / DGCI&S MEIDB data and published as a static GitHub Pages site.

## Current build

The tracker covers **23 critical commodity groups** and currently carries official monthly data through **June 2026**. The baseline historical archive is complete from the TradeStat monthly lower bound of **January 2018 through June 2026**, spanning **102 calendar months** and **2,345 commodity-month history rows**.

There is one intentional series gap: **Solar PV for February 2022**. The ITC(HS) classification changed around that period, so the tracker explicitly marks the transition instead of inventing a bridge between old and new commodity codes. Apart from that classification transition, the validated USD history is continuous for the watched universe.

Historical HS8 quantity observations and implied unit values are present for **Natural Gas / LNG**, **Lithium & Compounds**, and **Solar Cells / Modules** wherever the period-specific exact HS8 mapping is valid. Solar PV retains the same intentional February 2022 transition gap.

The site has two complementary analytical layers:

- a lightweight **consolidated portfolio dashboard** for the full watched commodity universe; and
- a lazy-loaded **commodity intelligence drill-down** for each commodity, generated from the stored observation archive.

For an individual commodity such as Crude Oil, the intelligence view provides:

- month-by-month imports, exports and trade balance;
- every reported partner country for a selected month, with import/export value and share;
- historical trends for any selected supplier or export destination;
- annual consolidated imports, exports and balance;
- top supplier, supplier share and HHI concentration by year;
- long-run cumulative imports/exports, peak import month and dependency indicators;
- HS-level breakdowns and quantity / implied unit-value context where validated; and
- explicit classification-transition warnings so a missing mapping cannot be read as zero trade.

The consolidated portfolio view adds monthly and annual imports/exports for the complete watched universe, cumulative totals, peak import month and explicit complete/partial coverage status.

## Intelligence data architecture

`data/dashboard.json` remains the small portfolio-level payload used for the initial page load.

Deep country/month detail is generated deterministically from `data/observations/` into one file per commodity:

```text
data/intelligence/<commodity>.json
```

The browser downloads one of these files only when the user clicks **Explore intelligence**, keeping the homepage responsive as the archive grows. `data/intelligence/index.json` is the generated manifest.

The intelligence builder preserves all partner-country rows rather than limiting the stored drill-down to the top five. Repository tests require each intelligence file's periods and classification gaps to match the canonical dashboard history.

Rebuild the intelligence layer locally with:

```powershell
uv run python scripts/build_intelligence.py
```

## Derived analytics

The ingestion layer preserves partner-country detail and source provenance, then derives:

- imports, exports and trade balance;
- monthly YoY change and calendar-year YTD values;
- top suppliers / export destinations and concentration;
- a transparent dependency score;
- physical quantity and implied USD per source unit for validated HS8 mappings;
- monthly commodity history from stored observations;
- consolidated annual commodity and portfolio views; and
- revision history when an official observation changes semantically.

The source monitor checks TradeStat daily. Heavy ingestion runs only when official release metadata changes, a stored observation is stale, or a bounded Revised-Final refresh is required after a publication change. Timestamp-only source checks remain no-ops.

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
- **Solar Cells / Modules** — period-specific HS8 mappings (`NOS`):
  - through January 2022: `85414011`, `85414012`
  - February 2022: intentional transition gap
  - from March 2022: `85414200`, `85414300`

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
- Generated commodity intelligence must stay synchronized with dashboard periods and classification gaps.
- The April 2026 TradeStat ITC-HS reallocation/unit warning remains a classification guardrail.

### Revision-aware observations

The dashboard reads one current document from:

```text
data/observations/YYYY-MM/<commodity>.<value_type>.json
```

Before replacing an existing current observation, the ingester computes a deterministic semantic fingerprint. Fetch-time-only provenance such as `retrieved_at` is excluded from that identity.

If the refetched observation is semantically identical, the current file is left untouched and no revision is created. If official values, partner rows, headers/status markers, report date, checksum, HS mapping, units, totals or other semantic content changes, the previous current document is preserved at:

```text
data/revisions/YYYY-MM/<commodity>.<value_type>/<fingerprint>.json
```

This applies to both the daily source watcher and historical backfills because they share the same observation writer. Deterministic fingerprints also prevent duplicate archive copies when the same historical version is encountered again.

When official publication metadata changes, the daily watcher plans a bounded Revised-Final sweep. Normally it rechecks the trailing three Revised-Final months; if the official Revised-Final cutoff advances, it also covers the newly revised interval. Automatic sweeps are capped at 12 months so the daily watcher cannot become an unbounded historical backfill.

### Classification-aware series

Solar PV is explicitly versioned around the ITC(HS) 2022 change:

- through **January 2022**: `85414011`, `85414012`
- **February 2022**: transition month intentionally not auto-stitched
- from **March 2022**: `85414200`, `85414300`

This prevents the history layer from pretending the current solar codes existed unchanged across the classification transition. Consequently, February 2022 is shown as an explicit coverage/classification gap rather than zero trade.

## Automation

### Daily source watch

`.github/workflows/source-watch.yml`:

1. checks the official TradeStat release state;
2. compares stored latest observations with current HS mappings and quantity provenance;
3. plans a bounded Revised-Final historical refresh when official publication metadata changes;
4. fetches only stale/latest layers plus any required forced historical revision window;
5. archives superseded semantic observations before replacing them;
6. rebuilds `data/dashboard.json`, `data/revision_summary.json` and `data/intelligence/`;
7. validates the commodity master, generated history/intelligence synchronization, Python tests and frontend JavaScript; and
8. commits official data plus generated intelligence and any revision archives back to `main`.

### Validation

`.github/workflows/validate.yml` runs on pushes and pull requests and checks:

- generated commodity intelligence can be rebuilt from stored observations;
- commodity-master and generated-dashboard validation;
- Python tests, including intelligence/dashboard synchronization; and
- JavaScript syntax for the homepage, portfolio history and commodity intelligence views.

### Historical backfill

A controlled reusable workflow is available at `.github/workflows/backfill.yml`. It is intentionally separate from the lightweight daily updater.

The planned baseline backfill is now **complete from January 2018 through the latest stored release**. The workflow remains available for resumable repairs, targeted refetches, official revisions, and rebuilding missing USD or eligible quantity layers.

The workflow can backfill **USD**, **quantity**, or **both** layers in one run. When `both` is selected, USD is processed first and then eligible HS8 quantity observations are processed before final validation and commit.

The backfill is **resumable**. Before any request, `scripts/backfill_tradestat.py` checks each period/commodity observation for:

- active period-specific HS mapping;
- requested import/export coverage;
- value type;
- successful stored status; and
- for quantity, selector code `2` plus direct-unit scale `1`.

Current observations are skipped automatically. Missing, incomplete or stale observations are fetched. If a forced or stale refetch produces a genuine revision, the prior version is archived by the shared observation writer.

Safety limits remain in place: all-commodity USD runs are limited to 12 months per workflow run; single-commodity or quantity runs may cover up to 36 months. The backfill guard treats **January 2018** as the monthly history lower bound and rejects earlier periods.

Preview a lower-bound year without network writes:

```powershell
uv run python scripts/backfill_tradestat.py --start-period 2018-01 --end-period 2018-12 --value-type usd --trade-type both --dry-run
```

Re-running that batch is safe: already-current observations are skipped automatically unless `--force` is supplied.

For GitHub Actions, select `both` in the **Backfill TradeStat history** workflow when USD and eligible HS8 quantity history should be checked together.

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

## Repository structure

```text
.
├── .github/workflows/
│   ├── backfill.yml
│   ├── source-watch.yml
│   └── validate.yml
├── assets/
│   ├── css/
│   │   ├── intelligence.css
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
│   └── validate_data.py
├── src/tracker/
│   ├── aggregation.py
│   ├── dashboard.py
│   ├── derived.py
│   ├── intelligence.py
│   ├── releases.py
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

GitHub Pages is enabled for the repository. Updates committed to `main` trigger the repository's Pages build/deployment flow, so the static site and its generated data move together.

## Next build priorities

1. Maintain and revalidate the **2018-present** archive as TradeStat publishes Final and Revised-Final updates.
2. Extend exact-HS8 quantity coverage where stable, economically meaningful mappings can be validated.
3. Add richer cross-commodity comparison and supplier-country concentration views on top of the intelligence layer.
4. Continue validating, archiving and surfacing official revisions as the Revised-Final window moves.
5. Continue promoting broad HS2/4/6 commodity groups to validated HS8 definitions where an exact, stable mapping is economically meaningful.
