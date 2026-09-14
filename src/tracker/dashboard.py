from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .aggregation import aggregate_commodity, portfolio_summary
from .derived import derive_unit_values


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _observation_value_type(doc: dict[str, Any]) -> str | None:
    explicit = doc.get("value_type")
    if explicit:
        return str(explicit)
    report_types = {str(report.get("value_type", "usd")) for report in doc.get("reports", [])}
    if not report_types:
        return "usd"
    if len(report_types) == 1:
        return next(iter(report_types))
    return None


def _is_usd_observation(doc: dict[str, Any]) -> bool:
    return _observation_value_type(doc) == "usd"


def _documents_by_commodity(period_dir: Path, value_type: str) -> dict[str, dict[str, Any]]:
    """Return one observation per commodity/value type, preferring explicit v2+ files."""
    selected: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
    suffix = f".{value_type}.json"
    for path in sorted(period_dir.glob("*.json")):
        doc = _load(path)
        if _observation_value_type(doc) != value_type:
            continue
        commodity_id = str(doc.get("commodity", {}).get("id") or "")
        if not commodity_id:
            continue
        score = (
            1 if doc.get("value_type") == value_type else 0,
            1 if path.name.endswith(suffix) else 0,
        )
        previous = selected.get(commodity_id)
        if previous is None or score > previous[0]:
            selected[commodity_id] = (score, doc)
    return {commodity_id: pair[1] for commodity_id, pair in selected.items()}


def _live_metrics(doc: dict[str, Any]) -> dict[str, Any]:
    reports = doc.get("reports", [])
    return aggregate_commodity(reports) if reports else doc.get("metrics", {})


def _commodity_card(
    usd_doc: dict[str, Any],
    quantity_doc: dict[str, Any] | None,
) -> dict[str, Any]:
    metrics = _live_metrics(usd_doc)
    card = {
        "id": usd_doc["commodity"]["id"],
        "name": usd_doc["commodity"]["name"],
        "category": usd_doc["commodity"]["category"],
        "hs_codes": usd_doc["commodity"]["hs_codes"],
        "mapping_status": usd_doc["commodity"]["mapping_status"],
        **metrics,
        "status": usd_doc.get("status", "ok"),
    }
    unit_values = derive_unit_values(usd_doc, quantity_doc)
    if quantity_doc is not None or unit_values["status"] == "ok":
        card["unit_values"] = unit_values
    return card


def _history_point(
    period: str,
    usd_doc: dict[str, Any],
    quantity_doc: dict[str, Any] | None,
) -> dict[str, Any]:
    metrics = _live_metrics(usd_doc)
    dependency = metrics.get("dependency", {})
    unit_values = derive_unit_values(usd_doc, quantity_doc)
    return {
        "period": period,
        "imports": metrics.get("imports"),
        "exports": metrics.get("exports"),
        "balance": metrics.get("balance"),
        "import_yoy_pct": metrics.get("import_yoy_pct"),
        "export_yoy_pct": metrics.get("export_yoy_pct"),
        "ytd_imports": metrics.get("ytd_imports"),
        "ytd_exports": metrics.get("ytd_exports"),
        "ytd_balance": metrics.get("ytd_balance"),
        "dependency_score": dependency.get("score"),
        "dependency_risk": dependency.get("risk"),
        "unit_values": unit_values.get("aggregate", {}),
        "status": usd_doc.get("status", "ok"),
    }


def _empty_dashboard() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "as_of": None,
        "currency": "USD",
        "unit_scale": "million",
        "status": "awaiting_trade_ingestion",
        "summary": {"imports": None, "exports": None, "balance": None},
        "commodities": [],
        "monthly": [],
        "commodity_history": {},
    }


def build_dashboard(observations_root: Path, out_path: Path) -> dict[str, Any]:
    period_dirs = sorted(p for p in observations_root.glob("????-??") if p.is_dir())
    if not period_dirs:
        doc = _empty_dashboard()
        out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        return doc

    monthly: list[dict[str, Any]] = []
    commodity_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    latest_commodities: list[dict[str, Any]] = []
    latest_period: str | None = None

    for period_dir in period_dirs:
        usd_docs = _documents_by_commodity(period_dir, "usd")
        if not usd_docs:
            # A quantity-only backfill must never advance the dashboard's headline period.
            continue
        quantity_docs = _documents_by_commodity(period_dir, "quantity")

        reports = [report for doc in usd_docs.values() for report in doc.get("reports", [])]
        summary = portfolio_summary(reports)
        monthly.append({"period": period_dir.name, **summary})

        cards: list[dict[str, Any]] = []
        for commodity_id in sorted(usd_docs):
            usd_doc = usd_docs[commodity_id]
            quantity_doc = quantity_docs.get(commodity_id)
            cards.append(_commodity_card(usd_doc, quantity_doc))
            commodity_history[commodity_id].append(
                _history_point(period_dir.name, usd_doc, quantity_doc)
            )

        latest_period = period_dir.name
        latest_commodities = cards

    if latest_period is None or not monthly:
        doc = _empty_dashboard()
        out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        return doc

    latest_summary = monthly[-1].copy()
    latest_summary.pop("period", None)
    dashboard = {
        "schema_version": 3,
        "as_of": latest_period,
        "currency": "USD",
        "unit_scale": "million",
        "status": "ok",
        "summary": latest_summary,
        "commodities": latest_commodities,
        "monthly": monthly,
        "commodity_history": dict(sorted(commodity_history.items())),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8")
    return dashboard
