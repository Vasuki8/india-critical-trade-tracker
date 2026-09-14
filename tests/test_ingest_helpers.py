import json
from pathlib import Path

from scripts.ingest_tradestat import (
    QUANTITY_SCALE_TO_SOURCE_UNIT,
    hs_codes_for_period,
    ingest_one,
    is_queryable_commodity,
    latest_period_from_status,
)


def test_latest_period_from_source_status(tmp_path: Path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"data_available": "Jan 2018 to Jun 2026"}), encoding="utf-8")
    assert latest_period_from_status(path) == "2026-06"


def test_review_mapping_is_skipped():
    ok, reason = is_queryable_commodity(
        {"mapping_status": "version_sensitive_needs_hs8_review", "hs_codes": ["85414200"]}
    )
    assert not ok
    assert "review" in reason


def test_quantity_accepts_only_hs8():
    ok, reason = is_queryable_commodity(
        {"mapping_status": "hs8_validated", "hs_codes": ["28252000", "28369100"]},
        value_type="quantity",
    )
    assert ok
    assert reason is None

    ok, reason = is_queryable_commodity(
        {"mapping_status": "heading_validated", "hs_codes": ["2709"]},
        value_type="quantity",
    )
    assert not ok
    assert "HS8" in reason


def test_solar_classification_eras_do_not_stitch_transition_month():
    solar = {
        "hs_codes": ["85414200", "85414300"],
        "classification_transition_periods": ["2022-02"],
        "classification_eras": [
            {"from": "2018-01", "through": "2022-01", "hs_codes": ["85414011", "85414012"]},
            {"from": "2022-03", "through": None, "hs_codes": ["85414200", "85414300"]},
        ],
    }

    old_codes, _ = hs_codes_for_period(solar, "2022-01")
    transition_codes, transition_note = hs_codes_for_period(solar, "2022-02")
    new_codes, _ = hs_codes_for_period(solar, "2022-03")

    assert old_codes == ["85414011", "85414012"]
    assert transition_codes == []
    assert "transition" in transition_note
    assert new_codes == ["85414200", "85414300"]


class _QuantityClient:
    def fetch_commodity_all_countries(self, **kwargs):
        return {
            "period": f"{kwargs['year']:04d}-{kwargs['month']:02d}",
            "trade_type": kwargs["trade_type"],
            "hs_code": kwargs["hscode"],
            "value_type": kwargs["value_type"],
            "value_selector_code": "2",
            "source_quantity_unit": "KGS",
            "rows": [],
            "totals": {"value": 12.5},
        }


def test_quantity_ingestion_persists_direct_unit_scale_metadata():
    commodity = {
        "id": "lithium",
        "name": "Lithium & Compounds",
        "category": "Strategic Minerals",
        "priority": "critical",
        "hs_codes": ["28252000"],
        "mapping_status": "hs8_validated",
    }

    doc = ingest_one(
        _QuantityClient(),
        commodity,
        period="2026-06",
        hs_codes=["28252000"],
        value_type="quantity",
        year_type="calendar",
        trade_types=["import"],
    )

    assert doc["quantity_scale_to_source_unit"] == QUANTITY_SCALE_TO_SOURCE_UNIT == 1
    assert "already expressed" in doc["quantity_scale_note"]
    assert doc["reports"][0]["quantity_scale_to_source_unit"] == 1
    assert "already expressed" in doc["reports"][0]["quantity_scale_note"]
