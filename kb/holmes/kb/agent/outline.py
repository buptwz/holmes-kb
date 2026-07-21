"""Document outline extraction — heading structure analysis for LLM prompts.

Provides utilities to extract and format document headings, used by both
the Summarizer (to guide section-by-section reading) and the Generator
(to reference source structure during KB entry generation).
"""

from __future__ import annotations

import re
from typing import Any

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)

# Sections above this threshold get a size warning in the prompt
_LARGE_SECTION_CHARS = 3000


def extract_document_outline(source: str) -> list[dict[str, Any]]:
    """Extract headings from source document as a structured outline.

    Returns list of {"level": int, "text": str, "offset": int, "length": int}.
    ``length`` is the character count from this heading to the next heading
    (or end of document).
    """
    headings: list[dict[str, Any]] = []
    for m in _HEADING_RE.finditer(source):
        headings.append({
            "level": len(m.group(1)),
            "text": m.group(2).strip(),
            "offset": m.start(),
        })
    # Compute section lengths
    total = len(source)
    for i, h in enumerate(headings):
        next_offset = headings[i + 1]["offset"] if i + 1 < len(headings) else total
        h["length"] = next_offset - h["offset"]
    return headings


def format_outline_for_prompt(outline: list[dict[str, Any]], total_chars: int) -> str:
    """Format outline into a concise string for injection into LLM prompt."""
    if not outline:
        return ""
    lines = [f"Document outline ({len(outline)} sections, {total_chars} chars total):"]
    for h in outline:
        indent = "  " * (h["level"] - 1)
        length = h.get("length", 0)
        size_hint = f"  ⚠ LARGE ({length} chars)" if length >= _LARGE_SECTION_CHARS else ""
        lines.append(
            f"{indent}{'#' * h['level']} {h['text']}  "
            f"[char {h['offset']}–{h['offset'] + length}]{size_hint}"
        )
    lines.append("")
    lines.append(
        "Ensure ALL sections above are covered in your extraction. "
        "For LARGE sections, make multiple read_document_range calls to cover the full content."
    )
    return "\n".join(lines)


def merge_read_ranges(
    read_ranges: list[tuple[int, int]],
    gap_tolerance: int = 50,
) -> list[tuple[int, int]]:
    """Merge overlapping/near-contiguous read ranges.

    Ranges separated by ≤ ``gap_tolerance`` chars are merged — small gaps come
    from LLMs issuing slightly misaligned consecutive read_document_range calls
    and do not represent genuinely unread content.
    """
    merged: list[list[int]] = []
    for start, end in sorted(read_ranges):
        if merged and start <= merged[-1][1] + gap_tolerance:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def find_unread_sections(
    outline: list[dict[str, Any]],
    read_ranges: list[tuple[int, int]],
) -> list[str]:
    """Return heading texts whose full char range was never read (T033).

    A section counts as read only when its entire [offset, offset+length)
    span is contained in the union of read_document_range ranges. This is the
    pipeline-level hard invariant: extraction coverage claims are checked
    against what was ACTUALLY read, not what the summary mentions.
    """
    if not outline:
        return []
    merged = merge_read_ranges(read_ranges)
    unread: list[str] = []
    for h in outline:
        start = h["offset"]
        end = start + h.get("length", 0)
        if end <= start:
            continue
        covered = any(s <= start and e >= end for s, e in merged)
        if not covered:
            unread.append(h["text"])
    return unread


def check_outline_coverage(
    outline: list[dict[str, Any]],
    summary: dict[str, Any],
) -> list[str]:
    """Check which outline ### sections are not reflected in the summary.

    Only checks ### (level 3) headings — these are the content-level sections
    most likely to represent distinct branches or steps. ## headings are
    structural (Symptoms, Resolution) and covered by type-level checks elsewhere.

    Returns list of uncovered section texts (empty = full coverage).
    """
    if not outline:
        return []

    # Only check ### headings (level 3) — the content sections
    h3_headings = [h for h in outline if h["level"] == 3]
    if not h3_headings:
        return []

    # Build a lowercase search corpus from all summary fields
    corpus_parts: list[str] = []
    corpus_parts.append(summary.get("brief", ""))
    corpus_parts.extend(summary.get("key_facts", []))
    for cmd_item in summary.get("commands", []):
        if isinstance(cmd_item, dict):
            corpus_parts.append(cmd_item.get("cmd", ""))
            corpus_parts.append(cmd_item.get("expected", ""))
        else:
            corpus_parts.append(str(cmd_item))
    corpus_parts.extend(summary.get("symptoms", []))
    for step in summary.get("steps", []):
        if isinstance(step, dict):
            corpus_parts.append(step.get("action", ""))
            corpus_parts.append(step.get("command", ""))
            corpus_parts.append(step.get("expected", ""))
        else:
            corpus_parts.append(str(step))
    for b in summary.get("resolution_branches", []):
        if isinstance(b, dict):
            corpus_parts.append(b.get("when", ""))
            corpus_parts.append(b.get("label", ""))
    corpus = "\n".join(str(p) for p in corpus_parts).lower()

    # Common heading prefixes that appear in many sections — not distinctive
    _STOP_TERMS = frozenset({
        "路径", "step", "步骤", "分支", "path", "branch", "phase", "阶段",
        "问题", "issue", "处理", "排查",
    })

    uncovered: list[str] = []
    for h in h3_headings:
        text = h["text"]
        # Extract CJK bigrams + ASCII words as search tokens
        # This handles "物理连接问题" → ["物理", "理连", "连接", "接问", "问题"]
        tokens: list[str] = []
        # ASCII/mixed tokens
        tokens.extend(re.findall(r"[A-Za-z0-9]{2,}", text.lower()))
        # CJK: sliding 2-gram window for substring matching
        cjk_chars = re.findall(r"[\u4e00-\u9fff]+", text)
        for run in cjk_chars:
            if len(run) >= 2:
                for i in range(len(run) - 1):
                    tokens.append(run[i:i+2])

        # Filter out stop terms
        tokens = [t for t in tokens if t not in _STOP_TERMS]
        if not tokens:
            continue

        # A section is "covered" if at least one token appears in corpus
        covered = any(t in corpus for t in tokens)
        if not covered:
            uncovered.append(text)

    return uncovered
