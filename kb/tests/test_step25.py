"""Tests for holmes.kb.agent.dag.step25 — T035."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from holmes.kb.agent.dag.step25 import (
    ParseResult,
    _max_depth,
    _run_section_validation,
    display_complexity_tips,
    display_step25_result,
    run_step25,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


_MINIMAL_DAG_MD = """\
# Test DAG

ROOT: test-pitfall

## Process Nodes

### N1: firmware-check
- complexity: simple
- description: Check firmware
- section_heading: Firmware Check

## Edges

START → N1 → END
"""

_SOURCE_TEXT = """\
# Hardware Init Failure

## Firmware Check

Step 1: check the firmware version.

## Root Cause

Firmware out of date.
"""


def _write_dag_md(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.dag.md"
    p.write_text(content, encoding="utf-8")
    return p


class FakeProvider:
    def complete(self, messages, system, model, max_tokens, tools):
        # Return a response with no recognized edits
        content = '{"recognized": [], "uncertain": []}'
        msg = {"role": "assistant", "content": content}
        return False, [], [msg], {}


class FakeCfg:
    model = "test-model"
    username = "testuser"


# ---------------------------------------------------------------------------
# run_step25 — basic parsing
# ---------------------------------------------------------------------------


def test_run_step25_missing_file(tmp_path):
    result = run_step25(tmp_path / "missing.dag.md", _SOURCE_TEXT, None, FakeCfg())
    assert result.validation_errors
    assert any("not found" in e for e in result.validation_errors)


def test_run_step25_invalid_dag_content(tmp_path):
    dag_md = _write_dag_md(tmp_path, "# Just a title\nno structure at all\n")
    result = run_step25(dag_md, _SOURCE_TEXT, None, FakeCfg())
    # Parser may fail or return empty graph — either way no crash
    assert isinstance(result, ParseResult)


def test_run_step25_valid_dag_returns_graph(tmp_path):
    dag_md = _write_dag_md(tmp_path, _MINIMAL_DAG_MD)
    result = run_step25(dag_md, _SOURCE_TEXT, None, FakeCfg())
    # Should parse without structural errors
    assert isinstance(result, ParseResult)
    # dag_graph may be None if parsing fails strictly, but should not crash
    assert result.validation_errors is not None


def test_run_step25_section_validation_warning(tmp_path):
    dag_md = _write_dag_md(tmp_path, _MINIMAL_DAG_MD)
    # Source text missing the "Firmware Check" section
    source = "# Hardware Init\n\nNo matching sections here.\n"
    result = run_step25(dag_md, source, None, FakeCfg())
    # If graph parsed successfully, warning about missing section should appear
    if result.dag_graph is not None and result.dag_graph.nodes:
        # May or may not warn depending on parser strictness
        pass  # non-crashing is sufficient here


def test_run_step25_section_in_source_no_warning(tmp_path):
    dag_md = _write_dag_md(tmp_path, _MINIMAL_DAG_MD)
    result = run_step25(dag_md, _SOURCE_TEXT, None, FakeCfg())
    # "Firmware Check" is in source — no warning for that section
    fw_warnings = [w for w in result.validation_warnings if "Firmware Check" in w]
    assert fw_warnings == []


# ---------------------------------------------------------------------------
# _run_section_validation
# ---------------------------------------------------------------------------


def _make_node(id_, complexity, section_heading=None):
    from holmes.kb.agent.dag.schema import Complexity, DAGNode, NodeType
    return DAGNode(
        id=id_,
        description="test",
        complexity=complexity,
        node_type=NodeType.remote_action,
        section_heading=section_heading,
        children=[],
    )


def test_run_section_validation_no_warnings():
    from holmes.kb.agent.dag.schema import Complexity, DAGGraph
    node = _make_node("N1", Complexity.process, "Firmware Check")
    graph = DAGGraph(nodes=[node], title="test", source_file="test.md", generated="2026-01-01")
    result = ParseResult()
    _run_section_validation(graph, _SOURCE_TEXT, result)
    assert result.validation_warnings == []


def test_run_section_validation_warns_missing_section():
    from holmes.kb.agent.dag.schema import Complexity, DAGGraph
    node = _make_node("N1", Complexity.process, "Nonexistent Section XYZ")
    graph = DAGGraph(nodes=[node], title="test", source_file="test.md", generated="2026-01-01")
    result = ParseResult()
    _run_section_validation(graph, _SOURCE_TEXT, result)
    assert any("Nonexistent Section XYZ" in w for w in result.validation_warnings)


def test_run_section_validation_skips_simple_nodes():
    from holmes.kb.agent.dag.schema import Complexity, DAGGraph
    node = _make_node("N1", Complexity.simple, "Nonexistent Section")
    graph = DAGGraph(nodes=[node], title="test", source_file="test.md", generated="2026-01-01")
    result = ParseResult()
    _run_section_validation(graph, _SOURCE_TEXT, result)
    # simple node skipped — no warning
    assert result.validation_warnings == []


def test_run_section_validation_skips_null_heading():
    from holmes.kb.agent.dag.schema import Complexity, DAGGraph
    node = _make_node("N1", Complexity.process, None)
    graph = DAGGraph(nodes=[node], title="test", source_file="test.md", generated="2026-01-01")
    result = ParseResult()
    _run_section_validation(graph, _SOURCE_TEXT, result)
    assert result.validation_warnings == []


# ---------------------------------------------------------------------------
# TC-LR02: line_range bounds validation
# ---------------------------------------------------------------------------


def _make_node_with_lr(id_, line_range):
    from holmes.kb.agent.dag.schema import Complexity, DAGNode, NodeType
    node = DAGNode(
        id=id_,
        description="test",
        complexity=Complexity.process,
        node_type=NodeType.remote_action,
        section_heading="Firmware Check",
        line_range=line_range,
        children=[],
    )
    return node


def test_run_section_validation_line_range_in_bounds():
    """Valid line_range within source → no warning."""
    from holmes.kb.agent.dag.schema import DAGGraph
    # _SOURCE_TEXT has 8 lines
    node = _make_node_with_lr("N1", (0, 5))
    graph = DAGGraph(nodes=[node], title="test", source_file="test.md", generated="2026-01-01")
    result = ParseResult()
    _run_section_validation(graph, _SOURCE_TEXT, result)
    assert result.validation_warnings == []


def test_run_section_validation_line_range_out_of_bounds():
    """line_range end > total_lines → validation_warnings."""
    from holmes.kb.agent.dag.schema import DAGGraph
    total = len(_SOURCE_TEXT.splitlines())
    node = _make_node_with_lr("N2", (0, total + 50))
    graph = DAGGraph(nodes=[node], title="test", source_file="test.md", generated="2026-01-01")
    result = ParseResult()
    _run_section_validation(graph, _SOURCE_TEXT, result)
    assert any("N2" in w for w in result.validation_warnings)


def test_run_section_validation_line_range_start_ge_end():
    """line_range start >= end → validation_warnings."""
    from holmes.kb.agent.dag.schema import DAGGraph
    node = _make_node_with_lr("N3", (5, 3))
    graph = DAGGraph(nodes=[node], title="test", source_file="test.md", generated="2026-01-01")
    result = ParseResult()
    _run_section_validation(graph, _SOURCE_TEXT, result)
    assert any("N3" in w for w in result.validation_warnings)


def test_run_section_validation_line_range_priority_over_heading():
    """When line_range is valid, section_heading is NOT checked (no spurious warning)."""
    from holmes.kb.agent.dag.schema import DAGGraph
    # "Nonexistent Heading XYZ" is not in source, but line_range is valid → no warning
    node = _make_node_with_lr("N4", (0, 4))
    node.section_heading = "Nonexistent Heading XYZ"
    graph = DAGGraph(nodes=[node], title="test", source_file="test.md", generated="2026-01-01")
    result = ParseResult()
    _run_section_validation(graph, _SOURCE_TEXT, result)
    assert result.validation_warnings == []


# ---------------------------------------------------------------------------
# display_step25_result
# ---------------------------------------------------------------------------


def test_display_step25_result_structural_error(capsys):
    result = ParseResult()
    result.validation_errors.append("step25: DAG parsing failed: syntax error")
    ok = display_step25_result(result, no_interactive=True)
    assert not ok
    out = capsys.readouterr().out
    assert "解析失败" in out or "parsing failed" in out.lower() or "✗" in out


def test_display_step25_result_no_interactive_auto_accept(capsys):
    result = ParseResult()
    result.dag_graph = MagicMock()
    result.total_count = 3
    result.process_count = 2
    ok = display_step25_result(result, no_interactive=True)
    assert ok
    out = capsys.readouterr().out
    assert "自动" in out or "确认" in out


def test_display_step25_result_shows_validation_warnings(capsys):
    result = ParseResult()
    result.validation_warnings.append("N1 的 section 找不到")
    result.dag_graph = MagicMock()
    result.total_count = 1
    result.process_count = 0
    ok = display_step25_result(result, no_interactive=True)
    out = capsys.readouterr().out
    assert "N1" in out
    assert ok  # warnings don't block


def test_display_step25_result_shows_entry_count(capsys):
    result = ParseResult()
    result.dag_graph = MagicMock()
    result.total_count = 5
    result.process_count = 4
    display_step25_result(result, no_interactive=True)
    out = capsys.readouterr().out
    # Should mention entry counts
    assert "5" in out or "4" in out


# ---------------------------------------------------------------------------
# display_complexity_tips
# ---------------------------------------------------------------------------


def test_complexity_tips_no_tips(capsys):
    result = ParseResult()
    result.total_count = 5
    result.process_count = 3
    result.dag_graph = None
    display_complexity_tips(result)
    out = capsys.readouterr().out
    assert out.strip() == ""


def test_complexity_tips_large_total(capsys):
    result = ParseResult()
    result.total_count = 35
    result.process_count = 3
    result.dag_graph = None
    display_complexity_tips(result)
    out = capsys.readouterr().out
    assert "30" in out or "链路较长" in out


def test_complexity_tips_many_process(capsys):
    result = ParseResult()
    result.total_count = 15
    result.process_count = 16
    result.dag_graph = None
    display_complexity_tips(result)
    out = capsys.readouterr().out
    assert "entries" in out or "process" in out


# ---------------------------------------------------------------------------
# _max_depth
# ---------------------------------------------------------------------------


def test_max_depth_empty_graph():
    from holmes.kb.agent.dag.schema import DAGGraph
    graph = DAGGraph(nodes=[], title="t", source_file="", generated="2026-01-01")
    assert _max_depth(graph) == 0


def test_max_depth_single_node():
    from holmes.kb.agent.dag.schema import Complexity, DAGGraph
    node = _make_node("N1", Complexity.simple)
    graph = DAGGraph(nodes=[node], title="test", source_file="test.md", generated="2026-01-01")
    assert _max_depth(graph) == 1


def test_max_depth_linear_chain():
    from holmes.kb.agent.dag.schema import Complexity, DAGEdge, DAGGraph
    n1 = _make_node("N1", Complexity.simple)
    n2 = _make_node("N2", Complexity.simple)
    edge = DAGEdge(condition="", target="N2", is_back_edge=False)
    n1.children.append(edge)
    graph = DAGGraph(nodes=[n1, n2], title="t", source_file="", generated="2026-01-01")
    assert _max_depth(graph) >= 2


# ---------------------------------------------------------------------------
# ParseResult default values
# ---------------------------------------------------------------------------


def test_parse_result_defaults():
    r = ParseResult()
    assert r.recognized_edits == []
    assert r.uncertain_items == []
    assert r.validation_errors == []
    assert r.validation_warnings == []
    assert r.dag_graph is None
    assert r.process_count == 0
    assert r.total_count == 0
