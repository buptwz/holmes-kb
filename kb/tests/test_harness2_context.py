"""Unit tests for 038 per-node context optimization — T1-T9 in tasks.md.

Tests:
    T1 - _build_node_messages contains DAG overview
    T2 - _build_node_messages includes source segment when line_range present
    T3 - _build_node_messages gives Grep fallback when no line_range
    T4 - _build_node_messages includes brief from prior entries
    T5 - _collect_brief correctly extracts title and step_count
    T6 - _collect_brief returns None when no matching entry
    T7 - _topological_reverse puts leaf nodes before parent nodes
    T8 - _build_root_messages includes all entry briefs
    T9 - context size stays constant across many nodes
    T10 - _build_root_messages child_ids: entry point with process entry
    T11 - _build_root_messages child_ids: BFS through entry-pointless decision node
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from holmes.kb.agent.dag.harness2 import Agent2Harness, EntryBrief
from holmes.kb.agent.report import ImportReport


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


class FakeConfig:
    model = "test-model"
    username = "testuser"
    api_key = "sk-test"
    api_base_url = ""


def _make_harness(
    tmp_path: Path,
    nodes: list[dict],
    entry_ids: dict | None = None,
) -> Agent2Harness:
    """Create a minimal Agent2Harness with a pre-written .dag.json."""
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "title": "Test DAG",
        "source_file": "test.md",
        "nodes": nodes,
        "entry_ids": entry_ids or {},
        "import_seq": "001",
    }
    dag_path = state_dir / "abc12345.dag.json"
    dag_path.write_text(json.dumps(data), encoding="utf-8")

    provider = MagicMock()
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="abc12345",
        source_file="test.md",
        dag_json_path=dag_path,
    )
    harness._load_dag_json(ImportReport())
    return harness


# ---------------------------------------------------------------------------
# T1 - _build_node_messages contains DAG overview
# ---------------------------------------------------------------------------


def test_build_node_messages_contains_dag(tmp_path):
    nodes = [
        {"id": "N1", "complexity": "process", "description": "Fix firmware", "children": []},
        {"id": "N2", "complexity": "process", "description": "Replace hardware", "children": []},
    ]
    entry_ids = {"N1": "proc-n1-001", "N2": "proc-n2-001", "root": "root-001"}
    harness = _make_harness(tmp_path, nodes, entry_ids)

    msgs = harness._build_node_messages(
        node=nodes[0],
        source_lines=["line1", "line2"],
        briefs=[],
    )
    content = msgs[0]["content"]

    # DAG overview must include node IDs
    assert "N1" in content
    assert "N2" in content
    # entry_ids table must be present
    assert "proc-n1-001" in content
    assert "root-001" in content


# ---------------------------------------------------------------------------
# T2 - _build_node_messages includes source segment when line_range present
# ---------------------------------------------------------------------------


def test_build_node_messages_source_segment(tmp_path):
    source_lines = [f"line {i}" for i in range(1, 21)]  # 20 lines
    nodes = [
        {
            "id": "N1",
            "complexity": "process",
            "description": "Test node",
            "line_range": [5, 10],
            "children": [],
        }
    ]
    entry_ids = {"N1": "proc-n1-001", "root": "root-001"}
    harness = _make_harness(tmp_path, nodes, entry_ids)

    msgs = harness._build_node_messages(
        node=nodes[0],
        source_lines=source_lines,
        briefs=[],
    )
    content = msgs[0]["content"]

    # line_range [5, 10] with ±5 expansion → lines 0-15 (0-indexed)
    # "line 1" through "line 15" should appear
    assert "line 5" in content
    assert "line 10" in content
    # Should NOT contain Grep instruction since line_range is present
    assert "Grep" not in content


# ---------------------------------------------------------------------------
# T3 - _build_node_messages gives Grep fallback when no line_range
# ---------------------------------------------------------------------------


def test_build_node_messages_grep_fallback(tmp_path):
    nodes = [
        {
            "id": "N1",
            "complexity": "process",
            "description": "Check memory",
            "section_heading": "## Memory Check",
            "children": [],
        }
    ]
    entry_ids = {"N1": "proc-n1-001", "root": "root-001"}
    harness = _make_harness(tmp_path, nodes, entry_ids)

    msgs = harness._build_node_messages(
        node=nodes[0],
        source_lines=["some source"],
        briefs=[],
    )
    content = msgs[0]["content"]

    # No line_range → Grep instruction should appear
    assert "Grep" in content


# ---------------------------------------------------------------------------
# T4 - _build_node_messages includes brief from prior entries
# ---------------------------------------------------------------------------


def test_build_node_messages_contains_brief(tmp_path):
    nodes = [
        {"id": "N1", "complexity": "process", "description": "Fix N1", "children": []},
        {"id": "N2", "complexity": "process", "description": "Fix N2", "children": []},
    ]
    entry_ids = {"N1": "proc-n1-001", "N2": "proc-n2-001", "root": "root-001"}
    harness = _make_harness(tmp_path, nodes, entry_ids)

    briefs = [
        {
            "node_id": "N1",
            "entry_id": "proc-n1-001",
            "title": "First step procedure",
            "step_count": 3,
            "has_children": False,
        }
    ]

    msgs = harness._build_node_messages(
        node=nodes[1],
        source_lines=["source"],
        briefs=briefs,
    )
    content = msgs[0]["content"]

    # Brief info must appear in context
    assert "N1" in content
    assert "proc-n1-001" in content
    assert "First step procedure" in content


# ---------------------------------------------------------------------------
# T5 - _collect_brief correctly extracts title and step_count
# ---------------------------------------------------------------------------


def test_collect_brief_extracts_correctly(tmp_path):
    nodes = [{"id": "N1", "complexity": "process", "description": "test"}]
    entry_ids = {"N1": "proc-n1-001"}
    harness = _make_harness(tmp_path, nodes, entry_ids)

    body = (
        "## Steps\n\n"
        "1. **[api]** Run nvidia-smi\n"
        "   Expected output: GPU list\n\n"
        "2. **[decide]** Check result:\n"
        "   - OK → done\n\n"
        "3. **[remote]** Restart service\n"
    )
    ctx = {
        "written_entries": [
            {
                "entry_id": "proc-n1-001",
                "frontmatter": {"title": "GPU Firmware Fix", "child_entry_ids": ["child-001"]},
                "body": body,
            }
        ]
    }

    brief = harness._collect_brief(ctx, "N1", "proc-n1-001")

    assert brief is not None
    assert brief["entry_id"] == "proc-n1-001"
    assert brief["node_id"] == "N1"
    assert brief["title"] == "GPU Firmware Fix"
    assert brief["step_count"] == 3
    assert brief["has_children"] is True


# ---------------------------------------------------------------------------
# T6 - _collect_brief returns None when no matching entry
# ---------------------------------------------------------------------------


def test_collect_brief_returns_none(tmp_path):
    nodes = [{"id": "N1", "complexity": "process", "description": "test"}]
    entry_ids = {"N1": "proc-n1-001"}
    harness = _make_harness(tmp_path, nodes, entry_ids)

    ctx = {"written_entries": []}

    brief = harness._collect_brief(ctx, "N1", "proc-n1-001")
    assert brief is None


def test_collect_brief_returns_none_wrong_entry_id(tmp_path):
    nodes = [{"id": "N1", "complexity": "process", "description": "test"}]
    entry_ids = {"N1": "proc-n1-001"}
    harness = _make_harness(tmp_path, nodes, entry_ids)

    ctx = {
        "written_entries": [
            {
                "entry_id": "proc-n2-001",  # different entry
                "frontmatter": {"title": "Different"},
                "body": "1. step\n",
            }
        ]
    }

    brief = harness._collect_brief(ctx, "N1", "proc-n1-001")
    assert brief is None


# ---------------------------------------------------------------------------
# T7 - _topological_reverse puts leaf nodes before parent nodes
# ---------------------------------------------------------------------------


def test_topological_reverse_leaves_first(tmp_path):
    """N3 (leaf) must come before N2 (parent of N3)."""
    nodes = [
        {
            "id": "N2",
            "complexity": "process",
            "description": "Parent node",
            "children": [{"target": "N3", "condition": "when broken"}],
        },
        {
            "id": "N3",
            "complexity": "process",
            "description": "Leaf node",
            "children": [],
        },
    ]
    entry_ids = {"N2": "proc-n2-001", "N3": "proc-n3-001", "root": "root-001"}
    harness = _make_harness(tmp_path, nodes, entry_ids)

    ordered = harness._topological_reverse(nodes)
    ids = [n["id"] for n in ordered]

    assert ids.index("N3") < ids.index("N2"), f"Expected N3 before N2, got order: {ids}"


def test_topological_reverse_multi_level(tmp_path):
    """N4 (leaf) → N3 → N2 chain: must be ordered N4, N3, N2."""
    nodes = [
        {
            "id": "N2",
            "complexity": "process",
            "description": "Top",
            "children": [{"target": "N3", "condition": "A"}],
        },
        {
            "id": "N3",
            "complexity": "process",
            "description": "Middle",
            "children": [{"target": "N4", "condition": "B"}],
        },
        {
            "id": "N4",
            "complexity": "process",
            "description": "Leaf",
            "children": [],
        },
    ]
    entry_ids = {"N2": "e2", "N3": "e3", "N4": "e4"}
    harness = _make_harness(tmp_path, nodes, entry_ids)

    ordered = harness._topological_reverse(nodes)
    ids = [n["id"] for n in ordered]

    assert ids.index("N4") < ids.index("N3"), f"N4 must be before N3, got: {ids}"
    assert ids.index("N3") < ids.index("N2"), f"N3 must be before N2, got: {ids}"


# ---------------------------------------------------------------------------
# T8 - _build_root_messages includes all entry briefs
# ---------------------------------------------------------------------------


def test_build_root_messages_has_all_briefs(tmp_path):
    nodes = [
        {"id": "N1", "complexity": "process", "description": "A", "children": []},
        {"id": "N2", "complexity": "process", "description": "B", "children": []},
    ]
    entry_ids = {"N1": "proc-n1-001", "N2": "proc-n2-001", "root": "root-001"}
    harness = _make_harness(tmp_path, nodes, entry_ids)

    briefs = [
        {"node_id": "N1", "entry_id": "proc-n1-001", "title": "Step A", "step_count": 2, "has_children": False},
        {"node_id": "N2", "entry_id": "proc-n2-001", "title": "Step B", "step_count": 3, "has_children": False},
    ]

    msgs = harness._build_root_messages(source_text="full source text here", briefs=briefs)
    content = msgs[0]["content"]

    # All entry IDs must appear
    assert "proc-n1-001" in content
    assert "proc-n2-001" in content
    # Root entry_id must appear
    assert "root-001" in content
    # Source text must appear
    assert "full source text here" in content


# ---------------------------------------------------------------------------
# T9 - context size stays constant across many nodes (no accumulation)
# ---------------------------------------------------------------------------


def test_context_size_constant(tmp_path):
    """Context for the 5th node must not be significantly larger than the 1st.

    Each per-node call starts with a fresh messages list. The context grows
    only by the brief list (≈50 tokens/entry), not by full conversation history.
    """
    source_lines = [f"line {i}: some diagnostic content" for i in range(1, 101)]
    nodes = [
        {
            "id": f"N{i}",
            "complexity": "process",
            "description": f"Node {i} description",
            "line_range": [i * 5, i * 5 + 4],
            "children": [],
        }
        for i in range(1, 6)
    ]
    entry_ids = {f"N{i}": f"proc-n{i}-001" for i in range(1, 6)}
    entry_ids["root"] = "root-001"
    harness = _make_harness(tmp_path, nodes, entry_ids)

    # Build messages for node 1 with 0 briefs
    msgs_1 = harness._build_node_messages(nodes[0], source_lines, briefs=[])
    size_1 = len(msgs_1[0]["content"])

    # Build messages for node 5 with 4 briefs (simulating 4 prior nodes written)
    briefs = [
        {
            "node_id": f"N{i}",
            "entry_id": f"proc-n{i}-001",
            "title": f"Procedure for node {i}",
            "step_count": 3,
            "has_children": False,
        }
        for i in range(1, 5)
    ]
    msgs_5 = harness._build_node_messages(nodes[4], source_lines, briefs=briefs)
    size_5 = len(msgs_5[0]["content"])

    # Context should not blow up: node 5 context < 3x node 1 context
    # (In old single-loop mode, node 5 would accumulate all tool results → much larger)
    assert size_5 < size_1 * 3, (
        f"Context grew too much: node1={size_1} chars, node5={size_5} chars "
        f"(ratio={size_5/size_1:.1f}x, expected <3x)"
    )
    # Also verify absolute size is reasonable (< 3000 chars for this small test)
    assert size_5 < 3000, f"Context too large: {size_5} chars"


# ---------------------------------------------------------------------------
# T10/T11 - _build_root_messages child_ids BFS algorithm
# ---------------------------------------------------------------------------


def test_build_root_messages_child_ids_direct_entry_point(tmp_path):
    """T10: when the topological entry point has a process entry, it appears in child_ids_yaml."""
    nodes = [
        {"id": "N1", "description": "step A", "children": [{"target": "N2"}]},
        {"id": "N2", "description": "step B", "children": []},
    ]
    entry_ids = {"N1": "proc-n1-001", "N2": "proc-n2-001", "root": "root-001"}
    harness = _make_harness(tmp_path, nodes, entry_ids)
    msgs = harness._build_root_messages(source_text="src", briefs=[])
    content = msgs[0]["content"]
    # N1 is the entry point and has an entry → should appear
    assert "proc-n1-001" in content
    # N2 is not a direct child of root (it's a grandchild via N1)
    assert "proc-n2-001" not in content.split("child_entry_ids")[1].split("entry_ids 表")[0]


def test_build_root_messages_child_ids_bfs_through_decision_node(tmp_path):
    """T11: when the entry point has no process entry (decision node), BFS finds its children."""
    nodes = [
        # N1 is a decision node with no entry; N2, N3 are its children with entries
        {"id": "N1", "description": "decide", "children": [{"target": "N2"}, {"target": "N3"}]},
        {"id": "N2", "description": "action A", "children": []},
        {"id": "N3", "description": "action B", "children": []},
    ]
    entry_ids = {"N2": "proc-n2-001", "N3": "proc-n3-001", "root": "root-001"}
    harness = _make_harness(tmp_path, nodes, entry_ids)
    msgs = harness._build_root_messages(source_text="src", briefs=[])
    content = msgs[0]["content"]
    # N1 has no entry — BFS should find N2 and N3
    assert "proc-n2-001" in content
    assert "proc-n3-001" in content
    # "(no direct children found)" must NOT appear
    assert "no direct children found" not in content
