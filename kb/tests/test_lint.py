"""Tests for holmes.kb.agent.dag.lint — T018."""

from __future__ import annotations

import pytest

from holmes.kb.agent.dag.lint import LintResult, run_lint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(written_entries=None, dag_json=None):
    return {
        "written_entries": written_entries or [],
        "dag_json": dag_json or {},
    }


def _make_pitfall(entry_id, children=None, source_file="doc.md", source_hash="abc"):
    fm = {
        "type": "pitfall",
        "title": f"Pitfall {entry_id}",
        "description": "desc",
        "category": "general",
        "pitfall_structure": "tree",
        "kb_status": "draft",
        "source_file": source_file,
        "source_hash": source_hash,
        "import_trace_id": "t1",
        "child_entry_ids": children or [],
        "maturity": "draft",
        "decay_status": "ok",
        "next_decay_check": "2026-12-01",
        "contributors": ["user1"],
        "tags": [],
    }
    return {"entry_id": entry_id, "frontmatter": fm}


def _make_process(entry_id, parent_id, children=None, source_file="doc.md", source_hash="abc"):
    fm = {
        "type": "process",
        "title": f"Process {entry_id}",
        "description": "desc",
        "category": "general",
        "kb_status": "draft",
        "source_file": source_file,
        "source_hash": source_hash,
        "import_trace_id": "t1",
        "parent_id": parent_id,
        "maturity": "draft",
        "decay_status": "ok",
        "next_decay_check": "2026-12-01",
        "contributors": ["user1"],
        "tags": [],
        "child_entry_ids": children or [],
    }
    return {"entry_id": entry_id, "frontmatter": fm}


# ---------------------------------------------------------------------------
# parent_id_consistency
# ---------------------------------------------------------------------------


def test_parent_id_consistency_pass():
    root = _make_pitfall("root-001", children=["proc-001"])
    proc = _make_process("proc-001", parent_id="root-001")
    ctx = _make_ctx([root, proc])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "parent_id_consistency")
    assert r.passed


def test_parent_id_consistency_fail_missing_parent():
    proc = _make_process("proc-001", parent_id="root-999")
    ctx = _make_ctx([proc])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "parent_id_consistency")
    assert not r.passed
    assert "root-999" in r.message


# ---------------------------------------------------------------------------
# child_entry_ids_consistency
# ---------------------------------------------------------------------------


def test_child_entry_ids_consistency_pass():
    root = _make_pitfall("root-001", children=["proc-001"])
    proc = _make_process("proc-001", parent_id="root-001")
    ctx = _make_ctx([root, proc])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "child_entry_ids_consistency")
    assert r.passed


def test_child_entry_ids_consistency_fail():
    root = _make_pitfall("root-001", children=["missing-proc"])
    ctx = _make_ctx([root])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "child_entry_ids_consistency")
    assert not r.passed
    assert "missing-proc" in r.message


def test_child_entry_ids_consistency_yaml_comment_stripped():
    root = _make_pitfall("root-001", children=["proc-001   # some title"])
    proc = _make_process("proc-001", parent_id="root-001")
    ctx = _make_ctx([root, proc])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "child_entry_ids_consistency")
    assert r.passed


# ---------------------------------------------------------------------------
# tree_completeness
# ---------------------------------------------------------------------------


def test_tree_completeness_pass():
    dag_json = {
        "entry_ids": {"N1": "proc-n1-001", "root": "root-001"},
        "nodes": [{"id": "N1", "complexity": "process"}],
    }
    root = _make_pitfall("root-001")
    proc = _make_process("proc-n1-001", parent_id="root-001")
    ctx = _make_ctx([root, proc], dag_json)
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "tree_completeness")
    assert r.passed


def test_tree_completeness_fail_missing_entry():
    dag_json = {
        "entry_ids": {"N1": "proc-n1-001", "root": "root-001"},
    }
    root = _make_pitfall("root-001")
    # proc-n1-001 not written
    ctx = _make_ctx([root], dag_json)
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "tree_completeness")
    assert not r.passed
    assert "proc-n1-001" in r.message


def test_tree_completeness_fail_orphan():
    dag_json = {"entry_ids": {"root": "root-001"}}
    root = _make_pitfall("root-001")
    orphan = _make_process("orphan-999", parent_id="root-001")
    ctx = _make_ctx([root, orphan], dag_json)
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "tree_completeness")
    assert not r.passed
    assert "orphan-999" in r.message


# ---------------------------------------------------------------------------
# no_cycle
# ---------------------------------------------------------------------------


def test_no_cycle_pass():
    root = _make_pitfall("root-001", children=["proc-001"])
    proc = _make_process("proc-001", parent_id="root-001")
    ctx = _make_ctx([root, proc])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "no_cycle")
    assert r.passed


def test_no_cycle_fail():
    a = _make_process("proc-a", parent_id="root-001", children=["proc-b"])
    b = _make_process("proc-b", parent_id="proc-a", children=["proc-a"])  # cycle!
    root = _make_pitfall("root-001")
    ctx = _make_ctx([root, a, b])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "no_cycle")
    assert not r.passed
    assert "Cycle" in r.message


# ---------------------------------------------------------------------------
# pitfall_has_root
# ---------------------------------------------------------------------------


def test_pitfall_has_root_pass():
    root = _make_pitfall("root-001")
    ctx = _make_ctx([root])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "pitfall_has_root")
    assert r.passed


def test_pitfall_has_root_fail_only_process():
    proc = _make_process("proc-001", parent_id="root-001")
    ctx = _make_ctx([proc])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "pitfall_has_root")
    assert not r.passed


def test_pitfall_has_root_fail_empty():
    ctx = _make_ctx([])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "pitfall_has_root")
    assert not r.passed


# ---------------------------------------------------------------------------
# source_file_consistent
# ---------------------------------------------------------------------------


def test_source_file_consistent_pass():
    root = _make_pitfall("root-001", source_file="doc.md", source_hash="abc")
    proc = _make_process("proc-001", parent_id="root-001", source_file="doc.md", source_hash="abc")
    ctx = _make_ctx([root, proc])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "source_file_consistent")
    assert r.passed


def test_source_file_consistent_fail_different_source():
    root = _make_pitfall("root-001", source_file="doc1.md", source_hash="abc")
    proc = _make_process("proc-001", parent_id="root-001", source_file="doc2.md", source_hash="abc")
    ctx = _make_ctx([root, proc])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "source_file_consistent")
    assert not r.passed


# ---------------------------------------------------------------------------
# evidence_fields_present
# ---------------------------------------------------------------------------


def test_evidence_fields_present_pass():
    root = _make_pitfall("root-001")
    ctx = _make_ctx([root])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "evidence_fields_present")
    assert r.passed


def test_evidence_fields_present_fail_missing_maturity():
    root = _make_pitfall("root-001")
    root["frontmatter"].pop("maturity")
    ctx = _make_ctx([root])
    results = run_lint(ctx)
    r = next(r for r in results if r.rule == "evidence_fields_present")
    assert not r.passed
    assert "maturity" in r.message


# ---------------------------------------------------------------------------
# run_lint returns 7 results
# ---------------------------------------------------------------------------


def test_run_lint_returns_seven_results():
    ctx = _make_ctx([_make_pitfall("root-001")])
    results = run_lint(ctx)
    assert len(results) == 7
    rules = {r.rule for r in results}
    expected = {
        "parent_id_consistency",
        "child_entry_ids_consistency",
        "tree_completeness",
        "no_cycle",
        "pitfall_has_root",
        "source_file_consistent",
        "evidence_fields_present",
    }
    assert rules == expected
