from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tracker.aggregation import aggregate_commodity
from src.tracker.dashboard import build_dashboard
from src.tracker.tradestat import TradeStatClient, VALID_HS_LENGTHS

MASTER_PATH = ROOT / "data" / "commodities.json"
SOURCE_STATUS_PATH = ROOT / "data" / "source_status.json"
OBS_ROOT = ROOT / "data" / "observations"
DASHBOARD_PATH = ROOT / "data" / "dashboard.json"

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
QUANTITY_SCALE_TO_SOURCE_UNIT = 1_000
QUANTITY_SCALE_NOTE = "TradeStat quantity values are thousands of the displayed source unit (for example KGS or NOS)."


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_period_from_status(path: Path = SOURCE_STATUS_PATH) -> str:
    status = load_json(path)
    text = status.get("data_available") or ""
    match = re.search(r"to\s+([A-Za-z]+)\s+(\d{4})", text, flags=re.I)
    if not match:
        raise ValueError(f"Could not parse latest period from source status: {text!r}")
    month_name, year_text = match.groups()
    month = MONTHS.get(month_name.lower())
    if month is None:
        raise ValueError(f"Unknown month in source status: {month_name}")
    return f"{int(year_text):04d}-{month:02d}"


def _period_in_range(period: str, start: str | None, through: str | None) -> bool:
    if start and period < start:
        return False
    if through and period > through:
        return False
    return True


def hs_codes_for_period(item: dict[str, Any], period: str) -> tuple[list[str], str | None]:
    transitions = set(item.get("classification_transition_periods", []))
    if period in transitions:
        return [], f"classification transition month intentionally skipped: {period}"

    eras = item.get("classification_eras") or []
    if eras:
        for era in eras:
            if _period_in_range(period, era.get("from"), era.get("through")):
                return list(era.get("hs_codes", [])), era.get("note")
        return [], f"no classification mapping defined for {period}"

    return list(item.get("hs_codes", [])), None


def is_queryable_commodity(
    item: dict[str, Any],
    value_type: str = "usd",
    hs_codes: list[str] | None = None,
) -> tuple[bool, str | None]:
    status = item.get("mapping_status", "")
    if re.search(r"needs|sensitive|partial", status, flags=re.I):
        return False, f"mapping status requires review: {status}"

    codes = list(hs_codes if hs_codes is not None else item.get("hs_codes", []))
    if not codes:
        return False, "no HS codes are mapped for this period"
    bad = [code for code in codes if len(code) not in VALID_HS_LENGTHS]
    if bad:
        return False, f"unsupported HS code length: {', '.join(bad)}"
    if value_type == "quantity":
        non_hs8 = [code for code in codes if len(code) != 8]
        if non_hs8:
            return False, f"quantity requires HS8 mappings; got {', '.join(non_hs8)}"
    return True, None


def ingest_one(
    client: TradeStatClient,
    commodity: dict[str, Any],
    *,
    period: str,
    hs_codes: list[str],
    value_type: str,
    year_type: str,
    trade_types: list[str],
    classification_note: str | None = None,
) -> dict[str, Any]:
    year, month = map(int, period.split("-"))
    reports: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for hs_code in hs_codes:
        for trade_type in trade_types:
            try:
                report = client.fetch_commodity_all_countries(
                    hscode=hs_code,
                    month=month,
                    year=year,
                    trade_type=trade_type,
                    value_type=value_type,
                    year_type=year_type,
                )
                if value_type == "quantity":
                    report["quantity_scale_to_source_unit"] = QUANTITY_SCALE_TO_SOURCE_UNIT
                    report["quantity_scale_note"] = QUANTITY_SCALE_NOTE
                reports.append(report)
                print(f"OK {period} {commodity['id']} {trade_type} HS {hs_code}")
            except Exception as exc:
                failures.append({"trade_type": trade_type, "hs_code": hs_code, "error": str(exc)})
                print(f"FAIL {period} {commodity['id']} {trade_type} HS {hs_code}: {exc}", file=sys.stderr)

    expected = len(hs_codes) * len(trade_types)
    status = "ok" if len(reports) == expected else "partial" if reports else "failed"
    metrics = aggregate_commodity(reports) if reports and value_type == "usd" else {}
    return {
        "schema_version": 3,
        "period": period,
        "value_type": value_type,
        "year_type": year_type,
        "quantity_scale_to_source_unit": QUANTITY_SCALE_TO_SOURCE_UNIT if value_type == "quantity" else None,
        "quantity_scale_note": QUANTITY_SCALE_NOTE if value_type == "quantity" else None,
        "commodity": {
            "id": commodity["id"],
            "name": commodity["name"],
            "category": commodity["category"],
            "priority": commodity["priority"],
            "hs_codes": hs_codes,
            "canonical_hs_codes": commodity.get("hs_codes", hs_codes),
            "mapping_status": commodity["mapping_status"],
            "classification_note": classification_note,
        },
        "status": status,
        "reports": reports,
        "metrics": metrics,
        "failures": failures,
    }


def write_observation(doc: dict[str, Any]) -> Path:
    out_dir = OBS_ROOT / doc["period"]
    out_dir.mkdir(parents=True, exist_ok=True)
    value_type = doc.get("value_type", "usd")
    path = out_dir / f"{doc['commodity']['id']}.{value_type}.json"
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest official TradeStat MEIDB monthly critical-commodity data")
    period = parser.add_mutually_exclusive_group(required=True)
    period.add_argument("--period", help="Calendar period YYYY-MM")
    period.add_argument("--latest", action="store_true", help="Use latest period from data/source_status.json")
    parser.add_argument("--commodity", action="append", help="Commodity id; repeatable. Default: all queryable groups")
    parser.add_argument("--trade-type", choices=["import", "export", "both"], default="both")
    parser.add_argument("--value-type", choices=["usd", "inr", "quantity"], default="usd")
    parser.add_argument("--year-type", choices=["calendar", "financial"], default="calendar")
    parser.add_argument("--allow-partial", action="store_true", help="Persist commodities even when one HS/trade request fails")
    parser.add_argument("--include-review-mappings", action="store_true", help="Attempt mappings marked for review")
    parser.add_argument("--no-build-dashboard", action="store_true")
    parser.add_argument("--delay", type=float, default=0.8, help="Polite delay between successful report requests")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    period = latest_period_from_status() if args.latest else args.period
    if not re.fullmatch(r"\d{4}-\d{2}", period or ""):
        raise SystemExit("period must be YYYY-MM")
    year, month = map(int, period.split("-"))
    if not 1 <= month <= 12 or year < 2018:
        raise SystemExit("period is outside MEIDB monthly coverage")

    master = load_json(MASTER_PATH)
    selected_ids = set(args.commodity or [])
    commodities = master["commodities"]
    if selected_ids:
        found = {c["id"] for c in commodities}
        missing = sorted(selected_ids - found)
        if missing:
            raise SystemExit(f"Unknown commodity id(s): {', '.join(missing)}")
        commodities = [c for c in commodities if c["id"] in selected_ids]

    trade_types = ["import", "export"] if args.trade_type == "both" else [args.trade_type]
    client = TradeStatClient(delay_seconds=args.delay)
    written = 0
    failed = 0
    skipped = 0

    for commodity in commodities:
        hs_codes, classification_note = hs_codes_for_period(commodity, period)
        queryable, reason = is_queryable_commodity(
            commodity,
            value_type=args.value_type,
            hs_codes=hs_codes,
        )
        if not queryable and not args.include_review_mappings:
            print(f"SKIP {commodity['id']}: {reason}")
            skipped += 1
            continue
        if not hs_codes:
            print(f"SKIP {commodity['id']}: {reason or 'no HS codes for period'}")
            skipped += 1
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
        if doc["status"] == "failed" or (doc["status"] == "partial" and not args.allow_partial):
            print(f"NOT WRITING {commodity['id']}: status={doc['status']}", file=sys.stderr)
            failed += 1
            continue
        path = write_observation(doc)
        print(f"WROTE {path.relative_to(ROOT)}")
        written += 1

    if not args.no_build_dashboard:
        dashboard = build_dashboard(OBS_ROOT, DASHBOARD_PATH)
        print(f"Dashboard status={dashboard['status']} as_of={dashboard['as_of']}")

    print(f"Completed period={period}: written={written}, skipped={skipped}, failed={failed}")
    if written == 0 and failed:
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
