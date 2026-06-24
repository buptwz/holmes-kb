"""Agent 1 domain-specific tools: write_dag, read_dag, output_dag.

These three tools are used exclusively by Agent 1 (DAG extraction harness).
They operate on the _import-state/ directory under kb_root.

Tool context dict (ctx) keys required by these functions:
    state_dir (Path): kb_root / "_import-state/"
    source_hash (str): 16-char SHA-256 prefix

Each function follows the same calling convention as existing holmes tools:
    handler(ctx: dict, tool_input: dict) -> dict
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from holmes.kb.atomic import atomic_write
from holmes.kb.agent.dag.formatter import dag_to_json, markdown_to_dag
from holmes.kb.agent.dag.schema import Complexity, DAGGraph


# ---------------------------------------------------------------------------
# Tool handler functions
# ---------------------------------------------------------------------------


def tool_write_dag(ctx: dict[str, Any], tool_input: dict[str, Any]) -> dict[str, Any]:
    """Write or overwrite the entire .dag.md file.

    Input:
        content (str): Complete .dag.md text (all three sections).

    Returns:
        success (bool): True on success.
        path (str): Relative path of the written file.
    """
    content = tool_input.get("content", "")
    if not content.strip():
        return {"error": "write_dag: content must not be empty"}

    state_dir: Path = ctx["state_dir"]
    source_hash: str = ctx["source_hash"]
    dag_md_path = state_dir / f"{source_hash}.dag.md"

    try:
        atomic_write(dag_md_path, content)
    except OSError as exc:
        return {"error": f"write_dag: write failed: {exc}"}

    return {"success": True, "path": dag_md_path.name}


def tool_read_dag(ctx: dict[str, Any], tool_input: dict[str, Any]) -> dict[str, Any]:
    """Read the current .dag.md content.

    No input parameters required.

    Returns:
        content (str): Current .dag.md text.
        error (str): Error message if the file doesn't exist yet.
    """
    state_dir: Path = ctx["state_dir"]
    source_hash: str = ctx["source_hash"]
    dag_md_path = state_dir / f"{source_hash}.dag.md"

    if not dag_md_path.exists():
        return {"error": "read_dag: no DAG written yet — call write_dag first"}

    try:
        content = dag_md_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": f"read_dag: read failed: {exc}"}

    return {"content": content}


def tool_output_dag(ctx: dict[str, Any], tool_input: dict[str, Any]) -> dict[str, Any]:
    """Validate .dag.md, generate .dag.json, and signal loop termination.

    No input parameters required.

    Validation rules (any failure returns error, agent must fix and retry):
        1. At least one root node (node not referenced by any structural edge)
        2. All edge targets exist in the node list (no dangling edges)
        3. No cycles (back-edges excluded from cycle detection)
        4. All process nodes have section_heading or non-empty description
        5. All non-END nodes have at least one outgoing edge

    Returns on success:
        _terminate (bool): True — signals harness to exit the loop.
        success (bool): True.
        nodes (int): Total node count.
        process_nodes (int): Process node count.
        dag_json_path (str): Path to generated .dag.json file.

    Returns on validation failure:
        error (str): Description of the first rule that failed.
    """
    state_dir: Path = ctx["state_dir"]
    source_hash: str = ctx["source_hash"]
    dag_md_path = state_dir / f"{source_hash}.dag.md"
    dag_json_path = state_dir / f"{source_hash}.dag.json"

    if not dag_md_path.exists():
        return {"error": "output_dag: no DAG written yet — call write_dag first"}

    # Parse .dag.md → DAGGraph
    try:
        content = dag_md_path.read_text(encoding="utf-8")
        graph = markdown_to_dag(content)
    except ValueError as exc:
        return {"error": f"output_dag: DAG parsing failed: {exc}"}
    except OSError as exc:
        return {"error": f"output_dag: read failed: {exc}"}

    # Run 5 validation rules
    validation_error = _validate_dag(graph)
    if validation_error:
        return {"error": validation_error}

    # Write .dag.json
    try:
        atomic_write(dag_json_path, dag_to_json(graph))
    except OSError as exc:
        return {"error": f"output_dag: failed to write .dag.json: {exc}"}

    # Store parsed graph in context for post-loop use
    ctx["_dag_graph"] = graph

    process_count = sum(1 for n in graph.nodes if n.complexity == Complexity.process)
    return {
        "_terminate": True,
        "success": True,
        "nodes": len(graph.nodes),
        "process_nodes": process_count,
        "dag_json_path": dag_json_path.name,
    }


# ---------------------------------------------------------------------------
# Validation — 5 rules
# ---------------------------------------------------------------------------


def _validate_dag(graph: DAGGraph) -> str:
    """Validate a DAGGraph against 5 structural rules.

    Returns:
        Empty string if all rules pass.
        Human-readable error string for the first failing rule.
    """
    nodes_by_id: dict[str, Any] = {n.id: n for n in graph.nodes}

    # Rule 1: At least one root node
    referenced: set[str] = set()
    for n in graph.nodes:
        for edge in n.children:
            if not edge.is_back_edge:
                referenced.add(edge.target)
    root_nodes = [n for n in graph.nodes if n.id not in referenced]
    if not root_nodes:
        return "至少存在一个根节点（无 parent 的节点）：当前所有节点都被引用，没有入口节点"

    # Rule 2: No dangling edges (all targets must exist or be "END")
    for n in graph.nodes:
        for edge in n.children:
            target = edge.target
            if target == "END":
                continue
            if target not in nodes_by_id:
                return (
                    f"悬空边：节点 {n.id} 引用了不存在的目标 {target}。"
                    f"请检查 N{target} 是否已在节点详情中定义。"
                )

    # Rule 3: No cycles (excluding back-edges)
    cycle_path = _detect_cycle(graph, nodes_by_id)
    if cycle_path:
        return (
            f"循环引用：{cycle_path}。"
            f"请将回路中表示'返回/重试'语义的那条边改为 [back_edge]，"
            f"并在节点 description 中注明（例：若失败可重试，回到 N1）。"
        )

    # Rule 4: All process nodes have section_heading or non-empty description
    for n in graph.nodes:
        if n.complexity == Complexity.process:
            has_heading = bool(n.section_heading and n.section_heading.strip())
            has_desc = bool(n.description and n.description.strip())
            if not has_heading and not has_desc:
                return (
                    f"Process 节点 {n.id} 既无 section_heading 也无有效 description。"
                    f"请添加 section_heading 或完善 description，供 Agent 2 定位原文内容。"
                )

    # Rule 5: All non-END nodes have at least one outgoing edge
    for n in graph.nodes:
        if n.is_end:
            continue
        all_edges = n.children
        if not all_edges:
            return (
                f"节点 {n.id} 无出边且未标记为 END。"
                f"请添加出边（- 条件 → **目标节点**）或将节点标记为终止（- END）。"
            )

    return ""  # all rules pass


def _detect_cycle(graph: DAGGraph, nodes_by_id: dict[str, Any]) -> str:
    """Detect cycles in the graph using DFS.

    Back-edges (edge.is_back_edge=True) are excluded from traversal.

    Returns:
        Cycle path string like "N3 → N8 → N3" if a cycle exists.
        Empty string if no cycle found.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n.id: WHITE for n in graph.nodes}
    parent: dict[str, str] = {}

    def dfs(node_id: str) -> str:
        color[node_id] = GRAY
        node = nodes_by_id.get(node_id)
        if node is None:
            color[node_id] = BLACK
            return ""
        for edge in node.children:
            if edge.is_back_edge or edge.target == "END":
                continue
            target = edge.target
            if target not in nodes_by_id:
                continue
            if color.get(target, WHITE) == GRAY:
                # Reconstruct cycle path
                path = [target, node_id]
                cur = node_id
                while cur in parent and parent[cur] != target:
                    cur = parent[cur]
                    path.append(cur)
                path.append(target)
                path.reverse()
                return " → ".join(path)
            if color.get(target, WHITE) == WHITE:
                parent[target] = node_id
                result = dfs(target)
                if result:
                    return result
        color[node_id] = BLACK
        return ""

    for n in graph.nodes:
        if color[n.id] == WHITE:
            result = dfs(n.id)
            if result:
                return result
    return ""


# ---------------------------------------------------------------------------
# Read / Grep tools for Agent 1 (file-based, works on source doc and dag files)
# ---------------------------------------------------------------------------


def tool_read(ctx: dict[str, Any], tool_input: dict[str, Any]) -> dict[str, Any]:
    """Read lines from a file.

    Input:
        path (str): File path — use source_file value for the source document.
        offset (int): Start line number (0-based, default 0).
        limit (int): Max lines to return (default 100).

    Returns:
        content (str): Requested lines joined by newlines.
        start_line (int): Actual start line.
        end_line (int): Actual end line (exclusive).
        total_lines (int): Total lines in file.
    """
    path_str = tool_input.get("path", "")
    offset = int(tool_input.get("offset", 0))
    limit = int(tool_input.get("limit", 100))
    limit = min(limit, 500)  # safety cap

    resolved = _resolve_file(ctx, path_str)
    if resolved is None:
        return {"error": f"Read: cannot find file '{path_str}'"}

    if isinstance(resolved, str):
        # In-memory source text
        lines = resolved.splitlines()
    else:
        try:
            lines = resolved.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return {"error": f"Read: {exc}"}

    total = len(lines)
    start = max(0, offset)
    end = min(total, start + limit)
    return {
        "content": "\n".join(lines[start:end]),
        "start_line": start,
        "end_line": end,
        "total_lines": total,
    }


def tool_grep(ctx: dict[str, Any], tool_input: dict[str, Any]) -> dict[str, Any]:
    """Search for a regex pattern in a file.

    Input:
        pattern (str): Python regular expression.
        path (str): File path — use source_file value for the source document.
        context_lines (int): Lines of context above/below each match (default 2).

    Returns:
        matches (list): Each item has {line_num, line, context_before, context_after}.
        total_matches (int): Number of matches found.
    """
    pattern = tool_input.get("pattern", "")
    path_str = tool_input.get("path", "")
    context_lines = int(tool_input.get("context_lines", 2))
    context_lines = min(context_lines, 10)

    if not pattern:
        return {"error": "Grep: pattern must not be empty"}

    resolved = _resolve_file(ctx, path_str)
    if resolved is None:
        return {"error": f"Grep: cannot find file '{path_str}'"}

    if isinstance(resolved, str):
        lines = resolved.splitlines()
    else:
        try:
            lines = resolved.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return {"error": f"Grep: {exc}"}

    try:
        compiled = re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        return {"error": f"Grep: invalid pattern: {exc}"}

    matches = []
    for i, line in enumerate(lines):
        if compiled.search(line):
            before_start = max(0, i - context_lines)
            after_end = min(len(lines), i + context_lines + 1)
            matches.append({
                "line_num": i,
                "line": line,
                "context_before": lines[before_start:i],
                "context_after": lines[i + 1:after_end],
            })
            if len(matches) >= 200:  # safety cap
                break

    return {"matches": matches, "total_matches": len(matches)}


def _resolve_file(ctx: dict[str, Any], path_str: str) -> "str | Path | None":
    """Resolve a file path for Read/Grep tools.

    Returns:
        str — the in-memory source_text (when path matches source file)
        Path — filesystem path (for _import-state/ files or other files)
        None — cannot resolve
    """
    source_file: str = ctx.get("source_file", "")
    source_text: str = ctx.get("source_text", "")
    kb_root: Path = ctx.get("kb_root", Path("."))
    state_dir: Path = ctx.get("state_dir", kb_root / "_import-state")

    # Special sentinel for source document
    if path_str in ("source", "source_document"):
        return source_text or None

    # Match by source_file name or path
    if source_file:
        # Check if path_str matches the source_file path
        source_path = Path(source_file)
        query_path = Path(path_str)
        if (
            query_path.name == source_path.name
            or str(query_path) == str(source_path)
            or path_str == source_file
        ):
            # Try filesystem first, fall back to in-memory
            candidate = kb_root / source_file
            if candidate.exists():
                return candidate
            return source_text or None

    # Try absolute path
    p = Path(path_str)
    if p.is_absolute() and p.exists():
        return p

    # Try relative to kb_root
    candidate = kb_root / path_str
    if candidate.exists():
        return candidate

    # Try relative to state_dir
    candidate2 = state_dir / path_str
    if candidate2.exists():
        return candidate2

    # Last resort: in-memory source_text for any unrecognised path
    if source_text:
        return source_text

    return None


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic input_schema format)
# ---------------------------------------------------------------------------

TOOLS1_DEFINITIONS: list[dict] = [
    {
        "name": "Read",
        "description": (
            "Read lines from a file. Use the source document path for the source, "
            "or use 'source' as a shortcut. Returns line content with line numbers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "offset": {"type": "integer", "description": "Start line (0-based, default 0)"},
                "limit": {"type": "integer", "description": "Max lines to return (default 100)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "Grep",
        "description": (
            "Search for a regex pattern in a file. Returns matching lines with context. "
            "Use source document path or 'source' for the source document."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python regex pattern"},
                "path": {"type": "string", "description": "File path to search"},
                "context_lines": {
                    "type": "integer",
                    "description": "Lines of context around each match (default 2)",
                },
            },
            "required": ["pattern", "path"],
        },
    },
    {
        "name": "write_dag",
        "description": (
            "Write or overwrite the entire .dag.md file. "
            "Call this with the complete three-section content. "
            "Each call completely replaces the previous content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Complete .dag.md content (all three sections)",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "read_dag",
        "description": "Read the current .dag.md content for self-review. No parameters required.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "output_dag",
        "description": (
            "Validate the current .dag.md, generate .dag.json, and terminate the loop. "
            "Only call this after the self-check checklist is complete. "
            "Returns an error if validation fails — fix the issue and retry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

# Handler map: name → function
TOOLS1_HANDLERS: dict[str, Any] = {
    "Read": tool_read,
    "Grep": tool_grep,
    "write_dag": tool_write_dag,
    "read_dag": tool_read_dag,
    "output_dag": tool_output_dag,
}
