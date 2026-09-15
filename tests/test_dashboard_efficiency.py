import json

import src.tracker.dashboard as dashboard_module


def _observation(value_type: str):
    return {
        "schema_version": 3,
        "period": "2026-06",
        "value_type": value_type,
        "commodity": {
            "id": "demo",
            "name": "Demo Commodity",
            "category": "Test",
            "hs_codes": ["1234"],
            "mapping_status": "heading_validated",
        },
        "status": "ok",
        "reports": [],
        "metrics": {
            "imports": 1.0,
            "exports": 0.5,
            "balance": -0.5,
            "dependency": {"score": 50.0, "risk": "moderate"},
        },
    }


def _unit_values():
    unavailable = {
        "status": "not_available",
        "usd_million": None,
        "raw_quantity_source_units": None,
        "quantity": None,
        "quantity_unit": None,
        "unit_value_usd_per_source_unit": None,
    }
    return {
        "status": "not_available",
        "aggregate": {"import": dict(unavailable), "export": dict(unavailable)},
        "by_hs_code": [],
    }


def test_dashboard_derives_unit_values_once_per_commodity_period(tmp_path, monkeypatch):
    observations = tmp_path / "observations"
    period_dir = observations / "2026-06"
    period_dir.mkdir(parents=True)
    (period_dir / "demo.usd.json").write_text(json.dumps(_observation("usd")), encoding="utf-8")
    (period_dir / "demo.quantity.json").write_text(json.dumps(_observation("quantity")), encoding="utf-8")

    calls = 0

    def fake_derive(usd_doc, quantity_doc):
        nonlocal calls
        calls += 1
        assert usd_doc["value_type"] == "usd"
        assert quantity_doc["value_type"] == "quantity"
        return _unit_values()

    monkeypatch.setattr(dashboard_module, "derive_unit_values", fake_derive)
    out_path = tmp_path / "dashboard.json"

    doc = dashboard_module.build_dashboard(observations, out_path)

    assert calls == 1
    assert doc["as_of"] == "2026-06"
    assert doc["commodities"][0]["unit_values"]["status"] == "not_available"
    assert doc["commodity_history"]["demo"][0]["unit_values"] == _unit_values()["aggregate"]


def test_dashboard_json_is_compact_and_round_trips(tmp_path):
    observations = tmp_path / "observations"
    observations.mkdir()
    out_path = tmp_path / "dashboard.json"

    doc = dashboard_module.build_dashboard(observations, out_path)
    text = out_path.read_text(encoding="utf-8")

    assert text.endswith("\n")
    assert "\n  \"" not in text
    assert json.loads(text) == doc
