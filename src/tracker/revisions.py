from __future__ import annotations

import json
from pathlib import Path
from typing import Any

METRIC_KEYS = (
    "imports",
    "exports",
    "balance",
    "ytd_imports",
    "ytd_exports",
    "ytd_balance",
)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _round(value: float) -> float:
    return round(value, 6)


def _delta(previous: Any, current: Any) -> dict[str, float | None] | None:
    before = _as_number(previous)
    after = _as_number(current)
    if before is None and after is None:
        return None
    before = before or 0.0
    after = after or 0.0
    change = after - before
    pct = None if before == 0 else change / before * 100
    return {
        "previous": _round(before),
        "current": _round(after),
        "change": _round(change),
        "change_pct": round(pct, 2) if pct is not None else None,
    }


def _report_key(report: dict[str, Any]) -> tuple[str, str]:
    return str(report.get("trade_type") or ""), str(report.get("hs_code") or "")


def _report_map(doc: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        key: report
        for report in doc.get("reports", [])
        if (key := _report_key(report))[0] and key[1]
    }


def _partner_map(report: dict[str, Any] | None) -> dict[str, float | None]:
    if report is None:
        return {}
    output: dict[str, float | None] = {}
    for row in report.get("rows", []):
        country = str(row.get("partner_country") or "").strip()
        if not country:
            continue
        value = _as_number(row.get("value"))
        output[country] = value
    return output


def _retrieved_at(doc: dict[str, Any]) -> str | None:
    values = [
        str(source.get("retrieved_at"))
        for report in doc.get("reports", [])
        if isinstance((source := report.get("source")), dict) and source.get("retrieved_at")
    ]
    return max(values) if values else None


def _report_dates(doc: dict[str, Any]) -> list[str]:
    values = {
        str(source.get("report_date"))
        for report in doc.get("reports", [])
        if isinstance((source := report.get("source")), dict) and source.get("report_date")
    }
    return sorted(values)


def _identity(doc: dict[str, Any]) -> tuple[str, str, str]:
    commodity = doc.get("commodity") or {}
    return (
        str(doc.get("period") or ""),
        str(commodity.get("id") or ""),
        str(doc.get("value_type") or "usd"),
    )


def compare_observations(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Quantify the user-visible changes between two versions of one observation."""
    previous_identity = _identity(previous)
    current_identity = _identity(current)
    if previous_identity != current_identity:
        raise ValueError(
            "cannot compare observations with different period/commodity/value_type identities: "
            f"{previous_identity!r} != {current_identity!r}"
        )

    metric_deltas: dict[str, dict[str, float | None]] = {}
    previous_metrics = previous.get("metrics") or {}
    current_metrics = current.get("metrics") or {}
    for key in METRIC_KEYS:
        change = _delta(previous_metrics.get(key), current_metrics.get(key))
        if change is not None and change["change"] != 0:
            metric_deltas[key] = change

    previous_reports = _report_map(previous)
    current_reports = _report_map(current)
    report_deltas: list[dict[str, Any]] = []
    for trade_type, hs_code in sorted(set(previous_reports) | set(current_reports)):
        before_report = previous_reports.get((trade_type, hs_code))
        after_report = current_reports.get((trade_type, hs_code))
        total_change = _delta(
            (before_report or {}).get("totals", {}).get("value"),
            (after_report or {}).get("totals", {}).get("value"),
        )

        before_partners = _partner_map(before_report)
        after_partners = _partner_map(after_report)
        before_countries = set(before_partners)
        after_countries = set(after_partners)
        changed_countries = sorted(
            country
            for country in before_countries | after_countries
            if before_partners.get(country) != after_partners.get(country)
        )

        report_added = before_report is None
        report_removed = after_report is None
        total_changed = total_change is not None and total_change["change"] != 0
        if not (report_added or report_removed or total_changed or changed_countries):
            continue

        report_deltas.append(
            {
                "trade_type": trade_type,
                "hs_code": hs_code,
                "report_added": report_added,
                "report_removed": report_removed,
                "total": total_change,
                "changed_partner_count": len(changed_countries),
                "added_partner_count": len(after_countries - before_countries),
                "removed_partner_count": len(before_countries - after_countries),
                "changed_partners": changed_countries,
            }
        )

    period, commodity_id, value_type = current_identity
    return {
        "period": period,
        "commodity_id": commodity_id,
        "value_type": value_type,
        "previous_retrieved_at": _retrieved_at(previous),
        "current_retrieved_at": _retrieved_at(current),
        "previous_report_dates": _report_dates(previous),
        "current_report_dates": _report_dates(current),
        "metric_deltas": metric_deltas,
        "changed_report_count": len(report_deltas),
        "report_deltas": report_deltas,
    }


def _load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _version_sort_key(doc: dict[str, Any]) -> tuple[str, str]:
    return _retrieved_at(doc) or "", json.dumps(_identity(doc), separators=(",", ":"))


def build_revision_summary(observation_root: Path, revision_root: Path) -> dict[str, Any]:
    """Build a deterministic summary for every observation that has archived versions."""
    entries: list[dict[str, Any]] = []
    if revision_root.exists():
        for period_dir in sorted(path for path in revision_root.iterdir() if path.is_dir()):
            period = period_dir.name
            for group_dir in sorted(path for path in period_dir.iterdir() if path.is_dir()):
                current_path = observation_root / period / f"{group_dir.name}.json"
                current = _load(current_path)
                if current is None:
                    continue

                archived = [
                    doc
                    for path in sorted(group_dir.glob("*.json"))
                    if (doc := _load(path)) is not None and _identity(doc) == _identity(current)
                ]
                if not archived:
                    continue

                versions = sorted([*archived, current], key=_version_sort_key)
                changes = [
                    compare_observations(before, after)
                    for before, after in zip(versions, versions[1:])
                ]
                entries.append(
                    {
                        "period": current.get("period"),
                        "commodity_id": current.get("commodity", {}).get("id"),
                        "value_type": current.get("value_type", "usd"),
                        "version_count": len(versions),
                        "archived_version_count": len(archived),
                        "first_retrieved_at": _retrieved_at(versions[0]),
                        "latest_retrieved_at": _retrieved_at(versions[-1]),
                        "changes": changes,
                    }
                )

    entries.sort(key=lambda item: (item["period"], item["commodity_id"], item["value_type"]))
    return {
        "schema_version": 1,
        "revision_group_count": len(entries),
        "entries": entries,
    }
