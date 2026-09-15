from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .aggregation import aggregate_commodity, portfolio_summary
from .derived import derive_unit_values


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_dashboard(path: Path, value: dict[str, Any]) -> None:
    """Write the eagerly loaded derived dashboard without pretty-print overhead."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


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
    """Compatibility helper retained for callers and value-type contract tests."""
    return _observation_value_type(doc) == "usd"


def _documents_by_value_type(period_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """Load a period directory once and select one observation per commodity/value type."""
    selected: dict[str, dict[str, tuple[tuple[int, int], dict[str, Any]]]] = defaultdict(dict)
    for path in sorted(period_dir.glob("*.json")):
        doc = _load(path)
        value_type = _observation_value_type(doc)
        if value_type is None:
            continue
        commodity_id = str(doc.get("commodity", {}).get("id") or "")
        if not commodity_id:
            continue
        suffix = f".{value_type}.json"
        score = (
            1 if doc.get("value_type") == value_type else 0,
            1 if path.name.endswith(suffix) else 0,
        )
        previous = selected[value_type].get(commodity_id)
        if previous is None or score > previous[0]:
            selected[value_type][commodity_id] = (score, doc)
    return {
        value_type: {commodity_id: pair[1] for commodity_id, pair in entries.items()}
        for value_type, entries in selected.items()
    }


def _live_metrics(doc: dict[str, Any]) -> dict[str, Any]:
    reports = doc.get("reports", [])
    return aggregate_commodity(reports) if reports else doc.get("metrics", {})


def _compact_unit_values(unit_values: dict[str, Any]) -> dict[str, Any]:
    """Keep browser-relevant unit-value fields while retaining real validation errors."""
    compact = {
        "status": unit_values.get("status", "not_available"),
        "method": unit_values.get("method"),
        "quantity_scale_note": unit_values.get("quantity_scale_note"),
        "aggregate": unit_values.get("aggregate", {}),
    }
    structural_mismatches = {"missing_usd_report", "missing_quantity_report"}
    diagnostics = [
        item
        for item in unit_values.get("by_hs_code", [])
        if item.get("status") not in structural_mismatches
    ]
    if diagnostics:
        compact["by_hs_code"] = diagnostics
    return {key: value for key, value in compact.items() if value is not None}


def _commodity_card(
    usd_doc: dict[str, Any],
    quantity_doc: dict[str, Any] | None,
    *,
    metrics: dict[str, Any] | None = None,
    unit_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = metrics if metrics is not None else _live_metrics(usd_doc)
    card = {
        "id": usd_doc["commodity"]["id"],
        "name": usd_doc["commodity"]["name"],
        "category": usd_doc["commodity"]["category"],
        "hs_codes": usd_doc["commodity"]["hs_codes"],
        "mapping_status": usd_doc["commodity"]["mapping_status"],
        **metrics,
        "status": usd_doc.get("status", "ok"),
    }
    unit_values = unit_values if unit_values is not None else derive_unit_values(usd_doc, quantity_doc)
    if quantity_doc is not None or unit_values["status"] == "ok":
        card["unit_values"] = _compact_unit_values(unit_values)
    return card


def _history_point(
    period: str,
    usd_doc: dict[str, Any],
    quantity_doc: dict[str, Any] | None,
    *,
    metrics: dict[str, Any] | None = None,
    unit_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = metrics if metrics is not None else _live_metrics(usd_doc)
    dependency = metrics.get("dependency", {})
    unit_values = unit_values if unit_values is not None else derive_unit_values(usd_doc, quantity_doc)
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


def _commodity_master(master_path: Path | None) -> dict[str, Any] | None:
    if master_path is None or not master_path.exists():
        return None
    try:
        value = _load(master_path)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value.get("commodities"), list) else None


def _coverage_metadata(
    observed_ids: set[str],
    expected_ids: set[str] | None,
) -> dict[str, Any]:
    if expected_ids is None:
        return {}
    missing = sorted(expected_ids - observed_ids)
    return {
        "coverage_status": "complete" if not missing else "partial",
        "observed_commodity_count": len(observed_ids),
        "expected_commodity_count": len(expected_ids),
        "missing_commodities": missing,
    }


def _history_gaps(
    master: dict[str, Any] | None,
    *,
    first_period: str,
    last_period: str,
) -> dict[str, list[dict[str, str]]]:
    if master is None:
        return {}
    output: dict[str, list[dict[str, str]]] = {}
    for commodity in master.get("commodities", []):
        commodity_id = str(commodity.get("id") or "")
        if not commodity_id:
            continue
        gaps = [
            {
                "period": period,
                "reason": "classification_transition",
                "note": "Historical mapping intentionally omitted for this classification transition month; do not interpret the missing observation as zero trade.",
            }
            for period in commodity.get("classification_transition_periods", [])
            if first_period <= period <= last_period
        ]
        if gaps:
            output[commodity_id] = gaps
    return output


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
        "history_gaps": {},
    }


def build_dashboard(
    observations_root: Path,
    out_path: Path,
    commodity_master_path: Path | None = None,
) -> dict[str, Any]:
    period_dirs = sorted(p for p in observations_root.glob("????-??") if p.is_dir())
    if not period_dirs:
        doc = _empty_dashboard()
        _write_dashboard(out_path, doc)
        return doc

    master = _commodity_master(commodity_master_path)
    expected_ids = (
        {str(item.get("id")) for item in master.get("commodities", []) if item.get("id")}
        if master is not None
        else None
    )

    monthly: list[dict[str, Any]] = []
    commodity_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    latest_commodities: list[dict[str, Any]] = []
    latest_period: str | None = None

    for period_dir in period_dirs:
        docs_by_type = _documents_by_value_type(period_dir)
        usd_docs = docs_by_type.get("usd", {})
        if not usd_docs:
            # A quantity-only backfill must never advance the dashboard's headline period.
            continue
        quantity_docs = docs_by_type.get("quantity", {})

        reports = (
            report
            for doc in usd_docs.values()
            for report in doc.get("reports", [])
        )
        summary = portfolio_summary(reports)
        coverage = _coverage_metadata(set(usd_docs), expected_ids)
        monthly.append({"period": period_dir.name, **summary, **coverage})

        cards: list[dict[str, Any]] = []
        for commodity_id in sorted(usd_docs):
            usd_doc = usd_docs[commodity_id]
            quantity_doc = quantity_docs.get(commodity_id)
            metrics = _live_metrics(usd_doc)
            unit_values = derive_unit_values(usd_doc, quantity_doc)
            cards.append(
                _commodity_card(
                    usd_doc,
                    quantity_doc,
                    metrics=metrics,
                    unit_values=unit_values,
                )
            )
            commodity_history[commodity_id].append(
                _history_point(
                    period_dir.name,
                    usd_doc,
                    quantity_doc,
                    metrics=metrics,
                    unit_values=unit_values,
                )
            )

        latest_period = period_dir.name
        latest_commodities = cards

    if latest_period is None or not monthly:
        doc = _empty_dashboard()
        _write_dashboard(out_path, doc)
        return doc

    latest_summary = monthly[-1].copy()
    latest_summary.pop("period", None)
    first_period = monthly[0]["period"]
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
        "history_gaps": _history_gaps(master, first_period=first_period, last_period=latest_period),
    }
    _write_dashboard(out_path, dashboard)
    return dashboard
