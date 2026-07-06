"""Holmes KB MCP server — exposes 6 KB tools via streamable-http transport."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from holmes.config import HolmesConfig, load_config
from holmes.mcp.tools import (
    handle_kb_confirm,
    handle_kb_draft,
    handle_kb_list,
    handle_kb_overview,
    handle_kb_read,
    handle_kb_search,
)

mcp = FastMCP("holmes-kb")

# Module-level state set by run_server() before mcp.run()
_kb_root: Optional[Path] = None
_config: Optional[HolmesConfig] = None


@mcp.tool()
def kb_overview() -> dict:
    """Get the full knowledge base index and troubleshooting protocol.

    Returns a complete entry index grouped by type → category, plus a
    'troubleshooting_protocol' that teaches you how to guide users through
    diagnostic procedures step by step.

    You MUST call kb_overview at the start of any session. The response includes:
    - index: all entries organized by type and category — browse to find matching failures
    - troubleshooting_protocol: step-by-step guide for how to use the KB during troubleshooting
    - session_id: save it and pass to kb_confirm when recording feedback
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_overview(_kb_root)


@mcp.tool()
def kb_list(
    type: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    session_id: str = "",
) -> dict:
    """List knowledge entries or skills with filtering and pagination.

    type filter (omit to list all):
      pitfall   — known failure patterns: symptoms → root cause → resolution
      process   — step-by-step diagnostic procedures (often children of a pitfall)
      model     — mental models and decision frameworks
      guideline — operational best practices and standards
      decision  — architecture/design decision records
      skill     — executable remediation scripts and instructions

    When type='skill', returns skill names and descriptions. category is ignored for skills.
    You MUST call kb_read on the specific entry or skill before using its content.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_list(_kb_root, type=type, category=category, limit=limit, offset=offset, session_id=session_id)


@mcp.tool()
def kb_read(entry_id: str, path: Optional[str] = None, session_id: str = "") -> dict:
    """Read a KB entry or skill. Returns content + tree navigation + usage guidance.

    The response includes a 'usage_guide' field with type-specific instructions:
    - pitfall entries: tells you to check Symptoms match, then read children for diagnostic steps
    - process entries: explains behavior tags ([api], [decide], [physical], etc.) and
      instructs you to present steps ONE AT A TIME, waiting for user feedback

    entry_id accepts any format: PT-DB-001, gpu-init-root-001, or skill names.
    For skills, optional path= reads a specific file (e.g. path='scripts/check.sh').

    Pitfall entries return 'children' (diagnostic procedures to walk through).
    Process entries return 'parent' (the overall failure pattern for context).
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_read(_kb_root, entry_id, path=path, session_id=session_id)


@mcp.tool()
def kb_search(
    query: str,
    type: Optional[str] = None,
    limit: int = 10,
    session_id: str = "",
) -> dict:
    """Search the knowledge base by keyword or natural language query.

    Supports cross-language matching — queries in Chinese find English entries
    and vice versa. Technical terms, error codes, and command names are matched
    precisely. Results are ranked by BM25 relevance with IDF weighting.

    SEARCH TIPS:
    - Symptom description: "redis connection timeout under load"
    - Error message verbatim: "ERR max number of clients reached"
    - Component + problem: "kafka consumer lag"
    - Chinese query for English entries: "连接池耗尽" finds "Connection Pool Exhausted"
    - If no results, try broader terms or different language

    type: optional filter by entry type (pitfall|model|guideline|process|decision).
    Note: skills are not included in the search index — use kb_list(type='skill') for skills.

    After identifying relevant entries, call kb_read to read their full content.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_search(_kb_root, query=query, type=type, limit=limit, session_id=session_id)


@mcp.tool()
def kb_confirm(entry_id: str, session_id: str, outcome: str = "solved", notes: str = "") -> dict:
    """Record usage feedback for a KB entry after applying its guidance.

    session_id: use the session_id returned by kb_overview.
    outcome: "solved" (fully resolved), "partial" (helped but incomplete), or "wrong" (incorrect/misleading).
    notes: optional free-text feedback (e.g. "step 3 was outdated", "missing GPU firmware check").

    Only "solved" outcome promotes maturity. "wrong" flags the entry for maintainer review.
    Duplicate confirms with the same session_id and entry_id are silently ignored.

    Call this after applying an entry's guidance:
    - outcome="solved": the issue is fully resolved
    - outcome="partial": the entry helped but didn't fully solve the problem
    - outcome="wrong": the entry's guidance was incorrect or misleading
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_confirm(_kb_root, entry_id, session_id, outcome=outcome, notes=notes)


@mcp.tool()
def kb_draft(content: str, title: Optional[str] = None, session_id: str = "") -> dict:
    """Save a draft document for later import — NO LLM processing.

    Use this when you've helped the user resolve an issue and want to capture
    the knowledge for future import.  The draft is saved as-is; a human engineer
    runs 'holmes import _drafts/<file>' to structure it into KB entries.

    content: Full natural-language description — symptoms, root cause, resolution,
             relevant context (service, environment, commands).  More detail is better.
    title:   Optional filename stem (e.g. 'redis-oom-2026-06-23').
             Defaults to a timestamp if omitted.
    session_id: use the session_id returned by kb_overview for this session.

    You MUST call kb_draft only when ALL of the following are true:
    1. You searched/browsed the KB and found no matching entry for this problem
    2. You successfully helped the user resolve the issue
    3. The user agrees the solution is worth preserving

    The draft is saved immediately (< 1 second, no LLM).
    Tell the user: "Draft saved. Import with: holmes import _drafts/<file>"
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    assert _config is not None, "Config not loaded — call run_server() first"
    return handle_kb_draft(
        _kb_root,
        content=content,
        title=title,
        config=_config,
        session_id=session_id,
    )


def run_server(kb_root: Path, port: int = 8765) -> None:
    """Start the Holmes KB MCP server.

    Args:
        kb_root: Path to the knowledge base root directory.
        port: HTTP port to listen on (default 8765).
    """
    global _kb_root, _config

    if not kb_root.exists():
        raise ValueError(f"KB root does not exist: {kb_root}")

    _kb_root = kb_root
    _config = load_config()

    # Rebuild index.json on startup so it reflects any git-pulled changes.
    try:
        from holmes.kb.store import rebuild_index_files
        rebuild_index_files(kb_root)
    except Exception:
        pass  # Non-fatal — find_entry has rglob fallback

    mcp.settings.port = port
    mcp.settings.stateless_http = True
    mcp.run(transport="streamable-http")
