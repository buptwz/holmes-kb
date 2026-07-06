"""Tests for holmes.kb.agent.dag.harness2 — T027, T030, T039."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holmes.kb.agent.dag.harness2 import (
    MAX_RETRIES_PER_ENTRY,
    Agent2Harness,
    MaxTurnsExceededError,
    run_agent2,
)
from holmes.kb.agent.report import ImportReport


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeConfig:
    model = "test-model"
    username = "testuser"
    api_key = "sk-test"
    api_base_url = ""


def _make_dag_json(
    tmp_path: Path,
    nodes: list[dict],
    entry_ids: dict | None = None,
    import_seq: str = "001",
    title: str = "Test DAG",
) -> Path:
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "title": title,
        "source_file": "test.md",
        "nodes": nodes,
        "entry_ids": entry_ids or {},
        "import_seq": import_seq,
    }
    p = state_dir / "abc12345.dag.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


class FakeProvider:
    """Mock LLMProvider that immediately calls finalize."""

    def __init__(self, call_finalize=True, max_calls=1):
        self.call_count = 0
        self.call_finalize = call_finalize
        self.max_calls = max_calls

    def complete(self, messages, system, model, max_tokens, tools):
        self.call_count += 1
        if self.call_count >= self.max_calls and self.call_finalize:
            # Return a finalize tool call
            tc = MagicMock()
            tc.name = "finalize"
            tc.input = {}
            tc.id = f"tool_{self.call_count}"
            return False, [tc], messages + [{"role": "assistant", "content": "done"}], {}
        # Return stop signal
        return True, [], messages, {}

    def append_tool_results(self, messages, results):
        for tool_use_id, content in results:
            messages = messages + [{"role": "user", "content": content}]
        return messages


# ---------------------------------------------------------------------------
# Agent2Harness initialization
# ---------------------------------------------------------------------------


def test_harness_init(tmp_path):
    dag_path = _make_dag_json(tmp_path, nodes=[], entry_ids={"root": "root-001"})
    provider = FakeProvider()
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="abc12345",
        dag_json_path=dag_path,
    )
    assert harness.source_hash == "abc12345"
    assert harness.dag_json_path == dag_path


def test_harness_default_dag_path(tmp_path):
    dag_path = _make_dag_json(tmp_path, nodes=[], entry_ids={})
    provider = FakeProvider()
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="abc12345",
    )
    expected = tmp_path / "_import-state" / "abc12345.dag.json"
    assert harness.dag_json_path == expected


# ---------------------------------------------------------------------------
# run() — missing .dag.json
# ---------------------------------------------------------------------------


def test_run_missing_dag_json(tmp_path):
    provider = FakeProvider()
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="missing",
    )
    report = harness.run()
    assert report.errors
    assert "dag.json" in report.errors[0].lower() or ".dag.json" in report.errors[0]


# ---------------------------------------------------------------------------
# run() — missing username
# ---------------------------------------------------------------------------


def test_run_missing_username(tmp_path):
    dag_path = _make_dag_json(tmp_path, nodes=[], entry_ids={"root": "root-001"})
    cfg = FakeConfig()
    cfg.username = ""
    provider = FakeProvider()
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=cfg,
        provider=provider,
        source_hash="abc12345",
        dag_json_path=dag_path,
    )
    report = harness.run()
    assert report.errors
    assert "username" in report.errors[0].lower()


# ---------------------------------------------------------------------------
# run() — dry_run (no files written)
# ---------------------------------------------------------------------------


def test_run_dry_run(tmp_path):
    nodes = [{"id": "N1", "complexity": "process", "description": "test"}]
    entry_ids = {"N1": "proc-n1-001", "root": "root-001"}
    dag_path = _make_dag_json(tmp_path, nodes=nodes, entry_ids=entry_ids)
    provider = FakeProvider(call_finalize=True)
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="abc12345",
        dag_json_path=dag_path,
        dry_run=True,
    )
    report = harness.run()
    # No actual files should be written
    assert not list((tmp_path / "_pending").rglob("*.md"))


# ---------------------------------------------------------------------------
# _execute_tool — whitelist enforcement
# ---------------------------------------------------------------------------


def test_execute_tool_whitelist_block(tmp_path):
    dag_path = _make_dag_json(tmp_path, nodes=[], entry_ids={})
    provider = FakeProvider()
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="abc12345",
        dag_json_path=dag_path,
    )
    ctx = {"state_dir": tmp_path, "source_hash": "abc12345", "dag_json": {}, "entry_ids": {}}
    result = harness._execute_tool("Bash", {}, ctx)
    assert "error" in result
    assert "not allowed" in result["error"]


def test_execute_tool_allowed_finalize(tmp_path):
    dag_path = _make_dag_json(tmp_path, nodes=[], entry_ids={})
    provider = FakeProvider()
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="abc12345",
        dag_json_path=dag_path,
    )
    ctx = {
        "state_dir": tmp_path,
        "source_hash": "abc12345",
        "dag_json": {"entry_ids": {}},
        "entry_ids": {},
        "written_entries": [],
        "_terminate": False,
        "lint_results": [],
    }
    result = harness._execute_tool("finalize", {}, ctx)
    assert result.get("success") or result.get("_terminate")


# ---------------------------------------------------------------------------
# _scan_written_node_ids — checkpoint recovery
# ---------------------------------------------------------------------------


def test_scan_written_node_ids_empty(tmp_path):
    nodes = [{"id": "N1", "complexity": "process"}]
    entry_ids = {"N1": "proc-n1-001", "root": "root-001"}
    dag_path = _make_dag_json(tmp_path, nodes=nodes, entry_ids=entry_ids)
    provider = FakeProvider()
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="abc12345",
        dag_json_path=dag_path,
    )
    harness._load_dag_json(ImportReport())
    result = harness._scan_written_node_ids()
    assert result == set()


def test_scan_written_node_ids_detects_existing_file(tmp_path):
    nodes = [{"id": "N1", "complexity": "process"}]
    entry_ids = {"N1": "proc-n1-001", "root": "root-001"}
    dag_path = _make_dag_json(tmp_path, nodes=nodes, entry_ids=entry_ids)

    # Create a fake written file
    pending_dir = tmp_path / "_pending" / "process" / "general"
    pending_dir.mkdir(parents=True, exist_ok=True)
    (pending_dir / "proc-n1-001.md").write_text("---\ntitle: X\n---\n")

    provider = FakeProvider()
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="abc12345",
        dag_json_path=dag_path,
    )
    harness._load_dag_json(ImportReport())
    result = harness._scan_written_node_ids()
    assert "N1" in result


# ---------------------------------------------------------------------------
# retry_nodes
# ---------------------------------------------------------------------------


def test_run_retry_nodes_limits_effective_nodes(tmp_path):
    nodes = [
        {"id": "N1", "complexity": "process", "description": "node1"},
        {"id": "N2", "complexity": "process", "description": "node2"},
    ]
    entry_ids = {"N1": "proc-n1-001", "N2": "proc-n2-001", "root": "root-001"}
    dag_path = _make_dag_json(tmp_path, nodes=nodes, entry_ids=entry_ids)

    calls = []

    class TrackingProvider(FakeProvider):
        def complete(self, messages, system, model, max_tokens, tools):
            calls.append(messages)
            return super().complete(messages, system, model, max_tokens, tools)

    provider = TrackingProvider(call_finalize=True)
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="abc12345",
        dag_json_path=dag_path,
        dry_run=True,
    )
    # Only retry N2
    report = harness.run(retry_nodes=["N2"])
    assert not report.errors or "maxTurns" in (report.errors[0] if report.errors else "")
    # Initial message should mention N2
    if calls:
        first_msg = str(calls[0])
        # N2 related entry_id should appear
        assert "N2" in first_msg or "proc-n2" in first_msg


# ---------------------------------------------------------------------------
# MaxTurnsExceededError
# ---------------------------------------------------------------------------


def test_max_turns_exceeded(tmp_path):
    nodes = [{"id": "N1", "complexity": "process"}]
    entry_ids = {"N1": "proc-n1-001", "root": "root-001"}
    dag_path = _make_dag_json(tmp_path, nodes=nodes, entry_ids=entry_ids)

    class NeverFinalizeProvider:
        def complete(self, messages, system, model, max_tokens, tools):
            # Never finalize, never stop
            tc = MagicMock()
            tc.name = "read_dag"
            tc.input = {}
            tc.id = "tc1"
            return False, [tc], messages, {}

        def append_tool_results(self, messages, results):
            return messages + [{"role": "user", "content": "result"}]

    provider = NeverFinalizeProvider()
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="abc12345",
        dag_json_path=dag_path,
    )

    with pytest.raises(MaxTurnsExceededError):
        harness._run_loop(
            messages=[{"role": "user", "content": "go"}],
            ctx={"dag_json": {}, "entry_ids": {}, "state_dir": tmp_path,
                 "source_hash": "abc12345", "kb_root": tmp_path, "source_file": "",
                 "source_text": "", "dry_run": False, "pending_root": tmp_path / "_pending",
                 "written_entries": [], "failed_entries": [], "_terminate": False,
                 "lint_results": [], "username": "test"},
            max_turns=2,
        )


# ---------------------------------------------------------------------------
# run_agent2 integration
# ---------------------------------------------------------------------------


def test_run_agent2_generates_ids_and_calls_harness(tmp_path):
    nodes = [{"id": "N1", "complexity": "process", "description": "test"}]
    dag_path = _make_dag_json(tmp_path, nodes=nodes)
    provider = FakeProvider(call_finalize=True)
    report = run_agent2(
        source_text="test source",
        file_path=None,
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="abc12345",
        dag_json_path=dag_path,
        dry_run=True,
    )
    # Should not error on ID generation
    id_errors = [e for e in report.errors if "ID generation" in e]
    assert not id_errors


def test_run_agent2_missing_dag_json(tmp_path):
    provider = FakeProvider()
    report = run_agent2(
        source_text="test",
        file_path=None,
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="missing_hash",
        dry_run=True,
    )
    assert report.errors
    assert "ID generation" in report.errors[0] or "not found" in report.errors[0]


# ---------------------------------------------------------------------------
# Guided retry — _execute_tool retry counting and error enrichment
# ---------------------------------------------------------------------------


def test_execute_tool_retry_counts_increment(tmp_path):
    """Successive write_entry failures increment retry count for the entry."""
    dag_path = _make_dag_json(tmp_path, nodes=[], entry_ids={})
    harness = Agent2Harness(
        kb_root=tmp_path, cfg=FakeConfig(), provider=FakeProvider(),
        source_hash="abc12345", dag_json_path=dag_path,
    )
    ctx = {
        "state_dir": tmp_path, "source_hash": "abc12345",
        "dag_json": {"entry_ids": {}}, "entry_ids": {},
        "kb_root": tmp_path, "pending_root": tmp_path / "_pending",
        "source_file": "", "source_text": "", "dry_run": True,
        "written_entries": [], "failed_entries": [], "_terminate": False,
    }

    # Simulate write_entry returning error by passing empty content
    for i in range(MAX_RETRIES_PER_ENTRY - 1):
        result = harness._execute_tool("write_entry", {"entry_id": "x", "content": ""}, ctx)
        assert "error" in result
        assert f"{i + 1}/{MAX_RETRIES_PER_ENTRY}" in result["error"]
        assert ctx["_terminate"] is False  # Not yet at max

    # One more failure → max retries → terminate
    result = harness._execute_tool("write_entry", {"entry_id": "x", "content": ""}, ctx)
    assert "error" in result
    assert ctx["_terminate"] is True
    assert len(ctx["failed_entries"]) == 1
    assert ctx["failed_entries"][0][0] == "x"


def test_execute_tool_retry_resets_on_success(tmp_path):
    """After a failed write, a successful write for a different entry works fine."""
    dag_path = _make_dag_json(tmp_path, nodes=[], entry_ids={})
    harness = Agent2Harness(
        kb_root=tmp_path, cfg=FakeConfig(), provider=FakeProvider(),
        source_hash="abc12345", dag_json_path=dag_path,
    )
    ctx = {
        "state_dir": tmp_path, "source_hash": "abc12345",
        "dag_json": {"entry_ids": {}}, "entry_ids": {},
        "kb_root": tmp_path, "pending_root": tmp_path / "_pending",
        "source_file": "", "source_text": "", "dry_run": True,
        "written_entries": [], "failed_entries": [], "_terminate": False,
    }

    # Fail entry-a once
    r = harness._execute_tool("write_entry", {"entry_id": "a", "content": ""}, ctx)
    assert "error" in r
    assert ctx["_retry_counts"]["a"] == 1

    # entry-b should start fresh counter
    r2 = harness._execute_tool("write_entry", {"entry_id": "b", "content": ""}, ctx)
    assert "error" in r2
    assert ctx["_retry_counts"]["b"] == 1  # Independent counter


def test_execute_tool_retry_source_hint_on_second_retry(tmp_path):
    """On 2nd+ retry, error includes source text hint."""
    nodes = [{"id": "N1", "complexity": "process", "line_range": [5, 15]}]
    entry_ids = {"N1": "proc-001", "root": "root-001"}
    dag_path = _make_dag_json(tmp_path, nodes=nodes, entry_ids=entry_ids)
    harness = Agent2Harness(
        kb_root=tmp_path, cfg=FakeConfig(), provider=FakeProvider(),
        source_hash="abc12345", dag_json_path=dag_path,
    )
    harness._load_dag_json(ImportReport())

    source_lines = [f"line {i}" for i in range(20)]
    ctx = {
        "state_dir": tmp_path, "source_hash": "abc12345",
        "dag_json": harness.dag_json, "entry_ids": harness.entry_ids,
        "kb_root": tmp_path, "pending_root": tmp_path / "_pending",
        "source_file": "", "source_text": "\n".join(source_lines),
        "dry_run": True, "written_entries": [], "failed_entries": [],
        "_terminate": False,
    }

    # 1st failure — no source hint
    r1 = harness._execute_tool("write_entry", {"entry_id": "proc-001", "content": ""}, ctx)
    assert "error" in r1
    assert "源文档原文" not in r1["error"]

    # 2nd failure — should include source hint
    r2 = harness._execute_tool("write_entry", {"entry_id": "proc-001", "content": ""}, ctx)
    assert "error" in r2
    assert "源文档原文" in r2["error"] or "源文档" in r2["error"]


