from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tracker.validation import load_json, validate_commodity_master, validate_dashboard


def main() -> int:
    master = load_json(ROOT / "data" / "commodities.json")
    dashboard = load_json(ROOT / "data" / "dashboard.json")

    errors = []
    errors.extend(validate_commodity_master(master))
    errors.extend(validate_dashboard(dashboard))
    if errors:
        print("Validation failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    history_rows = sum(len(rows) for rows in dashboard.get("commodity_history", {}).values())
    print(
        f"OK: {len(master['commodities'])} critical commodity groups validated; "
        f"dashboard as_of={dashboard.get('as_of')} history_rows={history_rows}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
