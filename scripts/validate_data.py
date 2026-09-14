from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tracker.validation import load_json, validate_commodity_master


def main() -> int:
    master = load_json(ROOT / "data" / "commodities.json")
    errors = validate_commodity_master(master)
    if errors:
        print("Validation failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print(f"OK: {len(master['commodities'])} critical commodity groups validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
