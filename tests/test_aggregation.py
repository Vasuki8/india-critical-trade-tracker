from src.tracker.aggregation import aggregate_commodity, portfolio_summary


def report(
    trade_type,
    hs_code,
    total,
    rows,
    *,
    previous=None,
    cumulative=None,
    cumulative_previous=None,
):
    return {
        "trade_type": trade_type,
        "hs_code": hs_code,
        "totals": {
            "value": total,
            "previous_year_value": previous,
            "cumulative_value": cumulative,
            "cumulative_previous_year_value": cumulative_previous,
        },
        "rows": [{"partner_country": c, "value": v} for c, v in rows],
    }


def test_aggregate_dependency_and_concentration():
    reports = [
        report("import", "2709", 100, [("A", 60), ("B", 40)]),
        report("export", "2709", 10, [("C", 10)]),
    ]
    agg = aggregate_commodity(reports)
    assert agg["imports"] == 100
    assert agg["exports"] == 10
    assert agg["balance"] == -90
    assert agg["supplier_concentration"]["top_partner_share_pct"] == 60.0
    assert agg["supplier_concentration"]["hhi"] == 5200.0
    assert agg["dependency"]["score"] > 60


def test_aggregate_yoy_and_ytd_metrics():
    reports = [
        report(
            "import", "2709", 120, [], previous=100,
            cumulative=650, cumulative_previous=500,
        ),
        report(
            "export", "2709", 45, [], previous=50,
            cumulative=240, cumulative_previous=200,
        ),
    ]
    agg = aggregate_commodity(reports)
    assert agg["import_yoy_pct"] == 20.0
    assert agg["export_yoy_pct"] == -10.0
    assert agg["ytd_imports"] == 650
    assert agg["ytd_exports"] == 240
    assert agg["ytd_balance"] == -410
    assert agg["ytd_import_yoy_pct"] == 30.0
    assert agg["ytd_export_yoy_pct"] == 20.0


def test_growth_is_unknown_when_previous_year_is_missing_or_zero():
    reports = [
        report("import", "2709", 10, [], previous=0),
        report("export", "2709", 0, [], previous=None),
    ]
    agg = aggregate_commodity(reports)
    assert agg["import_yoy_pct"] is None
    assert agg["export_yoy_pct"] is None


def test_portfolio_summary_drops_child_hs_codes_when_parent_is_present():
    reports = [
        report("import", "85", 1000, [], previous=900, cumulative=6000, cumulative_previous=5000),
        report("import", "8541", 300, [], previous=250, cumulative=1700, cumulative_previous=1500),
        report("import", "8517", 200, [], previous=180, cumulative=1200, cumulative_previous=1000),
        report("import", "2709", 500, [], previous=400, cumulative=3000, cumulative_previous=2500),
        report("export", "85", 400, [], previous=350, cumulative=2200, cumulative_previous=2000),
        report("export", "8541", 50, [], previous=40, cumulative=300, cumulative_previous=250),
        report("export", "2709", 10, [], previous=20, cumulative=80, cumulative_previous=100),
    ]
    summary = portfolio_summary(reports)
    assert summary["imports"] == 1500
    assert summary["exports"] == 410
    assert summary["import_previous_year"] == 1300
    assert summary["export_previous_year"] == 370
    assert summary["ytd_imports"] == 9000
    assert summary["ytd_exports"] == 2280
    assert "85" in summary["included_hs_codes"]
    assert "8541" not in summary["included_hs_codes"]
