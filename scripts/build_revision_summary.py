from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tracker.revisions import build_revision_summary

OBSERVATION_ROOT = ROOT / "data" / "observations"
REVISION_ROOT = ROOT / "data" / "revisions"
OUTPUT_PATH = ROOT / "data" / "revision_summary.json"


def main() -> int:
    summary = build_revision_summary(OBSERVATION_ROOT, REVISION_ROOT)
    rendered = json.dumps(summary, indent=2) + "\n"
    if OUTPUT_PATH.exists() and OUTPUT_PATH.read_text(encoding="utf-8") == rendered:
        print(
            f"Revision summary unchanged: groups={summary['revision_group_count']} "
            f"path={OUTPUT_PATH.relative_to(ROOT)}"
        )
        return 0

    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(
        f"Revision summary written: groups={summary['revision_group_count']} "
        f"path={OUTPUT_PATH.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
