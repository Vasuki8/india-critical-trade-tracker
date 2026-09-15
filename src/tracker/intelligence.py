from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .aggregation import aggregate_commodity_details, concentration_metrics
from .derived import derive_unit_values

ObservationIndex = dict[str, dict[str, dict[str, Path]]]


def _load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _build_observation_index(observations_root: Path) -> ObservationIndex:
    """Index archive paths once instead of probing every period for every commodity."""
    index: ObservationIndex = {}
    for period_dir in sorted(path for path in observations_root.glob("????-??") if path.is_dir()):
        period_entries: dict[str, dict[str, Path]] = defaultdict(dict)
        for path in period_dir.glob("*.json"):
            name = path.name
            if name.endswith(".usd.json"):
                commodity_id = name[:-9]
                period_entries[commodity_id]["usd"] = path
            elif name.endswith(".quantity.json"):
                commodity_id = name[:-14]
                period_entries[commodity_id]["quantity"] = path
            elif name.endswith(".json"):
                commodity_id = name[:-5]
                # Legacy observations were USD-only. Explicit v2+ files always win.
                period_entries[commodity_id].setdefault("usd", path)
        if period_entries:
            index[period_dir.name] = dict(period_entries)
    return index


def _reports(doc: dict[str, Any], trade_type: str) -> list[dict[str, Any]]:
    return [report for report in doc.get("reports", []) if report.get("trade_type") == trade_type]


def _hs_breakdown(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "hs_code": report.get("hs_code"),
            "description": report.get("description"),
            "value": report.get("totals", {}).get("value"),
            "source_unit": report.get("quantity_unit") or report.get("source_unit"),
        }
        for report in reports
    ]


def _unit_value_summary(
    usd_doc: dict[str, Any],
    quantity_doc: dict[str, Any] | None,
) -> dict[str, Any]:
    derived = derive_unit_values(usd_doc, quantity_doc)
    if derived.get("status") != "ok":
        return {"status": derived.get("status", "unavailable")}
    return {
        "status": "ok",
        "aggregate": derived.get("aggregate", {}),
        "hs_codes": derived.get("hs_codes", {}),
    }


def _month_entry(
    period: str,
    usd_doc: dict[str, Any],
    quantity_doc: dict[str, Any] | None,
) -> dict[str, Any]:
    reports = usd_doc.get("reports", [])
    metrics, imports_by_country, exports_by_country = aggregate_commodity_details(reports)
    imports = _reports(usd_doc, "import")
    exports = _reports(usd_doc, "export")
    return {
        "period": period,
        "imports": metrics.get("imports"),
        "exports": metrics.get("exports"),
        "balance": metrics.get("balance"),
        "import_yoy_pct": metrics.get("import_yoy_pct"),
        "export_yoy_pct": metrics.get("export_yoy_pct"),
        "ytd_imports": metrics.get("ytd_imports"),
        "ytd_exports": metrics.get("ytd_exports"),
        "dependency": metrics.get("dependency", {}),
        "supplier_concentration": metrics.get("supplier_concentration", {}),
        "export_destination_concentration": metrics.get("export_destination_concentration", {}),
        "imports_by_country": imports_by_country,
        "exports_by_country": exports_by_country,
        "import_hs_breakdown": _hs_breakdown(imports),
        "export_hs_breakdown": _hs_breakdown(exports),
        "unit_values": _unit_value_summary(usd_doc, quantity_doc),
        "status": usd_doc.get("status", "ok"),
    }


def _annual_summary(months: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for month in months:
        grouped[str(month["period"])[:4]].append(month)

    output = []
    for year in sorted(grouped):
        year_months = grouped[year]
        imports = round(sum(float(item.get("imports") or 0) for item in year_months), 6)
        exports = round(sum(float(item.get("exports") or 0) for item in year_months), 6)
        import_partners: dict[str, float] = defaultdict(float)
        export_partners: dict[str, float] = defaultdict(float)
        for item in year_months:
            for partner in item.get("imports_by_country", []):
                import_partners[partner["partner_country"]] += float(partner.get("value") or 0)
            for partner in item.get("exports_by_country", []):
                export_partners[partner["partner_country"]] += float(partner.get("value") or 0)

        import_rows = [
            {"partner_country": country, "value": round(value, 6)}
            for country, value in sorted(import_partners.items(), key=lambda item: item[1], reverse=True)
        ]
        export_rows = [
            {"partner_country": country, "value": round(value, 6)}
            for country, value in sorted(export_partners.items(), key=lambda item: item[1], reverse=True)
        ]
        import_concentration = concentration_metrics(import_rows)
        export_concentration = concentration_metrics(export_rows)
        output.append(
            {
                "year": year,
                "months_observed": len(year_months),
                "coverage_status": "complete" if len(year_months) == 12 else "partial",
                "imports": imports,
                "exports": exports,
                "balance": round(exports - imports, 6),
                "average_monthly_imports": round(imports / len(year_months), 6) if year_months else None,
                "average_monthly_exports": round(exports / len(year_months), 6) if year_months else None,
                "supplier_concentration": import_concentration,
                "export_destination_concentration": export_concentration,
                "top_import_partners": import_concentration.get("top_partners", []),
                "top_export_partners": export_concentration.get("top_partners", []),
            }
        )
    return output


def _history_gaps(commodity: dict[str, Any], first_period: str, last_period: str) -> list[dict[str, str]]:
    return [
        {
            "period": period,
            "reason": "classification_transition",
            "note": "Historical mapping intentionally omitted for this classification transition month; do not interpret the missing observation as zero trade.",
        }
        for period in commodity.get("classification_transition_periods", [])
        if first_period <= period <= last_period
    ]


def build_commodity_intelligence(
    observations_root: Path,
    commodity: dict[str, Any],
    *,
    observation_index: ObservationIndex | None = None,
) -> dict[str, Any] | None:
    commodity_id = str(commodity.get("id") or "")
    if not commodity_id:
        return None

    index = observation_index if observation_index is not None else _build_observation_index(observations_root)
    months = []
    for period, period_entries in index.items():
        paths = period_entries.get(commodity_id)
        if not paths or "usd" not in paths:
            continue
        usd_doc = _load(paths["usd"])
        if usd_doc is None or usd_doc.get("value_type", "usd") != "usd":
            continue
        quantity_path = paths.get("quantity")
        quantity_doc = _load(quantity_path) if quantity_path is not None else None
        months.append(_month_entry(period, usd_doc, quantity_doc))

    if not months:
        return None

    first_period = months[0]["period"]
    last_period = months[-1]["period"]
    latest = months[-1]
    return {
        "schema_version": 1,
        "commodity": {
            "id": commodity_id,
            "name": commodity.get("name"),
            "category": commodity.get("category"),
            "hs_codes": commodity.get("hs_codes", []),
            "mapping_status": commodity.get("mapping_status"),
        },
        "coverage": {
            "first_period": first_period,
            "last_period": last_period,
            "months_observed": len(months),
            "history_gaps": _history_gaps(commodity, first_period, last_period),
        },
        "latest": {
            "period": latest["period"],
            "imports": latest.get("imports"),
            "exports": latest.get("exports"),
            "balance": latest.get("balance"),
            "dependency": latest.get("dependency", {}),
            "supplier_concentration": latest.get("supplier_concentration", {}),
            "export_destination_concentration": latest.get("export_destination_concentration", {}),
        },
        "monthly": months,
        "annual": _annual_summary(months),
    }


def build_all_commodity_intelligence(
    observations_root: Path,
    master_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    master = _load(master_path)
    if master is None:
        raise ValueError(f"Unable to load commodity master: {master_path}")

    observation_index = _build_observation_index(observations_root)
    output_root.mkdir(parents=True, exist_ok=True)
    expected_files: set[Path] = set()
    built = []
    for commodity in master.get("commodities", []):
        doc = build_commodity_intelligence(
            observations_root,
            commodity,
            observation_index=observation_index,
        )
        if doc is None:
            continue
        path = output_root / f"{commodity['id']}.json"
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        expected_files.add(path)
        built.append(commodity["id"])

    for stale in output_root.glob("*.json"):
        if stale not in expected_files:
            stale.unlink()

    return {
        "schema_version": 1,
        "commodity_count": len(built),
        "commodities": sorted(built),
    }
