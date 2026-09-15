from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tracker.mapping_quality import (
    mapping_status_counts,
    quantity_mapping_count,
    validate_mapping_quality,
)
from src.tracker.quantity_coverage import validate_quantity_history
from src.tracker.validation import load_json, validate_commodity_master, validate_dashboard


def main() -> int:
    master = load_json(ROOT / "data" / "commodities.json")
    dashboard = load_json(ROOT / "data" / "dashboard.json")

    errors = []
    errors.extend(validate_commodity_master(master))
    errors.extend(validate_mapping_quality(master))
    errors.extend(validate_dashboard(dashboard))
    errors.extend(validate_quantity_history(master, dashboard, ROOT / "data" / "observations"))
    if errors:
        print("Validation failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    history_rows = sum(len(rows) for rows in dashboard.get("commodity_history", {}).values())
    status_counts = mapping_status_counts(master)
    exact_hs8 = status_counts.get("hs8_validated", 0)
    quantity_hs8 = quantity_mapping_count(master)
    quantity_history_complete = sum(
        1
        for item in master.get("commodities", [])
        if isinstance(item, dict)
        and isinstance(item.get("quantity_mapping"), dict)
        and isinstance(item["quantity_mapping"].get("history_complete_from"), str)
    )
    print(
        f"OK: {len(master['commodities'])} critical commodity groups validated; "
        f"exact_hs8={exact_hs8}/{len(master['commodities'])}; "
        f"quantity_hs8={quantity_hs8}/{len(master['commodities'])}; "
        f"quantity_history_complete={quantity_history_complete}/{quantity_hs8}; "
        f"dashboard as_of={dashboard.get('as_of')} history_rows={history_rows}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
