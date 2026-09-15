from src.tracker.dashboard import _compact_unit_values
from src.tracker.intelligence import _unit_value_summary


def _report(trade_type, hs_code, value, *, value_type, unit=None):
    report = {
        "trade_type": trade_type,
        "hs_code": hs_code,
        "value_type": value_type,
        "totals": {"value": value},
    }
    if value_type == "quantity":
        report.update(
            {
                "value_selector_code": "2",
                "source_quantity_unit": unit,
                "quantity_scale_to_source_unit": 1,
            }
        )
    return report


def test_dashboard_compaction_drops_parent_child_structural_mismatches():
    derived = {
        "status": "not_available",
        "method": "demo method",
        "quantity_scale_note": "demo note",
        "aggregate": {
            "import": {
                "status": "mixed_quantity_units",
                "component_units": ["KGS", "NOS"],
                "quantity": None,
            }
        },
        "by_hs_code": [
            {"hs_code": "8507", "status": "missing_quantity_report"},
            {"hs_code": "85071000", "status": "missing_usd_report"},
        ],
    }

    compact = _compact_unit_values(derived)

    assert compact["status"] == "not_available"
    assert compact["aggregate"]["import"]["status"] == "mixed_quantity_units"
    assert "by_hs_code" not in compact


def test_dashboard_compaction_preserves_meaningful_validation_diagnostic():
    derived = {
        "status": "not_available",
        "aggregate": {"import": {"status": "not_available"}},
        "by_hs_code": [
            {"hs_code": "28252000", "status": "unverified_quantity_selector"},
            {"hs_code": "28369100", "status": "missing_usd_report"},
        ],
    }

    compact = _compact_unit_values(derived)

    assert compact["by_hs_code"] == [
        {"hs_code": "28252000", "status": "unverified_quantity_selector"}
    ]


def test_intelligence_keeps_meaningful_mixed_unit_aggregate():
    usd = {
        "reports": [_report("import", "8507", 10.0, value_type="usd")],
    }
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

    summary = _unit_value_summary(usd, quantity)

    assert summary["status"] == "not_available"
    assert summary["aggregate"]["import"]["status"] == "mixed_quantity_units"
    assert summary["aggregate"]["import"]["component_units"] == ["KGS", "NOS"]


def test_intelligence_does_not_expand_dummy_aggregate_without_quantity_observation():
    usd = {
        "reports": [_report("import", "2701", 10.0, value_type="usd")],
    }

    summary = _unit_value_summary(usd, None)

    assert summary == {"status": "not_available"}
