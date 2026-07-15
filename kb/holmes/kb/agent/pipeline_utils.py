"""Pipeline utility functions — pure helpers extracted from ImportPipeline.

These are stateless, deterministic functions used during the import pipeline.
Separated to keep pipeline.py focused on orchestration logic.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import frontmatter as _fm


# ---------------------------------------------------------------------------
# Language detection fallback
# ---------------------------------------------------------------------------


def detect_language_heuristic(text: str, default: str = "en") -> str:
    """Detect language from text using CJK character ratio.

    If the text contains a significant proportion of Chinese characters
    (relative to alphabetic characters), return "zh". Otherwise return default.
    """
    sample = text[:3000]  # sample first 3000 chars
    cjk = sum(1 for c in sample if '\u4e00' <= c <= '\u9fff')
    alpha = sum(1 for c in sample if c.isascii() and c.isalpha())
    # If CJK chars are at least 10% of (CJK + alpha), treat as Chinese
    total = cjk + alpha
    if total > 0 and cjk / total >= 0.10:
        return "zh"
    return default


# ---------------------------------------------------------------------------
# Type inference from summary content
# ---------------------------------------------------------------------------


def infer_type_from_summary(summary: dict[str, Any]) -> str:
    """Infer KB entry type from Summarizer output content.

    Instead of relying on pre-classification, determine type from what was
    actually extracted -- symptoms, branches, outline sections, etc.
    """
    symptoms = summary.get("symptoms") or []
    branches = summary.get("resolution_branches") or []
    outline = summary.get("outline") or []
    section_names = {s.get("section", "").lower() for s in outline if isinstance(s, dict)}

    # Decision: has explicit "Decision" section + options analysis
    if "decision" in section_names or "rationale" in section_names:
        # Check if it's a guideline (rules/standards) or a decision (ADR)
        if "guideline" in section_names or "rule" in section_names:
            return "guideline"
        if "decision" in section_names:
            return "decision"

    # Pitfall: has symptoms OR resolution branches -- this is a failure investigation
    if len(symptoms) >= 2 or len(branches) >= 2:
        return "pitfall"

    # Model: has "overview" + "key concepts" -- knowledge/reference document
    if "overview" in section_names and "key concepts" in section_names:
        return "model"

    # Guideline: has "guideline" or "rule" section
    if "guideline" in section_names or "rule" in section_names:
        return "guideline"

    # Process: has "steps" or "procedure" section -- step-by-step procedure
    if "steps" in section_names or "procedure" in section_names:
        return "process"

    # Pitfall with single branch or few symptoms
    if symptoms or branches:
        return "pitfall"

    # Fallback: use outline section names as best guess
    if "purpose" in section_names or "outcome" in section_names:
        return "process"
    if "context" in section_names:
        return "decision"

    return "pitfall"  # safe default for NPI domain


# ---------------------------------------------------------------------------
# Fallback extraction (regex-based, no LLM)
# ---------------------------------------------------------------------------


def fallback_extract(source_text: str) -> dict[str, Any]:
    """Deterministic regex-based extraction when Summarizer LLM fails.

    Extracts headings, code-block commands, and first paragraph as brief.
    Guarantees a non-None summary so the pipeline can continue.
    """
    lines = source_text.splitlines()

    # Brief: first non-empty, non-heading line
    brief = ""
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            brief = stripped[:200]
            break

    # Key facts: all heading texts
    key_facts = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            key_facts.append(stripped[3:].strip())

    # Commands: lines starting with $ inside code blocks
    commands: list[dict[str, str]] = []
    in_code = False
    for line in lines:
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            m = re.match(r"^\$\s+(.+)", line.strip())
            if m:
                commands.append({"cmd": m.group(1), "expected": "", "risk": "read"})

    # Outline from headings
    outline = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            outline.append({"section": stripped[3:].strip(), "description": ""})

    return {
        "brief": brief,
        "key_facts": key_facts,
        "commands": commands,
        "symptoms": [],
        "resolution_branches": [],
        "outline": outline,
    }


# ---------------------------------------------------------------------------
# LLM output cleanup
# ---------------------------------------------------------------------------


def strip_llm_wrapper(draft: str) -> str:
    """Remove preamble text, code fences, and trailing noise from LLM output.

    LLMs commonly output patterns like:
      - "Here's the entry:\\n```markdown\\n---\\n..."
      - "```\\n---\\n...\\n```"
      - Some preamble text\\n---\\nfrontmatter\\n---\\nbody
    This function extracts the actual YAML-frontmatter markdown.
    """
    stripped = draft.strip()

    # Strategy 0: Handle "---\\n\\n```yaml\\n---\\n..." pattern
    # LLM sometimes outputs an empty frontmatter block followed by code-fenced real content
    fence_after_empty_fm = re.search(
        r"^---\s*\n\s*```(?:markdown|md|yaml)?\s*\n(---\n.+)",
        stripped, re.DOTALL,
    )
    if fence_after_empty_fm:
        inner = fence_after_empty_fm.group(1)
        if inner.rstrip().endswith("```"):
            inner = inner.rstrip()[:-3].rstrip()
        stripped = inner

    # Strategy 1: If it starts with ```, strip outer code fence
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Remove opening fence line
        lines = lines[1:]
        # Remove closing fence if present
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    # Strategy 2: If there's preamble before ---, find the first ---
    if not stripped.startswith("---"):
        # Look for ``` code fence containing ---
        fence_match = re.search(r"```(?:markdown|md|yaml)?\s*\n(---\n.+)", stripped, re.DOTALL)
        if fence_match:
            inner = fence_match.group(1)
            # Remove trailing ``` if present
            if inner.rstrip().endswith("```"):
                inner = inner.rstrip()[:-3].rstrip()
            stripped = inner
        else:
            # Just find the first ---
            idx = stripped.find("\n---\n")
            if idx != -1:
                stripped = stripped[idx + 1:]  # skip the \n before ---

    # Strategy 3: Remove trailing ``` if still present
    if stripped.rstrip().endswith("```"):
        stripped = stripped.rstrip()[:-3].rstrip()

    # Strategy 4: Fix missing closing --- in frontmatter.
    # If the draft starts with --- but has no second --- before body content,
    # find the first markdown heading (##) and insert --- before it.
    if stripped.startswith("---"):
        lines = stripped.splitlines()
        has_closing = False
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                has_closing = True
                break
            if line.startswith("## "):
                # Found body heading before closing --- -> insert one
                lines.insert(i, "---")
                stripped = "\n".join(lines)
                break
        # Also handle blank line after opening --- (yaml needs content right after)

    return stripped


def fix_yaml_values(draft: str) -> str:
    """Fix unquoted YAML values that contain colons.

    LLMs often produce: `title: Granite NPI: Per-Slot Config`
    YAML requires quoting when the value contains `: `.
    This method wraps such values in double quotes.
    """
    lines = draft.splitlines()
    in_frontmatter = False
    result = []
    for line in lines:
        if line.strip() == "---":
            in_frontmatter = not in_frontmatter
            result.append(line)
            continue
        if in_frontmatter:
            # Match `key: value` where value is not already quoted and not
            # a YAML collection (list/dict)
            m = re.match(r"^(\w[\w-]*:\s+)(.+)$", line)
            if m:
                key_part, value = m.group(1), m.group(2)
                # Skip if already quoted, or is a YAML list/bool/number
                if (
                    not value.startswith('"')
                    and not value.startswith("'")
                    and not value.startswith("[")
                    and not value.startswith("{")
                    and ": " in value
                ):
                    # Escape existing double quotes in value, then wrap
                    value = value.replace("\\", "\\\\").replace('"', '\\"')
                    line = f'{key_part}"{value}"'
        result.append(line)
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Fallback outline from summary content
# ---------------------------------------------------------------------------


def build_fallback_outline(
    summary: dict[str, Any], suggested_type: str,
) -> list[dict[str, str]]:
    """Build an outline from actual summary content when Summarizer omits it.

    Descriptions are derived from the extracted data, not generic placeholders.
    """
    n_facts = len(summary.get("key_facts", []))
    n_cmds = len(summary.get("commands", []))
    n_syms = len(summary.get("symptoms", []))
    n_branches = len(summary.get("resolution_branches", []))
    brief = summary.get("brief", "")

    # Truncate brief for use in descriptions
    brief_short = brief[:60] + "..." if len(brief) > 60 else brief

    _BUILDERS: dict[str, Any] = {
        "pitfall": lambda: [
            {
                "section": "Symptoms",
                "description": (
                    f"{n_syms} 个可观测现象" if n_syms
                    else "症状描述"
                ),
            },
            {
                "section": "Root Cause",
                "description": (
                    f"{n_facts} 个关键事实分析根因"
                    if n_facts else "根因分析"
                ),
            },
            {
                "section": "Resolution",
                "description": (
                    f"{n_branches} 条排查路径"
                    + (f"，含 {n_cmds} 个命令" if n_cmds else "")
                    if n_branches
                    else f"{n_cmds} 个命令" if n_cmds
                    else "排查步骤"
                ),
            },
        ],
        "model": lambda: [
            {"section": "Overview", "description": brief_short or "概念概述"},
            {
                "section": "Key Concepts",
                "description": f"{n_facts} 个关键概念" if n_facts else "核心概念",
            },
            {
                "section": "Usage",
                "description": (
                    f"使用指南，含 {n_cmds} 个命令" if n_cmds
                    else "使用指南"
                ),
            },
        ],
        "guideline": lambda: [
            {"section": "Context", "description": brief_short or "适用场景"},
            {
                "section": "Guideline",
                "description": f"{n_facts} 条规则" if n_facts else "规则要求",
            },
            {"section": "Rationale", "description": "规则依据与违规后果"},
        ],
        "process": lambda: [
            {"section": "Purpose", "description": brief_short or "流程目的"},
            {
                "section": "Steps",
                "description": (
                    f"操作步骤，含 {n_cmds} 个命令" if n_cmds
                    else "操作步骤"
                ),
            },
            {"section": "Outcome", "description": "预期结果与验证方法"},
        ],
        "decision": lambda: [
            {"section": "Context", "description": brief_short or "决策背景"},
            {
                "section": "Decision",
                "description": f"选定方案" + (f"，含 {n_cmds} 个命令" if n_cmds else ""),
            },
            {"section": "Rationale", "description": "选择依据与备选方案比较"},
        ],
    }

    builder = _BUILDERS.get(suggested_type)
    if builder:
        return builder()
    return []


# ---------------------------------------------------------------------------
# Structure validation
# ---------------------------------------------------------------------------


def check_structure(
    draft: str, suggested_type: str, has_complex_branching: bool = False,
) -> list[str]:
    """Check that the draft has the required sections for its KB type.

    Returns a list of error strings (empty = pass).
    """
    # Required sections per type (lowercase for matching)
    _REQUIRED: dict[str, list[str]] = {
        "pitfall": ["symptoms", "root cause", "resolution"],
        "model": ["overview", "key concepts", "usage"],
        "guideline": ["context", "guideline", "rationale"],
        "process": ["purpose", "steps", "outcome"],
        "decision": ["context", "decision", "rationale"],
    }

    required = _REQUIRED.get(suggested_type, [])
    if not required:
        return []

    # Extract ## headings from body
    try:
        post = _fm.loads(draft)
        body = post.content or ""
        meta = post.metadata or {}
    except Exception:
        body = draft
        meta = {}

    headings = [
        line.strip().lstrip("#").strip().lower()
        for line in body.splitlines()
        if line.strip().startswith("## ")
    ]

    errors = []

    # Contents section is required for ALL types
    if not any("contents" in h for h in headings):
        errors.append(
            f"Missing required section '## Contents' for type={suggested_type}"
        )

    for section in required:
        if not any(section in h for h in headings):
            errors.append(
                f"Missing required section '## {section.title()}' for type={suggested_type}"
            )

    # Check for empty required sections (Contents + type-specific)
    all_required = ["contents"] + required
    for section in all_required:
        for h in headings:
            if section in h:
                # Find content between this heading and the next
                idx = body.lower().find(f"## {h}")
                if idx == -1:
                    continue
                rest = body[idx:]
                lines = rest.splitlines()[1:]  # skip heading line
                content = []
                for line in lines:
                    if line.strip().startswith("## "):
                        break
                    content.append(line)
                text = "\n".join(content).strip()
                if not text:
                    errors.append(
                        f"Section '## {section.title()}' is empty for type={suggested_type}"
                    )
                break

    # ----------------------------------------------------------
    # Contents <-> body cross-validation
    # ----------------------------------------------------------
    # Extract the text block under ## Contents
    contents_text = ""
    for i, line in enumerate(body.splitlines()):
        if line.strip().lower().startswith("## contents"):
            rest_lines = body.splitlines()[i + 1:]
            buf = []
            for rl in rest_lines:
                if rl.strip().startswith("## "):
                    break
                buf.append(rl)
            contents_text = "\n".join(buf)
            break

    # Body headings excluding Contents itself
    body_sections = [h for h in headings if h != "contents"]

    if contents_text and not has_complex_branching:
        # Parse table rows: | Section | Description |
        toc_sections: list[str] = []
        for row in contents_text.splitlines():
            row = row.strip()
            if not row.startswith("|"):
                continue
            cells = [c.strip() for c in row.split("|") if c.strip()]
            if len(cells) < 2:
                continue
            # Skip header separator row like |---|---|
            if all(set(c) <= {"-", ":"} for c in cells):
                continue
            # Skip the header row "Section | Description"
            if cells[0].lower() == "section":
                continue
            toc_sections.append(cells[0].lower())

        if toc_sections:
            # Forward: every Contents entry must exist in body
            for ts in toc_sections:
                if not any(ts in bh for bh in body_sections):
                    errors.append(
                        f"Contents lists '{ts}' but no matching ## heading in body"
                    )
            # Reverse: every body heading must appear in Contents
            for bh in body_sections:
                if not any(bh in ts or ts in bh for ts in toc_sections):
                    errors.append(
                        f"Body has '## {bh.title()}' but it is not listed in Contents"
                    )

    if contents_text and has_complex_branching:
        # Cross-validate decision tree <-> body ### headings by TEXT,
        # not by letter labels. Letter labels [A], [B] are cosmetic
        # artifacts of tree rendering, not semantic identifiers.

        # Extract branch label TEXT from decision tree lines:
        #   "|- condition --> [A] ..." ->  "..."
        tree_branch_labels: list[str] = []
        for m in re.finditer(r"─→\s*\[[A-Za-z]\]\s*(.+)", contents_text):
            tree_branch_labels.append(m.group(1).strip().lower())

        # Extract ### heading TEXT under ## Resolution in body
        body_branch_headings: list[str] = []
        in_resolution = False
        for line in body.splitlines():
            stripped_line = line.strip().lower()
            if stripped_line.startswith("## resolution"):
                in_resolution = True
                continue
            if in_resolution and stripped_line.startswith("## ") and not stripped_line.startswith("### "):
                break
            if in_resolution and stripped_line.startswith("### "):
                heading_text = stripped_line[4:].strip()
                # Strip [A] prefix if Generator included it
                heading_text = re.sub(r"^\[[a-z]\]\s*", "", heading_text)
                body_branch_headings.append(heading_text)

        # Cross-validate using text fuzzy match (same logic as MCP _extract_branch_section)
        if tree_branch_labels:
            for tl in tree_branch_labels:
                if not any(tl in bh or bh in tl for bh in body_branch_headings):
                    errors.append(
                        f"Contents tree mentions '{tl}' but no matching ### heading in Resolution"
                    )
            for bh in body_branch_headings:
                if not any(bh in tl or tl in bh for tl in tree_branch_labels):
                    errors.append(
                        f"Resolution has ### '{bh}' but not represented in Contents tree"
                    )

    # DAG structure check: when complex branching is expected
    if has_complex_branching:
        dm = meta.get("decision_map")
        if not dm or not isinstance(dm, list) or len(dm) == 0:
            errors.append(
                "Missing 'decision_map' in frontmatter (required for complex branching)"
            )

    return errors
