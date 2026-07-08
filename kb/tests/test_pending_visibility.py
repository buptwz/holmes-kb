"""Tests for Bug-3: pending entries must be visible via MCP tools.

Bug-3B: handle_kb_read("pending-xxx") must return content, not error.
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


class TestHandleKbReadPendingEntry:
    """Bug-3B: handle_kb_read('pending-xxx') returns content, not error."""

    def test_pending_entry_readable(self, tmp_path: Path):
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(kb_root, "pending-20260617-120000-ab12", full=True)

        assert "error" not in result
        assert result["id"] == "pending-20260617-120000-ab12"
        assert "content" in result

    def test_nonexistent_pending_returns_not_found(self, tmp_path: Path):
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(kb_root, "pending-99999999-000000-xxxx")
        assert "error" in result
