"""Tests for the list_entries in-process cache (US4 perf optimisation)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from holmes.kb.store import (
    EntryMeta,
    _CACHE,
    invalidate_cache,
    list_entries,
    write_entry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENTRY_CONTENT = textwrap.dedent("""\
    ---
    id: PT-DB-001
    type: pitfall
    title: Test Entry
    maturity: draft
    category: database
    tags: []
    created_at: "2026-01-01T00:00:00+00:00"
    updated_at: "2026-01-01T00:00:00+00:00"
    ---

    ## Root Cause

    Some cause.

    ## Resolution

    Some resolution.
""")


def _make_kb(tmp_path: Path) -> Path:
    """Create a minimal KB with one pitfall entry."""
    kb = tmp_path / "kb"
    entry_dir = kb / "pitfall"
    entry_dir.mkdir(parents=True)
    (entry_dir / "PT-DB-001.md").write_text(_ENTRY_CONTENT, encoding="utf-8")
    return kb


# ---------------------------------------------------------------------------
# Cache hit: second call returns cached result without re-scanning disk
# ---------------------------------------------------------------------------

def test_cache_hit_avoids_second_scan(tmp_path: Path) -> None:
    """list_entries should not re-scan disk on a cache-hit call."""
    invalidate_cache()
    kb = _make_kb(tmp_path)

    scan_count = 0
    original_scan = __import__(
        "holmes.kb.store", fromlist=["_scan_entries_from_disk"]
    )._scan_entries_from_disk

    def _counting_scan(kb_root: Path, include_pending: bool) -> list[EntryMeta]:
        nonlocal scan_count
        scan_count += 1
        return original_scan(kb_root, include_pending)

    with patch("holmes.kb.store._scan_entries_from_disk", side_effect=_counting_scan):
        r1 = list_entries(kb)
        r2 = list_entries(kb)

    assert scan_count == 1, "Disk scan should happen exactly once; second call hits cache"
    assert r1 == r2


# ---------------------------------------------------------------------------
# Cache invalidation on write_entry
# ---------------------------------------------------------------------------

def test_cache_invalidated_after_write_entry(tmp_path: Path) -> None:
    """write_entry must clear the cache so the new file is visible on next call."""
    invalidate_cache()
    kb = _make_kb(tmp_path)

    # Populate cache with 1 entry.
    entries_before = list_entries(kb)
    assert len(entries_before) == 1

    # Write a second entry — should invalidate cache.
    new_content = _ENTRY_CONTENT.replace("PT-DB-001", "PT-DB-002").replace(
        "Test Entry", "Second Entry"
    )
    write_entry(kb / "pitfall" / "PT-DB-002.md", new_content)

    # After invalidation, next call should re-scan and find both entries.
    entries_after = list_entries(kb)
    assert len(entries_after) == 2


# ---------------------------------------------------------------------------
# Cache invalidation on write_pending
# ---------------------------------------------------------------------------

def test_cache_invalidated_after_write_pending(tmp_path: Path) -> None:
    """write_pending must clear the cache so pending entries are visible."""
    from holmes.kb.pending import write_pending

    invalidate_cache()
    kb = _make_kb(tmp_path)

    # Populate cache (no pending yet).
    before = list_entries(kb, include_pending=True)
    count_before = len(before)

    # Write a pending entry — should invalidate cache.
    content = _ENTRY_CONTENT.replace("PT-DB-001", "PENDING-X").replace(
        "Test Entry", "Pending Test"
    )
    write_pending(kb, content, source="test")

    after = list_entries(kb, include_pending=True)
    assert len(after) == count_before + 1


# ---------------------------------------------------------------------------
# Separate cache keys for include_pending=True and False
# ---------------------------------------------------------------------------

def test_separate_cache_keys_for_pending(tmp_path: Path) -> None:
    """include_pending=True and include_pending=False must use separate cache keys."""
    from holmes.kb.pending import write_pending

    invalidate_cache()
    kb = _make_kb(tmp_path)

    content = _ENTRY_CONTENT.replace("PT-DB-001", "PENDING-Y").replace(
        "Test Entry", "Pending Y"
    )
    write_pending(kb, content, source="test")
    invalidate_cache()

    without_pending = list_entries(kb, include_pending=False)
    with_pending = list_entries(kb, include_pending=True)

    assert len(with_pending) > len(without_pending)
    cache_key_false = (str(kb), False)
    cache_key_true = (str(kb), True)
    assert cache_key_false in _CACHE
    assert cache_key_true in _CACHE


# ---------------------------------------------------------------------------
# kb_type filter applied in-memory (no extra scan)
# ---------------------------------------------------------------------------

def test_kb_type_filter_does_not_re_scan(tmp_path: Path) -> None:
    """Filtering by kb_type should use the cached full list, not re-scan."""
    invalidate_cache()
    kb = _make_kb(tmp_path)

    scan_count = 0
    original_scan = __import__(
        "holmes.kb.store", fromlist=["_scan_entries_from_disk"]
    )._scan_entries_from_disk

    def _counting_scan(kb_root: Path, include_pending: bool) -> list[EntryMeta]:
        nonlocal scan_count
        scan_count += 1
        return original_scan(kb_root, include_pending)

    with patch("holmes.kb.store._scan_entries_from_disk", side_effect=_counting_scan):
        list_entries(kb)                          # populates cache
        list_entries(kb, kb_type="pitfall")        # should be cache hit + in-memory filter
        list_entries(kb, kb_type="model")          # another filter, same cache

    assert scan_count == 1, "Only one disk scan should occur across multiple kb_type filter calls"


# ---------------------------------------------------------------------------
# _bust_cache bypasses cache
# ---------------------------------------------------------------------------

def test_bust_cache_forces_rescan(tmp_path: Path) -> None:
    """_bust_cache=True should bypass the cache and do a fresh disk scan."""
    invalidate_cache()
    kb = _make_kb(tmp_path)

    scan_count = 0
    original_scan = __import__(
        "holmes.kb.store", fromlist=["_scan_entries_from_disk"]
    )._scan_entries_from_disk

    def _counting_scan(kb_root: Path, include_pending: bool) -> list[EntryMeta]:
        nonlocal scan_count
        scan_count += 1
        return original_scan(kb_root, include_pending)

    with patch("holmes.kb.store._scan_entries_from_disk", side_effect=_counting_scan):
        list_entries(kb)                     # scan #1
        list_entries(kb)                     # cache hit — no scan
        list_entries(kb, _bust_cache=True)   # forced scan #2

    assert scan_count == 2
