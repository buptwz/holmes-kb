"""Tests for governance.py — write protection and title duplicate guards."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from holmes.kb.governance import (
    DuplicateTitleError,
    check_title_duplicate,
    is_write_protected,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    kb_root: Path,
    entry_id: str,
    title: str,
    maturity: str,
    kb_type: str = "pitfall",
    category: str = "database",
) -> Path:
    """Write a minimal KB entry file and return its path."""
    entry_dir = kb_root / kb_type / category
    entry_dir.mkdir(parents=True, exist_ok=True)
    path = entry_dir / f"{entry_id}.md"
    content = f"""\
---
id: {entry_id}
type: {kb_type}
title: {title}
maturity: {maturity}
category: {category}
tags: []
created_at: "2025-01-01T00:00:00+00:00"
updated_at: "2025-01-01T00:00:00+00:00"
---

## Symptoms
Test.

## Root Cause
Test.

## Resolution
Test.
"""
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# check_title_duplicate
# ---------------------------------------------------------------------------

class TestCheckTitleDuplicate:

    def test_no_entries_returns_none(self, tmp_path):
        result = check_title_duplicate(tmp_path, "Some Title")
        assert result is None

    def test_match_verified_returns_id(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "Redis connection timeout", "verified")
        result = check_title_duplicate(tmp_path, "Redis connection timeout")
        assert result == "PT-DB-001"

    def test_match_proven_returns_id(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "Redis connection timeout", "proven")
        result = check_title_duplicate(tmp_path, "Redis connection timeout")
        assert result == "PT-DB-001"

    def test_draft_not_matched(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "Redis connection timeout", "draft")
        result = check_title_duplicate(tmp_path, "Redis connection timeout")
        assert result is None

    def test_case_insensitive_match(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "Redis Connection Timeout", "verified")
        result = check_title_duplicate(tmp_path, "redis connection timeout")
        assert result == "PT-DB-001"

    def test_no_match_returns_none(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "Redis connection timeout", "verified")
        result = check_title_duplicate(tmp_path, "MySQL deadlock issue")
        assert result is None

    def test_exclude_corrects_skips_target(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "Redis connection timeout", "verified")
        # When correcting PT-DB-001, its own title should not block the submission.
        result = check_title_duplicate(
            tmp_path, "Redis connection timeout", exclude_corrects="PT-DB-001"
        )
        assert result is None

    def test_exclude_corrects_does_not_skip_others(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "Redis connection timeout", "verified")
        _make_entry(tmp_path, "PT-DB-002", "Redis connection timeout", "verified")
        # Should still find the OTHER entry even with exclude_corrects set for PT-DB-001.
        result = check_title_duplicate(
            tmp_path, "Redis connection timeout", exclude_corrects="PT-DB-001"
        )
        assert result == "PT-DB-002"

    def test_empty_title_returns_none(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "Redis connection timeout", "verified")
        result = check_title_duplicate(tmp_path, "")
        assert result is None


# ---------------------------------------------------------------------------
# is_write_protected
# ---------------------------------------------------------------------------

class TestIsWriteProtected:

    def test_verified_entry_is_protected(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "Redis connection timeout", "verified")
        protected, msg = is_write_protected(tmp_path, "PT-DB-001")
        assert protected is True
        assert "PT-DB-001" in msg
        assert "verified" in msg

    def test_proven_entry_is_protected(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "Redis connection timeout", "proven")
        protected, msg = is_write_protected(tmp_path, "PT-DB-001")
        assert protected is True
        assert "proven" in msg

    def test_draft_entry_not_protected(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "Redis connection timeout", "draft")
        protected, msg = is_write_protected(tmp_path, "PT-DB-001")
        assert protected is False
        assert msg == ""

    def test_missing_entry_not_protected(self, tmp_path):
        protected, msg = is_write_protected(tmp_path, "PT-DB-NONEXISTENT")
        assert protected is False
        assert msg == ""

    def test_error_message_suggests_corrects(self, tmp_path):
        _make_entry(tmp_path, "PT-DB-001", "Redis connection timeout", "verified")
        protected, msg = is_write_protected(tmp_path, "PT-DB-001")
        assert "--corrects" in msg
