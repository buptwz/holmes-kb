"""DAG formatter: convert between .dag.md (human-readable) and DAGGraph (internal).

.dag.md is the user-editable file produced by Agent 1.  It has three sections:
  ## 文档摘要   — human summary of the document
  ## 排查树概览  — ASCII tree for visual review
  ## 节点详情   — structured node definitions (machine-parseable)

The parser (markdown_to_dag) is intentionally lenient: user edits may not
follow the exact format produced by dag_to_markdown, so regex patterns are
written to tolerate extra whitespace, omitted optional fields, and minor
formatting variations.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone


from holmes.kb.agent.dag.schema import (
    Complexity,
    DAGEdge,
    DAGGraph,
    DAGNode,
    NodeType,
)


# ---------------------------------------------------------------------------
# Serialise DAGGraph → .dag.md
# ---------------------------------------------------------------------------

_DAG_MD_HEADER = """\
# 排查树：{title}

> source: {source_file}
> generated: {generated}
> 说明：可直接编辑任意内容后运行 holmes import --resume
>       不需要修改则运行 holmes import --resume --skip-edit

---

"""

_SECTION_SUMMARY = "## 文档摘要\n\n"
_SECTION_OVERVIEW = "\n\n---\n\n## 排查树概览\n\n"
_SECTION_DETAILS = "\n\n---\n\n## 节点详情\n\n"


def dag_to_markdown(graph: DAGGraph, summary: str = "", overview: str = "") -> str:
    """Serialise a DAGGraph to .dag.md format.

    Args:
        graph: The DAG to serialise.
        summary: Optional 文档摘要 text (free-form prose).
        overview: Optional 排查树概览 ASCII tree text.

    Returns:
        Complete .dag.md content as a string.
    """
    parts: list[str] = []

    # Header
    parts.append(
        _DAG_MD_HEADER.format(
            title=graph.title,
            source_file=graph.source_file or "(unknown)",
            generated=graph.generated,
        )
    )

    # 文档摘要
    parts.append(_SECTION_SUMMARY)
    parts.append(summary or "(待填写)")

    # 排查树概览
    parts.append(_SECTION_OVERVIEW)
    if overview:
        parts.append(overview)
    else:
        parts.append(_build_ascii_tree(graph))

    # 节点详情
    parts.append(_SECTION_DETAILS)
    node_blocks = []
    for node in graph.nodes:
        node_blocks.append(_node_to_block(node))
    parts.append("\n\n---\n\n".join(node_blocks))

    return "".join(parts)


def _node_to_block(node: DAGNode) -> str:
    """Serialise one DAGNode to its ### block."""
    lines: list[str] = []
    icon = " 🔧" if node.complexity == Complexity.process and not node.is_end else ""
    lines.append(f"### {node.id} — {node.description}{icon}")
    lines.append(f"complexity: {node.complexity.value}")
    lines.append(f"node_type: {node.node_type.value}")
    if node.section_heading:
        lines.append(f'section_heading: "{node.section_heading}"')
    lines.append("")

    if node.is_end:
        lines.append("- END")
    else:
        for edge in node.children:
            back = " [back_edge]" if edge.is_back_edge else ""
            lines.append(f"- {edge.condition} → **{edge.target}**{back}")

    return "\n".join(lines)


def _build_ascii_tree(graph: DAGGraph) -> str:
    """Build a simple ASCII tree representation from the graph.

    Returns a multi-line string.  Only includes structural info (IDs + descriptions).
    """
    roots = graph.root_nodes()
    if not roots:
        return "(no root nodes)"

    lines: list[str] = []
    visited: set[str] = set()

    def _render(node: DAGNode, prefix: str, is_last: bool) -> None:
        if node.id in visited:
            lines.append(f"{prefix}{'└── ' if is_last else '├── '}[{node.id}] (→ already shown)")
            return
        visited.add(node.id)
        icon = " 🔧" if node.complexity == Complexity.process else ""
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{node.description}{icon}")
        child_prefix = prefix + ("    " if is_last else "│   ")
        non_back = [e for e in node.children if not e.is_back_edge]
        for i, edge in enumerate(non_back):
            child = graph.node_by_id(edge.target)
            if edge.target == "END" or (child and child.is_end):
                edge_last = (i == len(non_back) - 1)
                conn = "└── " if edge_last else "├── "
                lines.append(f"{child_prefix}{conn}{edge.condition} → END")
            elif child:
                _render(child, child_prefix, i == len(non_back) - 1)

    lines.append(graph.title)
    for i, root in enumerate(roots):
        _render(root, "", i == len(roots) - 1)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parse .dag.md → DAGGraph
# ---------------------------------------------------------------------------

# Patterns for parsing node blocks
_RE_NODE_HEADER = re.compile(
    r"^###\s+(N\w+)\s+[—\-]\s+(.+?)(?:\s*🔧)?\s*$", re.MULTILINE
)
_RE_COMPLEXITY = re.compile(r"^complexity:\s*(\w+)", re.MULTILINE)
_RE_NODE_TYPE = re.compile(r"^node_type:\s*(\w+)", re.MULTILINE)
_RE_SECTION_HEADING = re.compile(r'^section_heading:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
_RE_EDGE = re.compile(
    r"^-\s+(.+?)\s+(?:→|->)\s+\*\*([\w\d]+)\*\*(?:\s*🔧)?(?:\s*\[back_edge\])?\s*$",
    re.MULTILINE,
)
_RE_EDGE_END = re.compile(r"^-\s+(.+?)\s+(?:→|->)\s+END\b", re.MULTILINE)
_RE_PLAIN_END = re.compile(r"^-\s+END\s*$", re.MULTILINE)
_RE_BACK_EDGE = re.compile(r"\[back_edge\]")

_RE_TITLE = re.compile(r"^#\s+排查树[：:]\s*(.+?)\s*$", re.MULTILINE)
_RE_SOURCE = re.compile(r"^>\s+source:\s*(.+?)\s*$", re.MULTILINE)
_RE_GENERATED = re.compile(r"^>\s+generated:\s*(.+?)\s*$", re.MULTILINE)
_RE_DETAILS_SPLIT = re.compile(r"##\s+节点详情")


def markdown_to_dag(text: str) -> DAGGraph:
    """Parse a .dag.md string into a DAGGraph.

    Lenient parser — tolerates minor formatting variations from user editing.

    Args:
        text: Full .dag.md content.

    Returns:
        Parsed DAGGraph.

    Raises:
        ValueError: If the text cannot be parsed into a valid graph structure.
    """
    # Extract header metadata
    title_m = _RE_TITLE.search(text)
    title = title_m.group(1).strip() if title_m else "Unknown"

    source_m = _RE_SOURCE.search(text)
    source_file = source_m.group(1).strip() if source_m else ""

    generated_m = _RE_GENERATED.search(text)
    generated = generated_m.group(1).strip() if generated_m else _today()

    # Split off the 节点详情 section
    parts = _RE_DETAILS_SPLIT.split(text, maxsplit=1)
    if len(parts) < 2:
        raise ValueError("Missing '## 节点详情' section in .dag.md")
    details_section = parts[1]

    # Split into individual node blocks by ### headers
    node_blocks = _split_node_blocks(details_section)
    if not node_blocks:
        raise ValueError("No node blocks found in ## 节点详情 section")

    nodes: list[DAGNode] = []
    for block_id, block_text in node_blocks:
        node = _parse_node_block(block_id, block_text)
        nodes.append(node)

    return DAGGraph(
        nodes=nodes,
        title=title,
        source_file=source_file,
        generated=generated,
    )


def _split_node_blocks(details_text: str) -> list[tuple[str, str]]:
    """Split the 节点详情 section into (node_id, block_text) pairs."""
    blocks: list[tuple[str, str]] = []
    # Find all node header positions
    matches = list(_RE_NODE_HEADER.finditer(details_text))
    for i, m in enumerate(matches):
        node_id = m.group(1).strip()
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(details_text)
        block_text = details_text[start:end]
        blocks.append((node_id, block_text))
    return blocks


def _parse_node_block(node_id: str, block_text: str) -> DAGNode:
    """Parse a single ### node block into a DAGNode."""
    # Header line: description
    header_m = _RE_NODE_HEADER.search(block_text)
    description = header_m.group(2).strip() if header_m else node_id

    # complexity
    complexity_m = _RE_COMPLEXITY.search(block_text)
    complexity_val = complexity_m.group(1).strip().lower() if complexity_m else "simple"
    try:
        complexity = Complexity(complexity_val)
    except ValueError:
        complexity = Complexity.simple

    # node_type
    node_type_m = _RE_NODE_TYPE.search(block_text)
    node_type_val = node_type_m.group(1).strip().lower() if node_type_m else "action"
    try:
        node_type = NodeType(node_type_val)
    except ValueError:
        node_type = NodeType.action

    # section_heading (optional)
    section_m = _RE_SECTION_HEADING.search(block_text)
    section_heading = section_m.group(1).strip() if section_m else None

    # is_end: explicit END marker
    is_end = bool(_RE_PLAIN_END.search(block_text))

    # edges: "- condition → **target**"
    children: list[DAGEdge] = []
    seen_targets: set[str] = set()

    # Normal edges to named targets
    for em in _RE_EDGE.finditer(block_text):
        condition = em.group(1).strip()
        target = em.group(2).strip()
        is_back = bool(_RE_BACK_EDGE.search(em.group(0)))
        if target not in seen_targets:
            children.append(DAGEdge(condition=condition, target=target, is_back_edge=is_back))
            seen_targets.add(target)

    # Edges terminating at END (not a named node target, just a signal)
    for em in _RE_EDGE_END.finditer(block_text):
        condition = em.group(1).strip()
        children.append(DAGEdge(condition=condition, target="END"))

    return DAGNode(
        id=node_id,
        description=description,
        node_type=node_type,
        complexity=complexity,
        section_heading=section_heading,
        is_end=is_end,
        children=children,
    )


# ---------------------------------------------------------------------------
# Serialise DAGGraph → .dag.json (internal machine-readable format)
# ---------------------------------------------------------------------------


def dag_to_json(graph: DAGGraph) -> str:
    """Serialise a DAGGraph to a JSON string (.dag.json format)."""
    data = {
        "title": graph.title,
        "source_file": graph.source_file,
        "generated": graph.generated,
        "nodes": [
            {
                "id": n.id,
                "description": n.description,
                "node_type": n.node_type.value,
                "complexity": n.complexity.value,
                "section_heading": n.section_heading,
                "is_end": n.is_end,
                "children": [
                    {
                        "condition": e.condition,
                        "target": e.target,
                        "is_back_edge": e.is_back_edge,
                    }
                    for e in n.children
                ],
            }
            for n in graph.nodes
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def dag_from_json(text: str) -> DAGGraph:
    """Deserialise a DAGGraph from a .dag.json string."""
    data = json.loads(text)
    nodes = []
    for nd in data.get("nodes", []):
        children = [
            DAGEdge(
                condition=e["condition"],
                target=e["target"],
                is_back_edge=e.get("is_back_edge", False),
            )
            for e in nd.get("children", [])
        ]
        try:
            nt = NodeType(nd.get("node_type", "action"))
        except ValueError:
            nt = NodeType.action
        try:
            cx = Complexity(nd.get("complexity", "simple"))
        except ValueError:
            cx = Complexity.simple
        nodes.append(
            DAGNode(
                id=nd["id"],
                description=nd.get("description", ""),
                node_type=nt,
                complexity=cx,
                section_heading=nd.get("section_heading"),
                is_end=nd.get("is_end", False),
                children=children,
            )
        )
    return DAGGraph(
        nodes=nodes,
        title=data.get("title", ""),
        source_file=data.get("source_file", ""),
        generated=data.get("generated", _today()),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
