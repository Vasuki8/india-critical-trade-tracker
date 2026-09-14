from src.tracker.aggregation import aggregate_commodity, portfolio_summary


def report(trade_type, hs_code, total, rows):
    return {
        "trade_type": trade_type,
        "hs_code": hs_code,
        "totals": {"value": total},
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


def test_portfolio_summary_drops_child_hs_codes_when_parent_is_present():
    reports = [
        report("import", "85", 1000, []),
        report("import", "8541", 300, []),
        report("import", "8517", 200, []),
        report("import", "2709", 500, []),
        report("export", "85", 400, []),
        report("export", "8541", 50, []),
        report("export", "2709", 10, []),
    ]
    summary = portfolio_summary(reports)
    assert summary["imports"] == 1500
    assert summary["exports"] == 410
    assert "85" in summary["included_hs_codes"]
    assert "8541" not in summary["included_hs_codes"]
