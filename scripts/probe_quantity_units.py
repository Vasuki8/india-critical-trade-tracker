from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tracker.derived import _canonical_quantity_unit
from src.tracker.tradestat import TradeStatClient


@dataclass(frozen=True)
class ProbeResult:
    period: str
    trade_type: str
    hs_code: str
    data_status: str
    quantity: float | None
    source_quantity_unit: str | None
    canonical_quantity_unit: str | None
    quantity_normalization_factor: float | None
    commodity_description: str | None


def parse_period(value: str) -> tuple[int, int]:
    try:
        year_text, month_text = value.split("-", 1)
        year = int(year_text)
        month = int(month_text)
    except (ValueError, AttributeError) as exc:
        raise argparse.ArgumentTypeError("period must be YYYY-MM") from exc
    if year < 2018 or not 1 <= month <= 12 or value != f"{year:04d}-{month:02d}":
        raise argparse.ArgumentTypeError("period must be YYYY-MM and no earlier than 2018-01")
    return year, month


def _trade_types(value: str) -> tuple[str, ...]:
    return ("import", "export") if value == "both" else (value,)


def probe_quantity_units(
    *,
    client: TradeStatClient,
    hs_codes: list[str],
    periods: list[str],
    trade_type: str = "both",
    required_canonical_unit: str | None = None,
) -> tuple[list[ProbeResult], list[str]]:
    results: list[ProbeResult] = []
    violations: list[str] = []
    required = required_canonical_unit.upper() if required_canonical_unit else None

    for period in periods:
        year, month = parse_period(period)
        for direction in _trade_types(trade_type):
            for hs_code in hs_codes:
                report = client.fetch_commodity_all_countries(
                    hscode=hs_code,
                    month=month,
                    year=year,
                    trade_type=direction,
                    value_type="quantity",
                    year_type="calendar",
                )
                raw_quantity = report.get("totals", {}).get("value")
                quantity = float(raw_quantity) if raw_quantity is not None else None
                source_unit = report.get("source_quantity_unit")
                canonical_unit, factor = _canonical_quantity_unit(source_unit)
                data_status = str(report.get("data_status") or "unknown")

                result = ProbeResult(
                    period=period,
                    trade_type=direction,
                    hs_code=hs_code,
                    data_status=data_status,
                    quantity=quantity,
                    source_quantity_unit=source_unit,
                    canonical_quantity_unit=canonical_unit,
                    quantity_normalization_factor=factor,
                    commodity_description=report.get("commodity_description"),
                )
                results.append(result)

                if quantity is None or quantity <= 0:
                    continue
                if canonical_unit is None:
                    violations.append(
                        f"{period} {direction} {hs_code}: positive quantity {quantity} has no source unit"
                    )
                    continue
                if required is not None and canonical_unit != required:
                    violations.append(
                        f"{period} {direction} {hs_code}: expected canonical unit {required}, "
                        f"got {canonical_unit} from {source_unit!r}"
                    )

    return results, violations


def _summary(results: list[ProbeResult], violations: list[str]) -> dict[str, object]:
    positive = [row for row in results if row.quantity is not None and row.quantity > 0]
    return {
        "queries": len(results),
        "positive_series": len(positive),
        "source_units": sorted({row.source_quantity_unit for row in positive if row.source_quantity_unit}),
        "canonical_units": sorted({row.canonical_quantity_unit for row in positive if row.canonical_quantity_unit}),
        "violations": violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe live TradeStat HS8 quantity units without writing tracker observations."
    )
    parser.add_argument("--hs-code", action="append", required=True, dest="hs_codes")
    parser.add_argument("--period", action="append", required=True, dest="periods")
    parser.add_argument("--trade-type", choices=("import", "export", "both"), default="both")
    parser.add_argument(
        "--require-canonical-unit",
        help="Fail when a positive quantity resolves to a different canonical unit, e.g. KGS.",
    )
    parser.add_argument("--delay-seconds", type=float, default=0.8)
    args = parser.parse_args()

    client = TradeStatClient(delay_seconds=max(args.delay_seconds, 0.0))
    results, violations = probe_quantity_units(
        client=client,
        hs_codes=args.hs_codes,
        periods=args.periods,
        trade_type=args.trade_type,
        required_canonical_unit=args.require_canonical_unit,
    )

    for row in results:
        print(json.dumps(asdict(row), ensure_ascii=False, sort_keys=True))
    print("PROBE_SUMMARY " + json.dumps(_summary(results, violations), ensure_ascii=False, sort_keys=True))

    if violations:
        for violation in violations:
            print(f"PROBE_VIOLATION {violation}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
