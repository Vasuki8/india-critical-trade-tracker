import json
from pathlib import Path

from scripts.ingest_tradestat import hs_codes_for_period, is_queryable_commodity

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data" / "commodities.json"


def _batteries():
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    return next(item for item in master["commodities"] if item["id"] == "batteries")


def test_batteries_quantity_mapping_tracks_2022_classification_break():
    batteries = _batteries()

    pre_codes, _ = hs_codes_for_period(batteries, "2022-01", value_type="quantity")
    transition_codes, transition_note = hs_codes_for_period(
        batteries, "2022-02", value_type="quantity"
    )
    post_codes, _ = hs_codes_for_period(batteries, "2022-03", value_type="quantity")

    assert pre_codes == [
        "85071000",
        "85072000",
        "85073000",
        "85074000",
        "85075000",
        "85076000",
        "85078000",
        "85079010",
        "85079090",
    ]
    assert transition_codes == []
    assert "transition" in transition_note
    assert post_codes == [
        "85071000",
        "85072000",
        "85073000",
        "85075000",
        "85076000",
        "85078000",
        "85079010",
        "85079090",
    ]


def test_batteries_quantity_mapping_is_exact_but_not_parent_rollup_safe():
    batteries = _batteries()
    quantity = batteries["quantity_mapping"]

    assert quantity["enabled"] is True
    assert quantity["mode"] == "separate"
    assert quantity["mapping_status"] == "hs8_validated"
    assert quantity["rollup_to_value_mapping"] is False

    # Before the one-time archive bootstrap this field is absent. The bootstrap
    # adds it only after all historical fetches, derived builds, and validation
    # succeed. Both repository states are valid; any declared completion must
    # start at the known archive boundary.
    history_complete_from = quantity.get("history_complete_from")
    assert history_complete_from in {None, "2018-01"}

    codes, _ = hs_codes_for_period(batteries, "2026-06", value_type="quantity")
    queryable, reason = is_queryable_commodity(
        batteries,
        value_type="quantity",
        hs_codes=codes,
    )
    assert queryable is True
    assert reason is None
