"""Deterministic content fidelity check (039).

Replaces the unreliable Phase 3 LLM Verifier with zero-cost programmatic checks.
Verifies that key information from the source section is preserved in the generated draft.
"""

from __future__ import annotations

import re


def verify_content_fidelity(source_section: str, draft: str) -> list[str]:
    """Check that key information from source appears in the generated draft.

    Checks three categories:
    1. Numbers (versions, ports, thresholds, timeouts)
    2. Inline code / command fragments
    3. Proper nouns (CamelCase, uppercase abbreviations)

    Returns:
        List of human-readable warning strings. Empty list means all checks passed.
    """
    warnings: list[str] = []

    # 1. Number fidelity — hard facts like port numbers, version strings, thresholds
    src_nums = set(re.findall(r"\b\d+\.?\d*\b", source_section))
    draft_nums = set(re.findall(r"\b\d+\.?\d*\b", draft))
    missing_nums = src_nums - draft_nums
    # Only warn if significant numbers are missing (ignore trivial ones like "1", "2")
    significant_missing = {n for n in missing_nums if len(n) >= 2 or float(n) >= 10}
    if significant_missing:
        examples = sorted(significant_missing)[:5]
        warnings.append(f"数字丢失: {', '.join(examples)}")

    # 2. Code fragment fidelity — inline code between backticks
    src_code = set(re.findall(r"`([^`]+)`", source_section))
    draft_code = set(re.findall(r"`([^`]+)`", draft))
    if src_code:
        dropped = src_code - draft_code
        drop_ratio = len(dropped) / len(src_code)
        if drop_ratio > 0.3:
            warnings.append(
                f"代码片段丢失: {len(dropped)}/{len(src_code)} 个"
            )

    # 3. Proper noun fidelity — CamelCase words and uppercase abbreviations
    src_terms = set(re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", source_section))
    draft_terms = set(re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", draft))
    if src_terms:
        missing_terms = src_terms - draft_terms
        miss_ratio = len(missing_terms) / len(src_terms)
        if miss_ratio > 0.3:
            examples = sorted(missing_terms)[:5]
            warnings.append(f"术语丢失: {', '.join(examples)}")

    return warnings
