"""Tests for kb/holmes/kb/agent/dag/schema.py — DAGNode, DAGEdge, DAGGraph."""

from __future__ import annotations

import pytest

from holmes.kb.agent.dag.schema import (
    Agent1Session,
    Complexity,
    DAGEdge,
    DAGGraph,
    DAGNode,
    NodeType,
)


# ---------------------------------------------------------------------------
# NodeType enum
# ---------------------------------------------------------------------------


def test_node_type_values():
    assert NodeType.human_observation.value == "human_observation"
    assert NodeType.api_call.value == "api_call"
    assert NodeType.decision.value == "decision"
    assert NodeType.remote_action.value == "remote_action"
    assert NodeType.physical_action.value == "physical_action"


def test_node_type_from_string():
    assert NodeType("api_call") == NodeType.api_call
    with pytest.raises(ValueError):
        NodeType("unknown_type")


# ---------------------------------------------------------------------------
# Complexity enum
# ---------------------------------------------------------------------------


def test_complexity_values():
    assert Complexity.simple.value == "simple"
    assert Complexity.process.value == "process"


# ---------------------------------------------------------------------------
# DAGEdge
# ---------------------------------------------------------------------------


def test_dagedge_defaults():
    edge = DAGEdge(condition="红色闪烁", target="N3")
    assert edge.condition == "红色闪烁"
    assert edge.target == "N3"
    assert edge.is_back_edge is False


def test_dagedge_back_edge():
    edge = DAGEdge(condition="重试", target="N1", is_back_edge=True)
    assert edge.is_back_edge is True


# ---------------------------------------------------------------------------
# DAGNode
# ---------------------------------------------------------------------------


def test_dagnode_minimal():
    node = DAGNode(
        id="N1",
        description="检查电源指示灯",
        node_type=NodeType.human_observation,
        complexity=Complexity.simple,
    )
    assert node.id == "N1"
    assert node.section_heading is None
    assert node.is_end is False
    assert node.children == []


def test_dagnode_process_with_heading():
    node = DAGNode(
        id="N3",
        description="固件修复流程",
        node_type=NodeType.remote_action,
        complexity=Complexity.process,
        section_heading="### 固件修复步骤",
        children=[
            DAGEdge(condition="修复成功", target="END"),
            DAGEdge(condition="修复失败", target="N7"),
        ],
    )
    assert node.complexity == Complexity.process
    assert node.section_heading == "### 固件修复步骤"
    assert len(node.children) == 2


def test_dagnode_end():
    node = DAGNode(
        id="N99",
        description="终止",
        node_type=NodeType.decision,
        complexity=Complexity.simple,
        is_end=True,
    )
    assert node.is_end is True
    assert node.children == []


# ---------------------------------------------------------------------------
# DAGGraph
# ---------------------------------------------------------------------------


def _make_simple_graph() -> DAGGraph:
    n1 = DAGNode("N1", "root node", NodeType.decision, Complexity.simple,
                  children=[DAGEdge("yes", "N2"), DAGEdge("no", "N3")])
    n2 = DAGNode("N2", "leaf A", NodeType.remote_action, Complexity.process, is_end=True)
    n3 = DAGNode("N3", "leaf B", NodeType.remote_action, Complexity.simple, is_end=True)
    return DAGGraph(nodes=[n1, n2, n3], title="Test", source_file="test.md", generated="2026-06-24")


def test_daggraph_node_by_id():
    graph = _make_simple_graph()
    assert graph.node_by_id("N2") is not None
    assert graph.node_by_id("N2").description == "leaf A"
    assert graph.node_by_id("N99") is None


def test_daggraph_root_nodes():
    graph = _make_simple_graph()
    roots = graph.root_nodes()
    assert len(roots) == 1
    assert roots[0].id == "N1"


def test_daggraph_multi_root():
    """Two disconnected subtrees should both appear as roots."""
    n1 = DAGNode("N1", "tree 1 root", NodeType.decision, Complexity.simple,
                  children=[DAGEdge("done", "N2")])
    n2 = DAGNode("N2", "tree 1 leaf", NodeType.remote_action, Complexity.simple, is_end=True)
    n3 = DAGNode("N3", "tree 2 root", NodeType.decision, Complexity.simple,
                  children=[DAGEdge("done", "N4")])
    n4 = DAGNode("N4", "tree 2 leaf", NodeType.remote_action, Complexity.simple, is_end=True)
    graph = DAGGraph(nodes=[n1, n2, n3, n4], title="Multi", source_file="m.md", generated="2026-06-24")
    roots = graph.root_nodes()
    root_ids = {r.id for r in roots}
    assert root_ids == {"N1", "N3"}


def test_daggraph_back_edges_excluded_from_roots():
    """Back-edges should not cause their source to be considered referenced."""
    n1 = DAGNode("N1", "root", NodeType.decision, Complexity.simple,
                  children=[DAGEdge("loop", "N1", is_back_edge=True)])
    graph = DAGGraph(nodes=[n1], title="Loop", source_file="l.md", generated="2026-06-24")
    roots = graph.root_nodes()
    # N1 references itself via back_edge — it should still be a root
    assert len(roots) == 1
    assert roots[0].id == "N1"


# ---------------------------------------------------------------------------
# Agent1Session
# ---------------------------------------------------------------------------


def test_agent1session_defaults():
    session = Agent1Session(source_hash="abc123", turn_count=20, messages=[{"role": "user"}])
    assert session.source_file == ""
    assert session.turn_count == 20
    assert len(session.messages) == 1


def test_agent1session_with_source_file():
    session = Agent1Session(
        source_hash="abc123",
        turn_count=40,
        messages=[],
        source_file="docs/hardware-failure.md",
    )
    assert session.source_file == "docs/hardware-failure.md"
