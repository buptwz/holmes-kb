"""Tests for pending entry management — write_pending() behavior."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from holmes.kb.pending import write_pending


_CONTENT_NO_MATURITY = """\
---
type: pitfall
title: Kafka Rebalance Under Full GC
category: application
tags: [kafka, gc, rebalance]
created_at: "2026-01-01T00:00:00+00:00"
updated_at: "2026-01-01T00:00:00+00:00"
---

## Symptoms
Kafka consumer group triggers rebalance unexpectedly.

## Root Cause
Full GC pause exceeds session.timeout.ms.

## Resolution
Tune GC settings or increase session.timeout.ms.
"""

_CONTENT_WITH_MATURITY_DRAFT = """\
---
type: pitfall
title: Kafka Rebalance Under Full GC Draft
category: application
tags: [kafka, gc]
maturity: draft
created_at: "2026-01-01T00:00:00+00:00"
updated_at: "2026-01-01T00:00:00+00:00"
---

## Symptoms
Test.

## Root Cause
Test.

## Resolution
Test.
"""

_CONTENT_WITH_MATURITY_VERIFIED = """\
---
type: pitfall
title: Kafka Rebalance Under Full GC Verified
category: application
tags: [kafka, gc]
maturity: verified
created_at: "2026-01-01T00:00:00+00:00"
updated_at: "2026-01-01T00:00:00+00:00"
---

## Symptoms
Test.

## Root Cause
Test.

## Resolution
Test.
"""


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    (kb / "pitfall" / "application").mkdir(parents=True)
    (kb / "contributions" / "pending").mkdir(parents=True)
    return kb


class TestWritePendingMaturityInjection:

    def test_maturity_injected_when_missing(self, kb_root: Path):
        """write_pending() auto-injects maturity: draft when content lacks maturity field."""
        pending_id = write_pending(kb_root, _CONTENT_NO_MATURITY)
        pending_path = kb_root / "contributions" / "pending" / f"{pending_id}.md"
        post = frontmatter.load(str(pending_path))
        assert post.metadata.get("maturity") == "draft"

    def test_maturity_not_overwritten_when_draft_present(self, kb_root: Path):
        """write_pending() does not overwrite maturity: draft when caller supplies it."""
        pending_id = write_pending(kb_root, _CONTENT_WITH_MATURITY_DRAFT)
        pending_path = kb_root / "contributions" / "pending" / f"{pending_id}.md"
        post = frontmatter.load(str(pending_path))
        assert post.metadata.get("maturity") == "draft"

    def test_maturity_preserved_when_caller_supplies_verified(self, kb_root: Path):
        """write_pending() preserves maturity: verified when caller explicitly sets it."""
        pending_id = write_pending(kb_root, _CONTENT_WITH_MATURITY_VERIFIED)
        pending_path = kb_root / "contributions" / "pending" / f"{pending_id}.md"
        post = frontmatter.load(str(pending_path))
        assert post.metadata.get("maturity") == "verified"

    def test_pending_id_assigned(self, kb_root: Path):
        """write_pending() assigns a pending- prefixed ID."""
        pending_id = write_pending(kb_root, _CONTENT_NO_MATURITY)
        assert pending_id.startswith("pending-")

    def test_pending_fields_set(self, kb_root: Path):
        """write_pending() sets required pending state fields."""
        pending_id = write_pending(kb_root, _CONTENT_NO_MATURITY)
        pending_path = kb_root / "contributions" / "pending" / f"{pending_id}.md"
        post = frontmatter.load(str(pending_path))
        assert post.metadata.get("pending") is True
        assert "pending_since" in post.metadata
        assert "source" in post.metadata


# ---------------------------------------------------------------------------
# TestPendingSince — T010 (US3)
# ---------------------------------------------------------------------------


class TestPendingSince:
    """US3: list_pending() must include pending_since in returned dicts."""

    def test_list_pending_includes_pending_since(self, kb_root: Path):
        """T010a: new pending entry returned by list_pending() includes non-empty pending_since."""
        from holmes.kb.pending import list_pending

        pending_id = write_pending(kb_root, _CONTENT_NO_MATURITY)
        results = list_pending(kb_root)

        assert len(results) == 1
        assert "pending_since" in results[0], "pending_since key missing from list_pending() result"
        assert results[0]["pending_since"] != "", "pending_since should be non-empty for new entry"

    def test_list_pending_old_entry_missing_field_falls_back(self, kb_root: Path):
        """T010b: old pending entry without pending_since returns created_at (mtime fallback)."""
        from holmes.kb.pending import list_pending

        # Write a pending entry manually without pending_since field.
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / "old-entry.md").write_text(
            "---\nid: old-entry\ntype: pitfall\ntitle: Old Entry\n"
            "maturity: draft\ncategory: database\ntags: []\n"
            "created_at: '2024-01-01T00:00:00+00:00'\nupdated_at: ''\n---\n\nBody.\n",
            encoding="utf-8",
        )

        results = list_pending(kb_root)
        old = next(r for r in results if r["id"] == "old-entry")

        assert "pending_since" in old
        # With mtime fallback: created_at is used since pending_since is absent.
        assert old["pending_since"] == "2024-01-01T00:00:00+00:00"

    def test_list_pending_non_json_format_unchanged(self, kb_root: Path):
        """T010c: existing list fields (id, type, title, created_at, path) are still present."""
        from holmes.kb.pending import list_pending

        write_pending(kb_root, _CONTENT_NO_MATURITY)
        results = list_pending(kb_root)

        assert len(results) == 1
        rec = results[0]
        for key in ("id", "type", "title", "created_at", "path"):
            assert key in rec, f"Expected key '{key}' missing from list_pending() result"


# ---------------------------------------------------------------------------
# TestPendingMtimeFallback — T014 (US5)
# ---------------------------------------------------------------------------


class TestPendingMtimeFallback:
    """US5: list_pending() fills pending_since from file mtime when both date fields are empty."""

    def test_both_empty_uses_mtime(self, tmp_path):
        """T014a: entry with no pending_since or created_at gets pending_since from mtime."""
        from holmes.kb.pending import list_pending

        pending_dir = tmp_path / "contributions" / "pending"
        pending_dir.mkdir(parents=True)
        entry_path = pending_dir / "old-no-dates.md"
        entry_path.write_text(
            "---\nid: old-no-dates\ntype: pitfall\ntitle: No Dates\n"
            "maturity: draft\ncategory: database\ntags: []\n---\n\nBody.\n",
            encoding="utf-8",
        )

        results = list_pending(tmp_path)
        rec = next(r for r in results if r["id"] == "old-no-dates")

        assert rec["pending_since"], "pending_since should be non-empty"
        # Should be a valid ISO datetime string.
        from datetime import datetime
        parsed = datetime.fromisoformat(rec["pending_since"])
        assert parsed is not None

    def test_created_at_only_uses_created_at(self, tmp_path):
        """T014b: entry with created_at but no pending_since gets created_at as pending_since."""
        from holmes.kb.pending import list_pending

        pending_dir = tmp_path / "contributions" / "pending"
        pending_dir.mkdir(parents=True)
        (pending_dir / "only-created.md").write_text(
            "---\nid: only-created\ntype: pitfall\ntitle: Only Created\n"
            "maturity: draft\ncategory: database\ntags: []\n"
            "created_at: '2024-03-15T10:22:33+00:00'\n---\n\nBody.\n",
            encoding="utf-8",
        )

        results = list_pending(tmp_path)
        rec = next(r for r in results if r["id"] == "only-created")

        assert rec["pending_since"] == "2024-03-15T10:22:33+00:00"

    def test_pending_since_original_kept(self, tmp_path):
        """T014c: entry with pending_since already set retains original value."""
        from holmes.kb.pending import list_pending

        pending_dir = tmp_path / "contributions" / "pending"
        pending_dir.mkdir(parents=True)
        (pending_dir / "has-both.md").write_text(
            "---\nid: has-both\ntype: pitfall\ntitle: Has Both\n"
            "maturity: draft\ncategory: database\ntags: []\n"
            "pending_since: '2026-06-01T08:00:00+00:00'\n"
            "created_at: '2026-05-01T08:00:00+00:00'\n---\n\nBody.\n",
            encoding="utf-8",
        )

        results = list_pending(tmp_path)
        rec = next(r for r in results if r["id"] == "has-both")

        assert rec["pending_since"] == "2026-06-01T08:00:00+00:00"


# ---------------------------------------------------------------------------
# TestPendingSinceSource — T014 (US5)
# ---------------------------------------------------------------------------


class TestPendingSinceSource:
    """US5: list_pending() returns pending_since_source field indicating value origin."""

    def test_field_source_when_pending_since_present(self, tmp_path):
        """T014a: entry with pending_since field → source == 'field'."""
        from holmes.kb.pending import list_pending

        pending_dir = tmp_path / "contributions" / "pending"
        pending_dir.mkdir(parents=True)
        (pending_dir / "has-field.md").write_text(
            "---\nid: has-field\ntype: pitfall\ntitle: Has Field\n"
            "maturity: draft\ncategory: database\ntags: []\n"
            "pending_since: '2026-06-01T08:00:00+00:00'\n"
            "created_at: '2026-05-01T08:00:00+00:00'\n---\n\nBody.\n",
            encoding="utf-8",
        )

        results = list_pending(tmp_path)
        rec = next(r for r in results if r["id"] == "has-field")

        assert rec["pending_since_source"] == "field"

    def test_created_at_source_when_no_pending_since(self, tmp_path):
        """T014b: entry with only created_at → source == 'created_at'."""
        from holmes.kb.pending import list_pending

        pending_dir = tmp_path / "contributions" / "pending"
        pending_dir.mkdir(parents=True)
        (pending_dir / "only-created.md").write_text(
            "---\nid: only-created\ntype: pitfall\ntitle: Only Created\n"
            "maturity: draft\ncategory: database\ntags: []\n"
            "created_at: '2024-03-15T10:22:33+00:00'\n---\n\nBody.\n",
            encoding="utf-8",
        )

        results = list_pending(tmp_path)
        rec = next(r for r in results if r["id"] == "only-created")

        assert rec["pending_since_source"] == "created_at"

    def test_mtime_source_when_neither_field_present(self, tmp_path):
        """T014c: entry with no dates → source == 'mtime'."""
        from holmes.kb.pending import list_pending

        pending_dir = tmp_path / "contributions" / "pending"
        pending_dir.mkdir(parents=True)
        (pending_dir / "no-dates.md").write_text(
            "---\nid: no-dates\ntype: pitfall\ntitle: No Dates\n"
            "maturity: draft\ncategory: database\ntags: []\n---\n\nBody.\n",
            encoding="utf-8",
        )

        results = list_pending(tmp_path)
        rec = next(r for r in results if r["id"] == "no-dates")

        assert rec["pending_since_source"] == "mtime"


# ---------------------------------------------------------------------------
# D-5: _find_entry_by_hash scans pending directory
# ---------------------------------------------------------------------------


class TestFindEntryByHashPendingLayer:
    """D-5: _find_entry_by_hash must detect duplicates in contributions/pending/."""

    _DRAFT = (
        "---\n"
        "type: pitfall\n"
        "title: Redis OOM\n"
        "source_hash: abc1234567890xyz\n"
        "import_confidence: 0.9\n"
        "maturity: draft\n"
        "---\n\n## Root Cause\nMaxmemory policy misconfigured.\n"
    )

    def test_finds_match_in_pending(self, tmp_path):
        """Returns (pending_id, file_path) when pending file has matching source_hash."""
        from holmes.kb.agent.tools import _find_entry_by_hash
        from holmes.kb.pending import PENDING_DIR

        pending_dir = tmp_path / PENDING_DIR
        pending_dir.mkdir(parents=True)
        (pending_dir / "pending-20260609-abc123.md").write_text(self._DRAFT, encoding="utf-8")

        pid, fpath = _find_entry_by_hash(tmp_path, "abc1234567890xyz")
        assert pid == "pending-20260609-abc123"
        assert fpath is not None
        assert "pending-20260609-abc123" in fpath

    def test_returns_none_when_no_match_in_pending(self, tmp_path):
        """Returns (None, None) when pending file has a different source_hash."""
        from holmes.kb.agent.tools import _find_entry_by_hash
        from holmes.kb.pending import PENDING_DIR

        pending_dir = tmp_path / PENDING_DIR
        pending_dir.mkdir(parents=True)
        (pending_dir / "pending-other.md").write_text(self._DRAFT, encoding="utf-8")

        pid, fpath = _find_entry_by_hash(tmp_path, "differenthash0000")
        assert pid is None
        assert fpath is None

    def test_skips_corrupt_pending_file(self, tmp_path):
        """Malformed pending files are skipped silently; function does not raise."""
        from holmes.kb.agent.tools import _find_entry_by_hash
        from holmes.kb.pending import PENDING_DIR

        pending_dir = tmp_path / PENDING_DIR
        pending_dir.mkdir(parents=True)
        # Write a file with no frontmatter at all
        (pending_dir / "corrupt.md").write_text("not yaml at all ::::: {}", encoding="utf-8")
        # Write a valid file that also doesn't match
        (pending_dir / "valid.md").write_text(self._DRAFT, encoding="utf-8")

        # Should not raise; should not find match for a different hash
        pid, fpath = _find_entry_by_hash(tmp_path, "nomatch00000000x")
        assert pid is None

    def test_returns_none_when_pending_dir_missing(self, tmp_path):
        """If contributions/pending/ does not exist, returns (None, None) without error."""
        from holmes.kb.agent.tools import _find_entry_by_hash

        # No pending directory created — empty KB root
        pid, fpath = _find_entry_by_hash(tmp_path, "abc1234567890xyz")
        assert pid is None
        assert fpath is None

    def test_approved_kb_takes_priority_over_pending(self, tmp_path):
        """Approved KB match is returned before scanning pending directory."""
        from holmes.kb.agent.tools import _find_entry_by_hash
        from holmes.kb.pending import PENDING_DIR
        from holmes.kb.store import write_entry

        # Create an approved KB entry with the hash
        pitfall_dir = tmp_path / "pitfall" / "database"
        pitfall_dir.mkdir(parents=True)
        approved_content = (
            "---\n"
            "id: pitfall-database-001\n"
            "type: pitfall\n"
            "title: Redis OOM\n"
            "source_hash: abc1234567890xyz\n"
            "maturity: verified\n"
            "category: database\n"
            "tags: []\n"
            "---\n\n## Root Cause\nMaxmemory policy misconfigured.\n"
        )
        write_entry(pitfall_dir / "pitfall-database-001.md", approved_content)

        # Also create a pending entry with same hash (should NOT be returned)
        pending_dir = tmp_path / PENDING_DIR
        pending_dir.mkdir(parents=True)
        (pending_dir / "pending-duplicate.md").write_text(self._DRAFT, encoding="utf-8")

        pid, fpath = _find_entry_by_hash(tmp_path, "abc1234567890xyz")
        assert pid == "pitfall-database-001"
