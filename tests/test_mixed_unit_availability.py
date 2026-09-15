from src.tracker.derived import derive_unit_values


def _report(trade_type, hs_code, value, *, value_type, unit=None):
    report = {
        "trade_type": trade_type,
        "hs_code": hs_code,
        "value_type": value_type,
        "totals": {"value": value},
    }
    if value_type == "quantity":
        report["value_selector_code"] = "2"
        report["source_quantity_unit"] = unit
    return report


def _battery_quantity_observation(*, mixed_units=True):
    second_unit = "KGS" if mixed_units else "NOS"
    return {
        "commodity": {
            "quantity_mapping_mode": "separate",
            "quantity_rollup_to_value_mapping": False,
            "canonical_hs_codes": ["85071000", "85079090"],
        },
        "reports": [
            _report("import", "85071000", 100, value_type="quantity", unit="NOS"),
            _report("import", "85079090", 25, value_type="quantity", unit=second_unit),
            _report("export", "85071000", 40, value_type="quantity", unit="NOS"),
            _report("export", "85079090", 10, value_type="quantity", unit=second_unit),
        ],
    }


def _battery_usd_observation():
    return {
        "reports": [
            _report("import", "8507", 12.5, value_type="usd"),
            _report("export", "8507", 4.0, value_type="usd"),
        ]
    }


def test_separate_parent_child_mapping_surfaces_mixed_physical_units():
    result = derive_unit_values(_battery_usd_observation(), _battery_quantity_observation())

    assert result["status"] == "not_available"
    for trade_type, expected_usd in (("import", 12.5), ("export", 4.0)):
        aggregate = result["aggregate"][trade_type]
        assert aggregate["status"] == "mixed_quantity_units"
        assert aggregate["availability_reason"] == "mixed_physical_units"
        assert aggregate["mapping_method"] == "parent_value_child_hs8_separate"
        assert aggregate["value_hs_code"] == "8507"
        assert aggregate["quantity_hs_codes"] == ["85071000", "85079090"]
        assert aggregate["source_quantity_units"] == ["KGS", "NOS"]
        assert aggregate["component_units"] == ["KGS", "NOS"]
        assert aggregate["usd_million"] == expected_usd
        assert aggregate["quantity"] is None
        assert aggregate["unit_value_usd_per_source_unit"] is None


def test_explicit_non_rollup_is_reported_even_when_child_units_match():
    result = derive_unit_values(
        _battery_usd_observation(),
        _battery_quantity_observation(mixed_units=False),
    )

    aggregate = result["aggregate"]["import"]
    assert aggregate["status"] == "rollup_disabled"
    assert aggregate["availability_reason"] == "explicit_rollup_disabled"
    assert aggregate["source_quantity_units"] == ["NOS"]
    assert aggregate["component_units"] == ["NOS"]
    assert aggregate["quantity"] is None
    assert aggregate["unit_value_usd_per_source_unit"] is None


def test_separate_mapping_still_requires_exhaustive_child_set():
    quantity = _battery_quantity_observation()
    quantity["commodity"]["canonical_hs_codes"].append("85076000")

    result = derive_unit_values(_battery_usd_observation(), quantity)

    assert result["aggregate"]["import"]["status"] == "not_available"
    assert result["aggregate"]["export"]["status"] == "not_available"
