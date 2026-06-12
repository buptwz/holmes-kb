"""Holmes KB MCP server — exposes 5 KB tools via streamable-http transport."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from holmes.mcp.tools import (
    handle_kb_confirm,
    handle_kb_list,
    handle_kb_overview,
    handle_kb_read,
    handle_kb_submit,
)

mcp = FastMCP("holmes-kb")

# Module-level state set by run_server() before mcp.run()
_kb_root: Optional[Path] = None
_session_id: str = str(uuid4())[:8]


@mcp.tool()
def kb_overview() -> dict:
    """Get a structural overview of the knowledge base — available entry types, categories, and frequently used tags.

    You MUST call kb_overview at the start of any session in which you may need KB knowledge, before
    deciding which category to browse. This gives you the vocabulary and scope of what's available
    so you can formulate accurate follow-up calls to kb_list. Do NOT skip this call and jump directly
    to kb_list with a guessed category — you may miss relevant entries entirely.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_overview(_kb_root)


@mcp.tool()
def kb_list(
    type: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """List knowledge entries filtered by type and/or category, with brief content previews.

    You MUST call kb_list after kb_overview to browse entries in a relevant category. Scan the
    returned titles and briefs to identify which entries match the current problem — do NOT read
    every entry blindly. When the list is long, use limit and offset to paginate. You MUST call
    kb_read on the specific entry before presenting its guidance to the user.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_list(_kb_root, type=type, category=category, limit=limit, offset=offset)


@mcp.tool()
def kb_read(entry_id: str) -> dict:
    """Read the complete content of a KB entry by ID. Returns the full Markdown including all sections
    (Symptoms, Root Cause, Resolution for pitfalls; Steps for processes; script code for skills).

    You MUST call kb_read before using any entry's guidance — never act on just the brief from kb_list.
    For skill entries, the content will contain executable script code: you MUST create the script
    locally and execute it yourself using your bash capability; do NOT ask the user to run it manually
    unless the script requires credentials or elevated permissions you cannot access.

    This tool does NOT record any evidence. Reading an entry is not a signal of its usefulness.
    You MUST call kb_confirm separately after the entry has demonstrably helped resolve the issue.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_read(_kb_root, entry_id)


@mcp.tool()
def kb_confirm(entry_id: str) -> dict:
    """Record that a KB entry successfully helped resolve the current issue. This writes a validated
    evidence record that improves the entry's maturity score and elevates it in future search results.

    You MUST call kb_confirm when ALL of the following are true:
    1. You called kb_read on this entry during the current session
    2. You applied the entry's guidance (executed steps, ran the skill script, etc.)
    3. The user has explicitly confirmed that the issue is now resolved

    You MUST NOT call kb_confirm if:
    - The user has not yet confirmed the issue is resolved
    - You read the entry but decided it was not relevant
    - The resolution steps failed or only partially helped

    For skill entries: if the skill script executed successfully AND the user confirms the outcome
    is correct, you MUST call kb_confirm immediately without waiting for further prompting.

    Duplicate confirms within the same server session are silently ignored — safe to call once per
    entry per session.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_confirm(_kb_root, entry_id, _session_id)


@mcp.tool()
def kb_submit(
    title: str,
    type: str,
    content: str,
    category: Optional[str] = None,
    tags: Optional[list] = None,
) -> dict:
    """Submit a new knowledge entry for human review when you have encountered a problem pattern
    that is NOT already in the KB.

    You MUST call kb_submit when ALL of the following are true:
    1. You searched or browsed the KB and found no matching entry for the current problem
    2. You successfully helped the user resolve the issue
    3. The user agrees the solution is worth preserving

    You MUST NOT call kb_submit if a similar entry already exists — use kb_confirm on the existing
    entry instead. Do NOT submit low-quality, incomplete, or speculative entries. The content MUST
    include clear Symptoms, Root Cause, and Resolution sections for pitfall entries.

    After submitting, inform the user: "I've submitted this knowledge for review. A maintainer can
    publish it with: holmes kb confirm <id>"
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_submit(
        _kb_root, title=title, type=type, content=content,
        session_id=_session_id, category=category, tags=tags,
    )


def run_server(kb_root: Path, port: int = 8765) -> None:
    """Start the Holmes KB MCP server.

    Args:
        kb_root: Path to the knowledge base root directory.
        port: HTTP port to listen on (default 8765).
    """
    global _kb_root, _session_id

    if not kb_root.exists():
        raise ValueError(f"KB root does not exist: {kb_root}")

    _kb_root = kb_root
    _session_id = str(uuid4())[:8]

    mcp.settings.port = port
    mcp.run(transport="streamable-http")
