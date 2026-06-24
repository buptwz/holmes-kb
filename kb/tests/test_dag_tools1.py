"""Tests for kb/holmes/kb/agent/dag/tools1.py — write_dag, read_dag, output_dag."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from holmes.kb.agent.dag.schema import Complexity, DAGEdge, DAGGraph, DAGNode, NodeType
from holmes.kb.agent.dag.formatter import dag_to_markdown
from holmes.kb.agent.dag.tools1 import (
    tool_output_dag,
    tool_read_dag,
    tool_write_dag,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_state_dir(tmp_path):
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()
    return state_dir


@pytest.fixture()
def ctx(tmp_path, tmp_state_dir):
    return {
        "state_dir": tmp_state_dir,
        "source_hash": "abc12345678901ab",
        "source_file": "test.md",
        "source_text": "test content",
        "kb_root": tmp_path,
    }


def _valid_dag_md(source_hash: str = "abc12345678901ab") -> str:
    """Build a minimal valid .dag.md string."""
    n1 = DAGNode("N1", "root", NodeType.decision, Complexity.simple,
                  children=[DAGEdge("yes", "N2"), DAGEdge("no", "N3")])
    n2 = DAGNode("N2", "process node", NodeType.action, Complexity.process,
                  section_heading="### Steps",
                  children=[DAGEdge("done", "END")])
    n3 = DAGNode("N3", "simple end", NodeType.action, Complexity.simple,
                  is_end=True)
    graph = DAGGraph(nodes=[n1, n2, n3], title="Test", source_file="test.md", generated="2026-06-24")
    return dag_to_markdown(graph)


# ---------------------------------------------------------------------------
# write_dag
# ---------------------------------------------------------------------------


def test_write_dag_creates_file(ctx, tmp_state_dir):
    result = tool_write_dag(ctx, {"content": _valid_dag_md()})
    assert result.get("success") is True
    dag_path = tmp_state_dir / "abc12345678901ab.dag.md"
    assert dag_path.exists()


def test_write_dag_empty_content_returns_error(ctx):
    result = tool_write_dag(ctx, {"content": ""})
    assert "error" in result


def test_write_dag_overwrites_previous(ctx, tmp_state_dir):
    tool_write_dag(ctx, {"content": _valid_dag_md()})
    tool_write_dag(ctx, {"content": "# 排查树：Updated\n\n## 节点详情\n\n### N1 — x\ncomplexity: simple\nnode_type: action\n\n- END\n"})
    dag_path = tmp_state_dir / "abc12345678901ab.dag.md"
    content = dag_path.read_text()
    assert "Updated" in content


# ---------------------------------------------------------------------------
# read_dag
# ---------------------------------------------------------------------------


def test_read_dag_no_file_returns_error(ctx):
    result = tool_read_dag(ctx, {})
    assert "error" in result


def test_read_dag_returns_content(ctx, tmp_state_dir):
    md = _valid_dag_md()
    tool_write_dag(ctx, {"content": md})
    result = tool_read_dag(ctx, {})
    assert "content" in result
    assert "排查树" in result["content"]


# ---------------------------------------------------------------------------
# output_dag — validation rules
# ---------------------------------------------------------------------------


def test_output_dag_valid_passes(ctx):
    tool_write_dag(ctx, {"content": _valid_dag_md()})
    result = tool_output_dag(ctx, {})
    assert result.get("_terminate") is True
    assert result.get("success") is True
    assert result.get("nodes") == 3
    assert result.get("process_nodes") == 1


def test_output_dag_generates_json_file(ctx, tmp_state_dir):
    tool_write_dag(ctx, {"content": _valid_dag_md()})
    tool_output_dag(ctx, {})
    dag_json_path = tmp_state_dir / "abc12345678901ab.dag.json"
    assert dag_json_path.exists()
    data = json.loads(dag_json_path.read_text())
    assert "nodes" in data
    assert len(data["nodes"]) == 3


def test_output_dag_no_file_returns_error(ctx):
    result = tool_output_dag(ctx, {})
    assert "error" in result


# Rule 1: No root node
def test_output_dag_rule1_no_root(ctx, tmp_state_dir):
    """All nodes are referenced → no root → validation error."""
    md = """\
# 排查树：No Root

> source: test.md
> generated: 2026-06-24
> 说明：test

---

## 文档摘要

test

---

## 排查树概览

test

---

## 节点详情

### N1 — node 1
complexity: simple
node_type: action

- go → **N2**

---

### N2 — node 2
complexity: simple
node_type: action

- go → **N1**
"""
    tool_write_dag(ctx, {"content": md})
    result = tool_output_dag(ctx, {})
    # Either cycle detection (rule 3) or no-root (rule 1) fires
    assert "error" in result


# Rule 2: Dangling edge
def test_output_dag_rule2_dangling_edge(ctx):
    md = """\
# 排查树：Dangling

> source: test.md
> generated: 2026-06-24
> 说明：test

---

## 文档摘要

test

---

## 排查树概览

test

---

## 节点详情

### N1 — root
complexity: simple
node_type: action

- go → **N99**
"""
    tool_write_dag(ctx, {"content": md})
    result = tool_output_dag(ctx, {})
    assert "error" in result
    assert "N99" in result["error"]


# Rule 3: Cycle
def test_output_dag_rule3_cycle(ctx):
    md = """\
# 排查树：Cycle

> source: test.md
> generated: 2026-06-24
> 说明：test

---

## 文档摘要

test

---

## 排查树概览

test

---

## 节点详情

### N1 — root
complexity: simple
node_type: action

- go → **N2**

---

### N2 — node2
complexity: simple
node_type: action

- loop → **N3**

---

### N3 — node3
complexity: simple
node_type: action

- back → **N2**
"""
    tool_write_dag(ctx, {"content": md})
    result = tool_output_dag(ctx, {})
    assert "error" in result
    # Error should mention cycle
    assert "循环" in result["error"] or "N2" in result["error"] or "N3" in result["error"]


# Rule 4: Process node without section_heading or description
def test_output_dag_rule4_process_no_heading_no_desc():
    """Directly test _validate_dag rule 4 with a process node missing both fields."""
    from holmes.kb.agent.dag.tools1 import _validate_dag

    n1 = DAGNode("N1", "root", NodeType.decision, Complexity.simple,
                  children=[DAGEdge("yes", "N2")])
    # N2: process, description empty, no section_heading → rule 4 should fire
    n2 = DAGNode("N2", "", NodeType.action, Complexity.process,
                  section_heading=None,
                  children=[DAGEdge("done", "END")])
    graph = DAGGraph(nodes=[n1, n2], title="T", source_file="t.md", generated="2026-06-24")
    error = _validate_dag(graph)
    assert error != ""
    assert "N2" in error


# Rule 5: Node without outgoing edges and not END
def test_output_dag_rule5_no_outgoing_edges(ctx):
    md = """\
# 排查树：NoEdge

> source: test.md
> generated: 2026-06-24
> 说明：test

---

## 文档摘要

test

---

## 排查树概览

test

---

## 节点详情

### N1 — root
complexity: simple
node_type: action

- go → **N2**

---

### N2 — stranded
complexity: simple
node_type: action

"""
    tool_write_dag(ctx, {"content": md})
    result = tool_output_dag(ctx, {})
    assert "error" in result
    assert "N2" in result["error"]


# back_edge excluded from cycle detection
def test_output_dag_back_edge_not_cycle(ctx):
    """A back_edge should not trigger cycle detection."""
    md = """\
# 排查树：BackEdge

> source: test.md
> generated: 2026-06-24
> 说明：test

---

## 文档摘要

test

---

## 排查树概览

test

---

## 节点详情

### N1 — root
complexity: simple
node_type: action

- go → **N2**

---

### N2 — node
complexity: process
node_type: action
section_heading: "### Steps"

- retry → **N1** [back_edge]
- done → END
"""
    tool_write_dag(ctx, {"content": md})
    result = tool_output_dag(ctx, {})
    # Should pass validation (back_edge excluded from cycle check)
    assert result.get("_terminate") is True, f"Unexpected error: {result.get('error')}"


# Multi-root (multi_incident)
def test_output_dag_multi_root_allowed(ctx):
    """Two disconnected subtrees → two roots → valid."""
    md = """\
# 排查树：MultiRoot

> source: test.md
> generated: 2026-06-24
> 说明：test

---

## 文档摘要

test

---

## 排查树概览

test

---

## 节点详情

### N1 — tree 1 root
complexity: simple
node_type: action

- done → END

---

### N2 — tree 2 root
complexity: simple
node_type: action

- done → END
"""
    tool_write_dag(ctx, {"content": md})
    result = tool_output_dag(ctx, {})
    assert result.get("_terminate") is True, f"Unexpected error: {result.get('error')}"
    assert result.get("nodes") == 2
