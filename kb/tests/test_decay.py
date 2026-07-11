"""Tests for decay.py — maturity decay scan and demotion logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import frontmatter
import pytest

from holmes.kb.decay import (
    DecayChange,
    DecayResult,
    _get_reference_date,
    _months_since,
    archive_orphan,
    run_decay,
)
from holmes.kb.history import HISTORY_DIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    kb_root: Path,
    entry_id: str,
    maturity: str,
    evidence: list[dict] | None = None,
    last_referenced: str = "",
    updated_at: str = "2020-01-01T00:00:00+00:00",
    kb_type: str = "pitfall",
    category: str = "database",
) -> Path:
    """Write a minimal KB entry and return its path."""
    entry_dir = kb_root / kb_type / category
    entry_dir.mkdir(parents=True, exist_ok=True)
    path = entry_dir / f"{entry_id}.md"

    meta_lines = [
        f"id: {entry_id}",
        f"type: {kb_type}",
        f"title: Test entry {entry_id}",
        f"maturity: {maturity}",
        f"category: {category}",
        "tags: []",
        "created_at: '2020-01-01T00:00:00+00:00'",
        f"updated_at: '{updated_at}'",
    ]
    if last_referenced:
        meta_lines.append(f"last_referenced: '{last_referenced}'")
    if evidence is not None:
        if evidence:
            meta_lines.append("evidence:")
            for ev in evidence:
                meta_lines.append(f"  - session_id: '{ev['session_id']}'")
                meta_lines.append(f"    contributor: '{ev['contributor']}'")
                meta_lines.append(f"    date: '{ev['date']}'")
        else:
            meta_lines.append("evidence: []")

    content = "---\n" + "\n".join(meta_lines) + "\n---\n\n## Symptoms\nTest.\n\n## Root Cause\nTest.\n\n## Resolution\nTest.\n"
    path.write_text(content, encoding="utf-8")
    return path


def _old_iso(months_ago: int) -> str:
    """Return ISO timestamp that is approximately N months ago."""
    dt = datetime.now(timezone.utc) - timedelta(days=months_ago * 30)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# _get_reference_date
# ---------------------------------------------------------------------------

class TestGetReferenceDate:

    def test_returns_max_evidence_date(self):
        evidence = [
            {"session_id": "s1", "contributor": "a", "date": "2025-01-01T00:00:00+00:00"},
            {"session_id": "s2", "contributor": "b", "date": "2026-01-01T00:00:00+00:00"},
        ]
        result = _get_reference_date({"evidence": evidence})
        assert result.year == 2026

    def test_falls_back_to_last_referenced(self):
        metadata = {
            "evidence": [],
            "last_referenced": "2024-06-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00",
        }
        result = _get_reference_date(metadata)
        assert result.year == 2024

    def test_falls_back_to_updated_at(self):
        metadata = {"evidence": [], "updated_at": "2023-03-15T00:00:00+00:00"}
        result = _get_reference_date(metadata)
        assert result.year == 2023

    def test_returns_min_datetime_for_empty(self):
        result = _get_reference_date({})
        assert result == datetime.min.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# run_decay — dry_run
# ---------------------------------------------------------------------------

class TestRunDecayDryRun:

    def test_dry_run_does_not_modify_files(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "proven",
                    evidence=[{"session_id": "s1", "contributor": "a", "date": _old_iso(14)}])
        before = (tmp_path / "pitfall" / "database" / "PT-DB-001.md").read_text()
        result = run_decay(tmp_path, dry_run=True)
        after = (tmp_path / "pitfall" / "database" / "PT-DB-001.md").read_text()
        assert before == after
        assert len(result.changes) == 1

    def test_dry_run_does_not_create_snapshots(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "proven",
                    evidence=[{"session_id": "s1", "contributor": "a", "date": _old_iso(14)}])
        run_decay(tmp_path, dry_run=True)
        assert not (tmp_path / HISTORY_DIR).exists() or not list((tmp_path / HISTORY_DIR).glob("*.md"))

    def test_dry_run_reports_changes(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "proven",
                    evidence=[{"session_id": "s1", "contributor": "a", "date": _old_iso(14)}])
        result = run_decay(tmp_path, dry_run=True)
        assert result.scanned >= 1
        assert result.decayed == 1
        change = result.changes[0]
        assert change.id == "PT-DB-001"
        assert change.old_maturity == "proven"
        assert change.new_maturity == "verified"


# ---------------------------------------------------------------------------
# run_decay — actual demotion
# ---------------------------------------------------------------------------

class TestRunDecay:

    def test_proven_demoted_to_verified_after_12_months(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "proven",
                    evidence=[{"session_id": "s1", "contributor": "a", "date": _old_iso(14)}])
        result = run_decay(tmp_path)
        assert result.decayed == 1
        post = frontmatter.load(str(tmp_path / "pitfall" / "database" / "PT-DB-001.md"))
        assert post.metadata["maturity"] == "verified"

    def test_verified_demoted_to_draft_after_6_months(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "verified",
                    evidence=[{"session_id": "s1", "contributor": "a", "date": _old_iso(8)}])
        result = run_decay(tmp_path)
        assert result.decayed == 1
        post = frontmatter.load(str(tmp_path / "pitfall" / "database" / "PT-DB-001.md"))
        assert post.metadata["maturity"] == "draft"

    def test_proven_within_threshold_not_decayed(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "proven",
                    evidence=[{"session_id": "s1", "contributor": "a", "date": _old_iso(6)}])
        result = run_decay(tmp_path)
        assert result.decayed == 0
        post = frontmatter.load(str(tmp_path / "pitfall" / "database" / "PT-DB-001.md"))
        assert post.metadata["maturity"] == "proven"

    def test_decay_saves_snapshot(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "proven",
                    evidence=[{"session_id": "s1", "contributor": "a", "date": _old_iso(14)}])
        run_decay(tmp_path)
        history_files = list((tmp_path / HISTORY_DIR).glob("PT-DB-001-*.md"))
        assert len(history_files) == 1

    def test_decay_logs_event(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "proven",
                    evidence=[{"session_id": "s1", "contributor": "a", "date": _old_iso(14)}])
        run_decay(tmp_path)
        log = (tmp_path / "contributions" / "log.md").read_text()
        assert "decay" in log
        assert "PT-DB-001" in log

    def test_fresh_draft_not_affected(self, tmp_path):
        """A draft younger than 30 days is not archived."""
        _make_entry(tmp_path, "PT-DB-001", "draft",
                    updated_at=_old_iso(1))
        # Override created_at to recent so age < 30 days
        path = tmp_path / "pitfall" / "database" / "PT-DB-001.md"
        text = path.read_text()
        text = text.replace("created_at: '2020-01-01T00:00:00+00:00'",
                            f"created_at: '{_old_iso(0)}'")
        path.write_text(text)
        result = run_decay(tmp_path)
        assert result.decayed == 0

    def test_old_stale_draft_archived(self, tmp_path):
        """A draft older than 30 days and stale > 3 months gets archived."""
        _make_entry(tmp_path, "PT-DB-001", "draft",
                    updated_at=_old_iso(24))
        result = run_decay(tmp_path)
        assert result.decayed == 1
        assert result.changes[0].new_maturity == "archived"

    def test_type_filter_limits_scan(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "proven", kb_type="pitfall",
                    evidence=[{"session_id": "s1", "contributor": "a", "date": _old_iso(14)}])
        _make_entry(tmp_path, "MOD-001", "proven", kb_type="model", category="",
                    evidence=[{"session_id": "s1", "contributor": "a", "date": _old_iso(14)}])
        result = run_decay(tmp_path, kb_type="pitfall")
        assert result.scanned == 1

    def test_fallback_to_last_referenced(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "proven",
                    last_referenced=_old_iso(14))
        result = run_decay(tmp_path)
        assert result.decayed == 1


# ---------------------------------------------------------------------------
# archive_orphan
# ---------------------------------------------------------------------------

class TestArchiveOrphan:

    def test_moves_entry_to_archive_dir(self, tmp_path):
        path = _make_entry(tmp_path, "PT-OLD-001", "draft", evidence=[])
        archive_orphan(tmp_path, "PT-OLD-001")
        assert not path.exists()
        archive_path = tmp_path / "contributions" / "archive" / "PT-OLD-001.md"
        assert archive_path.exists()

    def test_raises_if_entry_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            archive_orphan(tmp_path, "PT-NONEXISTENT")

    def test_logs_archive_event(self, tmp_path):
        _make_entry(tmp_path, "PT-OLD-001", "draft", evidence=[])
        archive_orphan(tmp_path, "PT-OLD-001")
        log = (tmp_path / "contributions" / "log.md").read_text()
        assert "PT-OLD-001" in log
        assert "archived" in log
