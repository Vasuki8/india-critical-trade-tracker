import json
from pathlib import Path

from src.tracker.revisions import build_revision_summary

ROOT = Path(__file__).resolve().parents[1]


def test_tracked_revision_summary_matches_revision_archive_tree():
    expected = build_revision_summary(ROOT / "data" / "observations", ROOT / "data" / "revisions")
    actual = json.loads((ROOT / "data" / "revision_summary.json").read_text(encoding="utf-8"))
    assert actual == expected
