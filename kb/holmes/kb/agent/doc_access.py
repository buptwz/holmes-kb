"""Document access tools for the three-phase import pipeline.

Provides DocumentCursor (tracks what has been read) and three deterministic
tool functions that all phase agents can call to access the original source
document without truncation.

Tools (contract C-003):
    read_document_range  — return a character-range slice of the source.
    get_read_coverage    — return current coverage statistics.
    search_in_document   — substring search returning offset + context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# DocumentCursor
# ---------------------------------------------------------------------------


@dataclass
class DocumentCursor:
    """Tracks which portions of the source document have been read.

    The source_text is immutable after creation. All phases share a single
    cursor stored in ctx["doc_cursor"].

    Attributes:
        source_text: Full original source — never truncated.
        read_ranges: List of (start, end) character ranges that have been read,
                     maintained in sorted order with no overlaps.
    """

    source_text: str
    read_ranges: list[tuple[int, int]] = field(default_factory=list)

    @property
    def total_chars(self) -> int:
        return len(self.source_text)

    def read_range(self, start: int, end: int) -> str:
        """Return source_text[start:end], clamped to document bounds.

        Records the range as read so coverage_pct() increases accordingly.
        """
        start = max(0, start)
        end = min(self.total_chars, end)
        if end <= start:
            return ""
        text = self.source_text[start:end]
        self._record(start, end)
        return text

    def coverage_pct(self) -> float:
        """Percentage of unique document characters covered by read_ranges."""
        if self.total_chars == 0:
            return 100.0
        covered = sum(e - s for s, e in self.read_ranges)
        return min(100.0, round(covered / self.total_chars * 100, 1))

    def chars_read(self) -> int:
        """Total unique characters covered."""
        return sum(e - s for s, e in self.read_ranges)

    def find_section(self, heading: str) -> tuple[int, int] | None:
        """Locate a markdown heading and return (section_start, section_end).

        section_start is the first character of the heading line.
        section_end is the character before the next same-level or higher heading,
        or end-of-document.

        Returns None if the heading is not found.
        """
        idx = self.source_text.find(heading)
        if idx == -1:
            return None
        # Determine heading level (number of leading #).
        level_match = re.match(r"^(#{1,6})\s", heading)
        if not level_match:
            level = 1
        else:
            level = len(level_match.group(1))

        # Find the next heading of equal or higher level.
        pattern = re.compile(r"^#{1," + str(level) + r"}\s", re.MULTILINE)
        match = pattern.search(self.source_text, idx + 1)
        end = match.start() if match else self.total_chars
        return idx, end

    def _record(self, start: int, end: int) -> None:
        """Merge [start, end) into read_ranges, preserving sorted non-overlapping order."""
        new_ranges: list[tuple[int, int]] = []
        merged = False
        for s, e in self.read_ranges:
            if end < s:
                if not merged:
                    new_ranges.append((start, end))
                    merged = True
                new_ranges.append((s, e))
            elif start > e:
                new_ranges.append((s, e))
            else:
                start = min(start, s)
                end = max(end, e)
        if not merged:
            new_ranges.append((start, end))
        self.read_ranges = new_ranges


# ---------------------------------------------------------------------------
# Tool functions (C-003)
# ---------------------------------------------------------------------------


def read_document_range(
    ctx: dict[str, Any], tool_input: dict[str, Any]
) -> dict[str, Any]:
    """Return a character-range slice of the original source document.

    Input:
        start_char (int): Start offset (inclusive). Clamped to [0, total_chars].
        end_char (int): End offset (exclusive). Clamped to [0, total_chars].

    Returns:
        text (str): The requested slice.
        start_char (int): Actual start used (after clamping).
        end_char (int): Actual end used (after clamping).
        total_chars (int): Total document length.
    """
    cursor: DocumentCursor = ctx.get("doc_cursor")  # type: ignore[assignment]
    if cursor is None:
        source = ctx.get("source_text", "")
        cursor = DocumentCursor(source_text=source)
        ctx["doc_cursor"] = cursor

    start = int(tool_input.get("start_char", 0))
    end = int(tool_input.get("end_char", cursor.total_chars))
    start = max(0, min(start, cursor.total_chars))
    end = max(start, min(end, cursor.total_chars))

    text = cursor.read_range(start, end)
    return {
        "text": text,
        "start_char": start,
        "end_char": end,
        "total_chars": cursor.total_chars,
    }


def get_read_coverage(
    ctx: dict[str, Any], tool_input: dict[str, Any]  # noqa: ARG001
) -> dict[str, Any]:
    """Return current document reading coverage statistics.

    Input: {} (no parameters required)

    Returns:
        chars_read (int): Number of unique characters read so far.
        total_chars (int): Total document length.
        coverage_pct (float): chars_read / total_chars * 100.
    """
    cursor: DocumentCursor = ctx.get("doc_cursor")  # type: ignore[assignment]
    if cursor is None:
        source = ctx.get("source_text", "")
        cursor = DocumentCursor(source_text=source)
        ctx["doc_cursor"] = cursor

    return {
        "chars_read": cursor.chars_read(),
        "total_chars": cursor.total_chars,
        "coverage_pct": cursor.coverage_pct(),
    }


def search_in_document(
    ctx: dict[str, Any], tool_input: dict[str, Any]
) -> dict[str, Any]:
    """Case-insensitive substring search in the source document.

    Input:
        query (str): The search string.
        max_results (int, optional): Maximum matches to return. Default: 3.

    Returns:
        results (list): Up to max_results dicts with:
            offset (int): Character position of the match.
            context (str): 200 characters surrounding the match.
        total_matches (int): Total number of matches found.
    """
    cursor: DocumentCursor = ctx.get("doc_cursor")  # type: ignore[assignment]
    if cursor is None:
        source = ctx.get("source_text", "")
        cursor = DocumentCursor(source_text=source)
        ctx["doc_cursor"] = cursor

    query = str(tool_input.get("query", ""))
    max_results = int(tool_input.get("max_results", 3))
    if not query:
        return {"results": [], "total_matches": 0}

    text_lower = cursor.source_text.lower()
    query_lower = query.lower()
    results = []
    total = 0
    start = 0
    while True:
        idx = text_lower.find(query_lower, start)
        if idx == -1:
            break
        total += 1
        if len(results) < max_results:
            ctx_start = max(0, idx - 100)
            ctx_end = min(cursor.total_chars, idx + len(query) + 100)
            results.append({
                "offset": idx,
                "context": cursor.source_text[ctx_start:ctx_end],
            })
        start = idx + 1

    return {"results": results, "total_matches": total}


# ---------------------------------------------------------------------------
# Tool metadata for TOOL_DEFINITIONS / TOOL_HANDLERS registration
# ---------------------------------------------------------------------------

DOC_ACCESS_TOOL_DEFINITIONS = [
    {
        "name": "read_document_range",
        "description": (
            "Read a character range from the original source document. "
            "Use this to access any part of the document without truncation. "
            "Prefer smaller ranges (≤ 3000 chars) for focused reading."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_char": {
                    "type": "integer",
                    "description": "Start character offset (inclusive, 0-based).",
                },
                "end_char": {
                    "type": "integer",
                    "description": "End character offset (exclusive).",
                },
            },
            "required": ["start_char", "end_char"],
        },
    },
    {
        "name": "get_read_coverage",
        "description": (
            "Get current document reading coverage: how many characters have been "
            "read so far and what percentage of the document that represents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "search_in_document",
        "description": (
            "Search for a substring in the source document (case-insensitive). "
            "Returns up to max_results matches with surrounding context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring to search for.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 3).",
                },
            },
            "required": ["query"],
        },
    },
]

DOC_ACCESS_TOOL_HANDLERS = {
    "read_document_range": read_document_range,
    "get_read_coverage": get_read_coverage,
    "search_in_document": search_in_document,
}
