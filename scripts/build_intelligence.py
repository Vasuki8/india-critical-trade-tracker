from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tracker.intelligence import build_all_commodity_intelligence

OBSERVATIONS = ROOT / "data" / "observations"
MASTER = ROOT / "data" / "commodities.json"
OUTPUT = ROOT / "data" / "intelligence"
INDEX = OUTPUT / "index.json"


def main() -> int:
    summary = build_all_commodity_intelligence(OBSERVATIONS, MASTER, OUTPUT)
    rendered = json.dumps(summary, indent=2) + "\n"
    INDEX.write_text(rendered, encoding="utf-8")

    files = sorted(path for path in OUTPUT.glob("*.json") if path.name != "index.json")
    total_bytes = sum(path.stat().st_size for path in files)
    largest = max(files, key=lambda path: path.stat().st_size, default=None)
    largest_note = (
        f" largest={largest.name}:{largest.stat().st_size / 1024 / 1024:.2f}MiB"
        if largest is not None
        else ""
    )
    print(
        f"Commodity intelligence written: commodities={summary['commodity_count']} "
        f"path={OUTPUT.relative_to(ROOT)} total={total_bytes / 1024 / 1024:.2f}MiB"
        f"{largest_note}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
