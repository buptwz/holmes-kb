"""Tests for kb/holmes/kb/agent/dag/formatter.py — dag_to_markdown, markdown_to_dag."""

from __future__ import annotations

import json

import pytest

from holmes.kb.agent.dag.formatter import (
    dag_from_json,
    dag_to_json,
    dag_to_markdown,
    markdown_to_dag,
)
from holmes.kb.agent.dag.schema import (
    Complexity,
    DAGEdge,
    DAGGraph,
    DAGNode,
    NodeType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_graph() -> DAGGraph:
    n1 = DAGNode(
        id="N1",
        description="检查电源指示灯",
        node_type=NodeType.human_observation,
        complexity=Complexity.simple,
        children=[
            DAGEdge(condition="不亮", target="N2"),
            DAGEdge(condition="红色闪烁", target="N3"),
        ],
    )
    n2 = DAGNode(
        id="N2",
        description="检查电源线连接",
        node_type=NodeType.human_observation,
        complexity=Complexity.simple,
        children=[DAGEdge(condition="松动", target="END")],
    )
    n3 = DAGNode(
        id="N3",
        description="固件修复流程",
        node_type=NodeType.remote_action,
        complexity=Complexity.process,
        section_heading="### 固件修复步骤",
        children=[
            DAGEdge(condition="修复成功", target="END"),
            DAGEdge(condition="修复失败", target="N4"),
        ],
    )
    n4 = DAGNode(
        id="N4",
        description="硬件更换流程",
        node_type=NodeType.remote_action,
        complexity=Complexity.process,
        section_heading="### 硬件更换",
        children=[DAGEdge(condition="更换完成", target="END")],
    )
    return DAGGraph(
        nodes=[n1, n2, n3, n4],
        title="硬件初始化失败",
        source_file="hardware-failure.md",
        generated="2026-06-24",
    )


# ---------------------------------------------------------------------------
# dag_to_markdown
# ---------------------------------------------------------------------------


def test_dag_to_markdown_contains_title():
    graph = _make_graph()
    md = dag_to_markdown(graph)
    assert "# 排查树：硬件初始化失败" in md


def test_dag_to_markdown_contains_source():
    graph = _make_graph()
    md = dag_to_markdown(graph)
    assert "hardware-failure.md" in md


def test_dag_to_markdown_contains_sections():
    graph = _make_graph()
    md = dag_to_markdown(graph)
    assert "## 文档摘要" in md
    assert "## 排查树概览" in md
    assert "## 节点详情" in md


def test_dag_to_markdown_contains_nodes():
    graph = _make_graph()
    md = dag_to_markdown(graph)
    assert "### N1 — 检查电源指示灯" in md
    assert "### N3 — 固件修复流程" in md


def test_dag_to_markdown_process_icon():
    graph = _make_graph()
    md = dag_to_markdown(graph)
    # process node N3 should have 🔧
    assert "### N3 — 固件修复流程 🔧" in md


def test_dag_to_markdown_section_heading():
    graph = _make_graph()
    md = dag_to_markdown(graph)
    assert '### 固件修复步骤' in md


def test_dag_to_markdown_edges():
    graph = _make_graph()
    md = dag_to_markdown(graph)
    assert "- 不亮 → **N2**" in md
    assert "- 红色闪烁 → **N3**" in md


# ---------------------------------------------------------------------------
# markdown_to_dag
# ---------------------------------------------------------------------------

_SAMPLE_DAG_MD = """\
# 排查树：硬件初始化失败

> source: hardware-failure.md
> generated: 2026-06-24
> 说明：可直接编辑

---

## 文档摘要

核心问题：设备无法初始化

---

## 排查树概览

硬件初始化失败
└── ...

---

## 节点详情

### N1 — 检查电源指示灯
complexity: simple
node_type: human_observation

- 不亮 → **N2**
- 红色闪烁 → **N3** 🔧

---

### N3 — 固件修复流程 🔧
complexity: process
node_type: remote_action
section_heading: "### 固件修复步骤"

- 修复成功 → **END**
- 修复失败 → **N4**

---

### N4 — 硬件更换流程 🔧
complexity: process
node_type: remote_action
section_heading: "### 硬件更换"

- 更换完成 → END

---

### N2 — 检查电源线连接
complexity: simple
node_type: human_observation

- END
"""


def test_markdown_to_dag_title():
    graph = markdown_to_dag(_SAMPLE_DAG_MD)
    assert graph.title == "硬件初始化失败"


def test_markdown_to_dag_source():
    graph = markdown_to_dag(_SAMPLE_DAG_MD)
    assert graph.source_file == "hardware-failure.md"


def test_markdown_to_dag_node_count():
    graph = markdown_to_dag(_SAMPLE_DAG_MD)
    assert len(graph.nodes) == 4


def test_markdown_to_dag_node_ids():
    graph = markdown_to_dag(_SAMPLE_DAG_MD)
    ids = {n.id for n in graph.nodes}
    assert ids == {"N1", "N2", "N3", "N4"}


def test_markdown_to_dag_complexity():
    graph = markdown_to_dag(_SAMPLE_DAG_MD)
    n3 = graph.node_by_id("N3")
    assert n3 is not None
    assert n3.complexity == Complexity.process


def test_markdown_to_dag_node_type():
    graph = markdown_to_dag(_SAMPLE_DAG_MD)
    n1 = graph.node_by_id("N1")
    assert n1 is not None
    assert n1.node_type == NodeType.human_observation


def test_markdown_to_dag_section_heading():
    graph = markdown_to_dag(_SAMPLE_DAG_MD)
    n3 = graph.node_by_id("N3")
    assert n3 is not None
    assert n3.section_heading == "### 固件修复步骤"


def test_markdown_to_dag_edges():
    graph = markdown_to_dag(_SAMPLE_DAG_MD)
    n1 = graph.node_by_id("N1")
    assert n1 is not None
    edge_targets = {e.target for e in n1.children}
    assert "N2" in edge_targets
    assert "N3" in edge_targets


def test_markdown_to_dag_missing_details_section():
    with pytest.raises(ValueError, match="Missing '## 节点详情'"):
        markdown_to_dag("# 排查树：test\n\n## 文档摘要\n\nno details")


# ---------------------------------------------------------------------------
# Round-trip: dag_to_markdown → markdown_to_dag
# ---------------------------------------------------------------------------


def test_round_trip_node_count():
    original = _make_graph()
    md = dag_to_markdown(original)
    restored = markdown_to_dag(md)
    assert len(restored.nodes) == len(original.nodes)


def test_round_trip_node_ids():
    original = _make_graph()
    md = dag_to_markdown(original)
    restored = markdown_to_dag(md)
    orig_ids = {n.id for n in original.nodes}
    rest_ids = {n.id for n in restored.nodes}
    assert orig_ids == rest_ids


def test_round_trip_complexity():
    original = _make_graph()
    md = dag_to_markdown(original)
    restored = markdown_to_dag(md)
    orig_n3 = original.node_by_id("N3")
    rest_n3 = restored.node_by_id("N3")
    assert orig_n3 is not None and rest_n3 is not None
    assert rest_n3.complexity == orig_n3.complexity


def test_round_trip_section_heading():
    original = _make_graph()
    md = dag_to_markdown(original)
    restored = markdown_to_dag(md)
    orig_n3 = original.node_by_id("N3")
    rest_n3 = restored.node_by_id("N3")
    assert rest_n3.section_heading == orig_n3.section_heading


# ---------------------------------------------------------------------------
# dag_to_json / dag_from_json round-trip
# ---------------------------------------------------------------------------


def test_json_round_trip():
    original = _make_graph()
    json_str = dag_to_json(original)
    data = json.loads(json_str)
    assert data["title"] == "硬件初始化失败"
    assert len(data["nodes"]) == 4


def test_json_round_trip_restore():
    original = _make_graph()
    json_str = dag_to_json(original)
    restored = dag_from_json(json_str)
    assert restored.title == original.title
    assert len(restored.nodes) == len(original.nodes)
    n3 = restored.node_by_id("N3")
    assert n3 is not None
    assert n3.section_heading == "### 固件修复步骤"


# ---------------------------------------------------------------------------
# TC-LR: line_range serialization / deserialization (TC-LR02/03)
# ---------------------------------------------------------------------------


def _make_node_with_line_range() -> DAGNode:
    return DAGNode(
        id="N1",
        description="firmware repair",
        node_type=NodeType.remote_action,
        complexity=Complexity.process,
        section_heading="### Firmware",
        line_range=(10, 25),
        children=[DAGEdge(condition="done", target="END")],
    )


def test_dag_to_markdown_line_range_present():
    node = _make_node_with_line_range()
    graph = DAGGraph(nodes=[node], title="T", source_file="t.md", generated="2026-06-25")
    md = dag_to_markdown(graph)
    assert "line_range: [10, 25]" in md


def test_dag_to_markdown_no_line_range_absent():
    node = DAGNode(
        id="N1",
        description="simple check",
        node_type=NodeType.human_observation,
        complexity=Complexity.simple,
        children=[DAGEdge(condition="done", target="END")],
    )
    graph = DAGGraph(nodes=[node], title="T", source_file="t.md", generated="2026-06-25")
    md = dag_to_markdown(graph)
    assert "line_range" not in md


def test_markdown_to_dag_parses_line_range():
    md = """\
# 排查树：T

> source: t.md
> generated: 2026-06-25
> 说明：test

---

## 文档摘要

test

---

## 排查树概览

test

---

## 节点详情

### N1 — firmware repair 🔧
complexity: process
node_type: remote_action
section_heading: "### Firmware"
line_range: [10, 25]

- done → END
"""
    graph = markdown_to_dag(md)
    n1 = graph.node_by_id("N1")
    assert n1 is not None
    assert n1.line_range == (10, 25)


def test_markdown_to_dag_no_line_range_is_none():
    md = """\
# 排查树：T

> source: t.md
> generated: 2026-06-25
> 说明：test

---

## 文档摘要

test

---

## 排查树概览

test

---

## 节点详情

### N1 — simple check
complexity: simple
node_type: human_observation

- done → END
"""
    graph = markdown_to_dag(md)
    n1 = graph.node_by_id("N1")
    assert n1 is not None
    assert n1.line_range is None


def test_round_trip_line_range():
    node = _make_node_with_line_range()
    graph = DAGGraph(nodes=[node], title="T", source_file="t.md", generated="2026-06-25")
    md = dag_to_markdown(graph)
    restored = markdown_to_dag(md)
    n1 = restored.node_by_id("N1")
    assert n1 is not None
    assert n1.line_range == (10, 25)


def test_json_round_trip_line_range():
    node = _make_node_with_line_range()
    graph = DAGGraph(nodes=[node], title="T", source_file="t.md", generated="2026-06-25")
    json_str = dag_to_json(graph)
    restored = dag_from_json(json_str)
    n1 = restored.node_by_id("N1")
    assert n1 is not None
    assert n1.line_range == (10, 25)


def test_json_round_trip_no_line_range_is_none():
    node = DAGNode(
        id="N1",
        description="simple",
        node_type=NodeType.human_observation,
        complexity=Complexity.simple,
        children=[DAGEdge(condition="done", target="END")],
    )
    graph = DAGGraph(nodes=[node], title="T", source_file="t.md", generated="2026-06-25")
    json_str = dag_to_json(graph)
    restored = dag_from_json(json_str)
    n1 = restored.node_by_id("N1")
    assert n1 is not None
    assert n1.line_range is None


# ---------------------------------------------------------------------------
# Backward compat: old "action" node_type → remote_action
# ---------------------------------------------------------------------------


def test_markdown_backward_compat_action_maps_to_remote_action():
    md = """\
# 排查树：Compat

> source: t.md
> generated: 2026-06-25
> 说明：test

---

## 文档摘要

test

---

## 排查树概览

test

---

## 节点详情

### N1 — legacy action node
complexity: simple
node_type: action

- done → END
"""
    graph = markdown_to_dag(md)
    n1 = graph.node_by_id("N1")
    assert n1 is not None
    assert n1.node_type == NodeType.remote_action


def test_json_backward_compat_action_maps_to_remote_action():
    import json as _json
    raw = _json.dumps({
        "title": "T", "source_file": "t.md", "generated": "2026-06-25",
        "nodes": [{
            "id": "N1", "description": "legacy", "node_type": "action",
            "complexity": "simple", "section_heading": None, "line_range": None,
            "is_end": False, "children": [],
        }],
    })
    graph = dag_from_json(raw)
    n1 = graph.node_by_id("N1")
    assert n1 is not None
    assert n1.node_type == NodeType.remote_action
