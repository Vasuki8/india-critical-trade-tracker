from pathlib import Path
from textwrap import dedent


def replace_between(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[:start] + replacement + text[end:]


def patch_derived() -> None:
    path = Path("src/tracker/derived.py")
    text = path.read_text(encoding="utf-8")
    replacement = dedent(
        '''
        def _parent_value_child_quantity_rollup(
            usd_observation: dict[str, Any],
            quantity_observation: dict[str, Any] | None,
            trade_type: str,
        ) -> dict[str, Any] | None:
            """Blend one or more parent value reports with exhaustive HS8 quantities.

            This path is intentionally opt-in through observation provenance. Every
            quantity child must belong to exactly one monetary parent, every parent
            must have at least one child, and the observed child set must match the
            canonical quantity mapping. Component-level unit values remain unavailable
            because monetary value is not observed separately for each child; only the
            combined validated-parent unit value is derived.

            TradeStat can leave the source unit blank when a child line has exactly
            zero quantity. Such a zero line contributes no physical amount, so it may
            omit its unit without blocking the aggregate. Every positive child quantity
            must still report a verified unit that resolves to one common canonical
            unit.
            """
            if not _rollup_requested(quantity_observation):
                return None

            usd_reports = [
                report
                for report in usd_observation.get("reports", [])
                if report.get("trade_type") == trade_type
            ]
            quantity_reports = [
                report
                for report in (quantity_observation or {}).get("reports", [])
                if report.get("trade_type") == trade_type
            ]
            if not usd_reports or not quantity_reports:
                return None

            parent_codes = [str(report.get("hs_code") or "") for report in usd_reports]
            child_codes = [str(report.get("hs_code") or "") for report in quantity_reports]
            if (
                any(not code for code in parent_codes)
                or len(parent_codes) != len(set(parent_codes))
                or any(not code for code in child_codes)
                or len(child_codes) != len(set(child_codes))
            ):
                return None

            children_by_parent: dict[str, list[str]] = {code: [] for code in parent_codes}
            for child_code in child_codes:
                matches = [
                    parent_code
                    for parent_code in parent_codes
                    if len(parent_code) < len(child_code) and child_code.startswith(parent_code)
                ]
                if len(matches) != 1:
                    return None
                children_by_parent[matches[0]].append(child_code)
            if any(not children for children in children_by_parent.values()):
                return None

            canonical_children = {
                str(code)
                for code in (quantity_observation or {}).get("commodity", {}).get(
                    "canonical_hs_codes", []
                )
                if str(code)
            }
            if canonical_children and set(child_codes) != canonical_children:
                return None

            usd_values = [_total_value(report) for report in usd_reports]
            if any(value is None for value in usd_values):
                return None
            usd_million = sum(float(value) for value in usd_values if value is not None)

            metadata: dict[str, Any] = {
                "rollup_method": "parent_value_child_hs8_quantity",
                "value_hs_codes": sorted(parent_codes),
                "quantity_hs_codes": sorted(child_codes),
            }
            if len(parent_codes) == 1:
                metadata["value_hs_code"] = parent_codes[0]

            def unavailable(
                status: str,
                *,
                raw_quantity: float | None = None,
                source_units: set[str] | None = None,
                units: set[str] | None = None,
                quantity: float | None = None,
            ) -> dict[str, Any]:
                result: dict[str, Any] = {
                    "status": status,
                    "usd_million": round(usd_million, 6),
                    "raw_quantity_source_units": raw_quantity,
                    "quantity": round(quantity, 6) if quantity is not None else None,
                    "quantity_unit": next(iter(units)) if units and len(units) == 1 else None,
                    "unit_value_usd_per_source_unit": None,
                    **metadata,
                }
                if source_units is not None:
                    result["source_quantity_units"] = sorted(source_units)
                if units is not None and len(units) > 1:
                    result["component_units"] = sorted(units)
                return result

            units: set[str] = set()
            source_units: set[str] = set()
            total_raw_quantity = 0.0
            total_quantity = 0.0
            for report in quantity_reports:
                if not _quantity_selector_verified(report):
                    return unavailable("unverified_quantity_selector")
                raw_quantity = _total_value(report)
                if raw_quantity is None or raw_quantity < 0:
                    return unavailable("quantity_not_available")
                scale = _quantity_scale(report)
                if scale <= 0:
                    return unavailable("invalid_quantity_scale")

                total_raw_quantity += raw_quantity
                if raw_quantity == 0:
                    continue

                source_unit = _quantity_unit(report)
                unit, normalization_factor = _canonical_quantity_unit(source_unit)
                if unit is None or normalization_factor is None:
                    return unavailable(
                        "missing_quantity_unit",
                        raw_quantity=round(total_raw_quantity, 6),
                    )
                source_units.add(str(source_unit).upper())
                units.add(unit)
                total_quantity += raw_quantity * scale * normalization_factor

            raw_output = round(total_raw_quantity, 6) if len(source_units) <= 1 else None
            if total_quantity <= 0:
                return unavailable(
                    "quantity_not_available",
                    raw_quantity=raw_output,
                    source_units=source_units,
                    units=units,
                    quantity=total_quantity,
                )
            if len(units) != 1:
                return unavailable(
                    "mixed_quantity_units",
                    raw_quantity=raw_output,
                    source_units=source_units,
                    units=units,
                )

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
                **metadata,
            }


        '''
    )
    text = replace_between(
        text,
        "def _parent_value_child_quantity_rollup(",
        "def derive_unit_values(",
        replacement,
    )
    path.write_text(text, encoding="utf-8")


def patch_mapping_quality() -> None:
    path = Path("src/tracker/mapping_quality.py")
    text = path.read_text(encoding="utf-8")
    replacement = dedent(
        '''
            if rollup:
                value_codes = item.get("hs_codes")
                if not isinstance(value_codes, list) or not value_codes:
                    errors.append(
                        f"{prefix}.quantity_mapping: rollup requires a non-empty monetary hs_codes mapping"
                    )
                else:
                    valid_parents = [parent for parent in value_codes if isinstance(parent, str)]
                    matches_by_child: dict[str, list[str]] = {}
                    uncovered: list[str] = []
                    ambiguous: list[str] = []
                    for code in codes:
                        if not isinstance(code, str):
                            continue
                        matches = [
                            parent
                            for parent in valid_parents
                            if len(parent) < len(code) and code.startswith(parent)
                        ]
                        matches_by_child[code] = matches
                        if not matches:
                            uncovered.append(code)
                        elif len(matches) > 1:
                            ambiguous.append(code)
                    if uncovered:
                        errors.append(
                            f"{prefix}.quantity_mapping: rollup quantity codes must be children of the monetary mapping"
                        )
                    if ambiguous:
                        errors.append(
                            f"{prefix}.quantity_mapping: each rollup quantity code must match exactly one monetary parent"
                        )
                    unused_parents = [
                        parent
                        for parent in valid_parents
                        if not any(parent in matches for matches in matches_by_child.values())
                    ]
                    if unused_parents:
                        errors.append(
                            f"{prefix}.quantity_mapping: rollup monetary mappings must each have at least one quantity child"
                        )

        '''
    )
    start_marker = '    if rollup:\n        value_codes = item.get("hs_codes")'
    end_marker = '    transitions = quantity.get("classification_transition_periods", [])'
    text = replace_between(text, start_marker, end_marker, replacement)
    path.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    derived_path = Path("tests/test_derived.py")
    text = derived_path.read_text(encoding="utf-8")
    if "def test_multi_parent_heading_rollup_derives_aggregate_unit_value():" not in text:
        text += dedent(
            '''


            def test_multi_parent_heading_rollup_derives_aggregate_unit_value():
                usd = {
                    "reports": [
                        _report("import", "2605", 1.0, value_type="usd"),
                        _report("import", "8105", 5.0, value_type="usd"),
                    ]
                }
                quantity = {
                    "commodity": {
                        "canonical_hs_codes": ["26050000", "81052010", "81052020"],
                        "quantity_rollup_to_value_mapping": True,
                    },
                    "reports": [
                        _report("import", "26050000", 1_000_000, value_type="quantity", unit="KGS"),
                        _report("import", "81052010", 1_000_000, value_type="quantity", unit="KGS"),
                        _report("import", "81052020", 1_000_000, value_type="quantity", unit="KGS"),
                    ],
                }

                result = derive_unit_values(usd, quantity)

                aggregate = result["aggregate"]["import"]
                assert result["status"] == "ok"
                assert aggregate["status"] == "ok"
                assert aggregate["usd_million"] == 6.0
                assert aggregate["quantity"] == 3_000_000
                assert aggregate["quantity_unit"] == "KGS"
                assert aggregate["unit_value_usd_per_source_unit"] == 2.0
                assert aggregate["value_hs_codes"] == ["2605", "8105"]
                assert "value_hs_code" not in aggregate


            def test_multi_parent_heading_rollup_rejects_orphan_child():
                usd = {
                    "reports": [
                        _report("import", "2605", 1.0, value_type="usd"),
                        _report("import", "8105", 5.0, value_type="usd"),
                    ]
                }
                quantity = {
                    "commodity": {
                        "canonical_hs_codes": ["26050000", "99999999"],
                        "quantity_rollup_to_value_mapping": True,
                    },
                    "reports": [
                        _report("import", "26050000", 1_000_000, value_type="quantity", unit="KGS"),
                        _report("import", "99999999", 1_000_000, value_type="quantity", unit="KGS"),
                    ],
                }

                result = derive_unit_values(usd, quantity)

                assert result["status"] == "not_available"
                assert result["aggregate"]["import"]["status"] == "not_available"


            def test_multi_parent_heading_rollup_rejects_ambiguous_child():
                usd = {
                    "reports": [
                        _report("import", "81", 1.0, value_type="usd"),
                        _report("import", "8105", 5.0, value_type="usd"),
                    ]
                }
                quantity = {
                    "commodity": {
                        "canonical_hs_codes": ["81052010"],
                        "quantity_rollup_to_value_mapping": True,
                    },
                    "reports": [
                        _report("import", "81052010", 1_000_000, value_type="quantity", unit="KGS"),
                    ],
                }

                result = derive_unit_values(usd, quantity)

                assert result["status"] == "not_available"
                assert result["aggregate"]["import"]["status"] == "not_available"
            '''
        )
        derived_path.write_text(text, encoding="utf-8")

    master_path = Path("tests/test_commodity_master.py")
    text = master_path.read_text(encoding="utf-8")
    if "def test_quantity_rollup_rejects_ambiguous_value_parents():" not in text:
        text += dedent(
            '''


            def test_quantity_rollup_rejects_ambiguous_value_parents():
                item = _commodity(
                    hs_codes=["81", "8105"],
                    mapping_status="chapter_plus_ore",
                    quantity_mapping={
                        "enabled": True,
                        "mode": "separate",
                        "mapping_status": "hs8_validated",
                        "rollup_to_value_mapping": True,
                        "hs_codes": ["81052010"],
                    },
                )
                errors = validate_mapping_quality(_master_with(item))
                assert any("exactly one monetary parent" in error for error in errors)


            def test_quantity_rollup_requires_each_value_parent_to_have_child():
                item = _commodity(
                    hs_codes=["2605", "8105"],
                    mapping_status="heading_set",
                    quantity_mapping={
                        "enabled": True,
                        "mode": "separate",
                        "mapping_status": "hs8_validated",
                        "rollup_to_value_mapping": True,
                        "hs_codes": ["81052010"],
                    },
                )
                errors = validate_mapping_quality(_master_with(item))
                assert any("each have at least one quantity child" in error for error in errors)
            '''
        )
        master_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_derived()
    patch_mapping_quality()
    patch_tests()
