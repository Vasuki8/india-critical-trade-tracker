from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def _sum(values: Iterable[float | None]) -> float:
    return round(sum(v for v in values if v is not None), 6)


def _sum_optional(values: Iterable[float | None]) -> float | None:
    total = 0.0
    seen = False
    for value in values:
        if value is None:
            continue
        total += float(value)
        seen = True
    return round(total, 6) if seen else None


def _growth_pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


def _partner_rollup(reports: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_country: dict[str, float] = defaultdict(float)
    for report in reports:
        for row in report.get("rows", []):
            value = row.get("value")
            if value is not None and value > 0:
                by_country[row["partner_country"]] += float(value)

    ordered = sorted(by_country.items(), key=lambda item: item[1], reverse=True)
    total = sum(value for _, value in ordered)
    return [
        {
            "partner_country": country,
            "value": round(value, 6),
            "share_pct": round(value / total * 100, 2) if total > 0 else None,
        }
        for country, value in ordered
    ]


def concentration_metrics(partners: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(float(partner.get("value") or 0) for partner in partners)
    if total <= 0:
        return {"top_partner_share_pct": None, "hhi": None, "top_partners": []}

    hhi = 0.0
    top: list[dict[str, Any]] = []
    for index, partner in enumerate(partners):
        value = float(partner.get("value") or 0)
        if value <= 0:
            continue
        share_pct = value / total * 100
        hhi += share_pct * share_pct
        if index < 5:
            top.append(
                {
                    "partner_country": partner["partner_country"],
                    "value": round(value, 4),
                    "share_pct": round(share_pct, 2),
                }
            )
    return {
        "top_partner_share_pct": top[0]["share_pct"] if top else None,
        "hhi": round(hhi, 1),
        "top_partners": top,
    }


def dependency_score(import_value: float, export_value: float, supplier_metrics: dict[str, Any]) -> dict[str, Any]:
    if import_value <= 0:
        return {"score": None, "risk": "not_available", "import_reliance_pct": None}
    net_import = max(import_value - export_value, 0.0)
    import_reliance = min(max(net_import / import_value, 0.0), 1.0)
    top_share = (supplier_metrics.get("top_partner_share_pct") or 0.0) / 100.0
    hhi_component = min((supplier_metrics.get("hhi") or 0.0) / 10000.0, 1.0)
    score = 100 * (0.60 * import_reliance + 0.25 * top_share + 0.15 * hhi_component)
    score = round(score, 1)
    risk = "high" if score >= 70 else "moderate" if score >= 45 else "low"
    return {
        "score": score,
        "risk": risk,
        "import_reliance_pct": round(import_reliance * 100, 2),
        "method": "60% net-import reliance + 25% top-supplier share + 15% supplier HHI",
    }


def _trade_period_metrics(reports: Iterable[dict[str, Any]]) -> dict[str, Any]:
    current = 0.0
    previous = 0.0
    cumulative = 0.0
    cumulative_previous = 0.0
    has_previous = False
    has_cumulative = False
    has_cumulative_previous = False

    for report in reports:
        totals = report.get("totals", {})
        value = totals.get("value")
        if value is not None:
            current += float(value)

        value = totals.get("previous_year_value")
        if value is not None:
            previous += float(value)
            has_previous = True

        value = totals.get("cumulative_value")
        if value is not None:
            cumulative += float(value)
            has_cumulative = True

        value = totals.get("cumulative_previous_year_value")
        if value is not None:
            cumulative_previous += float(value)
            has_cumulative_previous = True

    current = round(current, 6)
    previous_value = round(previous, 6) if has_previous else None
    cumulative_value = round(cumulative, 6) if has_cumulative else None
    cumulative_previous_value = round(cumulative_previous, 6) if has_cumulative_previous else None
    return {
        "current": round(current, 4),
        "previous_year": round(previous_value, 4) if previous_value is not None else None,
        "yoy_pct": _growth_pct(current, previous_value),
        "ytd": round(cumulative_value, 4) if cumulative_value is not None else None,
        "ytd_previous_year": round(cumulative_previous_value, 4) if cumulative_previous_value is not None else None,
        "ytd_yoy_pct": _growth_pct(cumulative_value, cumulative_previous_value),
    }


def aggregate_commodity_details(
    reports: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Aggregate one commodity in a single report-partition pass.

    The returned partner rollups are reused by the intelligence builder, avoiding
    a second traversal and sort of every partner-country row.
    """
    imports: list[dict[str, Any]] = []
    exports: list[dict[str, Any]] = []
    for report in reports:
        trade_type = report.get("trade_type")
        if trade_type == "import":
            imports.append(report)
        elif trade_type == "export":
            exports.append(report)

    import_period = _trade_period_metrics(imports)
    export_period = _trade_period_metrics(exports)
    import_value = import_period["current"]
    export_value = export_period["current"]
    suppliers = _partner_rollup(imports)
    destinations = _partner_rollup(exports)
    supplier_metrics = concentration_metrics(suppliers)
    destination_metrics = concentration_metrics(destinations)
    ytd_balance = None
    if import_period["ytd"] is not None and export_period["ytd"] is not None:
        ytd_balance = round(export_period["ytd"] - import_period["ytd"], 4)

    metrics = {
        "imports": round(import_value, 4),
        "exports": round(export_value, 4),
        "balance": round(export_value - import_value, 4),
        "import_previous_year": import_period["previous_year"],
        "export_previous_year": export_period["previous_year"],
        "import_yoy_pct": import_period["yoy_pct"],
        "export_yoy_pct": export_period["yoy_pct"],
        "ytd_imports": import_period["ytd"],
        "ytd_exports": export_period["ytd"],
        "ytd_balance": ytd_balance,
        "ytd_imports_previous_year": import_period["ytd_previous_year"],
        "ytd_exports_previous_year": export_period["ytd_previous_year"],
        "ytd_import_yoy_pct": import_period["ytd_yoy_pct"],
        "ytd_export_yoy_pct": export_period["ytd_yoy_pct"],
        "unit": "USD million",
        "supplier_concentration": supplier_metrics,
        "export_destination_concentration": destination_metrics,
        "dependency": dependency_score(import_value, export_value, supplier_metrics),
    }
    return metrics, suppliers, destinations


def aggregate_commodity(reports: Iterable[dict[str, Any]]) -> dict[str, Any]:
    metrics, _suppliers, _destinations = aggregate_commodity_details(reports)
    return metrics


def _dedupe_union_reports(reports: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one report per trade type/HS code, then drop children covered by a shorter prefix."""
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for report in reports:
        key = (str(report.get("trade_type") or ""), str(report.get("hs_code") or ""))
        if key[0] and key[1]:
            unique[key] = report

    by_trade: dict[str, list[str]] = defaultdict(list)
    for trade_type, hs_code in unique:
        by_trade[trade_type].append(hs_code)

    output: list[dict[str, Any]] = []
    for trade_type in sorted(by_trade):
        codes = sorted(set(by_trade[trade_type]), key=lambda code: (len(code), code))
        kept: list[str] = []
        for code in codes:
            if any(code.startswith(parent) for parent in kept):
                continue
            kept.append(code)
            output.append(unique[(trade_type, code)])
    return output


def portfolio_summary(reports: Iterable[dict[str, Any]]) -> dict[str, Any]:
    union = _dedupe_union_reports(reports)
    imports: list[dict[str, Any]] = []
    exports: list[dict[str, Any]] = []
    for report in union:
        if report.get("trade_type") == "import":
            imports.append(report)
        elif report.get("trade_type") == "export":
            exports.append(report)

    import_period = _trade_period_metrics(imports)
    export_period = _trade_period_metrics(exports)
    import_value = import_period["current"]
    export_value = export_period["current"]
    ytd_balance = None
    if import_period["ytd"] is not None and export_period["ytd"] is not None:
        ytd_balance = round(export_period["ytd"] - import_period["ytd"], 4)
    return {
        "imports": round(import_value, 4),
        "exports": round(export_value, 4),
        "balance": round(export_value - import_value, 4),
        "import_previous_year": import_period["previous_year"],
        "export_previous_year": export_period["previous_year"],
        "import_yoy_pct": import_period["yoy_pct"],
        "export_yoy_pct": export_period["yoy_pct"],
        "ytd_imports": import_period["ytd"],
        "ytd_exports": export_period["ytd"],
        "ytd_balance": ytd_balance,
        "ytd_import_yoy_pct": import_period["ytd_yoy_pct"],
        "ytd_export_yoy_pct": export_period["ytd_yoy_pct"],
        "unit": "USD million",
        "coverage_method": "unique shortest-HS-prefix union to prevent parent/child double counting",
        "included_hs_codes": sorted({r["hs_code"] for r in union}, key=lambda code: (len(code), code)),
    }
