from __future__ import annotations

import json
from pathlib import Path

ALLOWED_PRIORITIES = {"critical", "high", "watch"}


def load_json(path: str | Path):
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


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
                if not isinstance(code, str) or not code.isdigit() or len(code) not in {2, 4, 5, 6, 8}:
                    errors.append(f"{prefix}: invalid HS code {code!r}")
        if not item.get("mapping_status"):
            errors.append(f"{prefix}: missing mapping_status")
    return errors
