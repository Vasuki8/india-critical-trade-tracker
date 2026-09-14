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
