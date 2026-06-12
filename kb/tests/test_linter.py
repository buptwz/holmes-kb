"""Tests for holmes.kb.linter — conflict_count accuracy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from holmes.kb.linter import lint


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    """Minimal KB directory structure."""
    (tmp_path / "contributions" / "conflicts").mkdir(parents=True)
    (tmp_path / "contributions" / "pending").mkdir(parents=True)
    return tmp_path


def _write_conflict(conflicts_dir: Path, name: str, status: str) -> None:
    (conflicts_dir / f"{name}.json").write_text(
        json.dumps({"conflict_id": name, "status": status, "entry_id": "PT-DB-001"}),
        encoding="utf-8",
    )


class TestConflictCount:

    def test_only_pending_review_counted(self, kb_root: Path):
        """T006: 1 pending_review + 1 resolved → conflict_count == 1."""
        conflicts_dir = kb_root / "contributions" / "conflicts"
        _write_conflict(conflicts_dir, "c-001", "pending_review")
        _write_conflict(conflicts_dir, "c-002", "resolved")

        report = lint(kb_root)
        assert report.conflict_count == 1

    def test_corrupted_json_skipped(self, kb_root: Path):
        """T007: Corrupted JSON file is silently skipped, not counted."""
        conflicts_dir = kb_root / "contributions" / "conflicts"
        _write_conflict(conflicts_dir, "c-001", "pending_review")
        (conflicts_dir / "broken.json").write_text("not valid json{{", encoding="utf-8")

        report = lint(kb_root)
        assert report.conflict_count == 1

    def test_empty_conflicts_dir(self, kb_root: Path):
        """T008: Empty conflicts directory → conflict_count == 0."""
        report = lint(kb_root)
        assert report.conflict_count == 0

    def test_all_resolved_gives_zero(self, kb_root: Path):
        """All conflicts resolved → conflict_count == 0."""
        conflicts_dir = kb_root / "contributions" / "conflicts"
        _write_conflict(conflicts_dir, "c-001", "resolved")
        _write_conflict(conflicts_dir, "c-002", "resolved")

        report = lint(kb_root)
        assert report.conflict_count == 0

    def test_multiple_pending_review_counted(self, kb_root: Path):
        """Multiple pending_review conflicts all counted."""
        conflicts_dir = kb_root / "contributions" / "conflicts"
        _write_conflict(conflicts_dir, "c-001", "pending_review")
        _write_conflict(conflicts_dir, "c-002", "pending_review")
        _write_conflict(conflicts_dir, "c-003", "resolved")

        report = lint(kb_root)
        assert report.conflict_count == 2
