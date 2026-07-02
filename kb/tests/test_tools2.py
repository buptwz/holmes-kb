"""Tests for holmes.kb.agent.dag.tools2 — T016."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from holmes.kb.agent.dag.tools2 import (
    TOOLS2_DEFINITIONS,
    TOOLS2_HANDLERS,
    tool_finalize,
    tool_read_dag2,
    tool_read_entry,
    tool_write_entry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(tmp_path: Path, dag_json=None, entry_ids=None, dry_run=False):
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    source_hash = "abc12345"
    ctx = {
        "state_dir": state_dir,
        "source_hash": source_hash,
        "source_file": "test.md",
        "source_text": "full text content",
        "kb_root": tmp_path,
        "dry_run": dry_run,
        "dag_json": dag_json or {},
        "entry_ids": entry_ids or {},
        "pending_root": tmp_path / "_pending",
        "written_entries": [],
        "failed_entries": [],
        "_terminate": False,
        "lint_results": [],
        "username": "testuser",
    }
    return ctx, state_dir, source_hash


def _make_dag_json_file(state_dir: Path, source_hash: str, data: dict):
    p = state_dir / f"{source_hash}.dag.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _pitfall_content(entry_id="root-001", parent_id=None, children=None):
    children_yaml = ""
    if children:
        children_yaml = "\n".join(f"  - {c}" for c in children)
        children_yaml = f"\nchild_entry_ids:\n{children_yaml}"
    else:
        children_yaml = "\nchild_entry_ids: []"
    parent_yaml = f"\nparent_id: {parent_id}" if parent_id else ""
    return f"""\
---
id: {entry_id}
title: "Test Pitfall"
description: "Test description"
type: pitfall
category: system
pitfall_structure: tree
kb_status: pending
source_file: test.md
source_hash: abc12345
import_trace_id: t1{parent_yaml}{children_yaml}
maturity: draft
decay_status: active
next_decay_check: "2026-12-01"
created_at: "2026-07-01T00:00:00+00:00"
updated_at: "2026-07-01T00:00:00+00:00"
contributors:
  - testuser
tags: []
---

## Symptoms

Test symptoms.

## Root Cause

Test root cause.

## Resolution

Test resolution.
"""


def _process_content(entry_id="proc-001", parent_id="root-001"):
    return f"""\
---
id: {entry_id}
title: "Test Process"
description: "Test process description"
type: process
category: system
kb_status: pending
source_file: test.md
source_hash: abc12345
import_trace_id: t1
parent_id: {parent_id}
maturity: draft
decay_status: active
next_decay_check: "2026-12-01"
created_at: "2026-07-01T00:00:00+00:00"
updated_at: "2026-07-01T00:00:00+00:00"
contributors:
  - testuser
tags: []
---

## Steps

1. Step one.
2. Step two.
"""


# ---------------------------------------------------------------------------
# tool_read_dag2
# ---------------------------------------------------------------------------


def test_read_dag2_returns_from_ctx(tmp_path):
    dag_json = {"title": "My DAG", "nodes": [], "entry_ids": {"root": "root-001"}, "import_seq": "001"}
    ctx, _, _ = _make_ctx(tmp_path, dag_json=dag_json, entry_ids={"root": "root-001"})
    result = tool_read_dag2(ctx, {})
    assert result["title"] == "My DAG"
    assert result["entry_ids"] == {"root": "root-001"}


def test_read_dag2_loads_from_file(tmp_path):
    ctx, state_dir, source_hash = _make_ctx(tmp_path)
    dag_data = {"title": "Loaded DAG", "nodes": [], "entry_ids": {"root": "root-001"}, "import_seq": "001", "source_file": "test.md"}
    _make_dag_json_file(state_dir, source_hash, dag_data)
    result = tool_read_dag2(ctx, {})
    assert result["title"] == "Loaded DAG"


def test_read_dag2_error_missing_file(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path)
    result = tool_read_dag2(ctx, {})
    assert "error" in result


# ---------------------------------------------------------------------------
# tool_write_entry
# ---------------------------------------------------------------------------


def test_write_entry_pitfall_success(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path, entry_ids={"root": "root-001"})
    content = _pitfall_content("root-001")
    result = tool_write_entry(ctx, {"entry_id": "root-001", "content": content})
    assert result.get("success")
    assert "root-001" in result.get("path", "")


def test_write_entry_creates_file(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path, entry_ids={"root": "root-001"})
    content = _pitfall_content("root-001")
    tool_write_entry(ctx, {"entry_id": "root-001", "content": content})
    written_files = list((tmp_path / "_pending").rglob("root-001.md"))
    assert written_files, "File should be written to _pending/"


def test_write_entry_dry_run_no_file(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path, entry_ids={"root": "root-001"}, dry_run=True)
    content = _pitfall_content("root-001")
    result = tool_write_entry(ctx, {"entry_id": "root-001", "content": content})
    assert result.get("success")
    written_files = list((tmp_path / "_pending").rglob("root-001.md"))
    assert not written_files, "Dry run should not write files"


def test_write_entry_missing_entry_id(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path)
    result = tool_write_entry(ctx, {"entry_id": "", "content": "some content"})
    assert "error" in result


def test_write_entry_empty_content(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path)
    result = tool_write_entry(ctx, {"entry_id": "root-001", "content": ""})
    assert "error" in result


def test_write_entry_missing_required_pitfall_field(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path, entry_ids={"root": "root-001"})
    # Remove 'description' from frontmatter
    content = _pitfall_content("root-001").replace("description: \"Test description\"\n", "")
    result = tool_write_entry(ctx, {"entry_id": "root-001", "content": content})
    assert "error" in result


def test_write_entry_missing_required_pitfall_section(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path, entry_ids={"root": "root-001"})
    content = _pitfall_content("root-001").replace("## Symptoms\n\nTest symptoms.\n\n", "")
    result = tool_write_entry(ctx, {"entry_id": "root-001", "content": content})
    assert "error" in result


def test_write_entry_process_success(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path, entry_ids={"root": "root-001", "N1": "proc-n1-001"})
    content = _process_content("proc-n1-001", parent_id="root-001")
    result = tool_write_entry(ctx, {"entry_id": "proc-n1-001", "content": content})
    assert result.get("success"), result


def test_write_entry_process_missing_steps(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path, entry_ids={"root": "root-001", "N1": "proc-n1-001"})
    content = _process_content("proc-n1-001").replace("## Steps\n\n1. Step one.\n2. Step two.\n", "")
    result = tool_write_entry(ctx, {"entry_id": "proc-n1-001", "content": content})
    assert "error" in result


def test_write_entry_unknown_type(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path)
    content = """\
---
title: "X"
type: unknown_type
description: "test"
---

Body.
"""
    result = tool_write_entry(ctx, {"entry_id": "x-001", "content": content})
    assert "error" in result


def test_write_entry_recorded_in_ctx(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path, entry_ids={"root": "root-001"})
    content = _pitfall_content("root-001")
    tool_write_entry(ctx, {"entry_id": "root-001", "content": content})
    assert len(ctx["written_entries"]) == 1
    assert ctx["written_entries"][0]["entry_id"] == "root-001"


def test_write_entry_child_id_validation(tmp_path):
    entry_ids = {"root": "root-001", "N1": "proc-001"}
    ctx, _, _ = _make_ctx(tmp_path, entry_ids=entry_ids)
    # Use a child_id not in entry_ids
    content = _pitfall_content("root-001", children=["nonexistent-id"])
    result = tool_write_entry(ctx, {"entry_id": "root-001", "content": content})
    assert "error" in result


# ---------------------------------------------------------------------------
# tool_read_entry
# ---------------------------------------------------------------------------


def test_read_entry_from_pending(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path, entry_ids={"root": "root-001"})
    content = _pitfall_content("root-001")
    tool_write_entry(ctx, {"entry_id": "root-001", "content": content})
    # Clear written_entries to force file-based lookup
    ctx["written_entries"] = []
    result = tool_read_entry(ctx, {"entry_id": "root-001"})
    assert result.get("title") == "Test Pitfall"


def test_read_entry_from_written_entries(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path, dry_run=True, entry_ids={"root": "root-001"})
    content = _pitfall_content("root-001")
    tool_write_entry(ctx, {"entry_id": "root-001", "content": content})
    result = tool_read_entry(ctx, {"entry_id": "root-001"})
    assert result.get("title") == "Test Pitfall"


def test_read_entry_not_found(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path)
    result = tool_read_entry(ctx, {"entry_id": "nonexistent-id"})
    assert "error" in result


def test_read_entry_empty_id(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path)
    result = tool_read_entry(ctx, {"entry_id": ""})
    assert "error" in result


# ---------------------------------------------------------------------------
# tool_finalize
# ---------------------------------------------------------------------------


def test_finalize_terminates_ctx(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path)
    result = tool_finalize(ctx, {})
    assert result.get("_terminate")
    assert ctx["_terminate"]


def test_finalize_returns_lint_counts(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path)
    result = tool_finalize(ctx, {})
    assert "lint_passed" in result
    assert "lint_failed" in result
    assert "lint_errors" in result


def test_finalize_lint_stored_in_ctx(tmp_path):
    ctx, _, _ = _make_ctx(tmp_path)
    tool_finalize(ctx, {})
    assert "lint_results" in ctx
    assert len(ctx["lint_results"]) == 7


# ---------------------------------------------------------------------------
# TOOLS2_DEFINITIONS and TOOLS2_HANDLERS
# ---------------------------------------------------------------------------


def test_tools2_definitions_count():
    assert len(TOOLS2_DEFINITIONS) == 6


def test_tools2_definitions_names():
    names = {t["name"] for t in TOOLS2_DEFINITIONS}
    assert names == {"Read", "Grep", "read_dag", "write_entry", "read_entry", "finalize"}


def test_tools2_handlers_match_definitions():
    def_names = {t["name"] for t in TOOLS2_DEFINITIONS}
    handler_names = set(TOOLS2_HANDLERS.keys())
    assert def_names == handler_names


def test_tools2_definitions_have_input_schema():
    for t in TOOLS2_DEFINITIONS:
        assert "input_schema" in t, f"{t['name']} missing input_schema"
