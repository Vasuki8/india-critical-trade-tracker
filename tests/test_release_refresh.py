import pytest

from src.tracker.releases import parse_release_month, revision_refresh_range


def test_parse_release_month():
    assert parse_release_month("Mar 2026") == (2026, 3)
    assert parse_release_month(" dec 2025 ") == (2025, 12)
    assert parse_release_month("2026-03") is None
    assert parse_release_month(None) is None


def test_timestamp_only_source_check_does_not_plan_revision_refresh():
    before = {
        "checked_at": "2026-09-13T00:00:00+00:00",
        "last_updated": "13/08/2026",
        "revised_final_through": "Mar 2026",
    }
    after = {
        **before,
        "checked_at": "2026-09-14T00:00:00+00:00",
    }
    assert revision_refresh_range(before, after) is None


def test_release_change_rechecks_trailing_revised_final_window():
    before = {"last_updated": "13/08/2026", "revised_final_through": "Mar 2026"}
    after = {"last_updated": "14/09/2026", "revised_final_through": "Mar 2026"}
    assert revision_refresh_range(before, after) == ("2026-01", "2026-03")


def test_cutoff_advance_covers_newly_revised_months_and_lookback():
    before = {"last_updated": "13/08/2026", "revised_final_through": "Mar 2026"}
    after = {"last_updated": "14/09/2026", "revised_final_through": "Jul 2026"}
    assert revision_refresh_range(before, after) == ("2026-04", "2026-07")


def test_revision_sweep_is_bounded_when_cutoff_jumps_far_forward():
    before = {"last_updated": "01/01/2025", "revised_final_through": "Jan 2025"}
    after = {"last_updated": "01/03/2026", "revised_final_through": "Mar 2026"}
    assert revision_refresh_range(before, after) == ("2025-04", "2026-03")


def test_missing_current_revised_final_cutoff_disables_sweep():
    before = {"last_updated": "13/08/2026", "revised_final_through": "Mar 2026"}
    after = {"last_updated": "14/09/2026", "revised_final_through": None}
    assert revision_refresh_range(before, after) is None


def test_invalid_bounds_are_rejected():
    with pytest.raises(ValueError):
        revision_refresh_range({}, {}, lookback_months=0)
    with pytest.raises(ValueError):
        revision_refresh_range({}, {}, lookback_months=4, max_months=3)
