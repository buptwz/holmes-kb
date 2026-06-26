"""Tests for M1: list_entries() kb_status filter and exclude_sub_entries filter."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from holmes.kb.store import EntryMeta, list_entries


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_entry(kb_root: Path, kb_type: str, filename: str, meta: dict, body: str = "") -> Path:
    """Write a minimal KB entry file and return its path."""
    type_dir = kb_root / kb_type
    type_dir.mkdir(parents=True, exist_ok=True)
    path = type_dir / filename
    post = frontmatter.Post(body, **meta)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return path


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    """Return a temporary KB root with a mix of entry types and statuses."""
    # Active pitfall (no kb_status field — legacy entry, treated as active)
    _write_entry(kb_root=tmp_path, kb_type="pitfall", filename="legacy-001.md", meta={
        "id": "legacy-001",
        "type": "pitfall",
        "title": "Legacy active entry",
        "maturity": "draft",
        "category": "network",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })

    # Active pitfall with explicit kb_status
    _write_entry(kb_root=tmp_path, kb_type="pitfall", filename="active-001.md", meta={
        "id": "active-001",
        "type": "pitfall",
        "title": "Explicit active entry",
        "maturity": "draft",
        "kb_status": "active",
        "category": "network",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })

    # Deprecated pitfall
    _write_entry(kb_root=tmp_path, kb_type="pitfall", filename="deprecated-001.md", meta={
        "id": "deprecated-001",
        "type": "pitfall",
        "title": "Deprecated entry",
        "maturity": "draft",
        "kb_status": "deprecated",
        "category": "network",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })

    # Pending pitfall (kb_status=pending; not in contributions/pending/ but same filter applies)
    _write_entry(kb_root=tmp_path, kb_type="pitfall", filename="pending-style-001.md", meta={
        "id": "pending-style-001",
        "type": "pitfall",
        "title": "Pending-status entry",
        "maturity": "draft",
        "kb_status": "pending",
        "category": "network",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })

    # Active process entry (NO parent_id — top-level process, should appear by default)
    _write_entry(kb_root=tmp_path, kb_type="process", filename="top-process-001.md", meta={
        "id": "top-process-001",
        "type": "process",
        "title": "Top-level process",
        "maturity": "draft",
        "kb_status": "active",
        "category": "network",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })

    # Active process sub-entry (HAS parent_id — should be hidden by default)
    _write_entry(kb_root=tmp_path, kb_type="process", filename="sub-process-001.md", meta={
        "id": "sub-process-001",
        "type": "process",
        "title": "Process sub-entry",
        "maturity": "draft",
        "kb_status": "active",
        "parent_id": "active-001",
        "category": "network",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })

    return tmp_path


# ---------------------------------------------------------------------------
# kb_status filter tests (T007)
# ---------------------------------------------------------------------------

class TestKbStatusFilter:
    def test_default_shows_only_active(self, kb_root: Path) -> None:
        """Default call returns only active entries (explicit + legacy no-field)."""
        entries = list_entries(kb_root)
        ids = {e.id for e in entries}
        assert "legacy-001" in ids, "Legacy entry (no kb_status) should be treated as active"
        assert "active-001" in ids, "Explicit active entry should appear"
        assert "deprecated-001" not in ids, "Deprecated entry should be hidden"
        assert "pending-style-001" not in ids, "Pending-status entry should be hidden"

    def test_all_flag_includes_deprecated(self, kb_root: Path) -> None:
        """kb_status=None returns both active and deprecated (and pending)."""
        entries = list_entries(kb_root, kb_status=None, exclude_sub_entries=False)
        ids = {e.id for e in entries}
        assert "active-001" in ids
        assert "deprecated-001" in ids
        assert "legacy-001" in ids

    def test_deprecated_only(self, kb_root: Path) -> None:
        """kb_status='deprecated' returns only deprecated entries."""
        entries = list_entries(kb_root, kb_status="deprecated", exclude_sub_entries=False)
        ids = {e.id for e in entries}
        assert ids == {"deprecated-001"}

    def test_legacy_entry_visible_by_default(self, kb_root: Path) -> None:
        """Legacy entry without kb_status field is treated as active and visible."""
        entries = list_entries(kb_root, kb_status="active")
        ids = {e.id for e in entries}
        assert "legacy-001" in ids

    def test_entrymeta_kb_status_populated(self, kb_root: Path) -> None:
        """EntryMeta.kb_status is populated from frontmatter."""
        entries = list_entries(kb_root, kb_status=None, exclude_sub_entries=False)
        by_id = {e.id: e for e in entries}
        assert by_id["active-001"].kb_status == "active"
        assert by_id["deprecated-001"].kb_status == "deprecated"
        assert by_id["legacy-001"].kb_status == "active"  # default


# ---------------------------------------------------------------------------
# exclude_sub_entries filter tests (T011)
# ---------------------------------------------------------------------------

class TestExcludeSubEntries:
    def test_default_hides_process_sub_entry(self, kb_root: Path) -> None:
        """By default, process entries with parent_id are excluded."""
        entries = list_entries(kb_root)
        ids = {e.id for e in entries}
        assert "sub-process-001" not in ids

    def test_top_level_process_visible_by_default(self, kb_root: Path) -> None:
        """Process entry without parent_id is visible by default."""
        entries = list_entries(kb_root)
        ids = {e.id for e in entries}
        assert "top-process-001" in ids

    def test_all_types_shows_sub_entries(self, kb_root: Path) -> None:
        """exclude_sub_entries=False shows process sub-entries."""
        entries = list_entries(kb_root, exclude_sub_entries=False)
        ids = {e.id for e in entries}
        assert "sub-process-001" in ids

    def test_entrymeta_parent_id_populated(self, kb_root: Path) -> None:
        """EntryMeta.parent_id is populated for sub-entries."""
        entries = list_entries(kb_root, exclude_sub_entries=False)
        by_id = {e.id: e for e in entries}
        assert by_id["sub-process-001"].parent_id == "active-001"
        assert by_id["top-process-001"].parent_id is None
