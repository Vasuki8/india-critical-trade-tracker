from pathlib import Path

from src.tracker.validation import load_json, validate_commodity_master

ROOT = Path(__file__).resolve().parents[1]


def test_commodity_master_is_valid():
    doc = load_json(ROOT / "data" / "commodities.json")
    assert validate_commodity_master(doc) == []


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
