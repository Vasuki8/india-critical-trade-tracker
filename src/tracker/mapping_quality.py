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


def _period_in_era(period: str, era: dict) -> bool:
    start = era.get("from")
    through = era.get("through")
    if not isinstance(start, str):
        return False
    if period < start:
        return False
    return through is None or (isinstance(through, str) and period <= through)


def validate_mapping_quality(doc: dict) -> list[str]:
    """Validate semantic precision metadata for commodity HS mappings.

    The generic commodity-master validator checks structural validity. This
    validator adds precision invariants so labels such as ``hs8_validated`` or
    ``chapter_broad`` cannot silently drift away from the code granularity they
    claim, and classification transition months cannot accidentally be stitched
    into an era.
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

        if not isinstance(eras, list) or not eras:
            continue

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
