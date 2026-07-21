"""Deterministic content fidelity check.

Three modes:
1. verify_summary_fidelity_042: checks that confirmed summary dict (042 pipeline)
   is fully reflected in the generated draft.
2. verify_summary_fidelity: checks KP-based summary (legacy pipeline).
3. verify_content_fidelity: legacy check comparing raw source section against draft.
"""

from __future__ import annotations

import re
from typing import Any


def verify_summary_fidelity_042(
    summary: dict[str, Any],
    draft: str,
    entry_type: str | None = None,
) -> tuple[list[str], list[str]]:
    """Check that the confirmed summary dict is fully reflected in the draft.

    Returns (errors, warnings):
      - errors: MUST retry — structural integrity broken, agent can't guide troubleshooting.
      - warnings: tolerable — information loss but the entry is still usable.

    Error vs warning thresholds are designed around one principle:
    "Can the agent still guide the engineer through the full troubleshooting flow?"
    If a missing item breaks routing or makes a step unexecutable → error.
    If a missing item reduces context but the flow still works → warning.
    """
    errors: list[str] = []
    warnings: list[str] = []
    draft_normalized = " ".join(draft.split())

    # ------------------------------------------------------------------
    # 1. Command fidelity
    #    Commands are the most actionable content — engineer executes these.
    #    Handles both new format (list[dict]) and legacy format (list[str]).
    #    >30% missing = error (too many steps broken)
    #    ≤30% missing = warning (most steps still work)
    # ------------------------------------------------------------------
    raw_commands = summary.get("commands", [])
    if raw_commands:
        missing_cmds = []
        for item in raw_commands:
            cmd_str = item.get("cmd", "") if isinstance(item, dict) else str(item)
            cmd_normalized = " ".join(cmd_str.split())
            if cmd_normalized and cmd_normalized not in draft_normalized:
                missing_cmds.append(cmd_str[:60])
        total = len(raw_commands)
        if missing_cmds:
            ratio = len(missing_cmds) / total
            msg = (
                f"命令丢失: {len(missing_cmds)}/{total} 个"
                f" — {', '.join(missing_cmds[:3])}"
            )
            if ratio > 0.3:
                errors.append(msg)
            else:
                warnings.append(msg)

    # ------------------------------------------------------------------
    # 1b. Expected output fidelity
    #     Commands with non-empty `expected` field should have a corresponding
    #     "Expected:" line in the draft. Missing = warning (context loss).
    # ------------------------------------------------------------------
    if raw_commands:
        cmds_with_expected = [
            item for item in raw_commands
            if isinstance(item, dict) and item.get("expected", "").strip()
        ]
        if cmds_with_expected:
            draft_lower = draft.lower()
            missing_expected = sum(
                1 for item in cmds_with_expected
                if "expected:" not in _get_context_after_cmd(draft_lower, item["cmd"])
            )
            if missing_expected > 0:
                warnings.append(
                    f"Expected 行缺失: {missing_expected}/{len(cmds_with_expected)} 个命令缺少预期输出说明"
                )

    # ------------------------------------------------------------------
    # 2. Resolution branch fidelity (pitfall only)
    #    Each branch is a diagnostic path. A missing branch = dead route.
    #    The agent sends engineer to a branch that doesn't exist → error.
    # ------------------------------------------------------------------
    branches = summary.get("resolution_branches", [])
    if branches:
        draft_lower = draft.lower()
        missing_branches = []
        for branch in branches:
            label = str(branch.get("label", "")).strip()
            if not label:
                continue
            # Check if branch label appears as a ### heading in the draft
            if f"### {label}".lower() not in draft_lower:
                # Fallback: check if label text appears anywhere (LLM may
                # have slightly reformatted the heading)
                if label.lower() not in draft_lower:
                    missing_branches.append(label)
        if missing_branches:
            errors.append(
                f"分支丢失: {', '.join(missing_branches)} "
                f"({len(missing_branches)}/{len(branches)} 个分支在 draft 中缺失)"
            )

    # ------------------------------------------------------------------
    # 2b. Step fidelity (all types)
    #     Steps are the ordered procedure — the agent walks the engineer
    #     through them one by one.
    #     >30% steps missing = error (procedure broken)
    #     ≤30% missing = warning
    #     ANY actor=human (physical) step missing = error — physical steps
    #     (waveform/voltage measurement, reseating) are the most critical
    #     and least recoverable information in NPI troubleshooting.
    # ------------------------------------------------------------------
    raw_steps = summary.get("steps", [])
    steps = [
        s for s in raw_steps
        if isinstance(s, dict) and (s.get("action") or s.get("command"))
    ]
    if steps:
        draft_lower = draft.lower()
        missing_steps: list[str] = []
        missing_human: list[str] = []
        for step in steps:
            if _step_in_draft(step, draft_normalized, draft_lower):
                continue
            label = (step.get("action") or step.get("command", ""))[:60]
            missing_steps.append(label)
            if step.get("actor") == "human":
                missing_human.append(label)
        if missing_human:
            errors.append(
                f"物理步骤丢失: {len(missing_human)} 个"
                f" — {', '.join(missing_human[:3])}"
            )
        if missing_steps:
            ratio = len(missing_steps) / len(steps)
            msg = (
                f"步骤丢失: {len(missing_steps)}/{len(steps)} 个"
                f" — {', '.join(missing_steps[:3])}"
            )
            if ratio > 0.3:
                errors.append(msg)
            else:
                warnings.append(msg)

    # ------------------------------------------------------------------
    # 3. Symptom fidelity (pitfall only)
    #    Symptoms are how the agent MATCHES the entry to the user's problem.
    #    ALL missing = error (entry unmatchable)
    #    Partial missing (≤50%) = warning (remaining symptoms still work)
    # ------------------------------------------------------------------
    symptoms = summary.get("symptoms", [])
    is_pitfall = (entry_type or "").lower() == "pitfall"
    if symptoms and is_pitfall:
        # Extract ## Symptoms section from draft for targeted checking
        symptoms_section = _extract_section_text(draft, "Symptoms")
        check_target = symptoms_section if symptoms_section else draft_lower

        missing_syms = []
        for sym in symptoms:
            sym_str = str(sym).strip()
            if not sym_str:
                continue
            # Extract distinctive tokens (CJK bigrams + ASCII words ≥3 chars)
            tokens = _extract_match_tokens(sym_str)
            # Symptom is "present" if ≥50% of its tokens appear in the section
            if tokens:
                hits = sum(1 for t in tokens if t in check_target.lower())
                if hits / len(tokens) < 0.5:
                    missing_syms.append(sym_str[:60])
        if missing_syms:
            ratio = len(missing_syms) / len(symptoms)
            msg = f"症状丢失: {len(missing_syms)}/{len(symptoms)} 个"
            if ratio > 0.5:
                errors.append(msg)
            else:
                warnings.append(msg)

    # ------------------------------------------------------------------
    # 4. Key fact number fidelity (all types)
    #    Numbers are context — thresholds, versions, specs. Important but
    #    not structural. Always a warning.
    # ------------------------------------------------------------------
    key_facts = summary.get("key_facts", [])
    if key_facts:
        fact_nums: set[str] = set()
        for fact in key_facts:
            fact_nums.update(re.findall(r"\b\d+\.?\d*\b", str(fact)))
        draft_nums = set(re.findall(r"\b\d+\.?\d*\b", draft))
        significant: set[str] = set()
        for n in fact_nums:
            try:
                if len(n) >= 2 or float(n) >= 10:
                    significant.add(n)
            except ValueError:
                pass
        missing = significant - draft_nums
        if missing:
            examples = sorted(missing)[:5]
            warnings.append(f"数字丢失: {', '.join(examples)}")

    return errors, warnings


def _step_in_draft(step: dict[str, Any], draft_normalized: str, draft_lower: str) -> bool:
    """Check whether a summary step is reflected in the draft.

    Steps with a command match on the verbatim command (whitespace-normalized);
    steps without a command match on ≥50% of the action's distinctive tokens
    (same heuristic as symptom matching).
    """
    command = str(step.get("command", "")).strip()
    if command:
        return " ".join(command.split()) in draft_normalized
    action = str(step.get("action", "")).strip()
    if not action:
        return True
    tokens = _extract_match_tokens(action)
    if not tokens:
        return action.lower() in draft_lower
    hits = sum(1 for t in tokens if t in draft_lower)
    return hits / len(tokens) >= 0.5


def _get_context_after_cmd(draft_lower: str, cmd: str) -> str:
    """Return ~300 chars of text after a command appears in the draft."""
    cmd_normalized = " ".join(cmd.split()).lower()
    pos = draft_lower.find(cmd_normalized[:40].lower())
    if pos == -1:
        return ""
    return draft_lower[pos:pos + 500]


def _extract_section_text(draft: str, section_name: str) -> str:
    """Extract text under a ## heading (until next ## or EOF). Lowercase."""
    pattern = rf"^##\s+{re.escape(section_name)}\b.*$"
    match = re.search(pattern, draft, re.MULTILINE | re.IGNORECASE)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^##\s+", draft[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(draft)
    return draft[start:end]


def _extract_match_tokens(text: str) -> list[str]:
    """Extract distinctive tokens for fuzzy presence checking.

    Returns ASCII words (≥3 chars) + CJK bigrams, lowercased.
    """
    tokens: list[str] = []
    # ASCII/mixed tokens
    tokens.extend(w.lower() for w in re.findall(r"[A-Za-z0-9_]{3,}", text))
    # CJK bigrams
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(run) >= 2:
            for i in range(len(run) - 1):
                tokens.append(run[i : i + 2])
    return tokens


def verify_summary_fidelity(kp: Any, draft: str) -> list[str]:
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
