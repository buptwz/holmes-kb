"""Interactive review gates for the import pipeline (042).

Two review points:
1. review_summary — after Summarizer, before Generator (confirm extracted content)
2. review_draft — after Generator, before write (confirm formatted output)
"""

from __future__ import annotations

from typing import Any, Optional

import click

from holmes.kb.agent.report import ImportReport


def review_summary(
    summary: dict[str, Any],
    no_interactive: bool,
    report: ImportReport,
    source_name: str = "",
) -> bool:
    """Display summary and let user confirm or skip.

    Args:
        summary: Dict with brief, key_facts, commands, symptoms,
                 resolution_branches.
        no_interactive: When True, auto-accept.
        report: ImportReport for logging.
        source_name: Source filename for display.

    Returns:
        True to proceed with generation, False to skip.
    """
    if no_interactive:
        return True

    brief = summary.get("brief", "(no brief)")
    key_facts = summary.get("key_facts", [])
    commands = summary.get("commands", [])
    symptoms = summary.get("symptoms", [])
    branches = summary.get("resolution_branches", [])

    print(f"\n┌─────────────────────────────────────────────┐")
    if source_name:
        print(f"│ Document: {source_name[:42]:<42s} │")
    print(f"│ Brief: {brief[:44]:<44s} │")
    print(f"│                                             │")
    print(f"│ Key Facts: {len(key_facts):<3d} items{' ' * 27}│")
    print(f"│ Commands:  {len(commands):<3d} items{' ' * 27}│")
    if symptoms:
        print(f"│ Symptoms:  {len(symptoms):<3d} items{' ' * 27}│")
    if branches:
        print(f"│ Branches:  {len(branches):<3d}{' ' * 33}│")
    print(f"│                                             │")
    print(f"│ [C]onfirm  [V]iew details  [S]kip          │")
    print(f"└─────────────────────────────────────────────┘")

    choice = click.prompt("", default="c").strip().lower()

    if choice in ("s", "skip"):
        report.warnings.append("用户跳过了摘要确认")
        return False

    if choice in ("v", "view"):
        _show_details(summary)
        confirm = click.prompt("\n[C]onfirm  [S]kip", default="c").strip().lower()
        if confirm in ("s", "skip"):
            report.warnings.append("用户跳过了摘要确认")
            return False

    return True


def review_draft(
    draft: str,
    fidelity_warnings: list[str],
    no_interactive: bool,
    report: ImportReport,
) -> bool:
    """Display generated draft with fidelity results; let user confirm.

    Args:
        draft: Generated KB entry Markdown.
        fidelity_warnings: Fidelity check results.
        no_interactive: When True, auto-accept.
        report: ImportReport for logging.

    Returns:
        True to write, False to skip.
    """
    # Always log fidelity warnings.
    for w in fidelity_warnings:
        report.warnings.append(w)

    if no_interactive:
        return True

    if not draft:
        return False

    title = _extract_title(draft)
    type_ = _extract_type(draft)
    chars = len(draft)
    status = " ⚠ " + "; ".join(fidelity_warnings) if fidelity_warnings else " ✓"

    print(f"\n生成结果:")
    print(f"  [{type_:10s}] {title[:50]} ({chars} chars){status}")

    choice = click.prompt(
        "\n[1] 写入 [2] 查看全文 [3] 取消", default="1"
    ).strip()

    if choice == "3":
        return False

    if choice == "2":
        preview = draft[:3000]
        print(f"\n{'=' * 60}")
        print(preview)
        if len(draft) > 3000:
            print(f"  ... ({len(draft) - 3000} chars truncated)")
        print(f"{'=' * 60}")
        keep = click.prompt("  写入? [y/n]", default="y").strip().lower()
        if keep != "y":
            return False

    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _show_details(summary: dict[str, Any]) -> None:
    """Print full summary details."""
    key_facts = summary.get("key_facts", [])
    commands = summary.get("commands", [])
    symptoms = summary.get("symptoms", [])
    branches = summary.get("resolution_branches", [])

    print(f"\n{'=' * 60}")
    print(f"Brief: {summary.get('brief', '')}")
    print(f"{'=' * 60}")

    print(f"\nKey Facts ({len(key_facts)}):")
    for i, fact in enumerate(key_facts, 1):
        print(f"  {i}. {fact}")

    print(f"\nCommands ({len(commands)}):")
    if commands:
        for i, cmd in enumerate(commands, 1):
            print(f"  {i}. {cmd}")
    else:
        print("  (none)")

    if symptoms:
        print(f"\nSymptoms ({len(symptoms)}):")
        for i, sym in enumerate(symptoms, 1):
            print(f"  {i}. {sym}")

    if branches:
        print(f"\nResolution Branches ({len(branches)}):")
        for i, b in enumerate(branches, 1):
            print(f"  {i}. [{b.get('when', '')}] → {b.get('label', '')}")


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


# ---------------------------------------------------------------------------
# Backward compatibility stubs (old function names used by tests)
# ---------------------------------------------------------------------------


def review_knowledge_points(km: Any, no_interactive: bool, report: Any) -> Any:
    """Stub — KP review removed in 042. Auto-accepts."""
    return km


def review_summaries(km: Any, no_interactive: bool, report: Any) -> Any:
    """Stub — KP summary review removed in 042. Auto-accepts."""
    return km


def review_drafts(
    kp_drafts: dict[str, str],
    fidelity_results: dict[str, list[str]],
    no_interactive: bool,
    report: Any,
) -> dict[str, str]:
    """Stub — multi-draft review removed in 042. Auto-accepts."""
    if report is not None:
        for kp_id, warnings in fidelity_results.items():
            for w in warnings:
                report.warnings.append(f"{kp_id}: {w}")
    return kp_drafts
