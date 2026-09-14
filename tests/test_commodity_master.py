from pathlib import Path

from src.tracker.mapping_quality import mapping_status_counts, validate_mapping_quality
from src.tracker.validation import load_json, validate_commodity_master

ROOT = Path(__file__).resolve().parents[1]


def _master_with(item: dict) -> dict:
    return {"commodities": [item]}


def _commodity(**overrides) -> dict:
    item = {
        "id": "sample",
        "name": "Sample",
        "priority": "critical",
        "hs_codes": ["12345678"],
        "mapping_status": "hs8_validated",
    }
    item.update(overrides)
    return item


def test_commodity_master_is_valid():
    doc = load_json(ROOT / "data" / "commodities.json")
    assert validate_commodity_master(doc) == []
    assert validate_mapping_quality(doc) == []


def test_core_commodities_present():
    doc = load_json(ROOT / "data" / "commodities.json")
    ids = {item["id"] for item in doc["commodities"]}
    expected = {"crude_oil", "gold", "semiconductors", "fertilizers", "lithium", "rare_earths"}
    assert expected <= ids


def test_natural_gas_uses_exact_hs8_lines():
    doc = load_json(ROOT / "data" / "commodities.json")
    gas = next(item for item in doc["commodities"] if item["id"] == "natural_gas_lng")

    assert gas["hs_codes"] == ["27111100", "27112100"]
    assert gas["mapping_status"] == "hs8_validated"


def test_mapping_status_counts_expose_exact_hs8_coverage():
    doc = load_json(ROOT / "data" / "commodities.json")
    counts = mapping_status_counts(doc)

    assert counts["hs8_validated"] == 3
    assert sum(counts.values()) == len(doc["commodities"])


def test_mapping_quality_rejects_unknown_status():
    errors = validate_mapping_quality(_master_with(_commodity(mapping_status="mystery")))
    assert any("unsupported mapping_status" in error for error in errors)


def test_mapping_quality_rejects_granularity_mismatch():
    errors = validate_mapping_quality(
        _master_with(_commodity(hs_codes=["2709"], mapping_status="hs8_validated"))
    )
    assert any("allows HS lengths [8]" in error for error in errors)


def test_mapping_quality_rejects_duplicate_codes():
    errors = validate_mapping_quality(
        _master_with(_commodity(hs_codes=["12345678", "12345678"]))
    )
    assert any("must not contain duplicates" in error for error in errors)


def test_mapping_quality_rejects_transition_covered_by_era():
    item = _commodity(
        hs_codes=["12345678"],
        classification_transition_periods=["2022-02"],
        classification_eras=[
            {"from": "2018-01", "through": "2022-02", "hs_codes": ["87654321"]},
            {"from": "2022-03", "through": None, "hs_codes": ["12345678"]},
        ],
    )
    errors = validate_mapping_quality(_master_with(item))
    assert any("transition period 2022-02 is covered" in error for error in errors)


def test_mapping_quality_requires_current_codes_to_match_open_era():
    item = _commodity(
        hs_codes=["12345678"],
        classification_eras=[
            {"from": "2018-01", "through": "2022-01", "hs_codes": ["87654321"]},
            {"from": "2022-03", "through": None, "hs_codes": ["11111111"]},
        ],
    )
    errors = validate_mapping_quality(_master_with(item))
    assert any("top-level hs_codes must match" in error for error in errors)
