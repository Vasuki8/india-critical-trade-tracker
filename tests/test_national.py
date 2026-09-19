from __future__ import annotations

import copy
import json
import pytest

from scripts import ingest_national
from src.tracker.national import (
    ENDPOINTS, PREFIXES, NationalDataError, build_month_snapshot,
    build_national_dashboard, build_payload, iter_periods, parse_report,
    semantic_fingerprint, validate_national_data, validate_observation,
    write_observation,
)


def report_html(kind="chapters", trade_type="import", period="2026-07"):
    """Small report preserving the verified July-2026 MEIDB HTML contract.

    Official full reports were separately checked for July 2026 and January
    2018: 98 HS2 rows and 251 country rows in each trade direction. The fixture
    deliberately uses fewer rows so validity does not depend on a fixed count.
    """
    year, month = map(int, period.split("-"))
    month_name = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")[month - 1]
    prefix = PREFIXES[(kind, trade_type)]
    selectors = {
        prefix + "Month": [(str(month), month_name)], prefix + "Year": [(str(year), str(year))],
        prefix + "ReportVal": [("1", "US $ Million"), ("3", "Rs. Crore"), ("2", "Quantity")],
        prefix + "ReportYear": [("2", "Calendar Year"), ("1", "Financial Year")],
    }
    selectors[prefix + ("CommodityLevel" if kind == "chapters" else "Country")] = [
        ("2", "2 digit Level") if kind == "chapters" else ("all", "--All --")
    ]
    form = '<input type="hidden" name="_token" value="test-token">'
    for name, options in selectors.items():
        form += f'<select name="{name}">' + "".join(
            f'<option value="{value}" {"selected" if i == 0 else ""}>{label}</option>'
            for i, (value, label) in enumerate(options)
        ) + "</select>"
    if kind == "chapters":
        form += '<input name="comlev" type="radio" value="all" checked><input name="comval" value="">'
        headings = ["S.No.", "HSCode", "Commodity"]
        identities = [["1", "01", "LIVE ANIMALS."], ["2", "02", "MEAT AND EDIBLE MEAT OFFAL."]]
        total_identity = ["", "", f"India's Total {trade_type.title()}"]
    else:
        headings = ["S.No.", "Country"]
        identities = [["1", "AFGHANISTAN"], ["2", "ALBANIA"]]
        total_identity = ["", f"India's Total {trade_type.title()}"]
    headings += [f"{month_name}-{year - 1} (R)", f"{month_name}-{year} (F)", "%Growth", f"Jan-{month_name}-{year - 1} (R)", f"Jan-{month_name}-{year} (F)", "%Growth"]
    amounts = [["10.00", "12.00", "20.00", "60.00", "84.00", "40.00"], ["20.00", "18.00", "-10.00", "140.00", "126.00", "-10.00"]]
    rows = [identity + amount for identity, amount in zip(identities, amounts)]
    rows.append(total_identity + ["30.00", "30.00", "0.00", "200.00", "210.00", "5.00"])
    table = '<table id="example1"><tr>' + "".join(f"<th>{value}</th>" for value in headings) + "</tr>"
    table += "".join("<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>" for row in rows) + "</table>"
    return f"<html><body>{form}<p>Data last updated on: 16/09/2026</p><p>Report Dated: 19 Sep 2026|| Values in US $ Million || (F) Final (R) Revised Final</p>{table}</body></html>"


def observation(period="2026-07"):
    reports = [parse_report(report_html(kind, trade_type, period), kind=kind, trade_type=trade_type, period=period, retrieved_at="2026-09-19T07:00:00+00:00") for kind, trade_type in ENDPOINTS]
    return {"schema_version": 1, "scope": "merchandise", "period": period, "status": "ok", "value_unit": "USD million", "year_type": "calendar", "reports": reports}


@pytest.mark.parametrize("kind,trade_type", ENDPOINTS)
def test_verified_national_query_and_parser_contract(kind, trade_type):
    payload = build_payload(kind=kind, trade_type=trade_type, period="2026-07", token="token")
    prefix = PREFIXES[(kind, trade_type)]
    assert payload[prefix + "Month"] == "7"
    assert payload[prefix + "Year"] == "2026"
    assert payload[prefix + "ReportVal"] == "1"
    assert payload[prefix + "ReportYear"] == "2"
    assert payload[prefix + ("CommodityLevel" if kind == "chapters" else "Country")] == ("2" if kind == "chapters" else "all")
    report = parse_report(report_html(kind, trade_type), kind=kind, trade_type=trade_type, period="2026-07")
    assert len(report["rows"]) == 2
    assert report["totals"]["value"] == 30
    assert report["rows"][0]["code"] == ("01" if kind == "chapters" else None)
    assert report["source"]["last_updated"] == "16/09/2026"


@pytest.mark.parametrize("replacement", ["", "<html>Internal Server Error</html>", "<html>Login</html>"])
def test_missing_result_does_not_become_zero(replacement):
    with pytest.raises(NationalDataError, match="table is missing"):
        parse_report(replacement, kind="chapters", trade_type="import", period="2026-07")


@pytest.mark.parametrize("before,after,match", [
    ("Values in US $ Million", "Values in Rs. Crore", "USD million"),
    ('value="7" selected', 'value="6" selected', "selection"),
    ("Jul-2026 (F)", "Jun-2026 (F)", "header"),
    ("Jan-Jul-2026 (F)", "Apr-Jul-2026 (F)", "calendar YTD"),
    ("India's Total Import", "Sub total", "official total"),
    ("<td>02</td>", "<td>01</td>", "Duplicate"),
    ("<td>12.00</td>", "<td>nan</td>", "Non-finite"),
    ("<td>12.00</td>", "<td>-12.00</td>", "nonnegative"),
    ("<td>12.00</td>", "<td>-</td>", "nonnegative"),
    ("<td>12.00</td>", "<td>14.00</td>", "do not reconcile"),
])
def test_rejects_wrong_or_incomplete_official_results(before, after, match):
    html = report_html().replace(before, after)
    with pytest.raises(NationalDataError, match=match):
        parse_report(html, kind="chapters", trade_type="import", period="2026-07")


def test_source_growth_is_preserved_and_rounding_is_tolerated():
    html = report_html().replace("<td>12.00</td>", "<td>12.01</td>").replace("<td>20.00</td>", "<td>-</td>", 1)
    report = parse_report(html, kind="chapters", trade_type="import", period="2026-07")
    assert report["rows"][0]["yoy_pct"] is None
    assert report["totals"]["value"] == 30
    assert report["totals"]["yoy_pct"] == 0


def test_duplicate_or_missing_direction_and_cross_axis_disagreement_rejected():
    doc = observation()
    doc["reports"][3] = copy.deepcopy(doc["reports"][2])
    with pytest.raises(NationalDataError, match="duplicated or missing"):
        validate_observation(doc)
    doc = observation()
    doc["reports"][2]["rows"][0]["value"] += 1
    doc["reports"][2]["totals"]["value"] += 1
    with pytest.raises(NationalDataError, match="totals disagree"):
        validate_observation(doc)


def test_missing_directional_row_is_unknown_even_when_other_direction_is_zero():
    doc = observation()
    row = copy.deepcopy(doc["reports"][0]["rows"][0])
    row.update({"rank": 3, "code": "03", "name": "FISH"})
    for key in ("previous_year_value", "value", "cumulative_previous_year_value", "cumulative_value"):
        row[key] = 0
    doc["reports"][0]["rows"].append(row)
    snapshot = build_month_snapshot(doc)
    assert snapshot["chapters"][2]["imports"] == 0
    assert snapshot["chapters"][2]["exports"] is None
    assert snapshot["chapters"][2]["balance"] is None


def test_timestamp_only_refresh_is_noop_and_real_revision_is_archived(tmp_path):
    doc = observation()
    assert write_observation(doc, tmp_path)
    original = (tmp_path / "observations/2026-07.json").read_bytes()
    for report in doc["reports"]:
        report["source"]["retrieved_at"] = "2026-09-20T07:00:00+00:00"
        report["source"]["report_date"] = "20 Sep 2026"
    assert not write_observation(doc, tmp_path)
    assert (tmp_path / "observations/2026-07.json").read_bytes() == original
    assert not (tmp_path / "revisions").exists()
    previous_hash = semantic_fingerprint(doc)
    for report in doc["reports"]:
        report["rows"][0]["value"] += 1
        report["totals"]["value"] += 1
    assert write_observation(doc, tmp_path)
    assert (tmp_path / f"revisions/2026-07/{previous_hash}.json").exists()


def test_dashboard_build_reports_gaps_and_validation_catches_stale_snapshot(tmp_path):
    write_observation(observation("2026-05"), tmp_path)
    write_observation(observation("2026-07"), tmp_path)
    dashboard = build_national_dashboard(tmp_path)
    assert dashboard["as_of"] == "2026-07"
    assert dashboard["coverage"]["missing_periods"] == ["2026-06"]
    assert dashboard["monthly"][0]["total_trade"] == 60
    assert dashboard["monthly"][0]["previous_year_imports"] == 30
    assert dashboard["monthly"][0]["previous_year_exports"] == 30
    assert dashboard["monthly"][0]["total_trade_yoy_pct"] == 0
    assert (tmp_path / "dashboard.json").read_text().count("\n") == 1
    assert (tmp_path / "months/2026-07.json").read_text().count("\n") == 1
    assert validate_national_data(tmp_path) == []
    month = tmp_path / "months/2026-07.json"
    value = json.loads(month.read_text())
    value["summary"]["imports"] = 1
    month.write_text(json.dumps(value))
    assert any("snapshot is stale" in error for error in validate_national_data(tmp_path))


@pytest.mark.parametrize("key,value", [
    ("period_count", 5), ("chapter_count", 99), ("partner_count", 251),
    ("missing_periods", []), ("first_period", "2026-06"),
])
def test_validation_checks_published_coverage(tmp_path, key, value):
    write_observation(observation("2026-05"), tmp_path)
    write_observation(observation("2026-07"), tmp_path)
    dashboard = build_national_dashboard(tmp_path)
    dashboard["coverage"][key] = value
    (tmp_path / "dashboard.json").write_text(json.dumps(dashboard))
    assert any("coverage counts" in error for error in validate_national_data(tmp_path))


def test_national_validation_requires_verified_data(tmp_path):
    build_national_dashboard(tmp_path)
    assert any("at least one complete" in error for error in validate_national_data(tmp_path))


def test_cli_resumes_complete_months_and_keeps_completed_month_when_next_fails(tmp_path, monkeypatch):
    write_observation(observation("2026-05"), tmp_path)
    called = []
    def fetch(client, period):
        called.append(period)
        if period == "2026-07":
            raise NationalDataError("test failure")
        return observation(period)
    monkeypatch.setattr(ingest_national, "fetch_month", fetch)
    result = ingest_national.main(["--start-period", "2026-05", "--end-period", "2026-07", "--output-root", str(tmp_path)])
    assert result == 1
    assert called == ["2026-06", "2026-07"]
    assert (tmp_path / "observations/2026-06.json").exists()
    assert not (tmp_path / "observations/2026-07.json").exists()
    assert json.loads((tmp_path / "dashboard.json").read_text())["as_of"] == "2026-06"


def test_period_range_validates_calendar_boundaries():
    assert list(iter_periods("2025-12", "2026-02")) == ["2025-12", "2026-01", "2026-02"]
    with pytest.raises(ValueError):
        list(iter_periods("2017-12", "2018-01"))
    with pytest.raises(ValueError):
        list(iter_periods("2026-02", "2026-01"))
