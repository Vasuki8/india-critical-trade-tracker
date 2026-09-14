# India Critical Commodity Trade Tracker

A GitHub-Pages-friendly tracker for India's strategically important commodity imports and exports, built around official Department of Commerce TradeStat / DGCI&S data.

## Current build

The project now includes a revision-aware MEIDB ingestion layer for **commodity-wise all-countries monthly data**. It supports imports and exports for valid 2-, 4-, 6- and 8-digit HS codes, preserves partner-country rows and source provenance, and calculates trade balance, supplier concentration and a transparent dependency score.

The source monitor checks TradeStat daily, but the heavier commodity ingestion only runs when the official release markers change or when the tracker has never been populated. TradeStat currently reports monthly MEIDB data from January 2018 onward.

### Data integrity rules

- Every stored observation retains period, trade type, HS code, partner country, source URL, report date, retrieval timestamp and response checksum.
- Quantity is rejected unless the mapping is an 8-digit HS code.
- Mappings marked `needs`, `partial` or `sensitive` are skipped by automatic ingestion until reviewed.
- Dashboard portfolio totals deduplicate parent/child HS mappings using a shortest-prefix union, so HS 85 is not added again to HS 8541/8517.
- A commodity is not written if one of its required import/export requests fails.
- The April 2026 TradeStat ITC-HS reallocation/unit warning remains a classification guardrail.

## Local setup with uv

```powershell
uv sync --dev
uv run python scripts/validate_data.py
uv run pytest -q
uv run python -m http.server 8000
```

Then open `http://localhost:8000`.

## Ingest official data

Latest official month for all automatically approved mappings:

```powershell
uv run python scripts/check_source.py
uv run python scripts/ingest_tradestat.py --latest --trade-type both
```

One commodity and one period:

```powershell
uv run python scripts/ingest_tradestat.py --period 2026-06 --commodity crude_oil --trade-type both
```

Rebuild the static dashboard JSON from stored observations:

```powershell
uv run python scripts/build_dashboard.py
```

## Repository structure

```text
.
├── .github/workflows/
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
│   ├── build_dashboard.py
│   ├── check_source.py
│   ├── ingest_tradestat.py
│   └── validate_data.py
├── src/tracker/
│   ├── aggregation.py
│   ├── dashboard.py
│   ├── tradestat.py
│   └── validation.py
├── tests/
├── index.html
└── pyproject.toml
```

## Dependency score

The first version is deliberately transparent rather than pretending to be a proprietary risk model:

- 60%: net-import reliance
- 25%: top supplier share
- 15%: supplier HHI concentration

The score is intended for ranking watched commodities, not as a claim about national strategic-risk policy.

## Next build priorities

1. Validate version-sensitive HS8 mappings for solar, lithium and other strategic materials.
2. Add quantity/unit series at HS8 and implied unit values.
3. Backfill monthly history from 2018 (and selected FTSPCC series from 2010 where definitions are compatible).
4. Add interactive historical charts and country drill-downs.
5. Track source revisions separately from first-release values.
