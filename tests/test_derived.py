from src.tracker.derived import derive_unit_values


def _report(trade_type, hs_code, value, *, value_type, unit=None, scale=None, selector=None):
    report = {
        "trade_type": trade_type,
        "hs_code": hs_code,
        "value_type": value_type,
        "source_quantity_unit": unit,
        "totals": {"value": value},
    }
    if value_type == "quantity":
        report["value_selector_code"] = "2" if selector is None else selector
    if scale is not None:
        report["quantity_scale_to_source_unit"] = scale
    return report


def test_derives_usd_per_source_unit_from_direct_units():
    usd = {"reports": [_report("import", "28252000", 2.5, value_type="usd")]}
    quantity = {
        "reports": [
            _report("import", "28252000", 500_000, value_type="quantity", unit="KGS"),
        ]
    }

    result = derive_unit_values(usd, quantity)

    assert result["status"] == "ok"
    component = result["by_hs_code"][0]
    assert component["raw_quantity_source_units"] == 500_000
    assert component["quantity"] == 500_000
    assert component["quantity_scale_to_source_unit"] == 1
    assert component["unit_value_usd_per_source_unit"] == 5.0
    assert result["aggregate"]["import"]["quantity_unit"] == "KGS"
    assert result["aggregate"]["import"]["unit_value_usd_per_source_unit"] == 5.0


def test_explicit_quantity_scale_is_respected():
    usd = {"reports": [_report("import", "28252000", 1.0, value_type="usd")]}
    quantity = {
        "reports": [
            _report("import", "28252000", 1_000_000, value_type="quantity", unit="KGS", scale=1),
        ]
    }

    result = derive_unit_values(usd, quantity)

    assert result["by_hs_code"][0]["quantity"] == 1_000_000
    assert result["by_hs_code"][0]["unit_value_usd_per_source_unit"] == 1.0


def test_unverified_quantity_selector_is_rejected():
    usd = {"reports": [_report("import", "28252000", 1.0, value_type="usd")]}
    quantity = {
        "reports": [
            _report("import", "28252000", 1_000_000, value_type="quantity", unit="KGS", selector="3"),
        ]
    }

    result = derive_unit_values(usd, quantity)

    assert result["status"] == "not_available"
    assert result["by_hs_code"][0]["status"] == "unverified_quantity_selector"
    assert result["by_hs_code"][0]["unit_value_usd_per_source_unit"] is None


def test_mixed_quantity_units_are_not_aggregated():
    usd = {
        "reports": [
            _report("import", "11111111", 1.0, value_type="usd"),
            _report("import", "22222222", 1.0, value_type="usd"),
        ]
    }
    quantity = {
        "reports": [
            _report("import", "11111111", 100, value_type="quantity", unit="KGS"),
            _report("import", "22222222", 10, value_type="quantity", unit="NOS"),
        ]
    }

    result = derive_unit_values(usd, quantity)

    assert result["aggregate"]["import"]["status"] == "mixed_quantity_units"
    assert result["aggregate"]["import"]["unit_value_usd_per_source_unit"] is None


def test_missing_quantity_report_is_transparent():
    usd = {"reports": [_report("export", "85414200", 4.0, value_type="usd")]}

    result = derive_unit_values(usd, None)

    assert result["status"] == "not_available"
    assert result["by_hs_code"][0]["status"] == "missing_quantity_report"


def test_parent_heading_rollup_derives_only_aggregate_unit_value():
    usd = {
        "reports": [
            _report("import", "2846", 6.0, value_type="usd"),
        ]
    }
    quantity = {
        "commodity": {
            "canonical_hs_codes": ["28461010", "28469090"],
            "quantity_rollup_to_value_mapping": True,
        },
        "reports": [
            _report("import", "28461010", 1_000_000, value_type="quantity", unit="KGS", scale=1),
            _report("import", "28469090", 2_000_000, value_type="quantity", unit="KGS", scale=1),
        ],
    }

    result = derive_unit_values(usd, quantity)

    assert result["status"] == "ok"
    aggregate = result["aggregate"]["import"]
    assert aggregate["status"] == "ok"
    assert aggregate["rollup_method"] == "parent_value_child_hs8_quantity"
    assert aggregate["value_hs_code"] == "2846"
    assert aggregate["quantity"] == 3_000_000
    assert aggregate["quantity_unit"] == "KGS"
    assert aggregate["unit_value_usd_per_source_unit"] == 2.0
    assert all(item["status"] != "ok" for item in result["by_hs_code"])


def test_parent_heading_rollup_requires_explicit_provenance():
    usd = {"reports": [_report("import", "2846", 6.0, value_type="usd")]}
    quantity = {
        "commodity": {"canonical_hs_codes": ["28461010", "28469090"]},
        "reports": [
            _report("import", "28461010", 1_000_000, value_type="quantity", unit="KGS"),
            _report("import", "28469090", 2_000_000, value_type="quantity", unit="KGS"),
        ],
    }

    result = derive_unit_values(usd, quantity)

    assert result["status"] == "not_available"
    assert result["aggregate"]["import"]["status"] == "not_available"


def test_parent_heading_rollup_rejects_mixed_child_units():
    usd = {"reports": [_report("import", "2846", 6.0, value_type="usd")]}
    quantity = {
        "commodity": {
            "canonical_hs_codes": ["28461010", "28469090"],
            "quantity_rollup_to_value_mapping": True,
        },
        "reports": [
            _report("import", "28461010", 1_000_000, value_type="quantity", unit="KGS"),
            _report("import", "28469090", 2_000_000, value_type="quantity", unit="NOS"),
        ],
    }

    result = derive_unit_values(usd, quantity)

    assert result["status"] == "not_available"
    assert result["aggregate"]["import"]["status"] == "mixed_quantity_units"
    assert result["aggregate"]["import"]["unit_value_usd_per_source_unit"] is None


def test_parent_heading_rollup_requires_complete_expected_child_set():
    usd = {"reports": [_report("import", "2846", 6.0, value_type="usd")]}
    quantity = {
        "commodity": {
            "canonical_hs_codes": ["28461010", "28461090", "28469090"],
            "quantity_rollup_to_value_mapping": True,
        },
        "reports": [
            _report("import", "28461010", 1_000_000, value_type="quantity", unit="KGS"),
            _report("import", "28469090", 2_000_000, value_type="quantity", unit="KGS"),
        ],
    }

    result = derive_unit_values(usd, quantity)

    assert result["status"] == "not_available"
    assert result["aggregate"]["import"]["status"] == "not_available"
