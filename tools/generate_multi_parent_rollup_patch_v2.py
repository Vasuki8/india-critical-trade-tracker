import sys
from pathlib import Path
from textwrap import dedent, indent

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.generate_multi_parent_rollup_patch import patch_derived, patch_tests, replace_between


def patch_mapping_quality() -> None:
    path = Path("src/tracker/mapping_quality.py")
    text = path.read_text(encoding="utf-8")
    block = dedent(
        '''
        if rollup:
            value_codes = item.get("hs_codes")
            if not isinstance(value_codes, list) or not value_codes:
                errors.append(
                    f"{prefix}.quantity_mapping: rollup requires a non-empty monetary hs_codes mapping"
                )
            else:
                valid_parents = [parent for parent in value_codes if isinstance(parent, str)]
                matches_by_child: dict[str, list[str]] = {}
                uncovered: list[str] = []
                ambiguous: list[str] = []
                for code in codes:
                    if not isinstance(code, str):
                        continue
                    matches = [
                        parent
                        for parent in valid_parents
                        if len(parent) < len(code) and code.startswith(parent)
                    ]
                    matches_by_child[code] = matches
                    if not matches:
                        uncovered.append(code)
                    elif len(matches) > 1:
                        ambiguous.append(code)
                if uncovered:
                    errors.append(
                        f"{prefix}.quantity_mapping: rollup quantity codes must be children of the monetary mapping"
                    )
                if ambiguous:
                    errors.append(
                        f"{prefix}.quantity_mapping: each rollup quantity code must match exactly one monetary parent"
                    )
                unused_parents = [
                    parent
                    for parent in valid_parents
                    if not any(parent in matches for matches in matches_by_child.values())
                ]
                if unused_parents:
                    errors.append(
                        f"{prefix}.quantity_mapping: rollup monetary mappings must each have at least one quantity child"
                    )

        '''
    )
    replacement = indent(block, "    ")
    start_marker = '    if rollup:\n        value_codes = item.get("hs_codes")'
    end_marker = '    transitions = quantity.get("classification_transition_periods", [])'
    text = replace_between(text, start_marker, end_marker, replacement)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_derived()
    patch_mapping_quality()
    patch_tests()
