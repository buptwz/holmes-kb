"""Deterministic content fidelity check.

Two modes:
1. verify_summary_fidelity: checks that the confirmed KP summary (key_facts +
   commands) is fully reflected in the generated draft. This is the primary
   check for the Summarizer→Generator pipeline.
2. verify_content_fidelity: legacy check comparing raw source section against
   draft. Kept for backward compatibility / DAG pipeline.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from holmes.kb.agent.knowledge_map import KnowledgePoint


def verify_summary_fidelity(kp: "KnowledgePoint", draft: str) -> list[str]:
    """Check that the confirmed KP summary is fully reflected in the draft.

    This is the correct fidelity check for the Summarizer→Generator pipeline:
    the summary (key_facts + commands) is the contract, not the raw source section.

    Checks:
    1. Every command in kp.commands must appear in the draft (substring match).
    2. Key numbers/values from key_facts should be present in the draft.

    Returns:
        List of human-readable warning strings. Empty list means all checks passed.
    """
    warnings: list[str] = []
    draft_lower = draft.lower()

    # 1. Command fidelity — every confirmed command must appear verbatim.
    if kp.commands:
        missing_cmds = []
        for cmd in kp.commands:
            # Check if command appears in draft (in code blocks or inline).
            # Normalize whitespace for matching.
            cmd_normalized = " ".join(cmd.split())
            draft_normalized = " ".join(draft.split())
            if cmd_normalized not in draft_normalized:
                missing_cmds.append(cmd[:60])
        if missing_cmds:
            warnings.append(
                f"命令丢失: {len(missing_cmds)}/{len(kp.commands)} 个"
                f" — {', '.join(missing_cmds[:3])}"
            )

    # 2. Key fact number fidelity — numbers from key_facts should appear in draft.
    if kp.key_facts:
        fact_nums: set[str] = set()
        for fact in kp.key_facts:
            fact_nums.update(re.findall(r"\b\d+\.?\d*\b", fact))
        draft_nums = set(re.findall(r"\b\d+\.?\d*\b", draft))
        # Only check significant numbers.
        significant = {n for n in fact_nums if len(n) >= 2 or float(n) >= 10}
        missing = significant - draft_nums
        if missing:
            examples = sorted(missing)[:5]
            warnings.append(f"数字丢失: {', '.join(examples)}")

    return warnings


def verify_content_fidelity(source_section: str, draft: str) -> list[str]:
    """Legacy check: key information from source section preserved in draft.

    Checks three categories:
    1. Numbers (versions, ports, thresholds, timeouts)
    2. Inline code / command fragments
    3. Proper nouns (CamelCase, uppercase abbreviations)

    Returns:
        List of human-readable warning strings. Empty list means all checks passed.
    """
    warnings: list[str] = []

    # 1. Number fidelity
    src_nums = set(re.findall(r"\b\d+\.?\d*\b", source_section))
    draft_nums = set(re.findall(r"\b\d+\.?\d*\b", draft))
    missing_nums = src_nums - draft_nums
    significant_missing = {n for n in missing_nums if len(n) >= 2 or float(n) >= 10}
    if significant_missing:
        examples = sorted(significant_missing)[:5]
        warnings.append(f"数字丢失: {', '.join(examples)}")

    # 2. Code fragment fidelity
    src_code = set(re.findall(r"`([^`]+)`", source_section))
    draft_code = set(re.findall(r"`([^`]+)`", draft))
    if src_code:
        dropped = src_code - draft_code
        drop_ratio = len(dropped) / len(src_code)
        if drop_ratio > 0.3:
            warnings.append(
                f"代码片段丢失: {len(dropped)}/{len(src_code)} 个"
            )

    # 3. Proper noun fidelity
    src_terms = set(re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", source_section))
    draft_terms = set(re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", draft))
    if src_terms:
        missing_terms = src_terms - draft_terms
        miss_ratio = len(missing_terms) / len(src_terms)
        if miss_ratio > 0.3:
            examples = sorted(missing_terms)[:5]
            warnings.append(f"术语丢失: {', '.join(examples)}")

    return warnings
