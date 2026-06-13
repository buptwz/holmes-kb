"""Holmes KB MCP server — exposes 6 KB tools via streamable-http transport."""

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
    handle_kb_search,
    handle_kb_submit,
)

mcp = FastMCP("holmes-kb")

# Module-level state set by run_server() before mcp.run()
_kb_root: Optional[Path] = None


@mcp.tool()
def kb_overview() -> dict:
    """Get a structural overview of the knowledge base — entry types, categories,
    frequently used tags, and available skills.

    You MUST call kb_overview at the start of any session in which you may need KB knowledge.
    The response includes a session_id — save it and pass it to kb_confirm when recording evidence.
    Next steps: use kb_search to find entries by keyword, or kb_list to browse by type/category.
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
    """List knowledge entries or skills.

    type: 'pitfall'|'model'|'guideline'|'process'|'decision'|'skill'
    When type='skill', returns skill names and descriptions. category is ignored for skills.
    When type is omitted, lists all entry types.
    You MUST call kb_read on the specific entry or skill before using its content.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_list(_kb_root, type=type, category=category, limit=limit, offset=offset)


@mcp.tool()
def kb_read(entry_id: str, path: Optional[str] = None) -> dict:
    """Read the full content of a KB entry or skill by ID.

    entry_id routing (automatic — no prefix needed):
    - Entry ID format (PT-DB-001): returns entry content + skill_refs list.
      skill_refs values can be passed directly as entry_id to read the linked skill.
    - Skill name format (redis-oom-recovery): returns SKILL.md instructions,
      linked_entries, and files list.
    - Skill name + path: reads a specific file within the skill directory.
      Example: kb_read(id='redis-oom-recovery', path='scripts/check.sh')

    After reading an entry, check skill_refs for linked skills and read them for
    executable remediation steps. After applying guidance and confirming resolution,
    call kb_confirm with the entry_id and your session_id from kb_overview.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_read(_kb_root, entry_id, path=path)


@mcp.tool()
def kb_search(
    query: str,
    type: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """Search the knowledge base by keyword query.

    Returns ranked entries matching the query across title, tags, and body.
    type: optional filter by entry type (pitfall|model|guideline|process|decision).
    Note: skills are not included in the search index — use kb_list(type='skill') for skills.

    After identifying relevant entries, call kb_read to read their full content.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_search(_kb_root, query=query, type=type, limit=limit)


@mcp.tool()
def kb_confirm(entry_id: str, session_id: str) -> dict:
    """Record that a KB entry successfully helped resolve the current issue.

    This writes a validated evidence record that improves the entry's maturity score.

    session_id: use the session_id returned by kb_overview for this session.
    Duplicate confirms with the same session_id and entry_id are silently ignored.

    You MUST call kb_confirm when ALL of the following are true:
    1. You called kb_read on this entry during the current session
    2. You applied the entry's guidance (executed steps, ran the skill, etc.)
    3. The user has explicitly confirmed that the issue is now resolved

    You MUST NOT call kb_confirm if the resolution failed or was only partial.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_confirm(_kb_root, entry_id, session_id)


@mcp.tool()
def kb_submit(
    title: str,
    type: str,
    content: str,
    session_id: str,
    category: Optional[str] = None,
    tags: Optional[list] = None,
) -> dict:
    """Submit a new knowledge entry for human review when the problem pattern is NOT in the KB.

    session_id: use the session_id returned by kb_overview for this session.
    type: pitfall|model|guideline|process|decision
    content: Markdown body with appropriate sections (## Symptoms, ## Root Cause, ## Resolution
    for pitfalls; ## Steps for processes; ## Rule for guidelines; etc.)

    You MUST call kb_submit only when:
    1. You searched/browsed the KB and found no matching entry
    2. You successfully helped the user resolve the issue
    3. The user agrees the solution is worth preserving

    Do NOT submit if a similar entry already exists — use kb_confirm instead.
    After submitting, tell the user: "Submitted for review. Publish with: holmes kb confirm <id>"
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_submit(
        _kb_root, title=title, type=type, content=content,
        session_id=session_id, category=category, tags=tags,
    )


def run_server(kb_root: Path, port: int = 8765) -> None:
    """Start the Holmes KB MCP server.

    Args:
        kb_root: Path to the knowledge base root directory.
        port: HTTP port to listen on (default 8765).
    """
    global _kb_root

    if not kb_root.exists():
        raise ValueError(f"KB root does not exist: {kb_root}")

    _kb_root = kb_root

    mcp.settings.port = port
    mcp.run(transport="streamable-http")
