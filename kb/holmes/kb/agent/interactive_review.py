"""Interactive review gates for the import pipeline.

Three review points:
1. review_knowledge_points — after Reader, before Summarizer (confirm KP list)
2. review_summaries — after Summarizer, before Generator (confirm extracted content)
3. review_drafts — after Generator, before write (confirm formatted output)
"""

from __future__ import annotations

from typing import Any, Optional

import click

from holmes.kb.agent.knowledge_map import KnowledgeMap
from holmes.kb.agent.report import ImportReport


def review_knowledge_points(
    km: KnowledgeMap,
    no_interactive: bool,
    report: ImportReport,
) -> KnowledgeMap:
    """Display KP manifest and let user confirm, skip, or cancel.

    In non-interactive mode, low-confidence KPs are logged as warnings
    but all are accepted.

    Returns:
        The (possibly filtered) KnowledgeMap.
    """
    if no_interactive:
        for kp in km.knowledge_points:
            if kp.confidence < 0.6:
                report.warnings.append(
                    f"{kp.id}: low confidence ({kp.confidence:.0%})"
                )
        return km

    if not km.knowledge_points:
        return km

    print(f"\n检测到 {len(km.knowledge_points)} 个知识点：")
    for kp in km.knowledge_points:
        parent = f"  └── (子 of {kp.parent_kp})" if kp.parent_kp else ""
        conf = f" ({kp.confidence:.0%})" if kp.confidence < 0.9 else ""
        chars = kp.section_end - kp.section_start
        print(
            f"  {kp.id} [{kp.type_hint:10s}] "
            f"{kp.description[:60]}{conf} ({chars} chars){parent}"
        )

    choice = click.prompt(
        "\n[1] 确认 [2] 跳过某些 [3] 取消", default="1"
    ).strip()

    if choice == "3":
        km.knowledge_points.clear()
        report.warnings.append("用户取消了 import")
        return km

    if choice == "2":
        skip_input = click.prompt(
            "输入要跳过的 KP id（逗号分隔）", default=""
        ).strip()
        if skip_input:
            skip_set = {s.strip() for s in skip_input.split(",") if s.strip()}
            before = len(km.knowledge_points)
            km.knowledge_points = [
                kp for kp in km.knowledge_points if kp.id not in skip_set
            ]
            skipped = before - len(km.knowledge_points)
            if skipped:
                print(f"  已跳过 {skipped} 个，保留 {len(km.knowledge_points)} 个")

    return km


def review_summaries(
    km: KnowledgeMap,
    no_interactive: bool,
    report: ImportReport,
) -> KnowledgeMap:
    """Display KP summaries (key_facts + commands) and let user confirm.

    This is the critical review point — user sees exactly what information
    was extracted before it gets formatted into KB entries.

    In non-interactive mode, all summarized KPs are accepted.

    Returns:
        The (possibly filtered) KnowledgeMap.
    """
    summarized = [kp for kp in km.knowledge_points if kp.summarized]

    if no_interactive:
        return km

    if not summarized:
        return km

    print(f"\n知识摘要（{len(summarized)} 个知识点）：")
    for kp in summarized:
        n_facts = len(kp.key_facts)
        n_cmds = len(kp.commands)
        n_rels = len(kp.related_kps)
        print(f"\n  {kp.id} [{kp.type_hint}] {kp.description[:60]}")
        print(f"    事实: {n_facts} 条  命令: {n_cmds} 条  关联: {n_rels} 条")
        # Show first few key facts as preview.
        for fact in kp.key_facts[:3]:
            print(f"      · {fact[:80]}")
        if n_facts > 3:
            print(f"      ... ({n_facts - 3} more)")
        if kp.commands:
            for cmd in kp.commands[:2]:
                print(f"      $ {cmd[:80]}")
            if n_cmds > 2:
                print(f"      ... ({n_cmds - 2} more)")

    choice = click.prompt(
        "\n[1] 确认全部 [2] 查看详情 [3] 跳过某些 [4] 取消", default="1"
    ).strip()

    if choice == "4":
        km.knowledge_points = [kp for kp in km.knowledge_points if not kp.summarized]
        report.warnings.append("用户取消了摘要确认")
        return km

    if choice == "2":
        for kp in summarized:
            print(f"\n{'=' * 60}")
            print(f"{kp.id} [{kp.type_hint}] {kp.description}")
            print(f"{'=' * 60}")
            print(f"\nKey Facts ({len(kp.key_facts)}):")
            for i, fact in enumerate(kp.key_facts, 1):
                print(f"  {i}. {fact}")
            print(f"\nCommands ({len(kp.commands)}):")
            if kp.commands:
                for i, cmd in enumerate(kp.commands, 1):
                    print(f"  {i}. {cmd}")
            else:
                print("  (none)")
            if kp.related_kps:
                print(f"\nRelated: {', '.join(kp.related_kps)}")

        choice = click.prompt(
            "\n[1] 确认全部 [3] 跳过某些 [4] 取消", default="1"
        ).strip()
        if choice == "4":
            km.knowledge_points = [kp for kp in km.knowledge_points if not kp.summarized]
            report.warnings.append("用户取消了摘要确认")
            return km

    if choice == "3":
        skip_input = click.prompt(
            "输入要跳过的 KP id（逗号分隔）", default=""
        ).strip()
        if skip_input:
            skip_set = {s.strip() for s in skip_input.split(",") if s.strip()}
            before = len(km.knowledge_points)
            km.knowledge_points = [
                kp for kp in km.knowledge_points if kp.id not in skip_set
            ]
            skipped = before - len(km.knowledge_points)
            if skipped:
                print(f"  已跳过 {skipped} 个，保留 {len(km.knowledge_points)} 个")

    return km


def review_drafts(
    kp_drafts: dict[str, str],
    fidelity_results: dict[str, list[str]],
    no_interactive: bool,
    report: ImportReport,
) -> dict[str, str]:
    """Display generated drafts with fidelity check results; let user confirm.

    In non-interactive mode, fidelity warnings are logged but all drafts proceed.

    Returns:
        The (possibly filtered) dict of kp_id → draft Markdown.
    """
    # Always log fidelity warnings.
    for kp_id, warnings in fidelity_results.items():
        for w in warnings:
            report.warnings.append(f"{kp_id}: {w}")

    if no_interactive:
        return kp_drafts

    if not kp_drafts:
        return kp_drafts

    print(f"\n生成结果（{len(kp_drafts)} 条）：")
    for kp_id, draft in kp_drafts.items():
        title = _extract_title(draft)
        type_ = _extract_type(draft)
        chars = len(draft)
        warnings = fidelity_results.get(kp_id, [])
        status = " ⚠ " + "; ".join(warnings) if warnings else " ✓"
        print(f"  {kp_id} [{type_:10s}] {title[:50]} ({chars} chars){status}")

    choice = click.prompt(
        "\n[1] 全部写入 [2] 逐条查看 [3] 取消", default="1"
    ).strip()

    if choice == "3":
        return {}

    if choice == "2":
        approved: dict[str, str] = {}
        for kp_id, draft in kp_drafts.items():
            print(f"\n{'=' * 60}\n{kp_id}:\n{'=' * 60}")
            preview = draft[:2000]
            print(preview)
            if len(draft) > 2000:
                print(f"  ... ({len(draft) - 2000} chars truncated)")
            keep = click.prompt("  写入? [y/n]", default="y").strip().lower()
            if keep == "y":
                approved[kp_id] = draft
        return approved

    return kp_drafts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_title(draft: str) -> str:
    """Extract title from YAML frontmatter."""
    for line in draft.splitlines():
        stripped = line.strip()
        if stripped.startswith("title:"):
            return stripped[6:].strip().strip('"').strip("'")
    return "(untitled)"


def _extract_type(draft: str) -> str:
    """Extract type from YAML frontmatter."""
    for line in draft.splitlines():
        stripped = line.strip()
        if stripped.startswith("type:"):
            return stripped[5:].strip()
    return "unknown"
