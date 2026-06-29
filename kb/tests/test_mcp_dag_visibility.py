"""Tests for MCP visibility of DAG-imported entries in _pending/.

Covers the full chain: import writes to _pending/ -> MCP tools can find them.

    T1 - handle_kb_list shows pending entries from _pending/
    T2 - handle_kb_list hides draft entries
    T3 - handle_kb_search finds entries in _pending/
    T4 - handle_kb_read reads entries from _pending/ by ID
    T5 - handle_kb_read resolves child_entry_ids for tree navigation
    T6 - handle_kb_confirm accepts new-format entry IDs
    T7 - list_entries scans _pending/<type>/ directories
    T8 - search scans _pending/<type>/ directories
"""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PITFALL_ROOT = """\
---
title: Disk Full — Cleanup Flow
description: Disk full causes service startup failure
type: pitfall
category: storage
pitfall_structure: tree
kb_status: pending
source_file: disk_full.md
source_hash: abc12345678901ab
import_trace_id: disk_full
child_entry_ids:
  - disk-full-N1-001
parent_id: null
maturity: draft
decay_status: active
next_decay_check: "2027-01-01"
contributors:
  - {user: testuser, role: initiator}
tags: [disk, storage]
---

## Symptoms

Service fails to start.

## Root Cause

Disk full.

## Resolution

See [cleanup](disk-full-N1-001).
"""

_PROCESS_CHILD = """\
---
title: Log Cleanup Steps
description: Clean up old logs
type: process
category: storage
kb_status: pending
source_file: disk_full.md
source_hash: abc12345678901ab
import_trace_id: disk_full
parent_id: disk-full-root-001
maturity: draft
decay_status: active
next_decay_check: "2027-01-01"
contributors:
  - {user: testuser, role: initiator}
tags: [disk, cleanup]
---

## Steps

1. **[api]** Check disk usage
   `df -h`

2. **[remote]** Remove old logs
   `find /var/log -name '*.gz' -mtime +30 -delete`
"""


@pytest.fixture()
def kb_with_pending(tmp_path: Path) -> Path:
    """Create a KB with entries in _pending/<type>/<category>/."""
    # Pitfall root in _pending/pitfall/storage/
    pitfall_dir = tmp_path / "_pending" / "pitfall" / "storage"
    pitfall_dir.mkdir(parents=True)
    (pitfall_dir / "disk-full-root-001.md").write_text(_PITFALL_ROOT, encoding="utf-8")

    # Process child in _pending/process/storage/
    process_dir = tmp_path / "_pending" / "process" / "storage"
    process_dir.mkdir(parents=True)
    (process_dir / "disk-full-N1-001.md").write_text(_PROCESS_CHILD, encoding="utf-8")

    # Also create empty confirmed dirs so list_entries doesn't skip
    for t in ("pitfall", "model", "guideline", "process", "decision"):
        (tmp_path / t).mkdir(exist_ok=True)

    # Evidence sidecar dir
    (tmp_path / "contributions" / "evidence").mkdir(parents=True, exist_ok=True)

    return tmp_path


# ---------------------------------------------------------------------------
# T1 - handle_kb_list shows pending entries
# ---------------------------------------------------------------------------


def test_kb_list_shows_pending_pitfall(kb_with_pending: Path):
    """Pitfall root in _pending/ should appear in kb_list."""
    from holmes.mcp.tools import handle_kb_list

    result = handle_kb_list(kb_with_pending)
    ids = [e["id"] for e in result["entries"]]
    assert "disk-full-root-001" in ids


def test_kb_list_shows_pending_with_type_filter(kb_with_pending: Path):
    """Type filter should work for pending entries too."""
    from holmes.mcp.tools import handle_kb_list

    result = handle_kb_list(kb_with_pending, type="pitfall")
    ids = [e["id"] for e in result["entries"]]
    assert "disk-full-root-001" in ids


# ---------------------------------------------------------------------------
# T2 - handle_kb_list hides draft entries
# ---------------------------------------------------------------------------


def test_kb_list_hides_draft_status(tmp_path: Path):
    """Entries with kb_status=draft should NOT appear in kb_list."""
    for t in ("pitfall", "model", "guideline", "process", "decision"):
        (tmp_path / t).mkdir(exist_ok=True)
    pitfall_dir = tmp_path / "_pending" / "pitfall" / "test"
    pitfall_dir.mkdir(parents=True)

    draft_entry = _PITFALL_ROOT.replace("kb_status: pending", "kb_status: draft")
    (pitfall_dir / "draft-entry-001.md").write_text(draft_entry, encoding="utf-8")

    from holmes.mcp.tools import handle_kb_list

    result = handle_kb_list(tmp_path)
    ids = [e["id"] for e in result["entries"]]
    assert "draft-entry-001" not in ids


# ---------------------------------------------------------------------------
# T3 - handle_kb_search finds entries in _pending/
# ---------------------------------------------------------------------------


def test_kb_search_finds_pending_entry(kb_with_pending: Path):
    """Search should find entries in _pending/ by keyword."""
    from holmes.mcp.tools import handle_kb_search

    result = handle_kb_search(kb_with_pending, query="disk full cleanup")
    ids = [item["id"] for item in result["items"]]
    assert any("disk-full" in eid for eid in ids), f"Expected disk-full entry in {ids}"


def test_kb_search_hides_pending_sub_entries(kb_with_pending: Path):
    """Process sub-entries (parent_id set) should be hidden from search.

    Sub-entries are navigated via kb_read tree navigation (root → children),
    not via direct search results.
    """
    from holmes.mcp.tools import handle_kb_search

    result = handle_kb_search(kb_with_pending, query="log cleanup")
    ids = [item["id"] for item in result["items"]]
    assert "disk-full-N1-001" not in ids, f"Sub-entry should be hidden from search, got {ids}"


# ---------------------------------------------------------------------------
# T4 - handle_kb_read reads entries from _pending/
# ---------------------------------------------------------------------------


def test_kb_read_pending_entry_by_id(kb_with_pending: Path):
    """kb_read should find entries in _pending/ by their ID."""
    from holmes.mcp.tools import handle_kb_read

    result = handle_kb_read(kb_with_pending, entry_id="disk-full-root-001")
    assert "error" not in result, result.get("error")
    assert result["id"] == "disk-full-root-001"
    assert result["type"] == "pitfall"
    assert "## Symptoms" in result["content"]


def test_kb_read_pending_process_entry(kb_with_pending: Path):
    """kb_read should find process entries in _pending/."""
    from holmes.mcp.tools import handle_kb_read

    result = handle_kb_read(kb_with_pending, entry_id="disk-full-N1-001")
    assert "error" not in result, result.get("error")
    assert result["type"] == "process"
    assert "## Steps" in result["content"]


# ---------------------------------------------------------------------------
# T5 - handle_kb_read resolves child_entry_ids for tree navigation
# ---------------------------------------------------------------------------


def test_kb_read_resolves_children(kb_with_pending: Path):
    """Pitfall root's child_entry_ids should resolve to [{id, title}]."""
    from holmes.mcp.tools import handle_kb_read

    result = handle_kb_read(kb_with_pending, entry_id="disk-full-root-001")
    assert "children" in result, "Expected children field in response"
    children = result["children"]
    assert len(children) == 1
    assert children[0]["id"] == "disk-full-N1-001"
    assert children[0]["title"] == "Log Cleanup Steps"


def test_kb_read_tree_navigation_chain(kb_with_pending: Path):
    """Full navigation: read root -> get child ID -> read child -> has Steps."""
    from holmes.mcp.tools import handle_kb_read

    # Step 1: Read pitfall root
    root = handle_kb_read(kb_with_pending, entry_id="disk-full-root-001")
    assert "children" in root
    child_id = root["children"][0]["id"]

    # Step 2: Read child process entry
    child = handle_kb_read(kb_with_pending, entry_id=child_id)
    assert "error" not in child
    assert "## Steps" in child["content"]
    assert "df -h" in child["content"]


# ---------------------------------------------------------------------------
# T6 - handle_kb_confirm accepts new-format entry IDs
# ---------------------------------------------------------------------------


def test_kb_confirm_accepts_new_format_id(kb_with_pending: Path):
    """kb_confirm should accept DAG-style IDs like 'disk-full-root-001'."""
    from holmes.mcp.tools import handle_kb_confirm

    result = handle_kb_confirm(
        kb_with_pending,
        entry_id="disk-full-root-001",
        session_id="test-session-001",
    )
    assert result.get("ok") is True, f"Expected ok=True, got {result}"


def test_kb_confirm_rejects_nonexistent_id(kb_with_pending: Path):
    """kb_confirm should reject IDs that don't exist in the KB."""
    from holmes.mcp.tools import handle_kb_confirm

    result = handle_kb_confirm(
        kb_with_pending,
        entry_id="nonexistent-entry-999",
        session_id="test-session-001",
    )
    assert result.get("ok") is False
    assert result.get("reason") == "not_found"


def test_kb_confirm_still_accepts_legacy_id(tmp_path: Path):
    """kb_confirm should still work with legacy IDs like PT-DB-001."""
    # Create a legacy-format entry
    pitfall_dir = tmp_path / "pitfall" / "database"
    pitfall_dir.mkdir(parents=True)
    (pitfall_dir / "PT-DB-001.md").write_text(
        "---\nid: PT-DB-001\ntype: pitfall\ntitle: Test\nmaturity: draft\n"
        "category: database\ntags: []\ncreated_at: '2026-01-01'\nupdated_at: '2026-01-01'\n---\n\n## Symptoms\nTest\n",
        encoding="utf-8",
    )
    (tmp_path / "contributions" / "evidence").mkdir(parents=True, exist_ok=True)

    from holmes.mcp.tools import handle_kb_confirm

    result = handle_kb_confirm(tmp_path, entry_id="PT-DB-001", session_id="test-session-002")
    assert result.get("ok") is True, f"Expected ok=True, got {result}"


# ---------------------------------------------------------------------------
# T7 - list_entries scans _pending/<type>/ directories
# ---------------------------------------------------------------------------


def test_list_entries_includes_pending_dir(kb_with_pending: Path):
    """list_entries with kb_status=None should include _pending/ entries."""
    from holmes.kb.store import list_entries

    entries = list_entries(kb_with_pending, kb_status=None, exclude_sub_entries=False)
    ids = [e.id for e in entries]
    assert "disk-full-root-001" in ids
    assert "disk-full-N1-001" in ids


def test_list_entries_pending_filter(kb_with_pending: Path):
    """list_entries with kb_status='pending' should only return pending entries."""
    from holmes.kb.store import list_entries

    entries = list_entries(kb_with_pending, kb_status="pending", exclude_sub_entries=False)
    assert len(entries) == 2
    assert all(e.kb_status == "pending" for e in entries)


def test_list_entries_active_filter_excludes_pending(kb_with_pending: Path):
    """list_entries with kb_status='active' should NOT return pending entries."""
    from holmes.kb.store import list_entries

    entries = list_entries(kb_with_pending, kb_status="active", exclude_sub_entries=False)
    ids = [e.id for e in entries]
    assert "disk-full-root-001" not in ids


# ---------------------------------------------------------------------------
# T8 - search scans _pending/<type>/ directories
# ---------------------------------------------------------------------------


def test_search_includes_pending_dir(kb_with_pending: Path):
    """search() should find entries in _pending/."""
    from holmes.kb.search import search

    results = search(kb_with_pending, query="disk full", active_only=True)
    ids = [r.entry_id for r in results]
    assert any("disk-full" in eid for eid in ids), f"Expected disk-full in {ids}"


def test_search_excludes_draft_status(tmp_path: Path):
    """search() with active_only=True should hide kb_status=draft entries."""
    for t in ("pitfall", "model", "guideline", "process", "decision"):
        (tmp_path / t).mkdir(exist_ok=True)
    pitfall_dir = tmp_path / "_pending" / "pitfall" / "test"
    pitfall_dir.mkdir(parents=True)

    draft_entry = _PITFALL_ROOT.replace("kb_status: pending", "kb_status: draft")
    (pitfall_dir / "draft-entry-001.md").write_text(draft_entry, encoding="utf-8")
    (tmp_path / "contributions" / "evidence").mkdir(parents=True, exist_ok=True)

    from holmes.kb.search import search

    results = search(tmp_path, query="disk full", active_only=True)
    ids = [r.entry_id for r in results]
    assert "draft-entry-001" not in ids
