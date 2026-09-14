import json
from pathlib import Path

from scripts.ingest_tradestat import is_queryable_commodity, latest_period_from_status


def test_latest_period_from_source_status(tmp_path: Path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"data_available": "Jan 2018 to Jun 2026"}), encoding="utf-8")
    assert latest_period_from_status(path) == "2026-06"


def test_review_mapping_is_skipped():
    ok, reason = is_queryable_commodity({"mapping_status": "version_sensitive_needs_hs8_review", "hs_codes": ["85414"]})
    assert not ok
    assert "review" in reason
