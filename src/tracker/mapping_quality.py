from __future__ import annotations

from collections import Counter


MAPPING_STATUS_CODE_LENGTHS: dict[str, set[int]] = {
    "hs8_validated": {8},
    "heading_validated": {4},
    "heading_set": {4},
    "chapter_broad": {2},
    "chapter_plus_ore": {2, 4},
    "heading_plus_chapter": {2, 4},
}
QUANTITY_MAPPING_MODES = {"same_as_value", "separate"}


def _period_in_era(period: str, era: dict) -> bool:
    start = era.get("from")
    through = era.get("through")
    if not isinstance(start, str):
        return False
    if period < start:
        return False
    return through is None or (isinstance(through, str) and period <= through)


def _validate_quantity_mapping(item: dict, *, prefix: str) -> list[str]:
    errors: list[str] = []
    quantity = item.get("quantity_mapping")
    if quantity is None:
        return errors
    if not isinstance(quantity, dict):
        return [f"{prefix}.quantity_mapping: must be an object"]

    enabled = quantity.get("enabled")
    if not isinstance(enabled, bool):
        errors.append(f"{prefix}.quantity_mapping: enabled must be boolean")
        return errors
    if not enabled:
        return errors

    mode = quantity.get("mode")
    if mode not in QUANTITY_MAPPING_MODES:
        errors.append(
            f"{prefix}.quantity_mapping: mode must be one of {sorted(QUANTITY_MAPPING_MODES)}"
        )
        return errors

    status = quantity.get("mapping_status")
    if status != "hs8_validated":
        errors.append(
            f"{prefix}.quantity_mapping: enabled quantity mappings must use mapping_status 'hs8_validated'"
        )

    rollup = quantity.get("rollup_to_value_mapping", False)
    if not isinstance(rollup, bool):
        errors.append(f"{prefix}.quantity_mapping: rollup_to_value_mapping must be boolean")
        rollup = False

    if mode == "same_as_value":
        if item.get("mapping_status") != "hs8_validated":
            errors.append(
                f"{prefix}.quantity_mapping: same_as_value requires the monetary mapping to be hs8_validated"
            )
        if "hs_codes" in quantity or "classification_eras" in quantity:
            errors.append(
                f"{prefix}.quantity_mapping: same_as_value must inherit codes/eras instead of redefining them"
            )
        if rollup:
            errors.append(
                f"{prefix}.quantity_mapping: rollup_to_value_mapping is only valid for separate mappings"
            )
        return errors

    codes = quantity.get("hs_codes")
    if not isinstance(codes, list) or not codes:
        errors.append(f"{prefix}.quantity_mapping: separate mode requires non-empty hs_codes")
        return errors
    if len(codes) != len(set(codes)):
        errors.append(f"{prefix}.quantity_mapping: hs_codes must not contain duplicates")
    non_hs8 = [code for code in codes if not isinstance(code, str) or len(code) != 8]
    if non_hs8:
        errors.append(
            f"{prefix}.quantity_mapping: separate quantity hs_codes must all be HS8"
        )

    if rollup:
        value_codes = item.get("hs_codes")
        if not isinstance(value_codes, list) or not value_codes:
            errors.append(
                f"{prefix}.quantity_mapping: rollup requires a non-empty monetary hs_codes mapping"
            )
        else:
            uncovered = [
                code
                for code in codes
                if isinstance(code, str)
                and not any(
                    isinstance(parent, str) and len(parent) < len(code) and code.startswith(parent)
                    for parent in value_codes
                )
            ]
            if uncovered:
                errors.append(
                    f"{prefix}.quantity_mapping: rollup quantity codes must be children of the monetary mapping"
                )

    transitions = quantity.get("classification_transition_periods", [])
    eras = quantity.get("classification_eras", [])
    if transitions and not eras:
        errors.append(f"{prefix}.quantity_mapping: transition periods require classification_eras")
    if isinstance(transitions, list) and len(transitions) != len(set(transitions)):
        errors.append(
            f"{prefix}.quantity_mapping: classification_transition_periods must not contain duplicates"
        )
    if not isinstance(eras, list) or not eras:
        return errors

    open_ended = [era for era in eras if isinstance(era, dict) and era.get("through") is None]
    if len(open_ended) != 1:
        errors.append(
            f"{prefix}.quantity_mapping: classification_eras must contain exactly one open-ended current era"
        )
    elif open_ended[0].get("hs_codes") != codes:
        errors.append(
            f"{prefix}.quantity_mapping: hs_codes must match the open-ended current era"
        )

    for era_index, era in enumerate(eras):
        if not isinstance(era, dict):
            continue
        era_codes = era.get("hs_codes")
        era_prefix = f"{prefix}.quantity_mapping.classification_eras[{era_index}]"
        if not isinstance(era_codes, list) or not era_codes:
            errors.append(f"{era_prefix}: hs_codes must be non-empty")
            continue
        if len(era_codes) != len(set(era_codes)):
            errors.append(f"{era_prefix}: hs_codes must not contain duplicates")
        if any(not isinstance(code, str) or len(code) != 8 for code in era_codes):
            errors.append(f"{era_prefix}: quantity hs_codes must all be HS8")

    if isinstance(transitions, list):
        for period in transitions:
            if not isinstance(period, str):
                continue
            covering_eras = [era for era in eras if isinstance(era, dict) and _period_in_era(period, era)]
            if covering_eras:
                errors.append(
                    f"{prefix}.quantity_mapping: transition period {period} is covered by a classification era"
                )

    return errors


def validate_mapping_quality(doc: dict) -> list[str]:
    """Validate semantic precision metadata for commodity HS mappings.

    The generic commodity-master validator checks structural validity. This
    validator adds precision invariants so labels such as ``hs8_validated`` or
    ``chapter_broad`` cannot silently drift away from the code granularity they
    claim, classification transition months cannot accidentally be stitched
    into an era, and quantity ingestion is explicitly authorized only through
    validated HS8 mappings.
    """

    errors: list[str] = []
    commodities = doc.get("commodities")
    if not isinstance(commodities, list):
        return ["mapping quality: commodities must be a list"]

    for index, item in enumerate(commodities):
        if not isinstance(item, dict):
            errors.append(f"mapping quality: commodities[{index}] must be an object")
            continue

        commodity_id = item.get("id") or f"commodities[{index}]"
        prefix = f"mapping quality[{commodity_id}]"
        status = item.get("mapping_status")
        allowed_lengths = MAPPING_STATUS_CODE_LENGTHS.get(status)
        if allowed_lengths is None:
            errors.append(f"{prefix}: unsupported mapping_status {status!r}")
            continue

        codes = item.get("hs_codes")
        if isinstance(codes, list):
            if len(codes) != len(set(codes)):
                errors.append(f"{prefix}: hs_codes must not contain duplicates")
            bad_lengths = sorted({len(code) for code in codes if isinstance(code, str)} - allowed_lengths)
            if bad_lengths:
                errors.append(
                    f"{prefix}: mapping_status {status!r} allows HS lengths "
                    f"{sorted(allowed_lengths)}, found {bad_lengths}"
                )

        transitions = item.get("classification_transition_periods", [])
        eras = item.get("classification_eras", [])
        if transitions and not eras:
            errors.append(f"{prefix}: transition periods require classification_eras")

        if isinstance(transitions, list) and len(transitions) != len(set(transitions)):
            errors.append(f"{prefix}: classification_transition_periods must not contain duplicates")

        if isinstance(eras, list) and eras:
            open_ended = [era for era in eras if isinstance(era, dict) and era.get("through") is None]
            if len(open_ended) != 1:
                errors.append(f"{prefix}: classification_eras must contain exactly one open-ended current era")
            elif isinstance(codes, list) and open_ended[0].get("hs_codes") != codes:
                errors.append(f"{prefix}: top-level hs_codes must match the open-ended current era")

            for era_index, era in enumerate(eras):
                if not isinstance(era, dict):
                    continue
                era_codes = era.get("hs_codes")
                era_prefix = f"{prefix}.classification_eras[{era_index}]"
                if isinstance(era_codes, list):
                    if len(era_codes) != len(set(era_codes)):
                        errors.append(f"{era_prefix}: hs_codes must not contain duplicates")
                    bad_lengths = sorted(
                        {len(code) for code in era_codes if isinstance(code, str)} - allowed_lengths
                    )
                    if bad_lengths:
                        errors.append(
                            f"{era_prefix}: mapping_status {status!r} allows HS lengths "
                            f"{sorted(allowed_lengths)}, found {bad_lengths}"
                        )

            if isinstance(transitions, list):
                for period in transitions:
                    if not isinstance(period, str):
                        continue
                    covering_eras = [era for era in eras if isinstance(era, dict) and _period_in_era(period, era)]
                    if covering_eras:
                        errors.append(
                            f"{prefix}: transition period {period} is covered by a classification era"
                        )

        errors.extend(_validate_quantity_mapping(item, prefix=prefix))

    return errors


def mapping_status_counts(doc: dict) -> dict[str, int]:
    commodities = doc.get("commodities", [])
    if not isinstance(commodities, list):
        return {}
    counts = Counter(
        item.get("mapping_status")
        for item in commodities
        if isinstance(item, dict) and isinstance(item.get("mapping_status"), str)
    )
    return dict(sorted(counts.items()))


def quantity_mapping_count(doc: dict) -> int:
    commodities = doc.get("commodities", [])
    if not isinstance(commodities, list):
        return 0
    return sum(
        1
        for item in commodities
        if isinstance(item, dict)
        and isinstance(item.get("quantity_mapping"), dict)
        and item["quantity_mapping"].get("enabled") is True
    )
