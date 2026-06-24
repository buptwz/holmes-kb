"""Step 2.5 — DAG parse normalization and cross-validation.

Runs after Agent 1 completes (and after optional user editing of .dag.md).
Responsibilities:
  1. Re-parse .dag.md with lenient parser
  2. LLM-based recognition of natural language edits
  3. Programmatic cross-validation (section_heading Grep against source)
  4. Structural error detection (dangling edges, cycles)
  5. Merged single-screen display → one user confirmation
  6. Complexity self-assessment tips (non-blocking)

ParseResult is returned for harness integration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import click

from holmes.kb.agent.dag.formatter import markdown_to_dag
from holmes.kb.agent.dag.schema import Complexity, DAGGraph
from holmes.kb.agent.dag.tools1 import _validate_dag


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ParseResult:
    """Result of Step 2.5 parse + validation.

    Attributes:
        recognized_edits: Human-readable descriptions of recognized user changes.
        uncertain_items: Items the system could not confidently interpret (⚠).
        validation_errors: Structural errors (dangling nodes, cycles) that
            block Agent 2 from starting.
        validation_warnings: Non-blocking warnings (e.g. section_heading not
            found in source text).
        dag_graph: Re-parsed DAGGraph after normalization, or None on structural error.
        process_count: Number of process nodes in the parsed graph.
        total_count: Total node count.
    """

    recognized_edits: list[str] = field(default_factory=list)
    uncertain_items: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    dag_graph: Optional[DAGGraph] = None
    process_count: int = 0
    total_count: int = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_step25(
    dag_md_path: Path,
    source_text: str,
    provider: Any,
    cfg: Any,
    no_interactive: bool = False,
) -> ParseResult:
    """Execute Step 2.5: parse, validate, display, and confirm.

    Args:
        dag_md_path: Path to the .dag.md file (possibly user-edited).
        source_text: Full, untruncated source document text.
        provider: LLMProvider instance for natural-language recognition call.
        cfg: HolmesConfig (model, username, etc.).
        no_interactive: If True, auto-accept the confirmation prompt.

    Returns:
        ``ParseResult`` — caller should check ``validation_errors`` before
        launching Agent 2; non-empty errors mean Agent 2 must not start.
    """
    result = ParseResult()

    # --- 1. Re-parse .dag.md ---
    if not dag_md_path.exists():
        result.validation_errors.append(
            f"step25: .dag.md not found: {dag_md_path}"
        )
        return result

    try:
        dag_content = dag_md_path.read_text(encoding="utf-8")
        graph = markdown_to_dag(dag_content)
        result.dag_graph = graph
        result.total_count = len(graph.nodes)
        result.process_count = sum(
            1 for n in graph.nodes if n.complexity == Complexity.process
        )
    except (ValueError, OSError) as exc:
        result.validation_errors.append(f"step25: DAG parsing failed: {exc}")
        return result

    # --- 2. Structural validation (programmatic) ---
    struct_error = _validate_dag(graph)
    if struct_error:
        result.validation_errors.append(struct_error)
        # Still attempt cross-validation on valid subset, but don't proceed.

    # --- 3. Cross-validation: Grep section_headings in source ---
    _run_section_validation(graph, source_text, result)

    # --- 4. LLM natural-language recognition (best-effort) ---
    if not result.validation_errors:
        _run_llm_recognition(dag_content, source_text, provider, cfg, result)

    return result


def display_step25_result(
    parse_result: ParseResult,
    no_interactive: bool = False,
) -> bool:
    """Display Step 2.5 results and prompt for user confirmation.

    Args:
        parse_result: Result from ``run_step25()``.
        no_interactive: If True, auto-accept without prompting.

    Returns:
        ``True`` if user confirms and Agent 2 should proceed.
        ``False`` if there are structural errors or user declines.
    """
    print("\n解析 + 验证完成：")
    print()

    # Recognized edits
    if parse_result.recognized_edits or parse_result.uncertain_items:
        print("  编辑识别：")
        for edit in parse_result.recognized_edits:
            print(f"    ✓ {edit}")
        for item in parse_result.uncertain_items:
            print(f"    ⚠ 不确定：{item}")
        print()

    # Content validation
    print("  内容验证：")
    if parse_result.validation_warnings:
        for w in parse_result.validation_warnings:
            print(f"    ⚠ {w}")
    else:
        n = parse_result.total_count
        print(f"    ✓ 全部 {n} 个节点结构验证通过")
    print()

    # Structural errors — block Agent 2
    if parse_result.validation_errors:
        print("解析失败，无法继续：")
        for err in parse_result.validation_errors:
            print(f"  ✗ {err}")
        print()
        print("请修改 .dag.md 后选择 [1] 重新编辑，或运行 holmes import --resume")
        return False

    # Summary
    pitfall_count = 1
    entry_count = pitfall_count + parse_result.process_count
    print(
        f"  共 {parse_result.total_count} 个节点，"
        f"将生成 {entry_count} 个 entries"
        f"（{pitfall_count} pitfall + {parse_result.process_count} process）"
    )
    print()

    # Confirmation
    if no_interactive:
        print("[自动] 已确认，开始生成。")
        return True

    try:
        answer = click.prompt(
            "确认并开始生成？",
            default="Y",
            prompt_suffix=" [Y / 需要修改] ",
        ).strip()
    except click.exceptions.Abort:
        answer = "N"

    if answer.upper() in ("Y", "YES", ""):
        return True

    print("请修改 .dag.md 后运行 holmes import --resume")
    return False


def display_complexity_tips(parse_result: ParseResult) -> None:
    """Print non-blocking complexity self-assessment tips after confirmation.

    Args:
        parse_result: Parsed DAG statistics.
    """
    tips: list[str] = []

    if parse_result.total_count > 20:
        tips.append("链路较长（>20 个节点），建议分阶段组织文档")
    if parse_result.process_count > 10:
        tips.append(f"将生成较多 entries（{parse_result.process_count} process），建议 review 关联关系")

    # Compute max nesting depth.
    if parse_result.dag_graph:
        depth = _max_depth(parse_result.dag_graph)
        if depth > 4:
            tips.append(f"嵌套较深（深度 {depth}），agent 导航可能受影响")

    if tips:
        print()
        print("提示（不影响生成流程）：")
        for tip in tips:
            print(f"  • {tip}")
        print()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_section_validation(
    graph: DAGGraph,
    source_text: str,
    result: ParseResult,
) -> None:
    """Grep each process node's section_heading in source_text.

    Adds warnings to result.validation_warnings for missing sections.
    """
    source_lines = source_text.splitlines()
    for node in graph.nodes:
        if node.complexity != Complexity.process:
            continue
        if not node.section_heading:
            continue  # null heading handled by Agent 2 fallback
        heading = node.section_heading.strip()
        # Simple substring search (case-insensitive) — not full Grep.
        found = any(heading.lower() in line.lower() for line in source_lines)
        if not found:
            result.validation_warnings.append(
                f"{node.id} 的 section \"{heading}\" 在原文中找不到"
            )


def _run_llm_recognition(
    dag_content: str,
    source_text: str,
    provider: Any,
    cfg: Any,
    result: ParseResult,
) -> None:
    """Use a single LLM call to identify natural-language edits in the DAG.

    On failure, silently skips (best-effort) — validation results are still shown.
    """
    if provider is None:
        return

    system = (
        "你是一个 DAG 格式分析助手。分析用户提供的 .dag.md 内容，"
        "识别其中可能的自然语言写法并返回 JSON 格式结果。"
    )
    user_msg = (
        f"以下是用户编辑的 .dag.md 内容，请识别其中的自然语言写法并以 JSON 返回：\n\n"
        f"```\n{dag_content[:3000]}\n```\n\n"
        "返回格式：\n"
        "{\"recognized\": [\"识别结果1\", ...], \"uncertain\": [\"不确定项1\", ...]}"
    )

    try:
        _stop, _tool_calls, messages, _usage = provider.complete(
            messages=[{"role": "user", "content": user_msg}],
            system=system,
            model=cfg.model,
            max_tokens=512,
            tools=[],
        )
        # Extract last assistant message text.
        last_msg = messages[-1] if messages else {}
        content = last_msg.get("content", "") if isinstance(last_msg, dict) else ""
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )

        # Parse JSON from response.
        import json
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            result.recognized_edits.extend(data.get("recognized", []))
            result.uncertain_items.extend(data.get("uncertain", []))
    except Exception:  # noqa: BLE001
        pass  # LLM recognition is best-effort


def _max_depth(graph: DAGGraph) -> int:
    """Compute maximum nesting depth of the DAG (excluding back-edges)."""
    memo: dict[str, int] = {}

    def _depth(node_id: str, visiting: set[str]) -> int:
        if node_id in memo:
            return memo[node_id]
        if node_id in visiting:
            return 0  # back-edge
        node = graph.node_by_id(node_id)
        if node is None:
            return 0
        visiting.add(node_id)
        children = [
            e.target for e in node.children
            if not e.is_back_edge and e.target != "END"
        ]
        child_depths = [_depth(c, visiting) for c in children]
        result_depth = 1 + (max(child_depths) if child_depths else 0)
        visiting.discard(node_id)
        memo[node_id] = result_depth
        return result_depth

    roots = graph.root_nodes()
    if not roots:
        return 0
    return max(_depth(r.id, set()) for r in roots)
