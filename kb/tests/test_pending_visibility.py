"""Tests for Bug-3: pending entries must be visible via MCP tools.

Bug-3A: _compute_linked_entries() must scan contributions/pending/.
Bug-3B: handle_kb_read("pending-xxx") must return content, not "Skill not found".
"""

from __future__ import annotations

from pathlib import Path

import pytest


PENDING_ENTRY = """\
---
id: pending-20260617-120000-ab12
type: pitfall
title: E810 TX Hang 排查
maturity: draft
category: network
tags: [e810]
created_at: 2026-06-17T12:00:00+00:00
updated_at: 2026-06-17T12:00:00+00:00
pending: true
pending_since: 2026-06-17T12:00:00+00:00
source: auto
source_session: 2026-06-17T12:00:00+00:00
suggested_type: pitfall
suggested_category: network
skill_refs:
  - e810-firmware-upgrade
---

## Symptoms

间歇性 TX Hang。

## Root Cause

固件版本过低。

## Resolution

升级固件后验证。
"""


def _setup_kb(tmp_path: Path, pending_content: str = PENDING_ENTRY) -> Path:
    """Create a minimal KB directory with one pending entry."""
    kb_root = tmp_path / "kb"
    pending_dir = kb_root / "contributions" / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    (pending_dir / "pending-20260617-120000-ab12.md").write_text(
        pending_content, encoding="utf-8"
    )
    return kb_root


class TestComputeLinkedEntriesScansPending:
    """Bug-3A: _compute_linked_entries() includes pending entries."""

    def test_pending_entry_appears_in_linked_entries(self, tmp_path: Path):
        from holmes.mcp.tools import _compute_linked_entries

        kb_root = _setup_kb(tmp_path)
        linked = _compute_linked_entries(kb_root, "e810-firmware-upgrade")
        assert "pending-20260617-120000-ab12" in linked

    def test_unknown_skill_returns_empty(self, tmp_path: Path):
        from holmes.mcp.tools import _compute_linked_entries

        kb_root = _setup_kb(tmp_path)
        linked = _compute_linked_entries(kb_root, "nonexistent-skill")
        assert linked == []

    def test_confirmed_entry_still_returned(self, tmp_path: Path):
        """Confirmed entries are still returned (no regression)."""
        from holmes.mcp.tools import _compute_linked_entries

        kb_root = _setup_kb(tmp_path)
        pitfall_dir = kb_root / "pitfall"
        pitfall_dir.mkdir(parents=True, exist_ok=True)
        (pitfall_dir / "PT-NW-001.md").write_text(
            "---\nid: PT-NW-001\ntype: pitfall\ntitle: Test\n"
            "skill_refs:\n  - e810-firmware-upgrade\n---\n\nBody.\n",
            encoding="utf-8",
        )
        linked = _compute_linked_entries(kb_root, "e810-firmware-upgrade")
        assert "PT-NW-001" in linked
        assert "pending-20260617-120000-ab12" in linked


class TestHandleKbReadPendingEntry:
    """Bug-3B: handle_kb_read('pending-xxx') returns content, not skill error."""

    def test_pending_entry_readable(self, tmp_path: Path):
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(kb_root, "pending-20260617-120000-ab12")

        assert "error" not in result
        assert result["id"] == "pending-20260617-120000-ab12"
        assert result.get("pending") is True
        assert "content" in result
        assert "skill_refs" in result
        assert "e810-firmware-upgrade" in result["skill_refs"]

    def test_nonexistent_pending_returns_not_found(self, tmp_path: Path):
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(kb_root, "pending-99999999-000000-xxxx")
        assert "error" in result

    def test_pending_with_path_returns_error(self, tmp_path: Path):
        """path param is not valid for pending entries."""
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(
            kb_root, "pending-20260617-120000-ab12", path="scripts/foo.sh"
        )
        assert "error" in result
