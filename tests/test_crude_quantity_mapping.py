import json
from pathlib import Path

from scripts.ingest_tradestat import hs_codes_for_period, is_queryable_commodity


ROOT = Path(__file__).resolve().parents[1]


def _crude_oil() -> dict:
    master = json.loads((ROOT / "data" / "commodities.json").read_text(encoding="utf-8"))
    return next(item for item in master["commodities"] if item["id"] == "crude_oil")


def test_crude_oil_quantity_mapping_tracks_itc_hs_2022_split():
    crude = _crude_oil()

    old_codes, old_note = hs_codes_for_period(crude, "2022-01", value_type="quantity")
    transition_codes, transition_note = hs_codes_for_period(crude, "2022-02", value_type="quantity")
    new_codes, new_note = hs_codes_for_period(crude, "2022-03", value_type="quantity")

    assert old_codes == ["27090000"]
    assert "Pre-ITC(HS) 2022" in old_note
    assert transition_codes == []
    assert "transition" in transition_note
    assert new_codes == ["27090010", "27090090"]
    assert "ITC(HS) 2022" in new_note


def test_crude_oil_quantity_mapping_is_exact_hs8_and_rolls_up_to_value_heading():
    crude = _crude_oil()
    quantity = crude["quantity_mapping"]

    assert crude["hs_codes"] == ["2709"]
    assert crude["mapping_status"] == "heading_validated"
    assert quantity["mode"] == "separate"
    assert quantity["mapping_status"] == "hs8_validated"
    assert quantity["rollup_to_value_mapping"] is True
    assert "history_complete_from" not in quantity

    for period in ("2018-01", "2022-01", "2022-03", "2026-06"):
        codes, _ = hs_codes_for_period(crude, period, value_type="quantity")
        ok, reason = is_queryable_commodity(crude, value_type="quantity", hs_codes=codes)
        assert ok, reason
        assert all(len(code) == 8 for code in codes)
