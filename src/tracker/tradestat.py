from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://tradestat.commerce.gov.in"
ENDPOINTS = {
    "export": "/meidb/commodity_wise_all_countries_export",
    "import": "/meidb/commodity_wise_all_countries_import",
}
FIELDS = {
    "export": {
        "hscode": "cwacexHSCODE",
        "month": "cwacexMonth",
        "year": "cwacexYear",
        "value_type": "cwacexReportVal",
        "year_type": "cwacexReportYear",
    },
    "import": {
        "hscode": "cwacimHSCODE",
        "month": "cwacimMonth",
        "year": "cwacimYear",
        "value_type": "cwacimReportVal",
        "year_type": "cwacimReportYear",
    },
}
VALUE_TYPES = {"usd": "1", "inr": "2", "quantity": "3"}
YEAR_TYPES = {"financial": "1", "calendar": "2"}
VALUE_UNITS = {"usd": "USD million", "inr": "INR crore", "quantity": "source unit"}
VALID_HS_LENGTHS = {2, 4, 6, 8}
NO_DATA_MARKERS = (
    "no result found",
    "no results found",
    "no data found",
    "no record found",
    "no records found",
)


class TradeStatError(RuntimeError):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _number(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = text.strip().replace(",", "").replace("−", "-")
    if not cleaned or cleaned.upper() in {"-", "NA", "N/A", "NIL"}:
        return None
    cleaned = cleaned.replace("%", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def validate_query(hscode: str, month: int, year: int, value_type: str, year_type: str) -> None:
    if not hscode.isdigit() or len(hscode) not in VALID_HS_LENGTHS:
        raise ValueError(f"HS code must be 2, 4, 6 or 8 digits; got {hscode!r}")
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")
    if year < 2018:
        raise ValueError("MEIDB monthly data starts in 2018")
    if value_type not in VALUE_TYPES:
        raise ValueError(f"unsupported value_type {value_type!r}")
    if year_type not in YEAR_TYPES:
        raise ValueError(f"unsupported year_type {year_type!r}")
    if value_type == "quantity" and len(hscode) != 8:
        raise ValueError("TradeStat exposes quantity only for 8-digit HS codes")


def build_payload(
    *, trade_type: str, token: str, hscode: str, month: int, year: int,
    value_type: str = "usd", year_type: str = "calendar",
) -> dict[str, str]:
    trade_type = trade_type.lower()
    if trade_type not in ENDPOINTS:
        raise ValueError("trade_type must be 'import' or 'export'")
    validate_query(hscode, month, year, value_type, year_type)
    f = FIELDS[trade_type]
    return {
        "_token": token,
        f["hscode"]: hscode,
        f["month"]: str(month),
        f["year"]: str(year),
        f["value_type"]: VALUE_TYPES[value_type],
        f["year_type"]: YEAR_TYPES[year_type],
    }


def parse_csrf_token(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find("input", attrs={"name": "_token"})
    if node is None or not node.get("value"):
        raise TradeStatError("TradeStat CSRF token not found; page contract may have changed")
    return str(node["value"])


def _find_result_table(soup: BeautifulSoup):
    table = soup.find("table", id="example1")
    if table is not None:
        return table
    for candidate in soup.find_all("table"):
        header = " ".join(cell.get_text(" ", strip=True) for cell in candidate.find_all(["th", "td"], limit=12))
        if "Country" in header and "Growth" in header:
            return candidate
    return None


def _extract_report_date(text: str) -> str | None:
    patterns = [
        r"Report\s+Dated:\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        r"Data\s+last\s+updated\s+on:\s*(\d{1,2}/\d{1,2}/\d{4})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            return m.group(1).strip()
    return None


def _extract_commodity(text: str, hscode: str) -> tuple[str | None, str | None]:
    compact = " ".join(text.split())
    m = re.search(rf"Commodity:\s*{re.escape(hscode)}\s+(.*?)\s+Unit:\s*([^\s]+)", compact, flags=re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, None


def _is_explicit_no_data(page_text: str) -> bool:
    lowered = page_text.lower()
    return any(marker in lowered for marker in NO_DATA_MARKERS)


def parse_commodity_all_countries(
    html: str,
    *,
    hscode: str,
    month: int,
    year: int,
    trade_type: str,
    value_type: str = "usd",
    year_type: str = "calendar",
    source_url: str | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    validate_query(hscode, month, year, value_type, year_type)
    trade_type = trade_type.lower()
    if trade_type not in ENDPOINTS:
        raise ValueError("trade_type must be 'import' or 'export'")

    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    table = _find_result_table(soup)

    rows: list[dict[str, Any]] = []
    totals: dict[str, float | None] | None = None
    headers: list[str] = []
    data_status = "ok"

    if table is None:
        if not _is_explicit_no_data(page_text):
            raise TradeStatError("TradeStat result table not found and response was not an explicit no-data result")
        data_status = "no_data"
        totals = {
            "previous_year_value": None,
            "value": 0.0,
            "yoy_pct": None,
            "cumulative_previous_year_value": None,
            "cumulative_value": None,
            "cumulative_yoy_pct": None,
        }
    else:
        first_row = table.find("tr")
        if first_row is not None:
            headers = [c.get_text(" ", strip=True) for c in first_row.find_all(["th", "td"])]

        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
            if len(cells) < 4:
                continue
            row_text = " ".join(cells)
            if "total" in row_text.lower():
                totals = {
                    "previous_year_value": _number(cells[2]) if len(cells) > 2 else None,
                    "value": _number(cells[3]) if len(cells) > 3 else None,
                    "yoy_pct": _number(cells[4]) if len(cells) > 4 else None,
                    "cumulative_previous_year_value": _number(cells[5]) if len(cells) > 5 else None,
                    "cumulative_value": _number(cells[6]) if len(cells) > 6 else None,
                    "cumulative_yoy_pct": _number(cells[7]) if len(cells) > 7 else None,
                }
                continue
            if not cells[0].isdigit():
                continue
            rows.append({
                "rank": int(cells[0]),
                "partner_country": cells[1],
                "previous_year_value": _number(cells[2]) if len(cells) > 2 else None,
                "value": _number(cells[3]) if len(cells) > 3 else None,
                "yoy_pct": _number(cells[4]) if len(cells) > 4 else None,
                "cumulative_previous_year_value": _number(cells[5]) if len(cells) > 5 else None,
                "cumulative_value": _number(cells[6]) if len(cells) > 6 else None,
                "cumulative_yoy_pct": _number(cells[7]) if len(cells) > 7 else None,
            })

        if not rows and totals is None:
            if _is_explicit_no_data(page_text):
                data_status = "no_data"
                totals = {
                    "previous_year_value": None,
                    "value": 0.0,
                    "yoy_pct": None,
                    "cumulative_previous_year_value": None,
                    "cumulative_value": None,
                    "cumulative_yoy_pct": None,
                }
            else:
                raise TradeStatError("TradeStat table contained no parseable records")

        if totals is None:
            current_values = [r["value"] for r in rows if r["value"] is not None]
            previous_values = [r["previous_year_value"] for r in rows if r["previous_year_value"] is not None]
            totals = {
                "previous_year_value": round(sum(previous_values), 6) if previous_values else None,
                "value": round(sum(current_values), 6) if current_values else None,
                "yoy_pct": None,
                "cumulative_previous_year_value": None,
                "cumulative_value": None,
                "cumulative_yoy_pct": None,
            }

    description, source_unit = _extract_commodity(page_text, hscode)
    endpoint = source_url or BASE_URL + ENDPOINTS[trade_type]
    period = f"{year:04d}-{month:02d}"
    payload_for_hash = "|".join(
        f"{r['partner_country']}:{r['value']}" for r in sorted(rows, key=lambda x: x["partner_country"])
    ) + f"|status:{data_status}"
    checksum = hashlib.sha256(payload_for_hash.encode("utf-8")).hexdigest()

    return {
        "schema_version": 1,
        "period": period,
        "trade_type": trade_type,
        "hs_code": hscode,
        "hs_level": len(hscode),
        "value_type": value_type,
        "value_unit": VALUE_UNITS[value_type],
        "year_type": year_type,
        "data_status": data_status,
        "commodity_description": description,
        "source_quantity_unit": source_unit,
        "headers": headers,
        "rows": rows,
        "totals": totals,
        "source": {
            "provider": "DGCI&S / Department of Commerce, Government of India",
            "system": "TradeStat MEIDB",
            "url": endpoint,
            "report_date": _extract_report_date(page_text),
            "retrieved_at": retrieved_at or _utcnow(),
            "checksum_sha256": checksum,
        },
    }


class TradeStatClient:
    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: int = 90,
        retries: int = 3,
        delay_seconds: float = 0.8,
        user_agent: str = "india-critical-trade-tracker/0.2 (+https://github.com/Vasuki8/india-critical-trade-tracker)",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.delay_seconds = delay_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"})

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2 ** (attempt - 1), 8))
        raise TradeStatError(f"TradeStat request failed after {self.retries} attempts: {last_error}")

    def fetch_commodity_all_countries(
        self,
        *,
        hscode: str,
        month: int,
        year: int,
        trade_type: str,
        value_type: str = "usd",
        year_type: str = "calendar",
    ) -> dict[str, Any]:
        trade_type = trade_type.lower()
        if trade_type not in ENDPOINTS:
            raise ValueError("trade_type must be 'import' or 'export'")
        validate_query(hscode, month, year, value_type, year_type)

        endpoint = self.base_url + ENDPOINTS[trade_type]
        landing = self._request("GET", endpoint)
        token = parse_csrf_token(landing.text)
        payload = build_payload(
            trade_type=trade_type,
            token=token,
            hscode=hscode,
            month=month,
            year=year,
            value_type=value_type,
            year_type=year_type,
        )
        response = self._request("POST", endpoint, data=payload)
        parsed = parse_commodity_all_countries(
            response.text,
            hscode=hscode,
            month=month,
            year=year,
            trade_type=trade_type,
            value_type=value_type,
            year_type=year_type,
            source_url=endpoint,
        )
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        return parsed
