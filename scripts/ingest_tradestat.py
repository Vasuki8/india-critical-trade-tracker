from __future__ import annotations

import argparse
import hashlib
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
REVISION_ROOT = ROOT / "data" / "revisions"
DASHBOARD_PATH = ROOT / "data" / "dashboard.json"

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
QUANTITY_SCALE_TO_SOURCE_UNIT = 1
QUANTITY_SCALE_NOTE = "TradeStat MEIDB quantity values are already expressed in the displayed source unit (for example KGS or NOS)."
FETCH_TIME_ONLY_KEYS = {"retrieved_at", "report_date"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_period_from_status(path: Path = SOURCE_STATUS_PATH) -> str:
    status = load_json(path)
    text = status.get("data_available") or ""
    match = re.search(r"Data available:\s*(.*?)\s*\(\(R\)", text, flags=re.I)
    if not match:
        match = re.search(r"to\s+([A-Za-z]+)\s+(\d{4})", text, flags=re.I)
        if not match:
            raise ValueError(f"Could not parse latest period from source status: {text!r}")
        month_name, year_text = match.groups()
    else:
        available_text = match.group(1)
        period_match = re.search(r"to\s+([A-Za-z]+)\s+(\d{4})", available_text, flags=re.I)
        if not period_match:
            raise ValueError(f"Could not parse latest period from source status: {text!r}")
        month_name, year_text = period_match.groups()
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


def _codes_for_mapping(mapping: dict[str, Any], period: str) -> tuple[list[str], str | None]:
    transitions = set(mapping.get("classification_transition_periods", []))
    if period in transitions:
        return [], f"classification transition month intentionally skipped: {period}"

    eras = mapping.get("classification_eras") or []
    if eras:
        for era in eras:
            if _period_in_range(period, era.get("from"), era.get("through")):
                return list(era.get("hs_codes", [])), era.get("note") or mapping.get("note")
        return [], f"no classification mapping defined for {period}"

    return list(mapping.get("hs_codes", [])), mapping.get("note")


def _mapping_for_value_type(
    item: dict[str, Any],
    value_type: str,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if value_type != "quantity":
        return item, item.get("mapping_status"), None

    quantity = item.get("quantity_mapping")
    if not isinstance(quantity, dict) or quantity.get("enabled") is not True:
        return None, None, None

    mode = quantity.get("mode")
    if mode == "same_as_value":
        return item, quantity.get("mapping_status"), mode
    if mode == "separate":
        return quantity, quantity.get("mapping_status"), mode
    return None, quantity.get("mapping_status"), str(mode) if mode is not None else None


def hs_codes_for_period(
    item: dict[str, Any],
    period: str,
    value_type: str = "usd",
) -> tuple[list[str], str | None]:
    mapping, _status, _mode = _mapping_for_value_type(item, value_type)
    if mapping is None:
        if value_type == "quantity":
            return [], "quantity mapping is not enabled or has an unsupported mode"
        return [], "no mapping is enabled"
    return _codes_for_mapping(mapping, period)


def is_queryable_commodity(
    item: dict[str, Any],
    value_type: str = "usd",
    hs_codes: list[str] | None = None,
) -> tuple[bool, str | None]:
    mapping, status, mode = _mapping_for_value_type(item, value_type)
    if value_type == "quantity":
        if mapping is None:
            return False, "quantity mapping is not explicitly enabled"
        if mode not in {"same_as_value", "separate"}:
            return False, f"unsupported quantity mapping mode: {mode}"
        if status != "hs8_validated":
            return False, f"quantity mapping must be hs8_validated; got {status}"
    elif re.search(r"needs|sensitive|partial", str(status or ""), flags=re.I):
        return False, f"mapping status requires review: {status}"

    codes = list(hs_codes if hs_codes is not None else (mapping or item).get("hs_codes", []))
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


def _active_mapping_metadata(
    commodity: dict[str, Any],
    value_type: str,
) -> tuple[str, list[str], str | None, bool]:
    mapping, status, mode = _mapping_for_value_type(commodity, value_type)
    quantity = commodity.get("quantity_mapping") if value_type == "quantity" else None
    rollup = bool(quantity.get("rollup_to_value_mapping")) if isinstance(quantity, dict) else False
    if mapping is None:
        return commodity.get("mapping_status", ""), list(commodity.get("hs_codes", [])), mode, rollup
    return (
        str(status or commodity.get("mapping_status", "")),
        list(mapping.get("hs_codes", commodity.get("hs_codes", []))),
        mode,
        rollup,
    )


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
    active_mapping_status, canonical_hs_codes, quantity_mapping_mode, quantity_rollup = _active_mapping_metadata(
        commodity, value_type
    )
    commodity_metadata: dict[str, Any] = {
        "id": commodity["id"],
        "name": commodity["name"],
        "category": commodity["category"],
        "priority": commodity["priority"],
        "hs_codes": hs_codes,
        "canonical_hs_codes": canonical_hs_codes,
        "mapping_status": active_mapping_status,
        "classification_note": classification_note,
    }
    # Preserve the existing observation identity for ordinary USD and
    # same-as-value quantity mappings. Extra provenance is needed only when the
    # quantity mapping intentionally differs from the monetary definition.
    if value_type == "quantity" and quantity_mapping_mode == "separate":
        commodity_metadata.update(
            {
                "monetary_mapping_status": commodity["mapping_status"],
                "quantity_mapping_mode": quantity_mapping_mode,
                "quantity_rollup_to_value_mapping": quantity_rollup,
            }
        )

    return {
        "schema_version": 3,
        "period": period,
        "value_type": value_type,
        "year_type": year_type,
        "quantity_scale_to_source_unit": QUANTITY_SCALE_TO_SOURCE_UNIT if value_type == "quantity" else None,
        "quantity_scale_note": QUANTITY_SCALE_NOTE if value_type == "quantity" else None,
        "commodity": commodity_metadata,
        "status": status,
        "reports": reports,
        "metrics": metrics,
        "failures": failures,
    }


def _hash_json_token(hasher: Any, token: str) -> None:
    hasher.update(token.encode("utf-8"))


def _update_revision_hash(hasher: Any, value: Any) -> None:
    """Stream the legacy canonical revision JSON directly into ``hasher``.

    This deliberately reproduces ``json.dumps(_revision_payload(...),
    sort_keys=True, separators=(",", ":"), ensure_ascii=False)`` byte-for-byte
    without allocating a second full observation tree or a full JSON string.
    """
    if isinstance(value, dict):
        _hash_json_token(hasher, "{")
        first = True
        for key in sorted(value):
            if key in FETCH_TIME_ONLY_KEYS:
                continue
            if not first:
                _hash_json_token(hasher, ",")
            _hash_json_token(
                hasher,
                json.dumps(key, ensure_ascii=False, separators=(",", ":")),
            )
            _hash_json_token(hasher, ":")
            _update_revision_hash(hasher, value[key])
            first = False
        _hash_json_token(hasher, "}")
        return

    if isinstance(value, list):
        _hash_json_token(hasher, "[")
        for index, item in enumerate(value):
            if index:
                _hash_json_token(hasher, ",")
            _update_revision_hash(hasher, item)
        _hash_json_token(hasher, "]")
        return

    _hash_json_token(
        hasher,
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
    )


def observation_fingerprint(doc: dict[str, Any]) -> str:
    hasher = hashlib.sha256()
    _update_revision_hash(hasher, doc)
    return hasher.hexdigest()


def write_observation(
    doc: dict[str, Any],
    *,
    observation_root: Path = OBS_ROOT,
    revision_root: Path = REVISION_ROOT,
) -> Path:
    """Write the current observation and preserve superseded semantic versions.

    Fetch/render-time-only changes such as ``source.retrieved_at`` and the
    TradeStat HTML ``report_date`` are ignored. In that case the existing
    current file is left untouched, preventing noisy commits and false revision
    records. Genuine changes to official data, status headers, mappings, totals,
    partner rows, units, checksums, or other semantic content archive the prior
    current document before replacement.
    """
    out_dir = observation_root / doc["period"]
    out_dir.mkdir(parents=True, exist_ok=True)
    value_type = doc.get("value_type", "usd")
    commodity_id = doc["commodity"]["id"]
    path = out_dir / f"{commodity_id}.{value_type}.json"

    new_fingerprint = observation_fingerprint(doc)
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None

        if previous is not None:
            previous_fingerprint = observation_fingerprint(previous)
            if previous_fingerprint == new_fingerprint:
                return path

            archive_dir = revision_root / doc["period"] / f"{commodity_id}.{value_type}"
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_path = archive_dir / f"{previous_fingerprint}.json"
            if not archive_path.exists():
                archive_path.write_text(json.dumps(previous, indent=2) + "\n", encoding="utf-8")

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
        dashboard = build_dashboard(OBS_ROOT, DASHBOARD_PATH, MASTER_PATH)
        print(f"Dashboard status={dashboard['status']} as_of={dashboard['as_of']}")

    print(f"Completed period={period}: written={written}, skipped={skipped}, failed={failed}")
    if written == 0 and failed:
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
