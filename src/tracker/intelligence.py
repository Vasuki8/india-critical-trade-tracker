from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .aggregation import aggregate_commodity, concentration_metrics
from .derived import derive_unit_values


def _load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _observation_path(period_dir: Path, commodity_id: str, value_type: str) -> Path | None:
    explicit = period_dir / f"{commodity_id}.{value_type}.json"
    if explicit.exists():
        return explicit
    if value_type == "usd":
        legacy = period_dir / f"{commodity_id}.json"
        if legacy.exists():
            doc = _load(legacy)
            if doc is not None and doc.get("value_type", "usd") == "usd":
                return legacy
    return None


def _reports(doc: dict[str, Any], trade_type: str) -> list[dict[str, Any]]:
    return [report for report in doc.get("reports", []) if report.get("trade_type") == trade_type]


def _partner_rollup(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values: dict[str, float] = defaultdict(float)
    for report in reports:
        for row in report.get("rows", []):
            country = str(row.get("partner_country") or "").strip()
            value = row.get("value")
            if not country or value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if numeric > 0:
                values[country] += numeric

    total = sum(values.values())
    return [
        {
            "partner_country": country,
            "value": round(value, 6),
            "share_pct": round(value / total * 100, 2) if total > 0 else None,
        }
        for country, value in sorted(values.items(), key=lambda item: item[1], reverse=True)
    ]


def _hs_breakdown(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for report in reports:
        totals = report.get("totals", {})
        output.append(
            {
                "hs_code": report.get("hs_code"),
                "description": report.get("description"),
                "value": totals.get("value"),
                "source_unit": report.get("quantity_unit") or report.get("source_unit"),
            }
        )
    return output


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
    metrics = aggregate_commodity(usd_doc.get("reports", []))
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
        "imports_by_country": _partner_rollup(imports),
        "exports_by_country": _partner_rollup(exports),
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
        year_months = sorted(grouped[year], key=lambda item: item["period"])
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
    gaps = []
    for period in commodity.get("classification_transition_periods", []):
        if first_period <= period <= last_period:
            gaps.append(
                {
                    "period": period,
                    "reason": "classification_transition",
                    "note": "Historical mapping intentionally omitted for this classification transition month; do not interpret the missing observation as zero trade.",
                }
            )
    return gaps


def build_commodity_intelligence(
    observations_root: Path,
    commodity: dict[str, Any],
) -> dict[str, Any] | None:
    commodity_id = str(commodity.get("id") or "")
    if not commodity_id:
        return None

    months = []
    for period_dir in sorted(path for path in observations_root.glob("????-??") if path.is_dir()):
        usd_path = _observation_path(period_dir, commodity_id, "usd")
        if usd_path is None:
            continue
        usd_doc = _load(usd_path)
        if usd_doc is None:
            continue
        quantity_path = _observation_path(period_dir, commodity_id, "quantity")
        quantity_doc = _load(quantity_path) if quantity_path is not None else None
        months.append(_month_entry(period_dir.name, usd_doc, quantity_doc))

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

    output_root.mkdir(parents=True, exist_ok=True)
    expected_files: set[Path] = set()
    built = []
    for commodity in master.get("commodities", []):
        doc = build_commodity_intelligence(observations_root, commodity)
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
