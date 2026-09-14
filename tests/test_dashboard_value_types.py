import json
from pathlib import Path

from src.tracker.dashboard import _is_usd_observation, build_dashboard


def _report(*, trade_type="import", hs_code="28252000", value=2.5, value_type="usd", unit=None, selector=None):
    if selector is None:
        selector = "2" if value_type == "quantity" else "1"
    return {
        "trade_type": trade_type,
        "hs_code": hs_code,
        "value_type": value_type,
        "value_selector_code": selector,
        "source_quantity_unit": unit,
        "rows": [],
        "totals": {"value": value},
    }


def _doc(*, period, value_type, value, unit=None, selector=None):
    reports = [_report(value=value, value_type=value_type, unit=unit, selector=selector)]
    metrics = {}
    if value_type == "usd":
        metrics = {
            "imports": value,
            "exports": 0.0,
            "balance": -value,
            "unit": "USD million",
            "dependency": {"score": 60.0, "risk": "moderate"},
        }
    return {
        "schema_version": 3,
        "period": period,
        "value_type": value_type,
        "quantity_scale_to_source_unit": 1 if value_type == "quantity" else None,
        "commodity": {
            "id": "lithium",
            "name": "Lithium & Compounds",
            "category": "Strategic Minerals",
            "priority": "critical",
            "hs_codes": ["28252000"],
            "mapping_status": "hs8_validated",
        },
        "status": "ok",
        "reports": reports,
        "metrics": metrics,
        "failures": [],
    }


def _write(root: Path, doc: dict, filename: str):
    period_dir = root / doc["period"]
    period_dir.mkdir(parents=True, exist_ok=True)
    (period_dir / filename).write_text(json.dumps(doc), encoding="utf-8")


def test_explicit_usd_observation_is_included():
    assert _is_usd_observation({"value_type": "usd", "reports": []})


def test_quantity_observation_is_excluded():
    assert not _is_usd_observation({"value_type": "quantity", "reports": []})


def test_legacy_usd_observation_remains_supported():
    doc = {"reports": [{"value_type": "usd"}, {"value_type": "usd"}]}
    assert _is_usd_observation(doc)


def test_legacy_quantity_observation_is_excluded():
    doc = {"reports": [{"value_type": "quantity"}]}
    assert not _is_usd_observation(doc)


def test_quantity_only_newer_month_does_not_advance_dashboard_as_of(tmp_path: Path):
    observations = tmp_path / "observations"
    _write(observations, _doc(period="2026-06", value_type="usd", value=2.5), "lithium.usd.json")
    _write(
        observations,
        _doc(period="2026-07", value_type="quantity", value=500_000, unit="KGS"),
        "lithium.quantity.json",
    )

    dashboard = build_dashboard(observations, tmp_path / "dashboard.json")

    assert dashboard["as_of"] == "2026-06"
    assert [row["period"] for row in dashboard["monthly"]] == ["2026-06"]


def test_same_month_quantity_adds_implied_unit_value_from_direct_units(tmp_path: Path):
    observations = tmp_path / "observations"
    _write(observations, _doc(period="2026-06", value_type="usd", value=2.5), "lithium.usd.json")
    # MEIDB quantity is already expressed directly in KGS.
    _write(
        observations,
        _doc(period="2026-06", value_type="quantity", value=500_000, unit="KGS"),
        "lithium.quantity.json",
    )

    dashboard = build_dashboard(observations, tmp_path / "dashboard.json")
    unit_values = dashboard["commodities"][0]["unit_values"]

    assert dashboard["schema_version"] == 3
    assert unit_values["aggregate"]["import"]["quantity"] == 500_000
    assert unit_values["aggregate"]["import"]["raw_quantity_source_units"] == 500_000
    assert unit_values["aggregate"]["import"]["unit_value_usd_per_source_unit"] == 5.0
    assert dashboard["commodity_history"]["lithium"][0]["unit_values"]["import"]["quantity_unit"] == "KGS"


def test_unverified_quantity_selector_is_not_used_for_unit_value(tmp_path: Path):
    observations = tmp_path / "observations"
    _write(observations, _doc(period="2026-06", value_type="usd", value=2.5), "lithium.usd.json")
    _write(
        observations,
        _doc(period="2026-06", value_type="quantity", value=500_000, unit="KGS", selector="3"),
        "lithium.quantity.json",
    )

    dashboard = build_dashboard(observations, tmp_path / "dashboard.json")
    unit_values = dashboard["commodities"][0]["unit_values"]

    assert unit_values["status"] == "not_available"
    assert unit_values["aggregate"]["import"]["unit_value_usd_per_source_unit"] is None
    assert unit_values["by_hs_code"][0]["status"] == "unverified_quantity_selector"


def test_explicit_usd_file_wins_over_legacy_duplicate(tmp_path: Path):
    observations = tmp_path / "observations"
    legacy = _doc(period="2026-06", value_type="usd", value=1.0)
    legacy.pop("value_type")
    explicit = _doc(period="2026-06", value_type="usd", value=2.5)
    _write(observations, legacy, "lithium.json")
    _write(observations, explicit, "lithium.usd.json")

    dashboard = build_dashboard(observations, tmp_path / "dashboard.json")

    assert len(dashboard["commodities"]) == 1
    assert dashboard["summary"]["imports"] == 2.5
