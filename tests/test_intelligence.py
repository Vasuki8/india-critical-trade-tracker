import json
from pathlib import Path

from src.tracker.intelligence import build_all_commodity_intelligence, build_commodity_intelligence


def _observation(period: str, *, imports: float, exports: float) -> dict:
    return {
        "schema_version": 3,
        "period": period,
        "value_type": "usd",
        "status": "ok",
        "commodity": {
            "id": "crude_oil",
            "name": "Crude Oil",
            "category": "Energy",
            "hs_codes": ["2709"],
            "mapping_status": "validated",
        },
        "reports": [
            {
                "trade_type": "import",
                "hs_code": "2709",
                "description": "Crude petroleum",
                "totals": {"value": imports},
                "rows": [
                    {"partner_country": "A", "value": imports * 0.75},
                    {"partner_country": "B", "value": imports * 0.25},
                ],
            },
            {
                "trade_type": "export",
                "hs_code": "2709",
                "description": "Crude petroleum",
                "totals": {"value": exports},
                "rows": [
                    {"partner_country": "C", "value": exports},
                ],
            },
        ],
    }


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_commodity_intelligence_exposes_month_country_and_annual_views(tmp_path: Path):
    observations = tmp_path / "observations"
    _write(observations / "2025-01" / "crude_oil.usd.json", _observation("2025-01", imports=100, exports=10))
    _write(observations / "2025-02" / "crude_oil.usd.json", _observation("2025-02", imports=120, exports=20))

    commodity = {
        "id": "crude_oil",
        "name": "Crude Oil",
        "category": "Energy",
        "hs_codes": ["2709"],
        "mapping_status": "validated",
    }
    doc = build_commodity_intelligence(observations, commodity)

    assert doc is not None
    assert doc["schema_version"] == 2
    assert doc["coverage"]["first_period"] == "2025-01"
    assert doc["coverage"]["last_period"] == "2025-02"
    assert doc["coverage"]["months_observed"] == 2
    assert doc["monthly"][0]["imports_by_country"][0] == {
        "partner_country": "A",
        "value": 75.0,
    }
    assert "import_hs_breakdown" not in doc["monthly"][0]
    assert "export_hs_breakdown" not in doc["monthly"][0]
    assert doc["annual"][0]["imports"] == 220.0
    assert doc["annual"][0]["exports"] == 30.0
    assert doc["annual"][0]["balance"] == -190.0
    assert doc["annual"][0]["months_observed"] == 2
    assert doc["annual"][0]["coverage_status"] == "partial"
    assert doc["annual"][0]["supplier_concentration"]["top_partners"][0]["partner_country"] == "A"


def test_commodity_intelligence_preserves_classification_transition_gap(tmp_path: Path):
    observations = tmp_path / "observations"
    _write(observations / "2022-01" / "crude_oil.usd.json", _observation("2022-01", imports=10, exports=1))
    _write(observations / "2022-03" / "crude_oil.usd.json", _observation("2022-03", imports=12, exports=2))

    commodity = {
        "id": "crude_oil",
        "name": "Crude Oil",
        "category": "Energy",
        "hs_codes": ["2709"],
        "mapping_status": "validated",
        "classification_transition_periods": ["2022-02"],
    }
    doc = build_commodity_intelligence(observations, commodity)

    assert doc is not None
    assert doc["coverage"]["history_gaps"] == [
        {
            "period": "2022-02",
            "reason": "classification_transition",
            "note": "Historical mapping intentionally omitted for this classification transition month; do not interpret the missing observation as zero trade.",
        }
    ]


def test_build_all_writes_compact_lazy_load_file_per_commodity(tmp_path: Path):
    observations = tmp_path / "observations"
    _write(observations / "2025-01" / "crude_oil.usd.json", _observation("2025-01", imports=100, exports=10))
    master = tmp_path / "commodities.json"
    master.write_text(
        json.dumps(
            {
                "commodities": [
                    {
                        "id": "crude_oil",
                        "name": "Crude Oil",
                        "category": "Energy",
                        "hs_codes": ["2709"],
                        "mapping_status": "validated",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "intelligence"

    summary = build_all_commodity_intelligence(observations, master, output)

    assert summary["schema_version"] == 2
    assert summary["commodity_count"] == 1
    assert summary["commodities"] == ["crude_oil"]
    rendered = (output / "crude_oil.json").read_text(encoding="utf-8")
    assert "\n  \"" not in rendered
    saved = json.loads(rendered)
    assert saved["commodity"]["name"] == "Crude Oil"
    assert saved["monthly"][0]["imports"] == 100.0
