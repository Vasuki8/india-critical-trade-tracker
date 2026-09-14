from __future__ import annotations

from typing import Any

USD_MILLION_TO_USD = 1_000_000.0
DEFAULT_QUANTITY_SCALE_TO_SOURCE_UNIT = 1.0
VERIFIED_QUANTITY_SELECTOR_CODE = "2"


def _report_index(doc: dict[str, Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    if not doc:
        return {}
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for report in doc.get("reports", []):
        trade_type = str(report.get("trade_type") or "")
        hs_code = str(report.get("hs_code") or "")
        if trade_type and hs_code:
            output[(trade_type, hs_code)] = report
    return output


def _total_value(report: dict[str, Any] | None) -> float | None:
    if not report:
        return None
    value = report.get("totals", {}).get("value")
    if value is None:
        return None
    return float(value)


def _quantity_unit(report: dict[str, Any] | None) -> str | None:
    if not report:
        return None
    unit = report.get("source_quantity_unit")
    if unit is None:
        return None
    unit = str(unit).strip()
    return unit or None


def _quantity_scale(report: dict[str, Any] | None) -> float:
    if not report:
        return DEFAULT_QUANTITY_SCALE_TO_SOURCE_UNIT
    scale = report.get("quantity_scale_to_source_unit")
    if scale is None:
        return DEFAULT_QUANTITY_SCALE_TO_SOURCE_UNIT
    return float(scale)


def _quantity_selector_verified(report: dict[str, Any] | None) -> bool:
    if not report:
        return False
    return str(report.get("value_selector_code") or "") == VERIFIED_QUANTITY_SELECTOR_CODE


def _rollup_requested(quantity_observation: dict[str, Any] | None) -> bool:
    if not quantity_observation:
        return False
    return quantity_observation.get("commodity", {}).get("quantity_rollup_to_value_mapping") is True


def _parent_value_child_quantity_rollup(
    usd_observation: dict[str, Any],
    quantity_observation: dict[str, Any] | None,
    trade_type: str,
) -> dict[str, Any] | None:
    """Blend one parent value report with an exhaustive HS8 quantity set.

    This path is intentionally opt-in through observation provenance. It is used
    when the monetary series is stored at a validated parent heading while the
    quantity endpoint is queried at exact HS8 children that exhaust that heading.
    Component-level unit values remain unavailable because value is not observed
    separately for each child; only the aggregate parent-heading unit value is
    derived.

    TradeStat can leave the source unit blank when a child line has exactly zero
    quantity. Such a zero line contributes no physical amount, so it may omit its
    unit without blocking the aggregate. Every positive child quantity must still
    report a verified common physical unit.
    """
    if not _rollup_requested(quantity_observation):
        return None

    usd_reports = [
        report for report in usd_observation.get("reports", []) if report.get("trade_type") == trade_type
    ]
    quantity_reports = [
        report
        for report in (quantity_observation or {}).get("reports", [])
        if report.get("trade_type") == trade_type
    ]
    if len(usd_reports) != 1 or not quantity_reports:
        return None

    usd_report = usd_reports[0]
    parent_code = str(usd_report.get("hs_code") or "")
    child_codes = [str(report.get("hs_code") or "") for report in quantity_reports]
    if not parent_code or any(not code or not code.startswith(parent_code) or code == parent_code for code in child_codes):
        return None

    canonical_children = {
        str(code)
        for code in (quantity_observation or {}).get("commodity", {}).get("canonical_hs_codes", [])
        if str(code)
    }
    if canonical_children and set(child_codes) != canonical_children:
        return None

    usd_million = _total_value(usd_report)
    if usd_million is None:
        return None

    units: set[str] = set()
    total_raw_quantity = 0.0
    total_quantity = 0.0
    for report in quantity_reports:
        if not _quantity_selector_verified(report):
            return {
                "status": "unverified_quantity_selector",
                "usd_million": round(usd_million, 6),
                "raw_quantity_source_units": None,
                "quantity": None,
                "quantity_unit": None,
                "unit_value_usd_per_source_unit": None,
                "rollup_method": "parent_value_child_hs8_quantity",
            }
        raw_quantity = _total_value(report)
        if raw_quantity is None or raw_quantity < 0:
            return {
                "status": "quantity_not_available",
                "usd_million": round(usd_million, 6),
                "raw_quantity_source_units": None,
                "quantity": None,
                "quantity_unit": None,
                "unit_value_usd_per_source_unit": None,
                "rollup_method": "parent_value_child_hs8_quantity",
            }
        scale = _quantity_scale(report)
        if scale <= 0:
            return {
                "status": "invalid_quantity_scale",
                "usd_million": round(usd_million, 6),
                "raw_quantity_source_units": None,
                "quantity": None,
                "quantity_unit": None,
                "unit_value_usd_per_source_unit": None,
                "rollup_method": "parent_value_child_hs8_quantity",
            }

        total_raw_quantity += raw_quantity
        total_quantity += raw_quantity * scale
        if raw_quantity == 0:
            continue

        unit = _quantity_unit(report)
        if unit is None:
            return {
                "status": "missing_quantity_unit",
                "usd_million": round(usd_million, 6),
                "raw_quantity_source_units": round(total_raw_quantity, 6),
                "quantity": None,
                "quantity_unit": None,
                "unit_value_usd_per_source_unit": None,
                "rollup_method": "parent_value_child_hs8_quantity",
            }
        units.add(unit.upper())

    if total_quantity <= 0:
        return {
            "status": "quantity_not_available",
            "usd_million": round(usd_million, 6),
            "raw_quantity_source_units": round(total_raw_quantity, 6),
            "quantity": round(total_quantity, 6),
            "quantity_unit": next(iter(units)) if len(units) == 1 else None,
            "unit_value_usd_per_source_unit": None,
            "rollup_method": "parent_value_child_hs8_quantity",
        }
    if len(units) != 1:
        return {
            "status": "mixed_quantity_units",
            "usd_million": round(usd_million, 6),
            "raw_quantity_source_units": round(total_raw_quantity, 6),
            "quantity": None,
            "quantity_unit": None,
            "unit_value_usd_per_source_unit": None,
            "component_units": sorted(units),
            "rollup_method": "parent_value_child_hs8_quantity",
        }

    unit = next(iter(units))
    return {
        "status": "ok",
        "usd_million": round(usd_million, 6),
        "raw_quantity_source_units": round(total_raw_quantity, 6),
        "quantity": round(total_quantity, 6),
        "quantity_unit": unit,
        "unit_value_usd_per_source_unit": round(
            usd_million * USD_MILLION_TO_USD / total_quantity, 6
        ),
        "rollup_method": "parent_value_child_hs8_quantity",
        "value_hs_code": parent_code,
        "quantity_hs_codes": sorted(child_codes),
    }


def derive_unit_values(
    usd_observation: dict[str, Any],
    quantity_observation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Derive implied USD per displayed physical source unit from MEIDB reports.

    TradeStat monetary observations are USD million. The MEIDB quantity endpoint
    returns quantity directly in the displayed HS8 source unit (for example KGS
    or NOS), so the physical-unit scale is 1. Unit values are only derived from
    reports carrying the verified live quantity selector code (2). An explicit
    parent-heading rollup may derive only the aggregate unit value when the
    quantity observation records an exhaustive child-HS8 mapping.
    """
    usd_reports = _report_index(usd_observation)
    quantity_reports = _report_index(quantity_observation)
    keys = sorted(set(usd_reports) | set(quantity_reports), key=lambda key: (key[0], key[1]))

    components: list[dict[str, Any]] = []
    for trade_type, hs_code in keys:
        usd_report = usd_reports.get((trade_type, hs_code))
        quantity_report = quantity_reports.get((trade_type, hs_code))
        usd_million = _total_value(usd_report)
        raw_quantity = _total_value(quantity_report)
        quantity_unit = _quantity_unit(quantity_report)
        scale = _quantity_scale(quantity_report)
        quantity_source_units = raw_quantity * scale if raw_quantity is not None else None

        if usd_report is None:
            status = "missing_usd_report"
        elif quantity_report is None:
            status = "missing_quantity_report"
        elif not _quantity_selector_verified(quantity_report):
            status = "unverified_quantity_selector"
        elif raw_quantity is None or raw_quantity <= 0:
            status = "quantity_not_available"
        elif quantity_unit is None:
            status = "missing_quantity_unit"
        elif scale <= 0:
            status = "invalid_quantity_scale"
        elif usd_million is None:
            status = "usd_not_available"
        else:
            status = "ok"

        unit_value = None
        if status == "ok" and quantity_source_units:
            unit_value = round(usd_million * USD_MILLION_TO_USD / quantity_source_units, 6)

        components.append(
            {
                "trade_type": trade_type,
                "hs_code": hs_code,
                "status": status,
                "usd_million": usd_million,
                "raw_quantity_source_units": raw_quantity,
                "quantity_scale_to_source_unit": scale,
                "quantity": round(quantity_source_units, 6) if quantity_source_units is not None else None,
                "quantity_unit": quantity_unit,
                "unit_value_usd_per_source_unit": unit_value,
            }
        )

    aggregate: dict[str, Any] = {}
    for trade_type in ("import", "export"):
        valid = [
            item
            for item in components
            if item["trade_type"] == trade_type and item["status"] == "ok"
        ]
        if not valid:
            rollup = _parent_value_child_quantity_rollup(
                usd_observation,
                quantity_observation,
                trade_type,
            )
            if rollup is not None:
                aggregate[trade_type] = rollup
                continue
            aggregate[trade_type] = {
                "status": "not_available",
                "usd_million": None,
                "raw_quantity_source_units": None,
                "quantity": None,
                "quantity_unit": None,
                "unit_value_usd_per_source_unit": None,
            }
            continue

        units = {str(item["quantity_unit"]).upper() for item in valid}
        if len(units) != 1:
            aggregate[trade_type] = {
                "status": "mixed_quantity_units",
                "usd_million": round(sum(float(item["usd_million"]) for item in valid), 6),
                "raw_quantity_source_units": None,
                "quantity": None,
                "quantity_unit": None,
                "unit_value_usd_per_source_unit": None,
                "component_units": sorted(units),
            }
            continue

        total_usd_million = sum(float(item["usd_million"]) for item in valid)
        total_raw_quantity = sum(float(item["raw_quantity_source_units"]) for item in valid)
        total_quantity = sum(float(item["quantity"]) for item in valid)
        unit = valid[0]["quantity_unit"]
        aggregate[trade_type] = {
            "status": "ok",
            "usd_million": round(total_usd_million, 6),
            "raw_quantity_source_units": round(total_raw_quantity, 6),
            "quantity": round(total_quantity, 6),
            "quantity_unit": unit,
            "unit_value_usd_per_source_unit": round(
                total_usd_million * USD_MILLION_TO_USD / total_quantity, 6
            ) if total_quantity > 0 else None,
        }

    has_value = any(item["status"] == "ok" for item in components) or any(
        item.get("status") == "ok" for item in aggregate.values()
    )
    return {
        "status": "ok" if has_value else "not_available",
        "method": "USD million × 1,000,000 divided by TradeStat MEIDB quantity in the displayed physical source unit",
        "quantity_scale_note": "MEIDB quantity values are used directly in the displayed HS8 source unit; no thousand-unit multiplier is applied.",
        "aggregate": aggregate,
        "by_hs_code": components,
    }
