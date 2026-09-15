import json
from pathlib import Path

from src.tracker.quantity_coverage import validate_quantity_history


def _commodity(*, transition: bool = False) -> dict:
    item = {
        "id": "sample",
        "name": "Sample",
        "category": "Test",
        "priority": "critical",
        "hs_codes": ["12345678"],
        "mapping_status": "hs8_validated",
        "quantity_mapping": {
            "enabled": True,
            "mode": "same_as_value",
            "mapping_status": "hs8_validated",
            "history_complete_from": "2018-01",
        },
    }
    if transition:
        item["classification_transition_periods"] = ["2018-02"]
        item["classification_eras"] = [
            {"from": "2018-01", "through": "2018-01", "hs_codes": ["87654321"]},
            {"from": "2018-03", "through": None, "hs_codes": ["12345678"]},
        ]
    return item


def _dashboard(*periods: str) -> dict:
    return {
        "as_of": periods[-1],
        "monthly": [{"period": period} for period in periods],
    }


def _observation(period: str, code: str, *, selector: str = "2") -> dict:
    reports = []
    for trade_type in ("import", "export"):
        reports.append(
            {
                "period": period,
                "trade_type": trade_type,
                "hs_code": code,
                "value_type": "quantity",
                "value_selector_code": selector,
                "quantity_scale_to_source_unit": 1,
                "totals": {"value": 1},
            }
        )
    return {
        "period": period,
        "value_type": "quantity",
        "quantity_scale_to_source_unit": 1,
        "commodity": {"id": "sample", "hs_codes": [code]},
        "status": "ok",
        "reports": reports,
    }


def _write(root: Path, period: str, doc: dict) -> None:
    period_dir = root / period
    period_dir.mkdir(parents=True, exist_ok=True)
    (period_dir / "sample.quantity.json").write_text(json.dumps(doc), encoding="utf-8")


def test_declared_quantity_history_requires_every_period(tmp_path: Path):
    master = {"commodities": [_commodity()]}
    dashboard = _dashboard("2018-01", "2018-02")
    _write(tmp_path, "2018-01", _observation("2018-01", "12345678"))

    errors = validate_quantity_history(master, dashboard, tmp_path)

    assert len(errors) == 1
    assert "missing 1 declared-complete observation" in errors[0]
    assert "2018-02" in errors[0]


def test_declared_quantity_history_accepts_complete_current_files(tmp_path: Path):
    master = {"commodities": [_commodity()]}
    dashboard = _dashboard("2018-01", "2018-02")
    for period in ("2018-01", "2018-02"):
        _write(tmp_path, period, _observation(period, "12345678"))

    assert validate_quantity_history(master, dashboard, tmp_path) == []


def test_quantity_history_skips_explicit_classification_transition(tmp_path: Path):
    master = {"commodities": [_commodity(transition=True)]}
    dashboard = _dashboard("2018-01", "2018-02", "2018-03")
    _write(tmp_path, "2018-01", _observation("2018-01", "87654321"))
    _write(tmp_path, "2018-03", _observation("2018-03", "12345678"))

    assert validate_quantity_history(master, dashboard, tmp_path) == []


def test_quantity_history_rejects_stale_selector(tmp_path: Path):
    master = {"commodities": [_commodity()]}
    dashboard = _dashboard("2018-01")
    _write(tmp_path, "2018-01", _observation("2018-01", "12345678", selector="1"))

    errors = validate_quantity_history(master, dashboard, tmp_path)

    assert len(errors) == 1
    assert "stale or invalid" in errors[0]
    assert "selector" in errors[0]


def test_enabled_mapping_without_completeness_declaration_is_not_forced(tmp_path: Path):
    item = _commodity()
    del item["quantity_mapping"]["history_complete_from"]
    master = {"commodities": [item]}
    dashboard = _dashboard("2018-01")

    assert validate_quantity_history(master, dashboard, tmp_path) == []
