import json
from pathlib import Path

import pytest

from src.tracker.revisions import build_revision_summary, compare_observations


def _doc(*, period="2026-06", imports=10.0, exports=2.0, retrieved_at="2026-08-13T10:00:00+00:00"):
    return {
        "schema_version": 3,
        "period": period,
        "value_type": "usd",
        "commodity": {"id": "crude_oil", "name": "Crude Oil"},
        "status": "ok",
        "metrics": {
            "imports": imports,
            "exports": exports,
            "balance": exports - imports,
        },
        "reports": [
            {
                "trade_type": "import",
                "hs_code": "2709",
                "totals": {"value": imports},
                "rows": [
                    {"partner_country": "A", "value": 6.0 if imports == 10.0 else 7.0},
                    *(
                        [{"partner_country": "B", "value": 4.0}]
                        if imports == 10.0
                        else [{"partner_country": "C", "value": imports - 7.0}]
                    ),
                ],
                "source": {"report_date": "13 August 2026", "retrieved_at": retrieved_at},
            },
            {
                "trade_type": "export",
                "hs_code": "2709",
                "totals": {"value": exports},
                "rows": [{"partner_country": "X", "value": exports}],
                "source": {"report_date": "13 August 2026", "retrieved_at": retrieved_at},
            },
        ],
    }


def test_compare_observations_quantifies_metrics_reports_and_partners():
    previous = _doc(imports=10.0, exports=2.0)
    current = _doc(imports=12.0, exports=1.0, retrieved_at="2026-09-14T10:00:00+00:00")

    summary = compare_observations(previous, current)

    assert summary["metric_deltas"]["imports"] == {
        "previous": 10.0,
        "current": 12.0,
        "change": 2.0,
        "change_pct": 20.0,
    }
    assert summary["metric_deltas"]["exports"]["change"] == -1.0
    assert summary["metric_deltas"]["balance"]["change"] == -3.0
    assert summary["changed_report_count"] == 2

    import_change = next(item for item in summary["report_deltas"] if item["trade_type"] == "import")
    assert import_change["total"]["change"] == 2.0
    assert import_change["changed_partner_count"] == 3
    assert import_change["added_partner_count"] == 1
    assert import_change["removed_partner_count"] == 1
    assert import_change["changed_partners"] == ["A", "B", "C"]


def test_compare_observations_rejects_unrelated_documents():
    with pytest.raises(ValueError):
        compare_observations(_doc(period="2026-05"), _doc(period="2026-06"))


def test_build_revision_summary_pairs_archives_with_current(tmp_path: Path):
    observations = tmp_path / "observations"
    revisions = tmp_path / "revisions"
    current_path = observations / "2026-06" / "crude_oil.usd.json"
    archive_path = revisions / "2026-06" / "crude_oil.usd" / "old.json"
    current_path.parent.mkdir(parents=True)
    archive_path.parent.mkdir(parents=True)

    previous = _doc(imports=10.0, exports=2.0)
    current = _doc(imports=12.0, exports=1.0, retrieved_at="2026-09-14T10:00:00+00:00")
    archive_path.write_text(json.dumps(previous), encoding="utf-8")
    current_path.write_text(json.dumps(current), encoding="utf-8")

    summary = build_revision_summary(observations, revisions)

    assert summary["revision_group_count"] == 1
    entry = summary["entries"][0]
    assert entry["period"] == "2026-06"
    assert entry["commodity_id"] == "crude_oil"
    assert entry["version_count"] == 2
    assert entry["archived_version_count"] == 1
    assert len(entry["changes"]) == 1
    assert entry["changes"][0]["metric_deltas"]["imports"]["change"] == 2.0


def test_build_revision_summary_is_stable_when_no_revisions_exist(tmp_path: Path):
    summary = build_revision_summary(tmp_path / "observations", tmp_path / "revisions")
    assert summary == {"schema_version": 1, "revision_group_count": 0, "entries": []}
