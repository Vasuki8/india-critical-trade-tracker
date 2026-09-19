from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.ingest_tradestat import latest_period_from_status
from src.tracker.national import (
    build_national_dashboard,
    fetch_month,
    iter_periods,
    validate_national_data,
    validate_observation,
    write_observation,
)
from src.tracker.tradestat import TradeStatClient


def observation_is_current(path: Path, period: str) -> bool:
    try:
        observation = json.loads(path.read_text(encoding="utf-8"))
        validate_observation(observation)
        return observation["period"] == period
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest complete national merchandise reports from official TradeStat MEIDB")
    parser.add_argument("--start-period", help="First calendar month YYYY-MM; complete stored months are skipped")
    parser.add_argument("--end-period", help="Last calendar month YYYY-MM")
    parser.add_argument("--latest", action="store_true", help="Use the latest month in data/source_status.json")
    parser.add_argument("--force", action="store_true", help="Refetch complete stored months and archive genuine revisions")
    parser.add_argument("--build-only", action="store_true", help="Rebuild and validate display files from stored national reports")
    parser.add_argument("--output-root", type=Path, default=ROOT / "data" / "national")
    parser.add_argument("--delay", type=float, default=0.8, help="Polite pause between official report requests")
    args = parser.parse_args(argv)
    if args.delay < 0:
        parser.error("--delay must be nonnegative")
    if args.build_only:
        if args.latest or args.start_period or args.end_period or args.force:
            parser.error("--build-only cannot be combined with an ingestion range or --force")
    elif args.latest:
        if args.start_period or args.end_period:
            parser.error("--latest cannot be combined with a period range")
    elif not (args.start_period and args.end_period):
        parser.error("provide both --start-period and --end-period, or use --latest / --build-only")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.build_only:
            periods = []
        elif args.latest:
            periods = [latest_period_from_status()]
        else:
            periods = list(iter_periods(args.start_period, args.end_period))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    source_status = json.loads((ROOT / "data" / "source_status.json").read_text(encoding="utf-8"))
    summary = {"periods": len(periods), "written": 0, "unchanged": 0, "already_current": 0, "failed": 0}
    client = TradeStatClient(delay_seconds=args.delay) if periods else None
    for period in periods:
        path = args.output_root / "observations" / f"{period}.json"
        if not args.force and observation_is_current(path, period):
            print(f"CURRENT national {period}", flush=True)
            summary["already_current"] += 1
            continue
        try:
            observation = fetch_month(client, period)
            changed = write_observation(observation, args.output_root)
            summary["written" if changed else "unchanged"] += 1
            print(f"{'WROTE' if changed else 'UNCHANGED'} national {period}", flush=True)
        except Exception as exc:
            summary["failed"] += 1
            print(f"FAIL national {period}: {exc}; existing complete data is preserved", file=sys.stderr, flush=True)
    try:
        dashboard = build_national_dashboard(args.output_root, source_status)
        errors = validate_national_data(args.output_root)
        if errors:
            raise ValueError("; ".join(errors))
        print(f"National dashboard as_of={dashboard['as_of']} months={len(dashboard['monthly'])}", flush=True)
    except Exception as exc:
        summary["failed"] += 1
        print(f"FAIL national dashboard rebuild: {exc}", file=sys.stderr, flush=True)
    print("NATIONAL_INGEST_SUMMARY " + json.dumps(summary, sort_keys=True), flush=True)
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
