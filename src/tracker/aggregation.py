from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def _sum(values: Iterable[float | None]) -> float:
    return round(sum(v for v in values if v is not None), 6)


def _sum_optional(values: Iterable[float | None]) -> float | None:
    known = [float(v) for v in values if v is not None]
    if not known:
        return None
    return round(sum(known), 6)


def _growth_pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


def _partner_rollup(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_country: dict[str, float] = defaultdict(float)
    for report in reports:
        for row in report.get("rows", []):
            value = row.get("value")
            if value is not None and value > 0:
                by_country[row["partner_country"]] += float(value)
    return [
        {"partner_country": country, "value": round(value, 6)}
        for country, value in sorted(by_country.items(), key=lambda item: item[1], reverse=True)
    ]


def concentration_metrics(partners: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(float(p.get("value") or 0) for p in partners)
    if total <= 0:
        return {"top_partner_share_pct": None, "hhi": None, "top_partners": []}
    shares = [float(p.get("value") or 0) / total for p in partners if (p.get("value") or 0) > 0]
    hhi = sum((share * 100) ** 2 for share in shares)
    top = []
    for p in partners[:5]:
        top.append({
            "partner_country": p["partner_country"],
            "value": round(float(p["value"]), 4),
            "share_pct": round(float(p["value"]) / total * 100, 2),
        })
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


def _trade_period_metrics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    current = _sum(r.get("totals", {}).get("value") for r in reports)
    previous = _sum_optional(r.get("totals", {}).get("previous_year_value") for r in reports)
    cumulative = _sum_optional(r.get("totals", {}).get("cumulative_value") for r in reports)
    cumulative_previous = _sum_optional(
        r.get("totals", {}).get("cumulative_previous_year_value") for r in reports
    )
    return {
        "current": round(current, 4),
        "previous_year": round(previous, 4) if previous is not None else None,
        "yoy_pct": _growth_pct(current, previous),
        "ytd": round(cumulative, 4) if cumulative is not None else None,
        "ytd_previous_year": round(cumulative_previous, 4) if cumulative_previous is not None else None,
        "ytd_yoy_pct": _growth_pct(cumulative, cumulative_previous),
    }


def aggregate_commodity(reports: list[dict[str, Any]]) -> dict[str, Any]:
    imports = [r for r in reports if r.get("trade_type") == "import"]
    exports = [r for r in reports if r.get("trade_type") == "export"]
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
        "ytd_imports_previous_year": import_period["ytd_previous_year"],
        "ytd_exports_previous_year": export_period["ytd_previous_year"],
        "ytd_import_yoy_pct": import_period["ytd_yoy_pct"],
        "ytd_export_yoy_pct": export_period["ytd_yoy_pct"],
        "unit": "USD million",
        "supplier_concentration": supplier_metrics,
        "export_destination_concentration": destination_metrics,
        "dependency": dependency_score(import_value, export_value, supplier_metrics),
    }


def _dedupe_union_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one report per trade type/HS code, then drop child codes covered by a shorter tracked prefix."""
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for report in reports:
        key = (report.get("trade_type", ""), report.get("hs_code", ""))
        if key[0] and key[1]:
            unique[key] = report

    output: list[dict[str, Any]] = []
    for trade_type in {key[0] for key in unique}:
        codes = sorted({key[1] for key in unique if key[0] == trade_type}, key=lambda x: (len(x), x))
        kept: list[str] = []
        for code in codes:
            if any(code.startswith(parent) for parent in kept):
                continue
            kept.append(code)
            output.append(unique[(trade_type, code)])
    return output


def portfolio_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    union = _dedupe_union_reports(reports)
    imports = [r for r in union if r.get("trade_type") == "import"]
    exports = [r for r in union if r.get("trade_type") == "export"]
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
        "included_hs_codes": sorted({r["hs_code"] for r in union}, key=lambda x: (len(x), x)),
    }
