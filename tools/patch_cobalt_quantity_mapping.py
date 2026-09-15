from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_master() -> None:
    path = Path("data/commodities.json")
    text = path.read_text(encoding="utf-8")
    old = '    {"id":"cobalt","name":"Cobalt","category":"Strategic Minerals","priority":"critical","hs_codes":["2605","8105"],"mapping_status":"heading_set","icon":"battery"},'
    new = '''    {
      "id":"cobalt",
      "name":"Cobalt",
      "category":"Strategic Minerals",
      "priority":"critical",
      "hs_codes":["2605","8105"],
      "mapping_status":"heading_set",
      "icon":"battery",
      "quantity_mapping":{
        "enabled":true,
        "mode":"separate",
        "mapping_status":"hs8_validated",
        "rollup_to_value_mapping":true,
        "hs_codes":["26050000","81052010","81052020","81052030","81053000","81059000"],
        "note":"Exact ITC-HS8 lines under validated value headings 2605 and 8105. Official tariff schedules and live historical TradeStat probes across 2018-2026 confirmed positive sampled quantities in KGS, so compatible mass rollup is permitted. Historical completeness is declared only after the archive backfill succeeds."
      }
    },'''
    text = replace_once(text, old, new, label="Cobalt master entry")
    path.write_text(text, encoding="utf-8")


def patch_quantity_count() -> None:
    path = Path("tests/test_commodity_master.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    assert quantity_mapping_count(doc) == 6\n",
        "    assert quantity_mapping_count(doc) == 7\n",
        label="quantity mapping count",
    )
    path.write_text(text, encoding="utf-8")


def write_cobalt_tests() -> None:
    path = Path("tests/test_cobalt_quantity_mapping.py")
    path.write_text(
        '''import json
from pathlib import Path

from scripts.ingest_tradestat import hs_codes_for_period, is_queryable_commodity

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data" / "commodities.json"
EXPECTED_CODES = [
    "26050000",
    "81052010",
    "81052020",
    "81052030",
    "81053000",
    "81059000",
]


def _cobalt():
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    return next(item for item in master["commodities"] if item["id"] == "cobalt")


def test_cobalt_keeps_two_parent_value_mapping_and_exact_quantity_children():
    cobalt = _cobalt()
    quantity = cobalt["quantity_mapping"]

    assert cobalt["hs_codes"] == ["2605", "8105"]
    assert cobalt["mapping_status"] == "heading_set"
    assert quantity["enabled"] is True
    assert quantity["mode"] == "separate"
    assert quantity["mapping_status"] == "hs8_validated"
    assert quantity["rollup_to_value_mapping"] is True
    assert quantity["hs_codes"] == EXPECTED_CODES
    assert "history_complete_from" not in quantity


def test_cobalt_quantity_mapping_is_stable_across_archive_and_queryable():
    cobalt = _cobalt()

    first_codes, first_note = hs_codes_for_period(cobalt, "2018-01", value_type="quantity")
    latest_codes, latest_note = hs_codes_for_period(cobalt, "2026-06", value_type="quantity")

    assert first_codes == EXPECTED_CODES
    assert latest_codes == EXPECTED_CODES
    assert first_note == latest_note
    assert first_note is not None
    assert "Exact ITC-HS8 lines" in first_note
    assert "2018-2026" in first_note

    queryable, reason = is_queryable_commodity(
        cobalt,
        value_type="quantity",
        hs_codes=latest_codes,
    )
    assert queryable is True
    assert reason is None


def test_cobalt_has_no_artificial_classification_transition_gap():
    cobalt = _cobalt()

    assert cobalt.get("classification_transition_periods", []) == []
    assert cobalt["quantity_mapping"].get("classification_transition_periods", []) == []
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    patch_master()
    patch_quantity_count()
    write_cobalt_tests()
    Path(__file__).unlink()
