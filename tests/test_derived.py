from src.tracker.derived import derive_unit_values


def _report(trade_type, hs_code, value, *, value_type, unit=None):
    return {
        "trade_type": trade_type,
        "hs_code": hs_code,
        "value_type": value_type,
        "source_quantity_unit": unit,
        "totals": {"value": value},
    }


def test_derives_usd_per_source_unit():
    usd = {
        "reports": [
            _report("import", "28252000", 2.5, value_type="usd"),
        ]
    }
    quantity = {
        "reports": [
            _report("import", "28252000", 500_000, value_type="quantity", unit="KGS"),
        ]
    }

    result = derive_unit_values(usd, quantity)

    assert result["status"] == "ok"
    assert result["by_hs_code"][0]["unit_value_usd_per_source_unit"] == 5.0
    assert result["aggregate"]["import"]["quantity_unit"] == "KGS"
    assert result["aggregate"]["import"]["unit_value_usd_per_source_unit"] == 5.0


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
