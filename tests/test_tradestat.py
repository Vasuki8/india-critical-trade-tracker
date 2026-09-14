from pathlib import Path

import pytest

from src.tracker.tradestat import (
    TradeStatError,
    build_payload,
    parse_commodity_all_countries,
    parse_csrf_token,
    validate_query,
    validate_value_type_contract,
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


def test_quantity_and_inr_selector_codes_match_live_form():
    quantity = build_payload(
        trade_type="import", token="t", hscode="28252000", month=6, year=2026,
        value_type="quantity", year_type="calendar",
    )
    inr = build_payload(
        trade_type="export", token="t", hscode="28252000", month=6, year=2026,
        value_type="inr", year_type="calendar",
    )
    assert quantity["cwacimReportVal"] == "2"
    assert inr["cwacexReportVal"] == "3"


def test_value_selector_contract_accepts_verified_live_mapping():
    html = """
    <select name="cwacimReportVal" id="cwacimReportVal">
      <option value="1">US $ Million</option>
      <option value="3">₹ Crore</option>
      <option value="2">Quantity</option>
    </select>
    """
    validate_value_type_contract(html, "import")


def test_value_selector_contract_rejects_swapped_mapping():
    html = """
    <select name="cwacimReportVal" id="cwacimReportVal">
      <option value="1">US $ Million</option>
      <option value="2">₹ Crore</option>
      <option value="3">Quantity</option>
    </select>
    """
    with pytest.raises(TradeStatError):
        validate_value_type_contract(html, "import")


def test_parser_extracts_month_value_and_partner_rows():
    doc = parse_commodity_all_countries(
        HTML, hscode="2709", month=6, year=2026, trade_type="import", retrieved_at="2026-09-14T00:00:00+00:00"
    )
    assert doc["period"] == "2026-06"
    assert doc["data_status"] == "ok"
    assert doc["value_selector_code"] == "1"
    assert doc["totals"]["value"] == 1600.0
    assert doc["rows"][0]["partner_country"] == "RUSSIA"
    assert doc["rows"][0]["value"] == 1200.0
    assert doc["source"]["report_date"] == "13/08/2026"
    assert doc["commodity_description"].startswith("PETROLEUM OILS")
    assert doc["source_quantity_unit"] == "TON"


def test_missing_result_table_is_no_data():
    html = """
    <html><body>
      <input type="hidden" name="_token" value="abc123" />
      <div>Data last updated on: 13/08/2026</div>
      <div>Commodity search completed.</div>
    </body></html>
    """
    doc = parse_commodity_all_countries(
        html, hscode="2709", month=6, year=2026, trade_type="export", retrieved_at="2026-09-14T00:00:00+00:00"
    )
    assert doc["data_status"] == "no_data"
    assert doc["rows"] == []
    assert doc["totals"]["value"] == 0.0
    assert doc["totals"]["previous_year_value"] is None


def test_fatal_missing_table_response_is_failure():
    with pytest.raises(TradeStatError):
        parse_commodity_all_countries(
            "<html><body>Internal Server Error</body></html>",
            hscode="2709", month=6, year=2026, trade_type="export"
        )


def test_quantity_requires_hs8():
    with pytest.raises(ValueError):
        validate_query("2709", 6, 2026, "quantity", "calendar")


def test_five_digit_code_is_rejected():
    with pytest.raises(ValueError):
        validate_query("85414", 6, 2026, "usd", "calendar")
