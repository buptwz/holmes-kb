"""Tests for kb/holmes/kb/store.py — CRUD and index operations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from holmes.kb.store import (
    EntryMeta,
    list_entries,
    read_entry,
    rebuild_index_files,
    write_entry,
)


_SAMPLE_PITFALL = """\
---
id: PT-DB-001
type: pitfall
title: Redis Timeout
maturity: draft
category: database
tags: [redis]
created_at: "2026-01-01"
updated_at: "2026-01-01"
---

## Symptoms
Timeout errors.

## Root Cause
Small pool.

## Resolution
Increase pool size.
"""


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    """Create a minimal KB directory structure."""
    (tmp_path / "pitfall" / "database").mkdir(parents=True)
    (tmp_path / "model").mkdir()
    (tmp_path / "contributions" / "pending").mkdir(parents=True)
    return tmp_path


def test_write_and_read_entry(kb_root: Path):
    target = kb_root / "pitfall" / "database" / "PT-DB-001.md"
    write_entry(target, _SAMPLE_PITFALL)
    assert target.exists()
    content = read_entry(kb_root, "PT-DB-001")
    assert content is not None
    assert "Redis Timeout" in content


def test_read_entry_not_found(kb_root: Path):
    result = read_entry(kb_root, "XX-MISSING-999")
    assert result is None


def test_list_entries_returns_meta(kb_root: Path):
    target = kb_root / "pitfall" / "database" / "PT-DB-001.md"
    write_entry(target, _SAMPLE_PITFALL)
    entries = list_entries(kb_root)
    assert len(entries) == 1
    e = entries[0]
    assert e.id == "PT-DB-001"
    assert e.type == "pitfall"
    assert e.category == "database"


def test_list_entries_filtered_by_type(kb_root: Path):
    pitfall_path = kb_root / "pitfall" / "database" / "PT-DB-001.md"
    write_entry(pitfall_path, _SAMPLE_PITFALL)
    model_content = _SAMPLE_PITFALL.replace(
        "type: pitfall", "type: model"
    ).replace("id: PT-DB-001", "id: MD-SVC-001")
    model_path = kb_root / "model" / "MD-SVC-001.md"
    write_entry(model_path, model_content)

    pitfalls = list_entries(kb_root, kb_type="pitfall")
    assert all(e.type == "pitfall" for e in pitfalls)
    models = list_entries(kb_root, kb_type="model")
    assert all(e.type == "model" for e in models)


def test_rebuild_index_files(kb_root: Path):
    target = kb_root / "pitfall" / "database" / "PT-DB-001.md"
    write_entry(target, _SAMPLE_PITFALL)
    rebuild_index_files(kb_root)

    index_md = kb_root / "pitfall" / "_index.md"
    assert index_md.exists()
    assert "PT-DB-001" in index_md.read_text()

    index_json = kb_root / "index.json"
    assert index_json.exists()
    data = json.loads(index_json.read_text())
    assert data["total_entries"] == 1


def test_write_entry_creates_dirs(tmp_path: Path):
    """write_entry creates parent directories automatically."""
    deep_path = tmp_path / "a" / "b" / "c" / "entry.md"
    write_entry(deep_path, "---\n---\nHello")
    assert deep_path.exists()
