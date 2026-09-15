from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_dashboard() -> None:
    path = Path("src/tracker/dashboard.py")
    text = path.read_text(encoding="utf-8")
    marker = '''def _live_metrics(doc: dict[str, Any]) -> dict[str, Any]:
    reports = doc.get("reports", [])
    return aggregate_commodity(reports) if reports else doc.get("metrics", {})


'''
    helper = marker + '''def _compact_unit_values(unit_values: dict[str, Any]) -> dict[str, Any]:
    """Keep browser-relevant unit-value fields while retaining real validation errors."""
    compact = {
        "status": unit_values.get("status", "not_available"),
        "method": unit_values.get("method"),
        "quantity_scale_note": unit_values.get("quantity_scale_note"),
        "aggregate": unit_values.get("aggregate", {}),
    }
    structural_mismatches = {"missing_usd_report", "missing_quantity_report"}
    diagnostics = [
        item
        for item in unit_values.get("by_hs_code", [])
        if item.get("status") not in structural_mismatches
    ]
    if diagnostics:
        compact["by_hs_code"] = diagnostics
    return {key: value for key, value in compact.items() if value is not None}


'''
    text = replace_once(text, marker, helper, label="dashboard helper insertion")
    text = replace_once(
        text,
        '        card["unit_values"] = unit_values\n',
        '        card["unit_values"] = _compact_unit_values(unit_values)\n',
        label="dashboard card compaction",
    )
    path.write_text(text, encoding="utf-8")


def patch_intelligence() -> None:
    path = Path("src/tracker/intelligence.py")
    text = path.read_text(encoding="utf-8")
    start = text.index("def _unit_value_summary(")
    end = text.index("\ndef _month_entry(", start)
    replacement = '''def _unit_value_summary(
    usd_doc: dict[str, Any],
    quantity_doc: dict[str, Any] | None,
) -> dict[str, Any]:
    derived = derive_unit_values(usd_doc, quantity_doc)
    summary: dict[str, Any] = {
        "status": derived.get("status", "unavailable"),
    }
    aggregate = derived.get("aggregate", {})
    meaningful_aggregate = any(
        isinstance(metric, dict) and metric.get("status") not in {None, "not_available"}
        for metric in aggregate.values()
    )
    if quantity_doc is not None and meaningful_aggregate:
        # Preserve mixed-unit / disabled-rollup explanations as well as successful
        # aggregate unit values. Per-HS diagnostics remain in source observations.
        summary["aggregate"] = aggregate
    return summary

'''
    text = text[:start] + replacement + text[end + 1 :]
    path.write_text(text, encoding="utf-8")


def write_tests() -> None:
    path = Path("tests/test_unit_value_web_payload.py")
    path.write_text(
        '''from src.tracker.dashboard import _compact_unit_values
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
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    patch_dashboard()
    patch_intelligence()
    write_tests()
    Path(__file__).unlink()
