from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.ingest_tradestat import (
    DASHBOARD_PATH,
    MASTER_PATH,
    OBS_ROOT,
    hs_codes_for_period,
    ingest_one,
    is_queryable_commodity,
    load_json,
    write_observation,
)
from src.tracker.dashboard import build_dashboard
from src.tracker.tradestat import TradeStatClient

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def month_span(start: str, end: str) -> int:
    if not PERIOD_RE.fullmatch(start) or not PERIOD_RE.fullmatch(end):
        raise ValueError("start_period and end_period must be YYYY-MM")
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    span = (ey - sy) * 12 + em - sm + 1
    if span <= 0:
        raise ValueError("start_period must be <= end_period")
    if sy < 2018:
        raise ValueError("MEIDB monthly coverage starts in 2018")
    return span


def iter_periods(start: str, end: str) -> Iterable[str]:
    month_span(start, end)
    year, month = map(int, start.split("-"))
    end_year, end_month = map(int, end.split("-"))
    while (year, month) <= (end_year, end_month):
        yield f"{year:04d}-{month:02d}"
        month += 1
        if month == 13:
            month = 1
            year += 1


def _load_observation(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _report_pairs(doc: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for report in doc.get("reports", []):
        trade_type = str(report.get("trade_type") or "")
        hs_code = str(report.get("hs_code") or "")
        if trade_type and hs_code:
            pairs.add((trade_type, hs_code))
    return pairs


def observation_is_current(
    path: Path,
    *,
    period: str,
    value_type: str,
    active_hs_codes: list[str],
    trade_types: list[str],
) -> tuple[bool, str]:
    """Return whether a stored observation fully satisfies this backfill request."""
    doc = _load_observation(path)
    if doc is None:
        return False, "missing_or_invalid"
    if doc.get("period") != period:
        return False, "period_mismatch"
    if doc.get("value_type", "usd") != value_type:
        return False, "value_type_mismatch"
    if doc.get("status") != "ok":
        return False, f"status_{doc.get('status', 'unknown')}"

    stored_codes = list(doc.get("commodity", {}).get("hs_codes") or [])
    if stored_codes != list(active_hs_codes):
        return False, "period_mapping_changed"

    expected = {(trade_type, code) for code in active_hs_codes for trade_type in trade_types}
    if not expected <= _report_pairs(doc):
        return False, "report_coverage_incomplete"

    reports = [
        report
        for report in doc.get("reports", [])
        if (str(report.get("trade_type") or ""), str(report.get("hs_code") or "")) in expected
    ]
    if any(report.get("value_type", value_type) != value_type for report in reports):
        return False, "report_value_type_mismatch"

    if value_type == "quantity":
        if doc.get("quantity_scale_to_source_unit") != 1:
            return False, "quantity_scale_stale"
        if any(report.get("value_selector_code") != "2" for report in reports):
            return False, "quantity_selector_stale"
        if any(report.get("quantity_scale_to_source_unit") != 1 for report in reports):
            return False, "quantity_report_scale_stale"
    elif value_type == "usd":
        # USD has always used selector 1. Preserve compatibility with early stored
        # observations that predate explicit selector provenance, but reject a
        # contradictory selector if one is present.
        if any(report.get("value_selector_code") not in (None, "1") for report in reports):
            return False, "usd_selector_mismatch"

    return True, "current"


def default_span_limit(*, selected_all: bool, value_type: str) -> int:
    # All-commodity USD backfills generate the largest request volume. Quantity
    # currently applies only to a small exact-HS8 subset, and single-commodity
    # runs are similarly bounded, so they may cover a wider period per run.
    return 12 if selected_all and value_type == "usd" else 36


def select_commodities(master: dict[str, Any], requested: list[str] | None) -> tuple[list[dict[str, Any]], bool]:
    commodities = list(master.get("commodities", []))
    if not requested or requested == ["all"]:
        return commodities, True
    if "all" in requested:
        raise ValueError("'all' cannot be combined with explicit commodity ids")
    requested_set = set(requested)
    known = {item["id"] for item in commodities}
    missing = sorted(requested_set - known)
    if missing:
        raise ValueError(f"unknown commodity id(s): {', '.join(missing)}")
    return [item for item in commodities if item["id"] in requested_set], False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resume-safe bounded TradeStat history backfill")
    parser.add_argument("--start-period", required=True, help="First calendar month YYYY-MM")
    parser.add_argument("--end-period", required=True, help="Last calendar month YYYY-MM")
    parser.add_argument("--commodity", action="append", help="Commodity id; repeatable. Default: all")
    parser.add_argument("--trade-type", choices=["import", "export", "both"], default="both")
    parser.add_argument("--value-type", choices=["usd", "quantity"], default="usd")
    parser.add_argument("--year-type", choices=["calendar"], default="calendar")
    parser.add_argument("--force", action="store_true", help="Refetch even when a current observation already exists")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without network requests or writes")
    parser.add_argument("--no-build-dashboard", action="store_true")
    parser.add_argument("--delay", type=float, default=0.8, help="Polite delay between successful TradeStat reports")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        span = month_span(args.start_period, args.end_period)
        master = load_json(MASTER_PATH)
        commodities, selected_all = select_commodities(master, args.commodity)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    limit = default_span_limit(selected_all=selected_all, value_type=args.value_type)
    if span > limit:
        raise SystemExit(
            f"range is {span} months; limit is {limit} months for this request. "
            "Run history in smaller resumable batches."
        )

    trade_types = ["import", "export"] if args.trade_type == "both" else [args.trade_type]
    client = TradeStatClient(delay_seconds=args.delay)
    summary = {
        "periods": span,
        "written": 0,
        "already_current": 0,
        "mapping_or_scope_skips": 0,
        "failed": 0,
        "planned_fetches": 0,
    }

    for period in iter_periods(args.start_period, args.end_period):
        for commodity in commodities:
            hs_codes, classification_note = hs_codes_for_period(
                commodity,
                period,
                value_type=args.value_type,
            )
            queryable, reason = is_queryable_commodity(
                commodity,
                value_type=args.value_type,
                hs_codes=hs_codes,
            )
            if not queryable or not hs_codes:
                print(f"SKIP {period} {commodity['id']}: {reason or 'no HS codes for period'}")
                summary["mapping_or_scope_skips"] += 1
                continue

            path = OBS_ROOT / period / f"{commodity['id']}.{args.value_type}.json"
            current, current_reason = observation_is_current(
                path,
                period=period,
                value_type=args.value_type,
                active_hs_codes=hs_codes,
                trade_types=trade_types,
            )
            if current and not args.force:
                print(f"CURRENT {period} {commodity['id']} {args.value_type}")
                summary["already_current"] += 1
                continue

            summary["planned_fetches"] += 1
            print(f"FETCH {period} {commodity['id']} {args.value_type}: {current_reason if not args.force else 'forced'}")
            if args.dry_run:
                continue

            doc = ingest_one(
                client,
                commodity,
                period=period,
                hs_codes=hs_codes,
                value_type=args.value_type,
                year_type=args.year_type,
                trade_types=trade_types,
                classification_note=classification_note,
            )
            if doc["status"] != "ok":
                print(f"NOT WRITING {period} {commodity['id']}: status={doc['status']}", file=sys.stderr)
                summary["failed"] += 1
                continue
            written = write_observation(doc)
            print(f"WROTE {written.relative_to(ROOT)}")
            summary["written"] += 1

    if not args.dry_run and not args.no_build_dashboard:
        dashboard = build_dashboard(OBS_ROOT, DASHBOARD_PATH, MASTER_PATH)
        print(f"Dashboard status={dashboard['status']} as_of={dashboard['as_of']}")

    print("BACKFILL_SUMMARY " + json.dumps(summary, sort_keys=True))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
