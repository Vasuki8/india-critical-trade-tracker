from src.tracker.validation import validate_dashboard


def _dashboard():
    return {
        "as_of": "2026-06",
        "monthly": [
            {"period": "2026-04"},
            {"period": "2026-05"},
            {"period": "2026-06"},
        ],
        "commodities": [
            {"id": "lithium"},
            {"id": "solar_pv"},
        ],
        "commodity_history": {
            "lithium": [
                {
                    "period": "2026-05",
                    "unit_values": {
                        "import": {
                            "status": "ok",
                            "quantity": 100.0,
                            "unit_value_usd_per_source_unit": 20.0,
                        },
                        "export": {"status": "not_available"},
                    },
                },
                {
                    "period": "2026-06",
                    "unit_values": {
                        "import": {"status": "not_available"},
                        "export": {"status": "not_available"},
                    },
                },
            ],
            "solar_pv": [{"period": "2026-06"}],
        },
    }


def test_valid_dashboard_history_passes():
    assert validate_dashboard(_dashboard()) == []


def test_monthly_duplicate_and_unsorted_periods_fail():
    doc = _dashboard()
    doc["monthly"] = [
        {"period": "2026-06"},
        {"period": "2026-05"},
        {"period": "2026-05"},
    ]
    errors = validate_dashboard(doc)
    assert any("duplicate periods" in error for error in errors)
    assert any("sorted oldest to newest" in error for error in errors)


def test_as_of_must_match_latest_monthly_usd_period():
    doc = _dashboard()
    doc["as_of"] = "2026-05"
    errors = validate_dashboard(doc)
    assert any("must equal latest monthly USD period" in error for error in errors)
    assert any("after dashboard as_of" in error for error in errors)


def test_duplicate_or_future_commodity_history_fails():
    doc = _dashboard()
    doc["commodity_history"]["lithium"] = [
        {"period": "2026-06"},
        {"period": "2026-06"},
        {"period": "2026-07"},
    ]
    errors = validate_dashboard(doc)
    assert any("duplicate periods" in error for error in errors)
    assert any("2026-07 is after dashboard as_of" in error for error in errors)


def test_unknown_history_commodity_id_fails():
    doc = _dashboard()
    doc["commodity_history"]["unknown"] = [{"period": "2026-06"}]
    errors = validate_dashboard(doc)
    assert any("ids missing from dashboard.commodities" in error for error in errors)


def test_ok_unit_value_requires_positive_quantity_and_non_negative_price():
    doc = _dashboard()
    doc["commodity_history"]["lithium"][0]["unit_values"]["import"] = {
        "status": "ok",
        "quantity": 0,
        "unit_value_usd_per_source_unit": -1.0,
    }
    errors = validate_dashboard(doc)
    assert any("requires positive quantity" in error for error in errors)
    assert any("requires non-negative unit value" in error for error in errors)
