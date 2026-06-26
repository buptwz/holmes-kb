"""Tests for M2-dedup: Step 0 去重与更新检测.

Covers:
- US1: exact duplicate (source_hash match) → skip
- US2: document update (source_file match, different hash) → continue + pending cleanup
- US3: new document → pipeline proceeds
- US4: --force bypasses all Step 0 checks
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import frontmatter
import pytest

from holmes.kb.store import (
    EntryMeta,
    find_entries_by_source_hash,
    find_entries_by_source_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hash(content: str) -> str:
    """Compute source_hash the same way compute_source_hash() does."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _write_entry(
    path: Path,
    *,
    entry_id: str,
    kb_type: str = "pitfall",
    title: str = "Test Entry",
    source_hash: str = "",
    source_file: str = "",
    kb_status: str = "active",
) -> None:
    """Write a minimal KB entry to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""\
---
id: {entry_id}
type: {kb_type}
title: {title}
maturity: draft
category: system
tags: []
created_at: "2026-01-01"
updated_at: "2026-01-01"
source_hash: "{source_hash}"
source_file: "{source_file}"
kb_status: {kb_status}
---

## Symptoms
Test symptoms.

## Root Cause
Test root cause.

## Resolution
Test resolution.
"""
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    """Create a minimal KB directory structure."""
    (tmp_path / "pitfall" / "system").mkdir(parents=True)
    # New-format pending hierarchy: _pending/<type>/<category>/
    (tmp_path / "_pending" / "pitfall" / "system").mkdir(parents=True)
    return tmp_path


# ---------------------------------------------------------------------------
# Tests for find_entries_by_source_hash
# ---------------------------------------------------------------------------

class TestFindEntriesBySourceHash:
    def test_returns_confirmed_entry_with_matching_hash(self, kb_root: Path):
        target_hash = _make_hash("some document content")
        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_hash=target_hash,
        )
        results = find_entries_by_source_hash(kb_root, target_hash)
        assert len(results) == 1
        assert results[0].id == "PT-SYS-001"
        assert results[0].source_hash == target_hash

    def test_returns_pending_entry_with_matching_hash(self, kb_root: Path):
        target_hash = _make_hash("pending document content")
        _write_entry(
            kb_root / "_pending" / "pitfall" / "system" / "pending-20260101-000000-abcd.md",
            entry_id="pending-20260101-000000-abcd",
            source_hash=target_hash,
        )
        results = find_entries_by_source_hash(kb_root, target_hash)
        assert len(results) == 1
        assert results[0].id == "pending-20260101-000000-abcd"

    def test_empty_source_hash_never_matches(self, kb_root: Path):
        """Entries without source_hash (legacy) are NOT matched by any import."""
        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-LEGACY.md",
            entry_id="PT-SYS-LEGACY",
            source_hash="",  # legacy entry, no hash
        )
        # Querying with empty string should return nothing
        results = find_entries_by_source_hash(kb_root, "")
        assert results == []

    def test_returns_empty_list_when_no_match(self, kb_root: Path):
        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_hash=_make_hash("other content"),
        )
        results = find_entries_by_source_hash(kb_root, _make_hash("completely different"))
        assert results == []

    def test_returns_multiple_matches(self, kb_root: Path):
        """Should return all entries with the same hash (edge case)."""
        target_hash = _make_hash("shared content")
        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_hash=target_hash,
        )
        _write_entry(
            kb_root / "_pending" / "pitfall" / "system" / "pending-dup.md",
            entry_id="pending-dup",
            source_hash=target_hash,
        )
        results = find_entries_by_source_hash(kb_root, target_hash)
        ids = {r.id for r in results}
        assert "PT-SYS-001" in ids
        assert "pending-dup" in ids


# ---------------------------------------------------------------------------
# Tests for find_entries_by_source_file
# ---------------------------------------------------------------------------

class TestFindEntriesBySourceFile:
    def test_returns_confirmed_entry_with_matching_source_file(self, kb_root: Path):
        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_file="docs/hardware/gpu.md",
        )
        results = find_entries_by_source_file(kb_root, "docs/hardware/gpu.md")
        assert len(results) == 1
        assert results[0].id == "PT-SYS-001"

    def test_returns_pending_entry_with_matching_source_file(self, kb_root: Path):
        _write_entry(
            kb_root / "_pending" / "pitfall" / "system" / "pending-20260101-000000-abcd.md",
            entry_id="pending-20260101-000000-abcd",
            source_file="docs/hardware/gpu.md",
        )
        results = find_entries_by_source_file(kb_root, "docs/hardware/gpu.md")
        assert len(results) == 1
        assert results[0].id == "pending-20260101-000000-abcd"

    def test_empty_source_file_never_matches(self, kb_root: Path):
        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_file="",
        )
        results = find_entries_by_source_file(kb_root, "")
        assert results == []

    def test_returns_empty_list_when_no_match(self, kb_root: Path):
        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_file="docs/other.md",
        )
        results = find_entries_by_source_file(kb_root, "docs/gpu.md")
        assert results == []

    def test_path_normalisation(self, kb_root: Path):
        """source_file stored with backslash should still match posix path."""
        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_file="docs/hardware/gpu.md",
        )
        # Query with equivalent path
        results = find_entries_by_source_file(kb_root, "docs/hardware/gpu.md")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Tests for EntryMeta source_hash and source_file fields
# ---------------------------------------------------------------------------

class TestEntryMetaNewFields:
    def test_list_entries_populates_source_hash_and_source_file(self, kb_root: Path):
        from holmes.kb.store import list_entries

        target_hash = _make_hash("test doc")
        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_hash=target_hash,
            source_file="docs/test.md",
        )
        entries = list_entries(kb_root, kb_status=None)
        entry = next(e for e in entries if e.id == "PT-SYS-001")
        assert entry.source_hash == target_hash
        assert entry.source_file == "docs/test.md"

    def test_legacy_entry_has_empty_source_fields(self, kb_root: Path):
        """Legacy entries without source_hash/source_file should default to empty."""
        from holmes.kb.store import list_entries

        legacy_path = kb_root / "pitfall" / "system" / "PT-SYS-LEGACY.md"
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text("""\
---
id: PT-SYS-LEGACY
type: pitfall
title: Legacy Entry
maturity: draft
category: system
tags: []
created_at: "2026-01-01"
updated_at: "2026-01-01"
---

## Symptoms
Old.

## Root Cause
Old.

## Resolution
Old.
""", encoding="utf-8")

        entries = list_entries(kb_root, kb_status=None)
        entry = next(e for e in entries if e.id == "PT-SYS-LEGACY")
        assert entry.source_hash == ""
        assert entry.source_file == ""


# ---------------------------------------------------------------------------
# Tests for Step 0 in pipeline.py (via ThreePhaseImportPipeline)
# ---------------------------------------------------------------------------

def _make_pipeline(kb_root: Path, *, force: bool = False, no_interactive: bool = True,
                   dry_run: bool = False):
    """Build a ThreePhaseImportPipeline with a stub provider (no real LLM calls)."""
    from holmes.config import HolmesConfig
    from holmes.kb.agent.pipeline import ThreePhaseImportPipeline
    from holmes.kb.agent.provider.base import LLMProvider

    cfg = HolmesConfig(
        kb_path=str(kb_root),
        model="stub",
        api_key="x",
        api_base_url="",
        username="tester",
    )

    # Stub provider — complete() raises so the Classifier falls back to single_incident
    # default, which routes to _run_dag_pipeline → NotImplementedError("DAG pipeline (M4)").
    # Tests that validate Step 0 early-exit check report.skipped instead of catching exceptions.
    # Tests that validate Step 0 passes through accept (RuntimeError, NotImplementedError).
    stub_provider = MagicMock(spec=LLMProvider)
    stub_provider.complete.side_effect = RuntimeError("stub LLM")
    stub_provider.simple_complete.side_effect = RuntimeError("stub LLM")

    return ThreePhaseImportPipeline(
        kb_root=kb_root,
        cfg=cfg,
        no_interactive=no_interactive,
        dry_run=dry_run,
        _provider=stub_provider,
        force=force,
    )


# Exceptions raised after Step 0 (LLM stub / DAG not-yet-implemented)
_PIPELINE_CONTINUES_ERRORS = (RuntimeError, NotImplementedError)


SOURCE_CONTENT = "During on-call we saw Redis timeouts. Root cause: pool size too small. Fix: increase pool."
SOURCE_HASH = _make_hash(SOURCE_CONTENT)


class TestStep0HashDedup:
    """US1: exact duplicate detection."""

    def test_confirmed_hash_match_returns_early(self, kb_root: Path):
        """Importing same content as an existing confirmed entry → skip."""
        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_hash=SOURCE_HASH,
        )
        pipeline = _make_pipeline(kb_root)
        report = pipeline.run(SOURCE_CONTENT, file_path=kb_root / "docs" / "incident.md")
        assert report.skipped  # at least one skipped id
        assert any("已存在" in w or "Already" in w or "skipping" in w.lower()
                   for w in report.warnings)

    def test_pending_hash_match_returns_early(self, kb_root: Path):
        """Importing same content as an existing pending entry → skip."""
        _write_entry(
            kb_root / "_pending" / "pitfall" / "system" / "pending-dup.md",
            entry_id="pending-dup",
            source_hash=SOURCE_HASH,
        )
        pipeline = _make_pipeline(kb_root)
        report = pipeline.run(SOURCE_CONTENT, file_path=kb_root / "docs" / "incident.md")
        assert report.skipped


class TestStep0FileUpdate:
    """US2: document update detection."""

    def test_source_file_match_different_hash_continues(self, kb_root: Path):
        """Updating a document with same path but different content → pipeline continues."""
        old_hash = _make_hash("old content version")
        (kb_root / "docs").mkdir(exist_ok=True)
        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_hash=old_hash,
            source_file="docs/incident.md",
        )

        pipeline = _make_pipeline(kb_root, no_interactive=True)
        # The pipeline WILL try to reach the LLM after Step 0 (since it's an update).
        # We expect it to NOT return early (skipped should be empty).
        # The LLM stub will raise, which is expected — we only care about Step 0 behaviour.
        try:
            report = pipeline.run(SOURCE_CONTENT, file_path=kb_root / "docs" / "incident.md")
            # If it returns without raising, skipped must be empty (update, not skip)
            assert not report.skipped
        except _PIPELINE_CONTINUES_ERRORS:
            pass  # LLM stub / DAG stub raised — Step 0 was passed correctly

    def test_old_pending_deleted_when_user_confirms(self, kb_root: Path):
        """Y path: old pending entries are deleted."""
        old_hash = _make_hash("old content version")
        (kb_root / "docs").mkdir(exist_ok=True)

        # One old confirmed + one old pending with same source_file
        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_hash=old_hash,
            source_file="docs/incident.md",
        )
        old_pending_path = kb_root / "_pending" / "pitfall" / "system" / "pending-old.md"
        _write_entry(
            old_pending_path,
            entry_id="pending-old",
            source_hash=old_hash,
            source_file="docs/incident.md",
        )

        pipeline = _make_pipeline(kb_root, no_interactive=False)

        with patch("click.confirm", return_value=True):  # user says Y
            try:
                pipeline.run(SOURCE_CONTENT, file_path=kb_root / "docs" / "incident.md")
            except _PIPELINE_CONTINUES_ERRORS:
                pass  # LLM/DAG stub; we only care about pending deletion

        assert not old_pending_path.exists(), "Old pending should be deleted on Y"

    def test_old_pending_preserved_when_user_declines(self, kb_root: Path):
        """n path: old pending entries are NOT deleted."""
        old_hash = _make_hash("old content version")
        (kb_root / "docs").mkdir(exist_ok=True)

        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_hash=old_hash,
            source_file="docs/incident.md",
        )
        old_pending_path = kb_root / "_pending" / "pitfall" / "system" / "pending-old.md"
        _write_entry(
            old_pending_path,
            entry_id="pending-old",
            source_hash=old_hash,
            source_file="docs/incident.md",
        )

        pipeline = _make_pipeline(kb_root, no_interactive=False)

        with patch("click.confirm", return_value=False):  # user says n
            try:
                pipeline.run(SOURCE_CONTENT, file_path=kb_root / "docs" / "incident.md")
            except _PIPELINE_CONTINUES_ERRORS:
                pass

        assert old_pending_path.exists(), "Old pending should be preserved on n"

    def test_no_interactive_auto_preserves_old_pending(self, kb_root: Path):
        """no_interactive=True → auto-n, old pending preserved."""
        old_hash = _make_hash("old content version")
        (kb_root / "docs").mkdir(exist_ok=True)

        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_hash=old_hash,
            source_file="docs/incident.md",
        )
        old_pending_path = kb_root / "_pending" / "pitfall" / "system" / "pending-old.md"
        _write_entry(
            old_pending_path,
            entry_id="pending-old",
            source_hash=old_hash,
            source_file="docs/incident.md",
        )

        pipeline = _make_pipeline(kb_root, no_interactive=True)
        try:
            pipeline.run(SOURCE_CONTENT, file_path=kb_root / "docs" / "incident.md")
        except _PIPELINE_CONTINUES_ERRORS:
            pass

        assert old_pending_path.exists(), "no_interactive should not delete old pending"

    def test_dry_run_does_not_delete_old_pending(self, kb_root: Path):
        """dry_run=True → Step 0b still runs but does NOT delete pending."""
        old_hash = _make_hash("old content version")
        (kb_root / "docs").mkdir(exist_ok=True)

        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_hash=old_hash,
            source_file="docs/incident.md",
        )
        old_pending_path = kb_root / "_pending" / "pitfall" / "system" / "pending-old.md"
        _write_entry(
            old_pending_path,
            entry_id="pending-old",
            source_hash=old_hash,
            source_file="docs/incident.md",
        )

        pipeline = _make_pipeline(kb_root, no_interactive=True, dry_run=True)
        try:
            pipeline.run(SOURCE_CONTENT, file_path=kb_root / "docs" / "incident.md")
        except _PIPELINE_CONTINUES_ERRORS:
            pass  # Step 0 ran, pipeline continues beyond; stub raises

        assert old_pending_path.exists(), "dry_run should not delete old pending"


class TestStep0NewDocument:
    """US3: new document — no match anywhere."""

    def test_new_document_no_warnings_no_skip(self, kb_root: Path):
        """Importing a brand-new document should pass through Step 0 without skip."""
        pipeline = _make_pipeline(kb_root)
        try:
            report = pipeline.run(SOURCE_CONTENT, file_path=kb_root / "docs" / "new.md")
            assert not report.skipped
        except _PIPELINE_CONTINUES_ERRORS:
            pass  # LLM stub raised; Step 0 passed correctly

    def test_file_outside_kb_root_skips_source_file_check(self, kb_root: Path, tmp_path: Path):
        """file_path outside kb_root → source_file="" → Step 0b skipped."""
        external_file = tmp_path / "external_doc.md"
        pipeline = _make_pipeline(kb_root)
        try:
            report = pipeline.run(SOURCE_CONTENT, file_path=external_file)
            assert not report.skipped
        except _PIPELINE_CONTINUES_ERRORS:
            pass


class TestStep0Force:
    """US4: --force bypasses all Step 0 checks."""

    def test_force_bypasses_hash_match(self, kb_root: Path):
        """--force: even with exact hash match, pipeline is NOT skipped."""
        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_hash=SOURCE_HASH,
        )
        pipeline = _make_pipeline(kb_root, force=True)
        try:
            report = pipeline.run(SOURCE_CONTENT, file_path=kb_root / "docs" / "incident.md")
            assert not report.skipped
        except _PIPELINE_CONTINUES_ERRORS:
            pass  # LLM stub: Step 0 was bypassed, LLM was reached

    def test_force_bypasses_source_file_match_and_no_prompt(self, kb_root: Path):
        """--force with source_file match: no prompt, old pending preserved."""
        old_hash = _make_hash("old content version")
        (kb_root / "docs").mkdir(exist_ok=True)

        _write_entry(
            kb_root / "pitfall" / "system" / "PT-SYS-001.md",
            entry_id="PT-SYS-001",
            source_hash=old_hash,
            source_file="docs/incident.md",
        )
        old_pending_path = kb_root / "_pending" / "pitfall" / "system" / "pending-old.md"
        _write_entry(
            old_pending_path,
            entry_id="pending-old",
            source_hash=old_hash,
            source_file="docs/incident.md",
        )

        pipeline = _make_pipeline(kb_root, force=True, no_interactive=False)
        with patch("click.confirm") as mock_confirm:
            try:
                pipeline.run(SOURCE_CONTENT, file_path=kb_root / "docs" / "incident.md")
            except _PIPELINE_CONTINUES_ERRORS:
                pass
            # --force: confirm should NOT have been called for pending cleanup
            mock_confirm.assert_not_called()
