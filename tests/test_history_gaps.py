import json
from pathlib import Path

from src.tracker.dashboard import build_dashboard


def _doc(period: str, commodity_id: str, value: float) -> dict:
    return {
        "schema_version": 3,
        "period": period,
        "value_type": "usd",
        "commodity": {
            "id": commodity_id,
            "name": commodity_id,
            "category": "test",
            "priority": "critical",
            "hs_codes": ["2709" if commodity_id == "crude_oil" else "85414200"],
            "mapping_status": "hs8_validated" if commodity_id == "solar_pv" else "heading_validated",
        },
        "status": "ok",
        "reports": [
            {
                "trade_type": "import",
                "hs_code": "2709" if commodity_id == "crude_oil" else "85414200",
                "value_type": "usd",
                "rows": [],
                "totals": {"value": value},
            }
        ],
        "metrics": {},
    }


def _write_observation(root: Path, doc: dict) -> None:
    period_dir = root / doc["period"]
    period_dir.mkdir(parents=True, exist_ok=True)
    commodity_id = doc["commodity"]["id"]
    (period_dir / f"{commodity_id}.usd.json").write_text(json.dumps(doc), encoding="utf-8")


def test_dashboard_marks_transition_month_as_partial_coverage(tmp_path: Path):
    observations = tmp_path / "observations"
    for period in ("2022-01", "2022-02", "2022-03"):
        _write_observation(observations, _doc(period, "crude_oil", 10.0))
    _write_observation(observations, _doc("2022-01", "solar_pv", 2.0))
    _write_observation(observations, _doc("2022-03", "solar_pv", 3.0))

    master = {
        "commodities": [
            {"id": "crude_oil"},
            {
                "id": "solar_pv",
                "classification_transition_periods": ["2022-02"],
            },
        ]
    }
    master_path = tmp_path / "commodities.json"
    master_path.write_text(json.dumps(master), encoding="utf-8")

    dashboard = build_dashboard(observations, tmp_path / "dashboard.json", master_path)
    monthly = {row["period"]: row for row in dashboard["monthly"]}

    assert monthly["2022-01"]["coverage_status"] == "complete"
    assert monthly["2022-02"]["coverage_status"] == "partial"
    assert monthly["2022-02"]["observed_commodity_count"] == 1
    assert monthly["2022-02"]["expected_commodity_count"] == 2
    assert monthly["2022-02"]["missing_commodities"] == ["solar_pv"]
    assert monthly["2022-03"]["coverage_status"] == "complete"

    assert [point["period"] for point in dashboard["commodity_history"]["solar_pv"]] == ["2022-01", "2022-03"]
    assert dashboard["history_gaps"]["solar_pv"] == [
        {
            "period": "2022-02",
            "reason": "classification_transition",
            "note": "Historical mapping intentionally omitted for this classification transition month; do not interpret the missing observation as zero trade.",
        }
    ]
