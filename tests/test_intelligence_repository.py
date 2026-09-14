import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_generated_intelligence_matches_dashboard_history():
    dashboard = _load(ROOT / "data" / "dashboard.json")
    intelligence_root = ROOT / "data" / "intelligence"
    index = _load(intelligence_root / "index.json")

    expected_ids = sorted(dashboard.get("commodity_history", {}))
    assert index["commodities"] == expected_ids
    assert index["commodity_count"] == len(expected_ids)

    for commodity_id in expected_ids:
        doc = _load(intelligence_root / f"{commodity_id}.json")
        assert doc["commodity"]["id"] == commodity_id
        periods = [row["period"] for row in doc["monthly"]]
        dashboard_periods = [row["period"] for row in dashboard["commodity_history"][commodity_id]]
        assert periods == dashboard_periods
        assert periods == sorted(set(periods))
        assert doc["coverage"]["first_period"] == periods[0]
        assert doc["coverage"]["last_period"] == periods[-1]
        assert doc["coverage"]["months_observed"] == len(periods)
        assert doc["latest"]["period"] == periods[-1]

        expected_gaps = dashboard.get("history_gaps", {}).get(commodity_id, [])
        assert doc["coverage"]["history_gaps"] == expected_gaps

        annual_month_count = sum(row["months_observed"] for row in doc["annual"])
        assert annual_month_count == len(periods)
        for row in doc["annual"]:
            assert row["coverage_status"] == ("complete" if row["months_observed"] == 12 else "partial")
