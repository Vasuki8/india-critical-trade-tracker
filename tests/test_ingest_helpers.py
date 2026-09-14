import json
from copy import deepcopy
from pathlib import Path

from scripts.ingest_tradestat import (
    QUANTITY_SCALE_TO_SOURCE_UNIT,
    hs_codes_for_period,
    ingest_one,
    is_queryable_commodity,
    latest_period_from_status,
    observation_fingerprint,
    write_observation,
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


def test_quantity_requires_explicit_mapping_contract():
    ok, reason = is_queryable_commodity(
        {"mapping_status": "hs8_validated", "hs_codes": ["28252000", "28369100"]},
        value_type="quantity",
    )
    assert not ok
    assert "explicitly enabled" in reason


def test_quantity_accepts_only_explicit_hs8_mapping():
    ok, reason = is_queryable_commodity(
        {
            "mapping_status": "hs8_validated",
            "hs_codes": ["28252000", "28369100"],
            "quantity_mapping": {
                "enabled": True,
                "mode": "same_as_value",
                "mapping_status": "hs8_validated",
            },
        },
        value_type="quantity",
        hs_codes=["28252000", "28369100"],
    )
    assert ok
    assert reason is None

    ok, reason = is_queryable_commodity(
        {
            "mapping_status": "heading_validated",
            "hs_codes": ["2709"],
            "quantity_mapping": {
                "enabled": True,
                "mode": "same_as_value",
                "mapping_status": "hs8_validated",
            },
        },
        value_type="quantity",
        hs_codes=["2709"],
    )
    assert not ok
    assert "HS8" in reason


def test_separate_quantity_mapping_does_not_change_value_mapping():
    rare_earths = {
        "mapping_status": "heading_validated",
        "hs_codes": ["2846"],
        "quantity_mapping": {
            "enabled": True,
            "mode": "separate",
            "mapping_status": "hs8_validated",
            "hs_codes": [
                "28461010",
                "28461090",
                "28469010",
                "28469020",
                "28469030",
                "28469090",
            ],
        },
    }

    usd_codes, _ = hs_codes_for_period(rare_earths, "2026-06", value_type="usd")
    quantity_codes, _ = hs_codes_for_period(rare_earths, "2026-06", value_type="quantity")

    assert usd_codes == ["2846"]
    assert quantity_codes == [
        "28461010",
        "28461090",
        "28469010",
        "28469020",
        "28469030",
        "28469090",
    ]


def test_solar_classification_eras_do_not_stitch_transition_month():
    solar = {
        "hs_codes": ["85414200", "85414300"],
        "mapping_status": "hs8_validated",
        "quantity_mapping": {
            "enabled": True,
            "mode": "same_as_value",
            "mapping_status": "hs8_validated",
        },
        "classification_transition_periods": ["2022-02"],
        "classification_eras": [
            {"from": "2018-01", "through": "2022-01", "hs_codes": ["85414011", "85414012"]},
            {"from": "2022-03", "through": None, "hs_codes": ["85414200", "85414300"]},
        ],
    }

    old_codes, _ = hs_codes_for_period(solar, "2022-01", value_type="quantity")
    transition_codes, transition_note = hs_codes_for_period(solar, "2022-02", value_type="quantity")
    new_codes, _ = hs_codes_for_period(solar, "2022-03", value_type="quantity")

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
        "quantity_mapping": {
            "enabled": True,
            "mode": "same_as_value",
            "mapping_status": "hs8_validated",
        },
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
    assert doc["commodity"]["mapping_status"] == "hs8_validated"
    assert doc["commodity"]["quantity_mapping_mode"] == "same_as_value"


def _revision_doc(*, value: float = 10.0, retrieved_at: str = "2026-09-14T10:00:00+00:00") -> dict:
    return {
        "schema_version": 3,
        "period": "2026-06",
        "value_type": "usd",
        "year_type": "calendar",
        "commodity": {
            "id": "crude_oil",
            "name": "Crude Oil",
            "category": "Energy",
            "priority": "critical",
            "hs_codes": ["2709"],
            "canonical_hs_codes": ["2709"],
            "mapping_status": "heading_validated",
            "classification_note": None,
        },
        "status": "ok",
        "reports": [
            {
                "period": "2026-06",
                "trade_type": "import",
                "hs_code": "2709",
                "value_type": "usd",
                "headers": ["S.No.", "Country", "Jun-2025 (R)", "Jun-2026 (F)"],
                "rows": [{"partner_country": "TESTLAND", "value": value}],
                "totals": {"value": value},
                "source": {
                    "report_date": "13 August 2026",
                    "retrieved_at": retrieved_at,
                    "checksum_sha256": f"checksum-{value}",
                },
            }
        ],
        "metrics": {"imports": value},
        "failures": [],
    }


def test_observation_fingerprint_ignores_retrieval_timestamp():
    original = _revision_doc(retrieved_at="2026-09-14T10:00:00+00:00")
    refetched = _revision_doc(retrieved_at="2026-09-15T10:00:00+00:00")
    assert observation_fingerprint(original) == observation_fingerprint(refetched)


def test_timestamp_only_refetch_does_not_rewrite_or_archive(tmp_path: Path):
    observation_root = tmp_path / "observations"
    revision_root = tmp_path / "revisions"
    original = _revision_doc(retrieved_at="2026-09-14T10:00:00+00:00")
    refetched = _revision_doc(retrieved_at="2026-09-15T10:00:00+00:00")

    path = write_observation(original, observation_root=observation_root, revision_root=revision_root)
    before = path.read_text(encoding="utf-8")
    write_observation(refetched, observation_root=observation_root, revision_root=revision_root)

    assert path.read_text(encoding="utf-8") == before
    assert not revision_root.exists()


def test_semantic_change_archives_previous_observation(tmp_path: Path):
    observation_root = tmp_path / "observations"
    revision_root = tmp_path / "revisions"
    original = _revision_doc(value=10.0)
    revised = deepcopy(original)
    revised["reports"][0]["rows"][0]["value"] = 12.0
    revised["reports"][0]["totals"]["value"] = 12.0
    revised["reports"][0]["source"]["checksum_sha256"] = "checksum-12.0"
    revised["metrics"]["imports"] = 12.0

    path = write_observation(original, observation_root=observation_root, revision_root=revision_root)
    previous_fingerprint = observation_fingerprint(original)
    write_observation(revised, observation_root=observation_root, revision_root=revision_root)

    archive = revision_root / "2026-06" / "crude_oil.usd" / f"{previous_fingerprint}.json"
    assert archive.exists()
    assert json.loads(archive.read_text(encoding="utf-8")) == original
    assert json.loads(path.read_text(encoding="utf-8")) == revised


def test_existing_revision_archive_is_not_duplicated(tmp_path: Path):
    observation_root = tmp_path / "observations"
    revision_root = tmp_path / "revisions"
    original = _revision_doc(value=10.0)
    revised = _revision_doc(value=12.0)

    path = write_observation(original, observation_root=observation_root, revision_root=revision_root)
    write_observation(revised, observation_root=observation_root, revision_root=revision_root)
    write_observation(original, observation_root=observation_root, revision_root=revision_root)
    write_observation(revised, observation_root=observation_root, revision_root=revision_root)

    archive_dir = revision_root / "2026-06" / "crude_oil.usd"
    archives = sorted(archive_dir.glob("*.json"))
    assert len(archives) == 2
    assert json.loads(path.read_text(encoding="utf-8")) == revised
