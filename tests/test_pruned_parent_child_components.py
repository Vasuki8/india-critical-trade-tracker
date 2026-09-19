from src.tracker.derived import derive_unit_values


def _report(trade_type, hs_code, value, *, value_type, unit=None):
    report = {
        "trade_type": trade_type,
        "hs_code": hs_code,
        "value_type": value_type,
        "source_quantity_unit": unit,
        "totals": {"value": value},
    }
    if value_type == "quantity":
        report["value_selector_code"] = "2"
        report["quantity_scale_to_source_unit"] = 1
    return report


def test_mixed_unit_parent_child_mapping_omits_redundant_component_rows():
    usd = {"reports": [_report("import", "8507", 10.0, value_type="usd")]}
    quantity = {
        "commodity": {
            "quantity_mapping_mode": "separate",
            "quantity_rollup_to_value_mapping": False,
            "canonical_hs_codes": ["85071000", "85079090"],
        },
        "reports": [
            _report("import", "85071000", 100, value_type="quantity", unit="NOS"),
            _report("import", "85079090", 50, value_type="quantity", unit="KGS"),
        ],
    }

    result = derive_unit_values(usd, quantity)

    aggregate = result["aggregate"]["import"]
    assert aggregate["status"] == "mixed_quantity_units"
    assert aggregate["mapping_method"] == "parent_value_child_hs8_separate"
    assert aggregate["quantity_hs_codes"] == ["85071000", "85079090"]
    assert result["by_hs_code"] == []


def test_rollup_parent_child_mapping_omits_redundant_component_rows():
    usd = {"reports": [_report("import", "2846", 6.0, value_type="usd")]}
    quantity = {
        "commodity": {
            "quantity_mapping_mode": "separate",
            "quantity_rollup_to_value_mapping": True,
            "canonical_hs_codes": ["28461010", "28469090"],
        },
        "reports": [
            _report("import", "28461010", 1_000_000, value_type="quantity", unit="KGS"),
            _report("import", "28469090", 2_000_000, value_type="quantity", unit="KGS"),
        ],
    }

    result = derive_unit_values(usd, quantity)

    aggregate = result["aggregate"]["import"]
    assert aggregate["status"] == "ok"
    assert aggregate["rollup_method"] == "parent_value_child_hs8_quantity"
    assert aggregate["quantity"] == 3_000_000
    assert result["by_hs_code"] == []


def test_direct_hs8_mapping_keeps_component_detail():
    usd = {"reports": [_report("import", "28252000", 2.5, value_type="usd")]}
    quantity = {
        "commodity": {"quantity_mapping_mode": "same_as_value"},
        "reports": [
            _report("import", "28252000", 500_000, value_type="quantity", unit="KGS"),
        ],
    }

    result = derive_unit_values(usd, quantity)

    assert result["aggregate"]["import"]["status"] == "ok"
    assert len(result["by_hs_code"]) == 1
    assert result["by_hs_code"][0]["status"] == "ok"
