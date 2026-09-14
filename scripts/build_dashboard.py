"""Rebuild the static dashboard payload from stored monthly observations."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tracker.dashboard import build_dashboard

if __name__ == "__main__":
    doc = build_dashboard(
        ROOT / "data" / "observations",
        ROOT / "data" / "dashboard.json",
        ROOT / "data" / "commodities.json",
    )
    print(f"dashboard: status={doc['status']} as_of={doc['as_of']}")
