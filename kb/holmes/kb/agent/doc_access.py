"""Document access tools for the import pipeline (042).

Provides two stateless tool functions that pipeline agents can call to access
the original source document without truncation.

Tools:
    read_document_range  — return a character-range slice of the source.
    search_in_document   — substring search returning offset + context.
"""

from __future__ import annotations

import re
from typing import Any

# Default chunk size (chars) the pipeline prompts steer the LLM to read per
# read_document_range call when sweeping a full document. 8000 was
# over-conservative: with a 64K-token context (~200K chars) and compaction at
# 80%, 20K-char chunks cut tool-loop rounds roughly in half at zero risk.
READ_CHUNK_CHARS = 20000


# ---------------------------------------------------------------------------
# Tool functions
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
    source = ctx.get("source_text", "")
    total = len(source)

    start = int(tool_input.get("start_char", 0))
    end = int(tool_input.get("end_char", total))
    start = max(0, min(start, total))
    end = max(start, min(end, total))

    return {
        "text": source[start:end],
        "start_char": start,
        "end_char": end,
        "total_chars": total,
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
    source = ctx.get("source_text", "")
    total = len(source)

    query = str(tool_input.get("query", ""))
    max_results = int(tool_input.get("max_results", 3))
    if not query:
        return {"results": [], "total_matches": 0}

    text_lower = source.lower()
    query_lower = query.lower()
    results = []
    total_matches = 0
    pos = 0
    while True:
        idx = text_lower.find(query_lower, pos)
        if idx == -1:
            break
        total_matches += 1
        if len(results) < max_results:
            ctx_start = max(0, idx - 100)
            ctx_end = min(total, idx + len(query) + 100)
            results.append({
                "offset": idx,
                "context": source[ctx_start:ctx_end],
            })
        pos = idx + 1

    return {"results": results, "total_matches": total_matches}


# ---------------------------------------------------------------------------
# Tool metadata for TOOL_DEFINITIONS / TOOL_HANDLERS registration
# ---------------------------------------------------------------------------

DOC_ACCESS_TOOL_DEFINITIONS = [
    {
        "name": "read_document_range",
        "description": (
            "Read a character range from the original source document. "
            "Use this to access any part of the document without truncation. "
            f"For full-document sweeps read in chunks of up to {READ_CHUNK_CHARS} "
            "chars per call; use smaller ranges (≤ 3000 chars) only for focused "
            "re-reading of a specific section."
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
    "search_in_document": search_in_document,
}
