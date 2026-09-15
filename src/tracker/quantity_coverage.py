from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _period_in_range(period: str, start: str | None, through: str | None) -> bool:
    if start and period < start:
        return False
    if through and period > through:
        return False
    return True


def _codes_for_period(mapping: dict[str, Any], period: str) -> tuple[list[str], bool]:
    """Return active codes and whether an empty mapping is an intentional transition."""
    transitions = set(mapping.get("classification_transition_periods", []))
    if period in transitions:
        return [], True

    eras = mapping.get("classification_eras") or []
    if eras:
        for era in eras:
            if _period_in_range(period, era.get("from"), era.get("through")):
                return list(era.get("hs_codes", [])), False
        return [], False

    return list(mapping.get("hs_codes", [])), False


def _quantity_mapping(item: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    quantity = item.get("quantity_mapping")
    if not isinstance(quantity, dict) or quantity.get("enabled") is not True:
        return None, None
    mode = quantity.get("mode")
    if mode == "same_as_value":
        return quantity, item
    if mode == "separate":
        return quantity, quantity
    return quantity, None


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _report_pairs(doc: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (str(report.get("trade_type") or ""), str(report.get("hs_code") or ""))
        for report in doc.get("reports", [])
        if isinstance(report, dict)
    }


def _preview(periods: list[str], *, limit: int = 6) -> str:
    shown = periods[:limit]
    suffix = "" if len(periods) <= limit else f", ... (+{len(periods) - limit} more)"
    return ", ".join(shown) + suffix


def validate_quantity_history(
    master: dict[str, Any],
    dashboard: dict[str, Any],
    observations_root: Path,
) -> list[str]:
    """Validate quantity archives explicitly declared complete in the commodity master.

    Quantity mappings can be enabled before their older observations are backfilled.
    A mapping becomes a repository-level completeness contract only after it declares
    ``history_complete_from``. From that month through the dashboard ``as_of`` month,
    every mapped non-transition period must contain a current, successful quantity
    observation with both trade directions, selector 2, direct-unit scale 1, and the
    active period-specific HS8 code set.
    """
    errors: list[str] = []
    monthly_periods = [
        str(row.get("period"))
        for row in dashboard.get("monthly", [])
        if isinstance(row, dict) and isinstance(row.get("period"), str)
    ]
    as_of = dashboard.get("as_of")
    if isinstance(as_of, str):
        monthly_periods = [period for period in monthly_periods if period <= as_of]

    for item in master.get("commodities", []):
        if not isinstance(item, dict):
            continue
        quantity, mapping = _quantity_mapping(item)
        if quantity is None or mapping is None:
            continue
        if "history_complete_from" not in quantity:
            continue

        start = quantity.get("history_complete_from")
        commodity_id = str(item.get("id") or "")
        prefix = f"quantity history[{commodity_id}]"
        if not isinstance(start, str) or not PERIOD_RE.fullmatch(start):
            errors.append(f"{prefix}: history_complete_from must be YYYY-MM")
            continue
        if start < "2018-01":
            errors.append(f"{prefix}: history_complete_from cannot predate 2018-01")
            continue

        required_periods = [period for period in monthly_periods if period >= start]
        missing: list[str] = []
        invalid: list[str] = []
        mapping_gaps: list[str] = []

        for period in required_periods:
            active_codes, intentional_transition = _codes_for_period(mapping, period)
            if intentional_transition:
                continue
            if not active_codes:
                mapping_gaps.append(period)
                continue

            path = observations_root / period / f"{commodity_id}.quantity.json"
            doc = _load_json(path)
            if doc is None:
                missing.append(period)
                continue

            reasons: list[str] = []
            if doc.get("period") != period:
                reasons.append("period")
            if doc.get("value_type") != "quantity":
                reasons.append("value_type")
            if doc.get("status") != "ok":
                reasons.append("status")
            if doc.get("quantity_scale_to_source_unit") != 1:
                reasons.append("scale")

            stored_codes = list(doc.get("commodity", {}).get("hs_codes") or [])
            if stored_codes != active_codes:
                reasons.append("mapping")

            expected_pairs = {
                (trade_type, code)
                for code in active_codes
                for trade_type in ("import", "export")
            }
            if not expected_pairs <= _report_pairs(doc):
                reasons.append("report_coverage")

            relevant_reports = [
                report
                for report in doc.get("reports", [])
                if isinstance(report, dict)
                and (str(report.get("trade_type") or ""), str(report.get("hs_code") or ""))
                in expected_pairs
            ]
            if any(report.get("value_type") != "quantity" for report in relevant_reports):
                reasons.append("report_value_type")
            if any(report.get("value_selector_code") != "2" for report in relevant_reports):
                reasons.append("selector")
            if any(report.get("quantity_scale_to_source_unit") != 1 for report in relevant_reports):
                reasons.append("report_scale")

            if reasons:
                invalid.append(f"{period} ({'/'.join(sorted(set(reasons)))})")

        if mapping_gaps:
            errors.append(
                f"{prefix}: declared complete from {start} but has no active mapping for "
                f"{len(mapping_gaps)} required period(s): {_preview(mapping_gaps)}"
            )
        if missing:
            errors.append(
                f"{prefix}: missing {len(missing)} declared-complete observation(s): {_preview(missing)}"
            )
        if invalid:
            errors.append(
                f"{prefix}: {len(invalid)} declared-complete observation(s) are stale or invalid: "
                f"{_preview(invalid)}"
            )

    return errors
