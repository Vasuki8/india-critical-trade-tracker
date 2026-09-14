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
