from __future__ import annotations

import json
import re
from pathlib import Path

ALLOWED_PRIORITIES = {"critical", "high", "watch"}
VALID_HS_LENGTHS = {2, 4, 6, 8}
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def load_json(path: str | Path):
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def _valid_code(code: object) -> bool:
    return isinstance(code, str) and code.isdigit() and len(code) in VALID_HS_LENGTHS


def _valid_period(value: object) -> bool:
    return isinstance(value, str) and bool(PERIOD_RE.fullmatch(value))


def validate_commodity_master(doc: dict) -> list[str]:
    errors: list[str] = []
    commodities = doc.get("commodities")
    if not isinstance(commodities, list) or not commodities:
        return ["commodities must be a non-empty list"]

    seen: set[str] = set()
    for i, item in enumerate(commodities):
        prefix = f"commodities[{i}]"
        commodity_id = item.get("id")
        if not commodity_id:
            errors.append(f"{prefix}: missing id")
        elif commodity_id in seen:
            errors.append(f"{prefix}: duplicate id {commodity_id}")
        else:
            seen.add(commodity_id)

        if not item.get("name"):
            errors.append(f"{prefix}: missing name")
        if item.get("priority") not in ALLOWED_PRIORITIES:
            errors.append(f"{prefix}: invalid priority")

        codes = item.get("hs_codes")
        if not isinstance(codes, list) or not codes:
            errors.append(f"{prefix}: hs_codes must be non-empty")
        else:
            for code in codes:
                if not _valid_code(code):
                    errors.append(f"{prefix}: invalid HS code {code!r}")

        if not item.get("mapping_status"):
            errors.append(f"{prefix}: missing mapping_status")

        transitions = item.get("classification_transition_periods", [])
        if not isinstance(transitions, list):
            errors.append(f"{prefix}: classification_transition_periods must be a list")
        else:
            for period in transitions:
                if not _valid_period(period):
                    errors.append(f"{prefix}: invalid classification transition period {period!r}")

        eras = item.get("classification_eras", [])
        if not isinstance(eras, list):
            errors.append(f"{prefix}: classification_eras must be a list")
            continue

        previous_through: str | None = None
        for j, era in enumerate(eras):
            era_prefix = f"{prefix}.classification_eras[{j}]"
            start = era.get("from")
            through = era.get("through")
            era_codes = era.get("hs_codes")

            if not _valid_period(start):
                errors.append(f"{era_prefix}: invalid from period {start!r}")
            if through is not None and not _valid_period(through):
                errors.append(f"{era_prefix}: invalid through period {through!r}")
            if _valid_period(start) and _valid_period(through) and start > through:
                errors.append(f"{era_prefix}: from period is after through period")
            if previous_through is not None and _valid_period(start) and start <= previous_through:
                errors.append(f"{era_prefix}: classification eras overlap or are unsorted")

            if not isinstance(era_codes, list) or not era_codes:
                errors.append(f"{era_prefix}: hs_codes must be non-empty")
            else:
                for code in era_codes:
                    if not _valid_code(code):
                        errors.append(f"{era_prefix}: invalid HS code {code!r}")

            if isinstance(through, str) and _valid_period(through):
                previous_through = through
            elif through is None:
                previous_through = "9999-12"

    return errors


def _validate_period_sequence(periods: list[object], *, prefix: str) -> list[str]:
    errors: list[str] = []
    invalid = [period for period in periods if not _valid_period(period)]
    if invalid:
        errors.append(f"{prefix}: invalid period value(s): {invalid!r}")
        return errors

    normalized = [str(period) for period in periods]
    if len(normalized) != len(set(normalized)):
        errors.append(f"{prefix}: duplicate periods are not allowed")
    if normalized != sorted(normalized):
        errors.append(f"{prefix}: periods must be sorted oldest to newest")
    return errors


def validate_dashboard(doc: dict) -> list[str]:
    """Validate generated dashboard chronology and cross-section/history integrity."""
    errors: list[str] = []
    as_of = doc.get("as_of")
    if not _valid_period(as_of):
        errors.append(f"dashboard: invalid as_of period {as_of!r}")

    monthly = doc.get("monthly")
    if not isinstance(monthly, list):
        errors.append("dashboard.monthly must be a list")
        monthly = []
    monthly_periods = [row.get("period") if isinstance(row, dict) else None for row in monthly]
    errors.extend(_validate_period_sequence(monthly_periods, prefix="dashboard.monthly"))
    valid_monthly_periods = [str(period) for period in monthly_periods if _valid_period(period)]
    if valid_monthly_periods and _valid_period(as_of) and valid_monthly_periods[-1] != as_of:
        errors.append(
            f"dashboard: as_of {as_of} must equal latest monthly USD period {valid_monthly_periods[-1]}"
        )

    commodities = doc.get("commodities")
    if not isinstance(commodities, list):
        errors.append("dashboard.commodities must be a list")
        commodities = []
    commodity_ids: list[str] = []
    for i, item in enumerate(commodities):
        if not isinstance(item, dict) or not item.get("id"):
            errors.append(f"dashboard.commodities[{i}]: missing id")
            continue
        commodity_ids.append(str(item["id"]))
    if len(commodity_ids) != len(set(commodity_ids)):
        errors.append("dashboard.commodities: duplicate commodity ids are not allowed")

    history = doc.get("commodity_history")
    if not isinstance(history, dict):
        errors.append("dashboard.commodity_history must be an object")
        history = {}

    for commodity_id, rows in history.items():
        prefix = f"dashboard.commodity_history[{commodity_id}]"
        if not isinstance(rows, list):
            errors.append(f"{prefix}: history must be a list")
            continue
        periods = [row.get("period") if isinstance(row, dict) else None for row in rows]
        errors.extend(_validate_period_sequence(periods, prefix=prefix))
        for j, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"{prefix}[{j}]: row must be an object")
                continue
            period = row.get("period")
            if _valid_period(period) and _valid_period(as_of) and period > as_of:
                errors.append(f"{prefix}[{j}]: period {period} is after dashboard as_of {as_of}")

            unit_values = row.get("unit_values")
            if not isinstance(unit_values, dict):
                continue
            for trade_type in ("import", "export"):
                metric = unit_values.get(trade_type)
                if not isinstance(metric, dict) or metric.get("status") != "ok":
                    continue
                quantity = metric.get("quantity")
                unit_value = metric.get("unit_value_usd_per_source_unit")
                if not isinstance(quantity, (int, float)) or quantity <= 0:
                    errors.append(f"{prefix}[{j}].unit_values.{trade_type}: ok status requires positive quantity")
                if not isinstance(unit_value, (int, float)) or unit_value < 0:
                    errors.append(f"{prefix}[{j}].unit_values.{trade_type}: ok status requires non-negative unit value")

    unknown_history_ids = sorted(set(history) - set(commodity_ids))
    if unknown_history_ids:
        errors.append(
            "dashboard.commodity_history contains ids missing from dashboard.commodities: "
            + ", ".join(unknown_history_ids)
        )

    return errors
