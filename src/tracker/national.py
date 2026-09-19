from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from src.tracker.tradestat import BASE_URL, TradeStatClient, TradeStatError, parse_csrf_token


class NationalDataError(TradeStatError):
    """An official national report could not be verified as complete."""


SCHEMA_VERSION = 1
SCOPE = "merchandise"
VALUE_UNIT = "USD million"
PROVIDER = "DGCI&S / Department of Commerce, Government of India"
SYSTEM = "TradeStat MEIDB"
PERIOD_RE = re.compile(r"^(20\d{2})-(0[1-9]|1[0-2])$")
ENDPOINTS = {
    ("chapters", "import"): "/meidb/commoditywise_import",
    ("chapters", "export"): "/meidb/commoditywise_export",
    ("partners", "import"): "/meidb/country_wise_import",
    ("partners", "export"): "/meidb/country_wise_export",
}
PREFIXES = {
    ("chapters", "import"): "imdd",
    ("chapters", "export"): "dd",
    ("partners", "import"): "cwim",
    ("partners", "export"): "cwe",
}
VALUE_KEYS = (
    "previous_year_value", "value", "yoy_pct", "cumulative_previous_year_value",
    "cumulative_value", "cumulative_yoy_pct",
)
AMOUNT_KEYS = ("previous_year_value", "value", "cumulative_previous_year_value", "cumulative_value")
VOLATILE_KEYS = {"retrieved_at", "report_date", "generated_at", "checked_at"}
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def period_parts(period: str) -> tuple[int, int]:
    match = PERIOD_RE.fullmatch(period or "")
    if match is None or int(match[1]) < 2018:
        raise ValueError("period must be YYYY-MM within MEIDB coverage from January 2018")
    return int(match[1]), int(match[2])


def iter_periods(start: str, end: str):
    year, month = period_parts(start)
    period_parts(end)
    if start > end:
        raise ValueError("start-period must not be after end-period")
    while (period := f"{year:04d}-{month:02d}") <= end:
        yield period
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _query_identity(kind: str, trade_type: str) -> tuple[str, str]:
    key = (kind, trade_type)
    if key not in ENDPOINTS:
        raise ValueError("kind must be chapters/partners and trade_type must be import/export")
    return key


def build_payload(*, kind: str, trade_type: str, period: str, token: str) -> dict[str, str]:
    key = _query_identity(kind, trade_type)
    year, month = period_parts(period)
    prefix = PREFIXES[key]
    payload = {
        "_token": token,
        f"{prefix}Month": str(month),
        f"{prefix}Year": str(year),
        f"{prefix}ReportVal": "1",
        f"{prefix}ReportYear": "2",
    }
    if kind == "chapters":
        payload.update({f"{prefix}CommodityLevel": "2", "comlev": "all", "comval": ""})
    else:
        payload[f"{prefix}Country"] = "all"
    return payload


def validate_form_contract(html: str, *, kind: str, trade_type: str) -> None:
    prefix = PREFIXES[_query_identity(kind, trade_type)]
    soup = BeautifulSoup(html, "html.parser")
    expected = {
        f"{prefix}ReportVal": ("1", ("us", "million")),
        f"{prefix}ReportYear": ("2", ("calendar",)),
    }
    expected[f"{prefix}{'CommodityLevel' if kind == 'chapters' else 'Country'}"] = (
        "2" if kind == "chapters" else "all", ("2",) if kind == "chapters" else ("all",),
    )
    for name, (value, terms) in expected.items():
        select = soup.find("select", attrs={"name": name})
        option = select.find("option", attrs={"value": value}) if select else None
        label = " ".join(option.get_text(" ", strip=True).lower().split()) if option else ""
        if not label or not all(term in label for term in terms):
            raise NationalDataError(f"National report form contract changed: {name}={value!r} ({label!r})")
    for name in (f"{prefix}Month", f"{prefix}Year"):
        if soup.find("select", attrs={"name": name}) is None:
            raise NationalDataError(f"National report form is missing {name}")


def _number(value: str) -> float | None:
    text = value.strip().replace(",", "").replace("\u2212", "-").rstrip("%")
    if text.upper() in {"", "-", "--", "---", "NA", "N/A", "NIL"}:
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise NationalDataError(f"Invalid numeric value in national report: {value!r}") from exc
    if not math.isfinite(number):
        raise NationalDataError(f"Non-finite numeric value in national report: {value!r}")
    return number


def _is_number(value: Any) -> bool:
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def _semantic(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _semantic(item) for key, item in value.items() if key not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_semantic(item) for item in value]
    return value


def semantic_fingerprint(value: dict[str, Any]) -> str:
    content = json.dumps(_semantic(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rounded(value: float) -> float:
    return round(value, 6)


def _difference(exports: Any, imports: Any) -> float | None:
    return _rounded(exports - imports) if _is_number(exports) and _is_number(imports) else None


def _sum_both(imports: Any, exports: Any) -> float | None:
    return _rounded(imports + exports) if _is_number(imports) and _is_number(exports) else None


def _source_date(text: str) -> str | None:
    match = re.search(r"Data\s+last\s+updated\s+on:\s*(\d{1,2}/\d{1,2}/\d{4})", text, flags=re.I)
    return match[1] if match else None


def _validate_headers(headers: list[str], *, kind: str, period: str) -> None:
    year, month = period_parts(period)
    prefix_count = 3 if kind == "chapters" else 2
    if len(headers) != prefix_count + 6:
        raise NationalDataError(f"Unexpected national table column count: {len(headers)}")
    identity_label = re.sub(r"[^a-z]", "", headers[1].lower())
    if identity_label != ("hscode" if kind == "chapters" else "country"):
        raise NationalDataError("National report table has the wrong breakdown columns")
    for offset, expected_year in ((0, year - 1), (1, year)):
        pattern = rf"\b{MONTH_NAMES[month - 1]}[\s-]*{expected_year}\b"
        if not re.search(pattern, headers[prefix_count + offset], flags=re.I):
            raise NationalDataError(f"National report month/year header does not match {period}")
        cumulative = re.sub(r"\s+", "", headers[prefix_count + offset + 3])
        cumulative_pattern = rf"^Jan-{MONTH_NAMES[month - 1]}-?{expected_year}(?:\([RF]\))?$"
        if not re.fullmatch(cumulative_pattern, cumulative, flags=re.I):
            raise NationalDataError("National report cumulative columns are not the requested calendar YTD")
    if any("growth" not in headers[prefix_count + offset].lower() for offset in (2, 5)):
        raise NationalDataError("National report growth columns changed")


def _validate_report(report: dict[str, Any]) -> None:
    kind, trade_type = _query_identity(report.get("kind"), report.get("trade_type"))
    period = report.get("period")
    period_parts(period)
    if report.get("scope") != SCOPE or report.get("value_unit") != VALUE_UNIT or report.get("year_type") != "calendar":
        raise NationalDataError("National report scope, value unit, or year type is incorrect")
    if report.get("value_selector_code") != "1":
        raise NationalDataError("National report must use the verified USD selector")
    _validate_headers(report.get("headers", []), kind=kind, period=period)
    rows, totals = report.get("rows"), report.get("totals")
    if not isinstance(rows, list) or not rows or not isinstance(totals, dict):
        raise NationalDataError("National report requires rows and an explicit official total")
    identities = set()
    ranks = []
    for row in rows:
        code, name = row.get("code"), row.get("name")
        if not isinstance(name, str) or not name.strip():
            raise NationalDataError("National report has an empty row name")
        if kind == "chapters" and (not isinstance(code, str) or not re.fullmatch(r"\d{2}", code) or code == "00"):
            raise NationalDataError(f"Invalid HS2 chapter code: {code!r}")
        if kind == "partners" and code is not None:
            raise NationalDataError("Country-wise report does not publish country codes")
        identity = code if kind == "chapters" else name
        if identity in identities:
            raise NationalDataError(f"Duplicate {kind} row: {identity}")
        identities.add(identity)
        ranks.append(row.get("rank"))
    if sorted(ranks) != list(range(1, len(rows) + 1)):
        raise NationalDataError("National report row sequence is incomplete or duplicated")
    for row in [*rows, totals]:
        for key in VALUE_KEYS:
            value = row.get(key)
            if key in AMOUNT_KEYS:
                if not _is_number(value) or value < 0:
                    raise NationalDataError(f"National report {key} must be a finite, nonnegative amount")
            elif value is not None and not _is_number(value):
                raise NationalDataError(f"National report {key} must be finite or unavailable")
    # Every amount is displayed with two decimals in the verified MEIDB tables.
    # Each rounded row and the rounded official total may differ by half a unit
    # in the last displayed decimal place; do not use a percentage tolerance.
    tolerance = (len(rows) + 1) * 0.005 + 1e-7
    for key in AMOUNT_KEYS:
        difference = abs(math.fsum(row[key] for row in rows) - totals[key])
        if difference > tolerance:
            raise NationalDataError(f"National {kind} {trade_type} {key} rows do not reconcile: difference {difference:.6f}, rounding tolerance {tolerance:.6f}")
    if totals["value"] <= 0 or totals["cumulative_value"] <= 0:
        raise NationalDataError("National totals must be positive for a published merchandise month")
    source = report.get("source") or {}
    if not source.get("retrieved_at") or source.get("url") != BASE_URL + ENDPOINTS[(kind, trade_type)]:
        raise NationalDataError("National report is missing its official source provenance")


def parse_report(
    html: str, *, kind: str, trade_type: str, period: str,
    source_url: str | None = None, retrieved_at: str | None = None,
) -> dict[str, Any]:
    key = _query_identity(kind, trade_type)
    expected_query = build_payload(kind=kind, trade_type=trade_type, period=period, token="")
    prefix = PREFIXES[key]
    soup = BeautifulSoup(html, "html.parser")
    text = " ".join(soup.get_text(" ", strip=True).split())
    table = soup.find("table", id="example1")
    if table is None:
        raise NationalDataError("Official national report result table is missing; refusing to publish a zero total")
    if not re.search(r"Values\s+in\s+US\s*\$\s*Million", text, flags=re.I):
        raise NationalDataError("Official national report does not confirm values in USD million")
    validate_form_contract(html, kind=kind, trade_type=trade_type)
    for name, value in expected_query.items():
        if name in {"_token", "comval"}:
            continue
        if name == "comlev":
            selected = soup.find("input", attrs={"name": name, "checked": True})
        else:
            select = soup.find("select", attrs={"name": name})
            selected = (select.find("option", selected=True) or select.find("option")) if select else None
        if selected is None or str(selected.get("value")) != value:
            raise NationalDataError(f"Official national report selection does not match requested {name}={value}")
    header = table.find("tr")
    headers = [" ".join(cell.get_text(" ", strip=True).split()) for cell in header.find_all(["th", "td"])] if header else []
    _validate_headers(headers, kind=kind, period=period)
    prefix_count = 3 if kind == "chapters" else 2
    expected_total_name = f"India's Total {trade_type.title()}"
    rows = []
    totals = None
    for tr in table.find_all("tr")[1:]:
        cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in tr.find_all("td")]
        if not cells:
            continue
        if len(cells) != prefix_count + 6:
            raise NationalDataError("National report contains a truncated or unexpected result row")
        numeric = dict(zip(VALUE_KEYS, (_number(value) for value in cells[prefix_count:]), strict=True))
        if cells[prefix_count - 1] == expected_total_name:
            if totals is not None:
                raise NationalDataError("National report contains multiple official total rows")
            totals = numeric
        else:
            if not cells[0].isdigit():
                raise NationalDataError("National report row is neither a numbered item nor the expected official total")
            rows.append({
                "rank": int(cells[0]), "code": cells[1] if kind == "chapters" else None,
                "name": cells[prefix_count - 1], **numeric,
            })
    if totals is None:
        raise NationalDataError("National report has no explicit official total")
    report_date = re.search(r"Report\s+Dated:\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text, flags=re.I)
    report = {
        "schema_version": SCHEMA_VERSION, "scope": SCOPE, "period": period,
        "kind": kind, "trade_type": trade_type, "value_unit": VALUE_UNIT,
        "value_selector_code": "1", "year_type": "calendar",
        "headers": headers, "rows": rows, "totals": totals,
        "source": {
            "provider": PROVIDER, "system": SYSTEM, "url": source_url or BASE_URL + ENDPOINTS[key],
            "last_updated": _source_date(text), "report_date": report_date[1] if report_date else None,
            "retrieved_at": retrieved_at or _utcnow(),
            "checksum_sha256": semantic_fingerprint({"headers": headers, "rows": rows, "totals": totals}),
        },
    }
    _validate_report(report)
    return report


def validate_observation(observation: dict[str, Any]) -> None:
    period_parts(observation.get("period"))
    if observation.get("schema_version") != SCHEMA_VERSION or observation.get("status") != "ok":
        raise NationalDataError("National observation schema/status is incorrect")
    if observation.get("scope") != SCOPE or observation.get("value_unit") != VALUE_UNIT or observation.get("year_type") != "calendar":
        raise NationalDataError("National observation scope, unit, or year type is incorrect")
    reports = observation.get("reports")
    if not isinstance(reports, list) or len(reports) != 4:
        raise NationalDataError("A national month requires all four official reports")
    report_map = _report_map(observation)
    if set(report_map) != set(ENDPOINTS):
        raise NationalDataError("A national month has duplicated or missing chapter/country trade directions")
    for report in reports:
        if report.get("period") != observation["period"]:
            raise NationalDataError("National report period does not match its observation")
        _validate_report(report)
    for trade_type in ("import", "export"):
        chapters = report_map[("chapters", trade_type)]["totals"]
        partners = report_map[("partners", trade_type)]["totals"]
        for key in AMOUNT_KEYS:
            if abs(chapters[key] - partners[key]) > 0.0100001:
                raise NationalDataError(f"National chapter and country {trade_type} totals disagree for {key}")


def _write_json(path: Path, value: dict[str, Any], *, compact: bool = False) -> None:
    content = json.dumps(
        value, indent=None if compact else 2, separators=(",", ":") if compact else None,
        ensure_ascii=False, allow_nan=False,
    ) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def fetch_report(client: TradeStatClient, *, kind: str, trade_type: str, period: str) -> dict[str, Any]:
    endpoint = client.base_url + ENDPOINTS[_query_identity(kind, trade_type)]
    landing = client._request("GET", endpoint)
    validate_form_contract(landing.text, kind=kind, trade_type=trade_type)
    payload = build_payload(kind=kind, trade_type=trade_type, period=period, token=parse_csrf_token(landing.text))
    response = client._request("POST", endpoint, data=payload)
    report = parse_report(response.text, kind=kind, trade_type=trade_type, period=period, source_url=endpoint)
    if client.delay_seconds:
        time.sleep(client.delay_seconds)
    return report


def fetch_month(client: TradeStatClient, period: str) -> dict[str, Any]:
    reports = []
    for kind, trade_type in ENDPOINTS:
        report = fetch_report(client, kind=kind, trade_type=trade_type, period=period)
        reports.append(report)
        print(f"OK national {period} {kind} {trade_type}: {len(report['rows'])} rows", flush=True)
    observation = {
        "schema_version": SCHEMA_VERSION, "scope": SCOPE, "period": period,
        "status": "ok", "value_unit": VALUE_UNIT, "year_type": "calendar", "reports": reports,
    }
    validate_observation(observation)
    return observation


def write_observation(observation: dict[str, Any], output_root: Path) -> bool:
    validate_observation(observation)
    path = output_root / "observations" / f"{observation['period']}.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        before = semantic_fingerprint(previous)
        if before == semantic_fingerprint(observation):
            return False
        _write_json(output_root / "revisions" / observation["period"] / f"{before}.json", previous)
    _write_json(path, observation)
    return True


def _report_map(observation: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(report.get("kind"), report.get("trade_type")): report for report in observation.get("reports", [])}


def build_month_snapshot(observation: dict[str, Any]) -> dict[str, Any]:
    validate_observation(observation)
    reports = _report_map(observation)
    imported = reports[("chapters", "import")]["totals"]
    exported = reports[("chapters", "export")]["totals"]
    previous_trade = _sum_both(imported["previous_year_value"], exported["previous_year_value"])
    current_trade = _sum_both(imported["value"], exported["value"])
    summary = {
        "period": observation["period"], "imports": imported["value"], "exports": exported["value"],
        "balance": _difference(exported["value"], imported["value"]),
        "total_trade": current_trade,
        "previous_year_imports": imported["previous_year_value"],
        "previous_year_exports": exported["previous_year_value"],
        "total_trade_yoy_pct": round((current_trade / previous_trade - 1) * 100, 2) if previous_trade else None,
        "import_yoy_pct": imported["yoy_pct"], "export_yoy_pct": exported["yoy_pct"],
        "ytd_imports": imported["cumulative_value"], "ytd_exports": exported["cumulative_value"],
    }
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "scope": SCOPE, "period": observation["period"],
        "value_unit": VALUE_UNIT, "year_type": "calendar", "summary": summary,
    }
    for kind in ("chapters", "partners"):
        def row_key(row):
            return row["code"] if kind == "chapters" else row["name"]
        imports = {row_key(row): row for row in reports[(kind, "import")]["rows"]}
        exports = {row_key(row): row for row in reports[(kind, "export")]["rows"]}
        merged = []
        for key in sorted(set(imports) | set(exports)):
            im, ex = imports.get(key, {}), exports.get(key, {})
            exemplar = im or ex
            merged.append({
                "code": exemplar["code"], "name": exemplar["name"],
                "imports": im.get("value"), "exports": ex.get("value"),
                "balance": _difference(ex.get("value"), im.get("value")),
                "import_yoy_pct": im.get("yoy_pct"), "export_yoy_pct": ex.get("yoy_pct"),
            })
        snapshot[kind] = merged
    sources = [report["source"] for report in observation["reports"]]
    snapshot["provenance"] = {
        "provider": PROVIDER, "system": SYSTEM,
        "retrieved_at": max(source["retrieved_at"] for source in sources),
        "last_updated": sources[0].get("last_updated"),
        "reports": [{"kind": report["kind"], "trade_type": report["trade_type"], **report["source"]} for report in observation["reports"]],
        "reconciliation": "Official chapter and country totals agree; published rows reconcile within display rounding.",
    }
    return snapshot


def _coverage(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    periods = [snapshot["period"] for snapshot in snapshots]
    present = set(periods)
    latest = snapshots[-1] if snapshots else None
    expected = list(iter_periods(periods[0], periods[-1])) if periods else []
    return {
        "first_period": periods[0] if periods else None, "last_period": periods[-1] if periods else None,
        "period_count": len(periods), "expected_month_count": len(expected),
        "missing_periods": [period for period in expected if period not in present],
        "chapter_count": len(latest["chapters"]) if latest else 0,
        "partner_count": len(latest["partners"]) if latest else 0,
        "source_first_period": "2018-01",
    }


def build_national_dashboard(output_root: Path, source_status: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshots = []
    for path in sorted((output_root / "observations").glob("*.json")):
        observation = json.loads(path.read_text(encoding="utf-8"))
        snapshot = build_month_snapshot(observation)
        if path.stem != snapshot["period"]:
            raise NationalDataError(f"Observation filename/period mismatch: {path}")
        snapshots.append(snapshot)
        _write_json(output_root / "months" / f"{snapshot['period']}.json", snapshot, compact=True)
    periods = [snapshot["period"] for snapshot in snapshots]
    latest = snapshots[-1] if snapshots else None
    source_status = source_status or {}
    source = {
        "provider": PROVIDER, "system": SYSTEM, "value_unit": VALUE_UNIT, "year_type": "calendar",
        "urls": {f"{kind}_{trade_type}": BASE_URL + endpoint for (kind, trade_type), endpoint in ENDPOINTS.items()},
        "last_updated": source_status.get("last_updated") or (latest or {}).get("provenance", {}).get("last_updated"),
        "final_through": source_status.get("final_through"),
        "revised_final_through": source_status.get("revised_final_through"),
        "classification_warning": source_status.get("classification_warning"),
        "retrieved_at": (latest or {}).get("provenance", {}).get("retrieved_at"),
    }
    dashboard = {
        "schema_version": SCHEMA_VERSION, "scope": SCOPE, "value_unit": VALUE_UNIT,
        "year_type": "calendar", "status": "ok" if snapshots else "awaiting_trade_ingestion",
        "as_of": periods[-1] if periods else None,
        "monthly": [snapshot["summary"] for snapshot in snapshots],
        "source": source,
        "coverage": _coverage(snapshots),
    }
    _write_json(output_root / "dashboard.json", dashboard, compact=True)
    return dashboard


def validate_national_data(output_root: Path) -> list[str]:
    """Return actionable validation errors without changing repository files."""
    errors = []
    observations = {}
    for path in sorted((output_root / "observations").glob("*.json")):
        try:
            observation = json.loads(path.read_text(encoding="utf-8"))
            validate_observation(observation)
            if path.stem != observation["period"]:
                raise NationalDataError("filename does not match observation period")
            expected = build_month_snapshot(observation)
            month_path = output_root / "months" / path.name
            actual = json.loads(month_path.read_text(encoding="utf-8"))
            if expected != actual:
                raise NationalDataError("display snapshot is stale or differs from the canonical reports")
            observations[observation["period"]] = expected
        except (OSError, ValueError, KeyError, TypeError, NationalDataError) as exc:
            errors.append(f"{path}: {exc}")
    try:
        dashboard = json.loads((output_root / "dashboard.json").read_text(encoding="utf-8"))
        periods = sorted(observations)
        if not periods:
            raise NationalDataError("national dashboard requires at least one complete verified observation")
        if dashboard.get("schema_version") != SCHEMA_VERSION or dashboard.get("status") != "ok":
            raise NationalDataError("dashboard schema/status is incorrect")
        if dashboard.get("scope") != SCOPE or dashboard.get("value_unit") != VALUE_UNIT or dashboard.get("year_type") != "calendar":
            raise NationalDataError("dashboard scope or unit is incorrect")
        if dashboard.get("as_of") != (periods[-1] if periods else None):
            raise NationalDataError("dashboard latest period is incorrect")
        if dashboard.get("monthly") != [observations[period]["summary"] for period in periods]:
            raise NationalDataError("dashboard monthly series is stale or differs from the canonical reports")
        expected_coverage = _coverage([observations[period] for period in periods])
        if dashboard.get("coverage") != expected_coverage:
            raise NationalDataError("dashboard coverage counts or missing periods differ from stored observations")
        source = dashboard.get("source") or {}
        if source.get("value_unit") != VALUE_UNIT or source.get("year_type") != "calendar":
            raise NationalDataError("dashboard source unit or year type is incorrect")
        expected_urls = {f"{kind}_{trade_type}": BASE_URL + endpoint for (kind, trade_type), endpoint in ENDPOINTS.items()}
        if source.get("urls") != expected_urls:
            raise NationalDataError("dashboard source URLs do not identify the official national reports")
        orphan_months = {path.stem for path in (output_root / "months").glob("*.json")} - set(periods)
        if orphan_months:
            raise NationalDataError(f"display snapshots without canonical observations: {sorted(orphan_months)}")
    except (OSError, ValueError, KeyError, TypeError, NationalDataError) as exc:
        errors.append(f"{output_root / 'dashboard.json'}: {exc}")
    return errors
