from __future__ import annotations

from typing import Any

USD_MILLION_TO_USD = 1_000_000.0
DEFAULT_QUANTITY_SCALE_TO_SOURCE_UNIT = 1.0
VERIFIED_QUANTITY_SELECTOR_CODE = "2"

# TradeStat explicitly notes that an HS8 commodity's displayed unit can change
# across history (for example TON before a revision and KGS afterward). Keep raw
# source units for provenance, but normalize only physically equivalent mass
# units before aggregating or deriving unit values. Unknown units remain in their
# own uppercase unit and are never converted implicitly.
MASS_UNIT_NORMALIZATION: dict[str, tuple[str, float]] = {
    "KGS": ("KGS", 1.0),
    "KG": ("KGS", 1.0),
    "KILOGRAM": ("KGS", 1.0),
    "KILOGRAMS": ("KGS", 1.0),
    "TON": ("KGS", 1_000.0),
    "TONS": ("KGS", 1_000.0),
    "TONNE": ("KGS", 1_000.0),
    "TONNES": ("KGS", 1_000.0),
    "MT": ("KGS", 1_000.0),
    "MTS": ("KGS", 1_000.0),
    "GMS": ("KGS", 0.001),
    "GM": ("KGS", 0.001),
    "GRAM": ("KGS", 0.001),
    "GRAMS": ("KGS", 0.001),
}


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


def _canonical_quantity_unit(unit: str | None) -> tuple[str | None, float | None]:
    """Return a conservative canonical unit and source-to-canonical factor.

    Only known mass-unit equivalents are converted. Any other non-empty unit is
    kept as its own uppercase canonical unit with factor 1, preserving the prior
    behavior while preventing false equivalence across unrelated unit families.
    """
    if unit is None:
        return None, None
    cleaned = " ".join(str(unit).strip().upper().split())
    if not cleaned:
        return None, None
    return MASS_UNIT_NORMALIZATION.get(cleaned, (cleaned, 1.0))


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
    report a verified unit that resolves to one common canonical unit.
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
    source_units: set[str] = set()
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
        if raw_quantity == 0:
            continue

        source_unit = _quantity_unit(report)
        unit, normalization_factor = _canonical_quantity_unit(source_unit)
        if unit is None or normalization_factor is None:
            return {
                "status": "missing_quantity_unit",
                "usd_million": round(usd_million, 6),
                "raw_quantity_source_units": round(total_raw_quantity, 6),
                "quantity": None,
                "quantity_unit": None,
                "unit_value_usd_per_source_unit": None,
                "rollup_method": "parent_value_child_hs8_quantity",
            }
        source_units.add(str(source_unit).upper())
        units.add(unit)
        total_quantity += raw_quantity * scale * normalization_factor

    raw_output = round(total_raw_quantity, 6) if len(source_units) <= 1 else None
    if total_quantity <= 0:
        return {
            "status": "quantity_not_available",
            "usd_million": round(usd_million, 6),
            "raw_quantity_source_units": raw_output,
            "source_quantity_units": sorted(source_units),
            "quantity": round(total_quantity, 6),
            "quantity_unit": next(iter(units)) if len(units) == 1 else None,
            "unit_value_usd_per_source_unit": None,
            "rollup_method": "parent_value_child_hs8_quantity",
        }
    if len(units) != 1:
        return {
            "status": "mixed_quantity_units",
            "usd_million": round(usd_million, 6),
            "raw_quantity_source_units": raw_output,
            "source_quantity_units": sorted(source_units),
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
        "raw_quantity_source_units": raw_output,
        "source_quantity_units": sorted(source_units),
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
    """Derive implied USD per canonical physical unit from MEIDB reports.

    TradeStat monetary observations are USD million. The MEIDB quantity endpoint
    returns quantity directly in the displayed HS8 source unit, so the physical-
    unit scale is 1. Verified equivalent mass units are normalized to KGS before
    aggregation so historical TradeStat unit changes do not create artificial
    level shifts. Unrelated unit families are never combined. Unit values are
    only derived from reports carrying the verified live quantity selector code
    (2). An explicit parent-heading rollup may derive only the aggregate unit
    value when the quantity observation records an exhaustive child-HS8 mapping.
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
        source_quantity_unit = _quantity_unit(quantity_report)
        quantity_unit, normalization_factor = _canonical_quantity_unit(source_quantity_unit)
        scale = _quantity_scale(quantity_report)
        quantity_source_units = raw_quantity * scale if raw_quantity is not None else None
        quantity = (
            quantity_source_units * normalization_factor
            if quantity_source_units is not None and normalization_factor is not None
            else None
        )

        if usd_report is None:
            status = "missing_usd_report"
        elif quantity_report is None:
            status = "missing_quantity_report"
        elif not _quantity_selector_verified(quantity_report):
            status = "unverified_quantity_selector"
        elif raw_quantity is None or raw_quantity <= 0:
            status = "quantity_not_available"
        elif quantity_unit is None or normalization_factor is None:
            status = "missing_quantity_unit"
        elif scale <= 0:
            status = "invalid_quantity_scale"
        elif usd_million is None:
            status = "usd_not_available"
        else:
            status = "ok"

        unit_value = None
        if status == "ok" and quantity:
            unit_value = round(usd_million * USD_MILLION_TO_USD / quantity, 6)

        components.append(
            {
                "trade_type": trade_type,
                "hs_code": hs_code,
                "status": status,
                "usd_million": usd_million,
                "raw_quantity_source_units": raw_quantity,
                "quantity_scale_to_source_unit": scale,
                "source_quantity_unit": source_quantity_unit,
                "quantity_normalization_factor": normalization_factor,
                "quantity": round(quantity, 6) if quantity is not None else None,
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
        source_units = {
            str(item["source_quantity_unit"]).upper()
            for item in valid
            if item.get("source_quantity_unit")
        }
        if len(units) != 1:
            aggregate[trade_type] = {
                "status": "mixed_quantity_units",
                "usd_million": round(sum(float(item["usd_million"]) for item in valid), 6),
                "raw_quantity_source_units": None,
                "source_quantity_units": sorted(source_units),
                "quantity": None,
                "quantity_unit": None,
                "unit_value_usd_per_source_unit": None,
                "component_units": sorted(units),
            }
            continue

        total_usd_million = sum(float(item["usd_million"]) for item in valid)
        total_raw_quantity = (
            sum(float(item["raw_quantity_source_units"]) for item in valid)
            if len(source_units) <= 1
            else None
        )
        total_quantity = sum(float(item["quantity"]) for item in valid)
        unit = valid[0]["quantity_unit"]
        aggregate[trade_type] = {
            "status": "ok",
            "usd_million": round(total_usd_million, 6),
            "raw_quantity_source_units": round(total_raw_quantity, 6) if total_raw_quantity is not None else None,
            "source_quantity_units": sorted(source_units),
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
        "method": "USD million × 1,000,000 divided by normalized TradeStat MEIDB quantity; verified mass units are canonicalized to KGS",
        "quantity_scale_note": "MEIDB quantity values are used directly in each displayed HS8 source unit; verified equivalent mass units are normalized before aggregation, with raw source units retained for provenance.",
        "aggregate": aggregate,
        "by_hs_code": components,
    }
