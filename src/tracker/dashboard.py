from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .aggregation import portfolio_summary


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_usd_observation(doc: dict[str, Any]) -> bool:
    value_type = doc.get("value_type")
    if value_type is not None:
        return value_type == "usd"
    reports = doc.get("reports", [])
    if not reports:
        return True
    return all(report.get("value_type", "usd") == "usd" for report in reports)


def build_dashboard(observations_root: Path, out_path: Path) -> dict[str, Any]:
    period_dirs = sorted(p for p in observations_root.glob("????-??") if p.is_dir())
    if not period_dirs:
        doc = {
            "schema_version": 2,
            "as_of": None,
            "currency": "USD",
            "unit_scale": "million",
            "status": "awaiting_trade_ingestion",
            "summary": {"imports": None, "exports": None, "balance": None},
            "commodities": [],
            "monthly": [],
        }
        out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        return doc

    monthly = []
    latest_commodities: list[dict[str, Any]] = []
    latest_period = period_dirs[-1].name

    for period_dir in period_dirs:
        docs = [_load(path) for path in sorted(period_dir.glob("*.json"))]
        docs = [doc for doc in docs if _is_usd_observation(doc)]
        reports = [report for doc in docs for report in doc.get("reports", [])]
        summary = portfolio_summary(reports)
        monthly.append({"period": period_dir.name, **summary})
        if period_dir.name == latest_period:
            latest_commodities = [
                {
                    "id": doc["commodity"]["id"],
                    "name": doc["commodity"]["name"],
                    "category": doc["commodity"]["category"],
                    "hs_codes": doc["commodity"]["hs_codes"],
                    "mapping_status": doc["commodity"]["mapping_status"],
                    **doc.get("metrics", {}),
                    "status": doc.get("status", "ok"),
                }
                for doc in docs
            ]

    latest_summary = monthly[-1].copy()
    latest_summary.pop("period", None)
    dashboard = {
        "schema_version": 2,
        "as_of": latest_period,
        "currency": "USD",
        "unit_scale": "million",
        "status": "ok",
        "summary": latest_summary,
        "commodities": latest_commodities,
        "monthly": monthly,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8")
    return dashboard
