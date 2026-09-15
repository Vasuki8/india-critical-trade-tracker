import pytest

from scripts.probe_quantity_units import parse_period, probe_quantity_units


class FakeClient:
    def __init__(self, reports):
        self.reports = reports

    def fetch_commodity_all_countries(self, **kwargs):
        key = (
            kwargs["year"],
            kwargs["month"],
            kwargs["trade_type"],
            kwargs["hscode"],
        )
        return self.reports[key]


def _report(quantity, unit, status="ok"):
    return {
        "data_status": status,
        "source_quantity_unit": unit,
        "commodity_description": "Cobalt test line",
        "totals": {"value": quantity},
    }


def test_parse_period_contract():
    assert parse_period("2018-01") == (2018, 1)
    assert parse_period("2026-12") == (2026, 12)
    with pytest.raises(Exception):
        parse_period("2017-12")
    with pytest.raises(Exception):
        parse_period("2026-6")


def test_probe_accepts_compatible_mass_unit_variants():
    reports = {
        (2018, 1, "import", "26050000"): _report(2.0, "TON"),
        (2018, 1, "import", "81052010"): _report(250.0, "KGS"),
    }
    rows, violations = probe_quantity_units(
        client=FakeClient(reports),
        hs_codes=["26050000", "81052010"],
        periods=["2018-01"],
        trade_type="import",
        required_canonical_unit="KGS",
    )

    assert violations == []
    assert [row.canonical_quantity_unit for row in rows] == ["KGS", "KGS"]
    assert [row.quantity_normalization_factor for row in rows] == [1000.0, 1.0]


def test_probe_rejects_positive_incompatible_unit():
    reports = {
        (2026, 6, "export", "81052020"): _report(4.0, "NOS"),
    }
    _, violations = probe_quantity_units(
        client=FakeClient(reports),
        hs_codes=["81052020"],
        periods=["2026-06"],
        trade_type="export",
        required_canonical_unit="KGS",
    )

    assert len(violations) == 1
    assert "expected canonical unit KGS" in violations[0]


def test_probe_rejects_positive_quantity_without_unit_but_allows_zero_no_data():
    positive_reports = {
        (2021, 1, "import", "81053000"): _report(1.0, None),
    }
    _, violations = probe_quantity_units(
        client=FakeClient(positive_reports),
        hs_codes=["81053000"],
        periods=["2021-01"],
        trade_type="import",
        required_canonical_unit="KGS",
    )
    assert len(violations) == 1
    assert "has no source unit" in violations[0]

    empty_reports = {
        (2021, 1, "import", "81053000"): _report(0.0, None, status="no_data"),
    }
    _, violations = probe_quantity_units(
        client=FakeClient(empty_reports),
        hs_codes=["81053000"],
        periods=["2021-01"],
        trade_type="import",
        required_canonical_unit="KGS",
    )
    assert violations == []
