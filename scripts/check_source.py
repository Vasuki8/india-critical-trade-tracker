from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "source_status.json"
URL = "https://tradestat.commerce.gov.in/meidb/commoditywise_import"


def normalize_space(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def html_to_text(markup: str) -> str:
    no_script = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", markup)
    no_tags = re.sub(r"(?s)<[^>]+>", " ", no_script)
    return normalize_space(html_lib.unescape(no_tags))


def parse_status(markup: str) -> dict:
    text = html_to_text(markup)
    available = re.search(r"Data available:\s*(.*?)\s*\(\(R\)", text, re.I)
    revised = re.search(r"Revised Final upto\s*([^,\)]+)", text, re.I)
    final = re.search(r"\(F\)\s*Final upto\s*([^\)]+)", text, re.I)
    updated = re.search(r"Data last updated on:\s*([0-9/]+)", text, re.I)
    warning = re.search(r"ITC HS Code.*?from April 2026\.", text, re.I)

    if not available or not updated:
        raise ValueError("TradeStat status markers not found; source layout may have changed")

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": "India Department of Commerce TradeStat MEIDB",
        "source_url": URL,
        "data_available": normalize_space(available.group(1)),
        "last_updated": updated.group(1),
        "final_through": normalize_space(final.group(1)) if final else None,
        "revised_final_through": normalize_space(revised.group(1)) if revised else None,
        "classification_warning": normalize_space(warning.group(0)) if warning else None,
        "fetch_status": "ok"
    }


def main() -> int:
    req = Request(URL, headers={"User-Agent": "india-critical-trade-tracker/0.1 (+GitHub Actions source monitor)"})
    with urlopen(req, timeout=30) as response:
        markup = response.read().decode("utf-8", errors="replace")
    status = parse_status(markup)
    OUT.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
