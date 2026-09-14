from pathlib import Path

import pytest

from src.tracker.tradestat import (
    build_payload,
    parse_commodity_all_countries,
    parse_csrf_token,
    validate_query,
)

FIXTURE = Path(__file__).parent / "fixtures" / "meidb_all_countries_sample.html"
HTML = FIXTURE.read_text(encoding="utf-8")


def test_csrf_token():
    assert parse_csrf_token(HTML) == "abc123"


def test_import_payload_uses_current_meidb_contract():
    payload = build_payload(
        trade_type="import", token="t", hscode="2709", month=6, year=2026,
        value_type="usd", year_type="calendar",
    )
    assert payload["cwacimHSCODE"] == "2709"
    assert payload["cwacimMonth"] == "6"
    assert payload["cwacimReportVal"] == "1"
    assert payload["cwacimReportYear"] == "2"


def test_export_payload_uses_current_meidb_contract():
    payload = build_payload(
        trade_type="export", token="t", hscode="2709", month=6, year=2026,
        value_type="usd", year_type="calendar",
    )
    assert payload["cwacexHSCODE"] == "2709"
    assert payload["cwacexMonth"] == "6"


def test_parser_extracts_month_value_and_partner_rows():
    doc = parse_commodity_all_countries(
        HTML, hscode="2709", month=6, year=2026, trade_type="import", retrieved_at="2026-09-14T00:00:00+00:00"
    )
    assert doc["period"] == "2026-06"
    assert doc["totals"]["value"] == 1600.0
    assert doc["rows"][0]["partner_country"] == "RUSSIA"
    assert doc["rows"][0]["value"] == 1200.0
    assert doc["source"]["report_date"] == "13/08/2026"
    assert doc["commodity_description"].startswith("PETROLEUM OILS")
    assert doc["source_quantity_unit"] == "TON"


def test_quantity_requires_hs8():
    with pytest.raises(ValueError):
        validate_query("2709", 6, 2026, "quantity", "calendar")


def test_five_digit_code_is_rejected():
    with pytest.raises(ValueError):
        validate_query("85414", 6, 2026, "usd", "calendar")
