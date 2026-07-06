"""Tests for kb/holmes/kb/agent/dag/harness1.py — Agent1Harness."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holmes.kb.agent.dag.harness1 import (
    Agent1Harness,
    MaxTurnsExceededError,
    SessionLoadError,
    find_pending_sessions,
)
from holmes.kb.agent.dag.formatter import dag_to_markdown
from holmes.kb.agent.dag.schema import (
    Complexity,
    DAGEdge,
    DAGGraph,
    DAGNode,
    NodeType,
)
from holmes.kb.agent.provider.base import LLMProvider, ToolCall


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------


class MockProvider(LLMProvider):
    """Mock provider that replays a scripted sequence of tool calls."""

    def __init__(self, turns: list[list[ToolCall]]):
        """turns: list of per-turn tool call lists.  [] or None = stop."""
        self._turns = list(turns)
        self._turn_index = 0

    def complete(self, messages, system, model, max_tokens, tools):
        if self._turn_index >= len(self._turns):
            return True, [], messages, {}  # stop
        calls = self._turns[self._turn_index]
        self._turn_index += 1
        updated = list(messages) + [{"role": "assistant", "tool_calls": calls}]
        if not calls:
            return True, [], updated, {}
        return False, calls, updated, {}

    def simple_complete(self, messages, system="", max_tokens=512):
        return ""

    def append_tool_results(self, messages, results):
        tool_result = {"role": "user", "tool_results": results}
        return list(messages) + [tool_result]


def _make_valid_dag_md() -> str:
    n1 = DAGNode("N1", "root", NodeType.decision, Complexity.simple,
                  children=[DAGEdge("yes", "N2")])
    n2 = DAGNode("N2", "proc", NodeType.remote_action, Complexity.process,
                  section_heading="### Steps",
                  children=[DAGEdge("done", "END")])
    g = DAGGraph(nodes=[n1, n2], title="T", source_file="src.md", generated="2026-06-24")
    return dag_to_markdown(g)


def _make_cfg():
    cfg = MagicMock()
    cfg.model = "test-model"
    return cfg


def _make_harness(tmp_path, no_interactive=True, dry_run=False):
    provider = MockProvider([])
    return Agent1Harness(
        kb_root=tmp_path,
        cfg=_make_cfg(),
        provider=provider,
        source_hash="abc12345678901ab",
        source_file="src.md",
        no_interactive=no_interactive,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# US2: Tool whitelist enforcement
# ---------------------------------------------------------------------------


def test_whitelist_allows_write_dag(tmp_path):
    harness = _make_harness(tmp_path)
    ctx = {
        "state_dir": tmp_path / "_import-state",
        "source_hash": "abc12345678901ab",
        "source_file": "src.md",
        "source_text": "test",
        "kb_root": tmp_path,
    }
    (tmp_path / "_import-state").mkdir()
    result = harness._execute_tool("write_dag", {"content": _make_valid_dag_md()}, ctx)
    assert "error" not in result or "not allowed" not in result.get("error", "")


def test_whitelist_allows_read_dag(tmp_path):
    harness = _make_harness(tmp_path)
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()
    ctx = {
        "state_dir": state_dir,
        "source_hash": "abc12345678901ab",
        "source_file": "src.md",
        "source_text": "test",
        "kb_root": tmp_path,
    }
    result = harness._execute_tool("read_dag", {}, ctx)
    # No "not allowed" error — might have "no DAG written yet" but that's OK
    assert "not allowed" not in result.get("error", "")


def test_whitelist_allows_read(tmp_path):
    harness = _make_harness(tmp_path)
    ctx = {
        "state_dir": tmp_path / "_import-state",
        "source_hash": "abc12345678901ab",
        "source_file": "src.md",
        "source_text": "line1\nline2\nline3",
        "kb_root": tmp_path,
    }
    result = harness._execute_tool("Read", {"path": "src.md", "offset": 0, "limit": 10}, ctx)
    assert "not allowed" not in result.get("error", "")


def test_whitelist_allows_grep(tmp_path):
    harness = _make_harness(tmp_path)
    ctx = {
        "state_dir": tmp_path / "_import-state",
        "source_hash": "abc12345678901ab",
        "source_file": "src.md",
        "source_text": "line1\nline2\nline3",
        "kb_root": tmp_path,
    }
    result = harness._execute_tool("Grep", {"pattern": "line", "path": "src.md"}, ctx)
    assert "not allowed" not in result.get("error", "")


def test_whitelist_blocks_write_kb_entry(tmp_path):
    harness = _make_harness(tmp_path)
    ctx = {}
    result = harness._execute_tool("write_kb_entry", {"content": "x"}, ctx)
    assert "error" in result
    assert "not allowed" in result["error"]


def test_whitelist_blocks_check_source_hash(tmp_path):
    harness = _make_harness(tmp_path)
    result = harness._execute_tool("check_source_hash", {"hash": "abc"}, {})
    assert "error" in result
    assert "not allowed" in result["error"]


def test_whitelist_blocks_arbitrary_tool(tmp_path):
    harness = _make_harness(tmp_path)
    result = harness._execute_tool("some_random_tool", {}, {})
    assert "error" in result
    assert "not allowed" in result["error"]


def test_whitelist_blocks_all_5_non_whitelisted_tools(tmp_path):
    harness = _make_harness(tmp_path)
    forbidden = ["write_kb_entry", "update_kb_entry", "check_source_hash",
                 "evaluate_skill", "create_skill_for_entry"]
    for name in forbidden:
        result = harness._execute_tool(name, {}, {})
        assert "not allowed" in result.get("error", ""), f"{name} should be blocked"


# ---------------------------------------------------------------------------
# US1: Loop runs and terminates on output_dag
# ---------------------------------------------------------------------------


def test_loop_terminates_on_output_dag(tmp_path):
    """Mock provider: turn 1 = write_dag, turn 2 = output_dag → loop ends."""
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()
    valid_md = _make_valid_dag_md()

    turns = [
        [ToolCall(id="t1", name="write_dag", input={"content": valid_md})],
        [ToolCall(id="t2", name="output_dag", input={})],
    ]
    provider = MockProvider(turns)
    harness = Agent1Harness(
        kb_root=tmp_path,
        cfg=_make_cfg(),
        provider=provider,
        source_hash="abc12345678901ab",
        source_file="src.md",
        no_interactive=True,
        dry_run=True,
    )
    report = harness.run("some source text")
    assert not report.errors
    assert any("節点" in t or "节点" in t for t in report.phase_traces)


def test_loop_stops_on_provider_stop(tmp_path):
    """Provider returns stop=True → loop exits gracefully."""
    provider = MockProvider([[]])  # empty tool calls = stop
    harness = Agent1Harness(
        kb_root=tmp_path,
        cfg=_make_cfg(),
        provider=provider,
        source_hash="abc12345678901ab",
        no_interactive=True,
        dry_run=True,
    )
    (tmp_path / "_import-state").mkdir()
    report = harness.run("source text")
    # Loop exited without error — just no DAG output
    assert not report.errors


# ---------------------------------------------------------------------------
# US4: Crash recovery
# ---------------------------------------------------------------------------


def test_crash_recovery_snapshot_written_at_turn_20(tmp_path):
    """After 20 turns, session.json should exist."""
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()

    # 20 turns each doing read_dag (which returns error since no file, but loop continues)
    turns = [
        [ToolCall(id=f"t{i}", name="read_dag", input={})]
        for i in range(20)
    ] + [[]]  # stop on turn 21
    provider = MockProvider(turns)
    harness = Agent1Harness(
        kb_root=tmp_path,
        cfg=_make_cfg(),
        provider=provider,
        source_hash="abc12345678901ab",
        source_file="src.md",
        no_interactive=True,
        dry_run=False,
    )
    harness.run("source text")
    session_path = state_dir / "abc12345678901ab.session.json"
    assert session_path.exists()
    data = json.loads(session_path.read_text())
    assert data["turn_count"] == 20


def test_crash_recovery_snapshot_overwritten_at_turn_40(tmp_path):
    """At turn 40, session.json is overwritten (not a new file)."""
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()

    turns = [
        [ToolCall(id=f"t{i}", name="read_dag", input={})]
        for i in range(40)
    ] + [[]]
    provider = MockProvider(turns)
    harness = Agent1Harness(
        kb_root=tmp_path,
        cfg=_make_cfg(),
        provider=provider,
        source_hash="abc12345678901ab",
        source_file="src.md",
        no_interactive=True,
        dry_run=False,
    )
    harness.run("source text")
    session_path = state_dir / "abc12345678901ab.session.json"
    assert session_path.exists()
    data = json.loads(session_path.read_text())
    assert data["turn_count"] == 40


def test_resume_loads_session_and_continues(tmp_path):
    """--resume loads session.json and the loop continues."""
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()

    # Write a pre-existing session snapshot
    session_data = {
        "source_hash": "abc12345678901ab",
        "source_file": "src.md",
        "turn_count": 5,
        "messages": [{"role": "user", "content": "restored from snapshot"}],
    }
    session_path = state_dir / "abc12345678901ab.session.json"
    session_path.write_text(json.dumps(session_data), encoding="utf-8")

    # Write a valid dag.md so output_dag will succeed
    valid_md = _make_valid_dag_md()
    (state_dir / "abc12345678901ab.dag.md").write_text(valid_md, encoding="utf-8")

    # Mock provider: just call output_dag on the first turn
    turns = [
        [ToolCall(id="t1", name="output_dag", input={})],
    ]
    provider = MockProvider(turns)
    harness = Agent1Harness(
        kb_root=tmp_path,
        cfg=_make_cfg(),
        provider=provider,
        source_hash="abc12345678901ab",
        source_file="src.md",
        no_interactive=True,
        dry_run=True,
    )
    report = harness.run("source text", resume=True)
    assert not report.errors
    assert any("resumed" in t for t in report.phase_traces)


def test_resume_missing_session_returns_error(tmp_path):
    """--resume without a session.json → report.errors populated."""
    (tmp_path / "_import-state").mkdir()
    provider = MockProvider([])
    harness = Agent1Harness(
        kb_root=tmp_path,
        cfg=_make_cfg(),
        provider=provider,
        source_hash="abc12345678901ab",
        no_interactive=True,
        dry_run=True,
    )
    report = harness.run("source text", resume=True)
    assert len(report.errors) > 0
    assert "resume" in report.errors[0].lower() or "session" in report.errors[0].lower()


# ---------------------------------------------------------------------------
# US4: MaxTurnsExceeded
# ---------------------------------------------------------------------------


def test_max_turns_exceeded(tmp_path):
    """Exceeding maxTurns=300 → report.errors has MaxTurnsExceededError message."""
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()

    # 301 turns of read_dag calls
    turns = [
        [ToolCall(id=f"t{i}", name="read_dag", input={})]
        for i in range(301)
    ]
    provider = MockProvider(turns)
    harness = Agent1Harness(
        kb_root=tmp_path,
        cfg=_make_cfg(),
        provider=provider,
        source_hash="abc12345678901ab",
        no_interactive=True,
        dry_run=False,
    )
    report = harness.run("source text")
    assert len(report.errors) > 0
    assert "maxTurns" in report.errors[0] or "300" in report.errors[0]


# ---------------------------------------------------------------------------
# US5: --no-interactive auto-selects [2]
# ---------------------------------------------------------------------------


def test_no_interactive_auto_selects_option2(tmp_path):
    """--no-interactive: auto_decisions records 'DAG 未经用户确认'."""
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()
    valid_md = _make_valid_dag_md()

    turns = [
        [ToolCall(id="t1", name="write_dag", input={"content": valid_md})],
        [ToolCall(id="t2", name="output_dag", input={})],
    ]
    provider = MockProvider(turns)
    harness = Agent1Harness(
        kb_root=tmp_path,
        cfg=_make_cfg(),
        provider=provider,
        source_hash="abc12345678901ab",
        source_file="src.md",
        no_interactive=True,
        dry_run=False,
    )
    report = harness.run("source text")
    assert "DAG 未经用户确认" in report.auto_decisions


# ---------------------------------------------------------------------------
# US6: --skip-edit
# ---------------------------------------------------------------------------


def test_skip_edit_bypasses_menu(tmp_path):
    """--skip-edit: same as --no-interactive for menu, records auto_decisions."""
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()
    valid_md = _make_valid_dag_md()

    turns = [
        [ToolCall(id="t1", name="write_dag", input={"content": valid_md})],
        [ToolCall(id="t2", name="output_dag", input={})],
    ]
    provider = MockProvider(turns)
    harness = Agent1Harness(
        kb_root=tmp_path,
        cfg=_make_cfg(),
        provider=provider,
        source_hash="abc12345678901ab",
        source_file="src.md",
        no_interactive=False,
        dry_run=False,
        skip_edit=True,
    )
    report = harness.run("source text")
    assert "DAG 未经用户确认" in report.auto_decisions


# ---------------------------------------------------------------------------
# find_pending_sessions
# ---------------------------------------------------------------------------


def test_find_pending_sessions_empty(tmp_path):
    result = find_pending_sessions(tmp_path)
    assert result == []


def test_find_pending_sessions_finds_files(tmp_path):
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()
    session = {
        "source_hash": "abc12345678901ab",
        "source_file": "foo.md",
        "turn_count": 10,
        "messages": [],
    }
    (state_dir / "abc12345678901ab.session.json").write_text(
        json.dumps(session), encoding="utf-8"
    )
    result = find_pending_sessions(tmp_path)
    assert len(result) == 1
    assert result[0]["source_hash"] == "abc12345678901ab"


# ---------------------------------------------------------------------------
# Read-phase nudge: model stops early without producing DAG
# ---------------------------------------------------------------------------


def test_read_phase_nudge_triggers_on_early_stop(tmp_path):
    """If model stops in read phase, harness nudges it to call write_dag."""
    from holmes.kb.agent.dag.harness1 import MAX_READ_NUDGES

    # Track how many times complete() is called
    call_count = 0

    class EarlyStopThenWriteProvider(MockProvider):
        def complete(self, messages, system, model, max_tokens, tools):
            nonlocal call_count
            call_count += 1
            if call_count <= MAX_READ_NUDGES:
                # First N calls: stop without tool calls (model thinks it's done)
                return True, [], list(messages) + [{"role": "assistant", "content": "done"}], {}
            # After nudges: produce write_dag + output_dag
            return super().complete(messages, system, model, max_tokens, tools)

    dag_md = _make_valid_dag_md()
    tc_write = ToolCall(id="tc1", name="write_dag", input={"content": dag_md})
    tc_read = ToolCall(id="tc2", name="read_dag", input={})
    tc_output = ToolCall(id="tc3", name="output_dag", input={})
    provider = EarlyStopThenWriteProvider([
        [tc_write],   # after nudge: write_dag
        [tc_read],    # read_dag
        [tc_output],  # output_dag
    ])

    harness = Agent1Harness(
        kb_root=tmp_path,
        cfg=_make_cfg(),
        provider=provider,
        source_hash="abc12345678901ab",
        source_file="src.md",
        no_interactive=True,
        dry_run=True,
    )

    report = harness.run(source_text="test source doc")
    # Should have been nudged MAX_READ_NUDGES times then succeeded
    assert call_count > MAX_READ_NUDGES
    # No "output_dag was not called" warning — DAG was produced
    assert not any("output_dag was not called" in w for w in report.warnings)


def test_read_phase_nudge_gives_up_after_max(tmp_path):
    """After MAX_READ_NUDGES, harness gives up and returns incomplete."""
    from holmes.kb.agent.dag.harness1 import MAX_READ_NUDGES

    # Always stop — never produce tool calls
    class AlwaysStopProvider(MockProvider):
        def complete(self, messages, system, model, max_tokens, tools):
            return True, [], list(messages) + [{"role": "assistant", "content": "done"}], {}

    provider = AlwaysStopProvider([])

    harness = Agent1Harness(
        kb_root=tmp_path,
        cfg=_make_cfg(),
        provider=provider,
        source_hash="abc12345678901ab",
        source_file="src.md",
        no_interactive=True,
        dry_run=True,
    )

    report = harness.run(source_text="test source doc")
    # Should have warning about incomplete DAG
    assert any("output_dag was not called" in w for w in report.warnings)
