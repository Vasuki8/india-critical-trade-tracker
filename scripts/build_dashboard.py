"""Rebuild the static dashboard payload from stored monthly observations."""

from pathlib import Path

from src.tracker.dashboard import build_dashboard

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    doc = build_dashboard(ROOT / "data" / "observations", ROOT / "data" / "dashboard.json")
    print(f"dashboard: status={doc['status']} as_of={doc['as_of']}")
