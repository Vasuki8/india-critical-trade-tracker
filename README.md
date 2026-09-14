# India Critical Commodity Trade Tracker

A static, GitHub-Pages-friendly tracker for India's strategically important commodity imports and exports. The project is designed around official Department of Commerce TradeStat / DGCI&S data, source provenance, revision handling and ITC-HS classification changes.

## Phase 1 status

Implemented:
- 23 critical commodity groups and initial HS mappings.
- Static dashboard shell with search/category filtering.
- Data contracts for commodity master, dashboard data and source status.
- Daily TradeStat source monitor.
- Validation tests and GitHub Actions CI.
- Explicit mapping statuses for HS definitions that still need HS8-level validation.

Not yet implemented:
- Automated monthly trade-value ingestion.
- Commodity × country supplier/destination ingestion.
- Quantity/unit ingestion.
- Dependency/concentration scoring.
- Historical charts and revision-aware backfills.

## Official source

Primary monthly source:
`https://tradestat.commerce.gov.in/meidb/commoditywise_import`

The tracker treats the April 2026 ITC-HS reallocation/unit warning as a schema/version issue rather than silently joining incompatible series.

## Local setup with uv

```powershell
uv sync --dev
uv run python scripts/validate_data.py
uv run pytest -q
uv run python -m http.server 8000
```

Then open `http://localhost:8000`.

To check the current official source status:

```powershell
uv run python scripts/check_source.py
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
│   └── source_status.json
├── scripts/
│   ├── check_source.py
│   └── validate_data.py
├── src/tracker/
│   └── validation.py
├── tests/
├── index.html
└── pyproject.toml
```

## Next build step

Build a revision-aware TradeStat ingestion adapter that writes normalized monthly observations with:
- period
- trade type
- HS version / HS code
- commodity group
- value in USD/INR
- quantity and unit when available
- partner country
- source URL
- source publication date
- retrieval timestamp
- final/revised-final status

No data point should reach the dashboard without its source and reporting period.
