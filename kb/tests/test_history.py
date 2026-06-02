"""Tests for history.py — VersionSnapshot creation and listing."""

from __future__ import annotations

import time
from pathlib import Path

import frontmatter
import pytest

from holmes.kb.history import HISTORY_DIR, list_snapshots, read_snapshot, save_snapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_CONTENT = """\
---
id: PT-DB-001
type: pitfall
title: Redis connection timeout
maturity: verified
category: database
tags: [redis]
created_at: "2025-01-01T00:00:00+00:00"
updated_at: "2025-01-01T00:00:00+00:00"
---

## Symptoms
Test symptoms.

## Root Cause
Test root cause.

## Resolution
Test resolution.
"""


# ---------------------------------------------------------------------------
# save_snapshot
# ---------------------------------------------------------------------------

class TestSaveSnapshot:

    def test_creates_history_dir(self, tmp_path):
        save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-001", reason="correction")
        assert (tmp_path / HISTORY_DIR).is_dir()

    def test_snapshot_file_exists(self, tmp_path):
        path = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-001")
        assert path.exists()

    def test_snapshot_filename_starts_with_entry_id(self, tmp_path):
        path = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-001")
        assert path.name.startswith("PT-DB-001-")

    def test_snapshot_filename_ends_with_md(self, tmp_path):
        path = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-001")
        assert path.suffix == ".md"

    def test_snapshot_has_replaced_at(self, tmp_path):
        path = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-001")
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        assert "replaced_at" in post.metadata

    def test_snapshot_has_replaced_by(self, tmp_path):
        path = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-20260601-ab12")
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        assert post.metadata["replaced_by"] == "pending-20260601-ab12"

    def test_snapshot_has_snapshot_reason_correction(self, tmp_path):
        path = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-001", reason="correction")
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        assert post.metadata["snapshot_reason"] == "correction"

    def test_snapshot_has_snapshot_reason_decay(self, tmp_path):
        path = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "decay", reason="decay")
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        assert post.metadata["snapshot_reason"] == "decay"

    def test_snapshot_preserves_original_fields(self, tmp_path):
        path = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-001")
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        assert post.metadata["id"] == "PT-DB-001"
        assert post.metadata["title"] == "Redis connection timeout"
        assert post.metadata["maturity"] == "verified"

    def test_default_reason_is_correction(self, tmp_path):
        path = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-001")
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        assert post.metadata["snapshot_reason"] == "correction"

    def test_multiple_snapshots_for_same_entry(self, tmp_path):
        path1 = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-001")
        time.sleep(1)  # ensure different timestamps
        path2 = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-002")
        assert path1 != path2
        assert path1.exists()
        assert path2.exists()


# ---------------------------------------------------------------------------
# list_snapshots
# ---------------------------------------------------------------------------

class TestListSnapshots:

    def test_returns_empty_list_if_no_history_dir(self, tmp_path):
        result = list_snapshots(tmp_path, "PT-DB-001")
        assert result == []

    def test_returns_empty_list_if_no_snapshots(self, tmp_path):
        (tmp_path / HISTORY_DIR).mkdir()
        result = list_snapshots(tmp_path, "PT-DB-001")
        assert result == []

    def test_returns_snapshot_paths(self, tmp_path):
        path = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-001")
        result = list_snapshots(tmp_path, "PT-DB-001")
        assert path in result

    def test_does_not_return_other_entry_snapshots(self, tmp_path):
        save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-001")
        save_snapshot(tmp_path, "PT-DB-002", SAMPLE_CONTENT, "pending-002")
        result = list_snapshots(tmp_path, "PT-DB-001")
        for p in result:
            assert p.name.startswith("PT-DB-001-")

    def test_sorted_by_timestamp(self, tmp_path):
        p1 = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-001")
        time.sleep(1)
        p2 = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-002")
        result = list_snapshots(tmp_path, "PT-DB-001")
        assert result[0] == p1
        assert result[1] == p2


# ---------------------------------------------------------------------------
# read_snapshot
# ---------------------------------------------------------------------------

class TestReadSnapshot:

    def test_reads_existing_snapshot(self, tmp_path):
        path = save_snapshot(tmp_path, "PT-DB-001", SAMPLE_CONTENT, "pending-001")
        content = read_snapshot(path)
        assert content is not None
        assert "Redis connection timeout" in content

    def test_returns_none_for_missing_file(self, tmp_path):
        result = read_snapshot(tmp_path / "nonexistent.md")
        assert result is None
