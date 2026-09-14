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
    print(
        f"Commodity intelligence written: commodities={summary['commodity_count']} "
        f"path={OUTPUT.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
