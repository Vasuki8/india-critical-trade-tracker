from __future__ import annotations

import re
from typing import Any

_RELEASE_MONTH_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})$",
    flags=re.I,
)
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def parse_release_month(value: Any) -> tuple[int, int] | None:
    """Parse TradeStat labels such as ``Mar 2026`` into ``(2026, 3)``."""
    if not isinstance(value, str):
        return None
    match = _RELEASE_MONTH_RE.fullmatch(value.strip())
    if match is None:
        return None
    month = _MONTHS[match.group(1).lower()]
    return int(match.group(2)), month


def format_period(period: tuple[int, int]) -> str:
    year, month = period
    return f"{year:04d}-{month:02d}"


def shift_month(period: tuple[int, int], offset: int) -> tuple[int, int]:
    year, month = period
    serial = year * 12 + (month - 1) + offset
    return serial // 12, serial % 12 + 1


def _months_between(start: tuple[int, int], end: tuple[int, int]) -> int:
    return (end[0] - start[0]) * 12 + end[1] - start[1] + 1


def revision_refresh_range(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    lookback_months: int = 3,
    max_months: int = 12,
) -> tuple[str, str] | None:
    """Return a bounded calendar range worth force-refetching for revisions.

    TradeStat exposes a ``revised_final_through`` cutoff but not a machine-readable
    list of individual months whose values changed. When an official publication
    changes, revisit a small trailing window ending at the current Revised-Final
    cutoff. If that cutoff advances by more than the lookback, also cover the newly
    revised interval, bounded by ``max_months`` so the daily watcher cannot turn into
    an unbounded historical backfill.

    Timestamp-only checks are ignored because ``checked_at`` is deliberately not
    considered publication metadata.
    """
    if lookback_months < 1:
        raise ValueError("lookback_months must be >= 1")
    if max_months < lookback_months:
        raise ValueError("max_months must be >= lookback_months")

    tracked_fields = ("last_updated", "revised_final_through")
    if not any(before.get(field) != after.get(field) for field in tracked_fields):
        return None

    current_cutoff = parse_release_month(after.get("revised_final_through"))
    if current_cutoff is None:
        return None

    trailing_start = shift_month(current_cutoff, -(lookback_months - 1))
    start = trailing_start

    previous_cutoff = parse_release_month(before.get("revised_final_through"))
    if previous_cutoff is not None and current_cutoff > previous_cutoff:
        newly_revised_start = shift_month(previous_cutoff, 1)
        if newly_revised_start < start:
            start = newly_revised_start

    if _months_between(start, current_cutoff) > max_months:
        start = shift_month(current_cutoff, -(max_months - 1))

    return format_period(start), format_period(current_cutoff)
