import json
from pathlib import Path

import pytest

from scripts.backfill_tradestat import (
    default_span_limit,
    iter_periods,
    month_span,
    observation_is_current,
    select_commodities,
)


def _write(path: Path, doc: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _observation(*, value_type="usd", selector="1", scale=None, hs_codes=None, trade_types=None):
    hs_codes = hs_codes or ["28252000"]
    trade_types = trade_types or ["import", "export"]
    reports = []
    for code in hs_codes:
        for trade_type in trade_types:
            report = {
                "trade_type": trade_type,
                "hs_code": code,
                "value_type": value_type,
                "value_selector_code": selector,
                "totals": {"value": 1.0},
            }
            if value_type == "quantity":
                report["quantity_scale_to_source_unit"] = scale
            reports.append(report)
    return {
        "period": "2026-06",
        "value_type": value_type,
        "quantity_scale_to_source_unit": scale if value_type == "quantity" else None,
        "status": "ok",
        "commodity": {"hs_codes": hs_codes},
        "reports": reports,
    }


def test_iter_periods_crosses_year_boundary():
    assert list(iter_periods("2025-11", "2026-02")) == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert month_span("2025-11", "2026-02") == 4


def test_invalid_or_reverse_range_is_rejected():
    with pytest.raises(ValueError):
        month_span("2026-13", "2026-14")
    with pytest.raises(ValueError):
        month_span("2026-06", "2026-05")
    with pytest.raises(ValueError):
        month_span("2017-12", "2018-01")


def test_span_limits_keep_all_usd_batches_small():
    assert default_span_limit(selected_all=True, value_type="usd") == 12
    assert default_span_limit(selected_all=False, value_type="usd") == 36
    assert default_span_limit(selected_all=True, value_type="quantity") == 36


def test_select_commodities_validates_ids():
    master = {"commodities": [{"id": "lithium"}, {"id": "solar_pv"}]}
    selected, is_all = select_commodities(master, ["lithium"])
    assert [item["id"] for item in selected] == ["lithium"]
    assert not is_all
    all_items, is_all = select_commodities(master, None)
    assert len(all_items) == 2 and is_all
    with pytest.raises(ValueError):
        select_commodities(master, ["missing"])


def test_current_usd_observation_is_skipped_even_with_legacy_missing_selector(tmp_path: Path):
    path = tmp_path / "lithium.usd.json"
    doc = _observation(value_type="usd")
    for report in doc["reports"]:
        report.pop("value_selector_code")
    _write(path, doc)

    current, reason = observation_is_current(
        path,
        period="2026-06",
        value_type="usd",
        active_hs_codes=["28252000"],
        trade_types=["import", "export"],
    )
    assert current
    assert reason == "current"


def test_quantity_requires_verified_selector_and_direct_scale(tmp_path: Path):
    path = tmp_path / "lithium.quantity.json"
    _write(path, _observation(value_type="quantity", selector="2", scale=1))
    current, _ = observation_is_current(
        path,
        period="2026-06",
        value_type="quantity",
        active_hs_codes=["28252000"],
        trade_types=["import", "export"],
    )
    assert current

    _write(path, _observation(value_type="quantity", selector="3", scale=1))
    current, reason = observation_is_current(
        path,
        period="2026-06",
        value_type="quantity",
        active_hs_codes=["28252000"],
        trade_types=["import", "export"],
    )
    assert not current and reason == "quantity_selector_stale"

    _write(path, _observation(value_type="quantity", selector="2", scale=1000))
    current, reason = observation_is_current(
        path,
        period="2026-06",
        value_type="quantity",
        active_hs_codes=["28252000"],
        trade_types=["import", "export"],
    )
    assert not current and reason == "quantity_scale_stale"


def test_mapping_and_trade_coverage_changes_force_refresh(tmp_path: Path):
    path = tmp_path / "lithium.usd.json"
    _write(path, _observation(value_type="usd", hs_codes=["28252000"], trade_types=["import"]))

    current, reason = observation_is_current(
        path,
        period="2026-06",
        value_type="usd",
        active_hs_codes=["28252000"],
        trade_types=["import", "export"],
    )
    assert not current and reason == "report_coverage_incomplete"

    current, reason = observation_is_current(
        path,
        period="2026-06",
        value_type="usd",
        active_hs_codes=["28252000", "28369100"],
        trade_types=["import"],
    )
    assert not current and reason == "period_mapping_changed"
