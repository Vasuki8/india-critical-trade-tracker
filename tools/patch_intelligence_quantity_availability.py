from pathlib import Path


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
        # The drill-down needs aggregate availability semantics even when no
        # implied unit value can be derived (for example mixed NOS + KGS
        # Batteries quantities). Per-HS diagnostics remain in observations.
        summary["aggregate"] = aggregate
    return summary

'''
    text = text[:start] + replacement + text[end + 1 :]
    path.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    path = Path("tests/test_intelligence.py")
    text = path.read_text(encoding="utf-8")
    addition = '''\n\ndef _quantity_report(trade_type: str, hs_code: str, value: float, unit: str | None) -> dict:
    return {
        "trade_type": trade_type,
        "hs_code": hs_code,
        "value_type": "quantity",
        "value_selector_code": "2",
        "source_quantity_unit": unit,
        "quantity_scale_to_source_unit": 1,
        "totals": {"value": value},
        "rows": [],
    }


def test_intelligence_preserves_mixed_unit_aggregate_availability(tmp_path: Path):
    observations = tmp_path / "observations"
    usd = _observation("2026-06", imports=10, exports=1)
    usd["commodity"]["id"] = "batteries"
    usd["commodity"]["name"] = "Electric Accumulators / Batteries"
    usd["commodity"]["category"] = "Clean Energy"
    usd["commodity"]["hs_codes"] = ["8507"]
    usd["commodity"]["mapping_status"] = "heading_validated"
    usd["reports"][0]["hs_code"] = "8507"
    usd["reports"][1]["hs_code"] = "8507"

    quantity = {
        "schema_version": 3,
        "period": "2026-06",
        "value_type": "quantity",
        "status": "ok",
        "commodity": {
            "id": "batteries",
            "name": "Electric Accumulators / Batteries",
            "category": "Clean Energy",
            "hs_codes": ["85071000", "85079090"],
            "canonical_hs_codes": ["85071000", "85079090"],
            "mapping_status": "hs8_validated",
            "quantity_mapping_mode": "separate",
            "quantity_rollup_to_value_mapping": False,
        },
        "reports": [
            _quantity_report("import", "85071000", 100, "NOS"),
            _quantity_report("import", "85079090", 50, "KGS"),
            _quantity_report("export", "85071000", 20, "NOS"),
            _quantity_report("export", "85079090", 10, "KGS"),
        ],
    }

    _write(observations / "2026-06" / "batteries.usd.json", usd)
    _write(observations / "2026-06" / "batteries.quantity.json", quantity)
    commodity = {
        "id": "batteries",
        "name": "Electric Accumulators / Batteries",
        "category": "Clean Energy",
        "hs_codes": ["8507"],
        "mapping_status": "heading_validated",
    }

    doc = build_commodity_intelligence(observations, commodity)

    assert doc is not None
    unit_values = doc["monthly"][0]["unit_values"]
    assert unit_values["status"] == "not_available"
    assert unit_values["aggregate"]["import"]["status"] == "mixed_quantity_units"
    assert unit_values["aggregate"]["import"]["component_units"] == ["KGS", "NOS"]
    assert unit_values["aggregate"]["export"]["status"] == "mixed_quantity_units"


def test_intelligence_does_not_expand_dummy_aggregate_without_quantity(tmp_path: Path):
    observations = tmp_path / "observations"
    _write(
        observations / "2025-01" / "crude_oil.usd.json",
        _observation("2025-01", imports=100, exports=10),
    )
    commodity = {
        "id": "crude_oil",
        "name": "Crude Oil",
        "category": "Energy",
        "hs_codes": ["2709"],
        "mapping_status": "validated",
    }

    doc = build_commodity_intelligence(observations, commodity)

    assert doc is not None
    assert doc["monthly"][0]["unit_values"] == {"status": "not_available"}
'''
    if "test_intelligence_preserves_mixed_unit_aggregate_availability" in text:
        raise SystemExit("intelligence availability tests already present")
    path.write_text(text.rstrip() + addition + "\n", encoding="utf-8")


if __name__ == "__main__":
    patch_intelligence()
    patch_tests()
    Path(__file__).unlink()
