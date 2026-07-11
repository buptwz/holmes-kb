"""Holmes KB MCP server — exposes 4 tools via streamable-http transport.

kb_browse (directory-style pagination), kb_read (two-layer), kb_confirm, kb_draft.
MCP is a passthrough — agent browses KB like a local directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from holmes.config import HolmesConfig, load_config
from holmes.mcp.tools import (
    handle_kb_browse,
    handle_kb_confirm,
    handle_kb_draft,
    handle_kb_read,
)

mcp = FastMCP("holmes-kb")

# Module-level state set by run_server() before mcp.run()
_kb_root: Optional[Path] = None
_config: Optional[HolmesConfig] = None


@mcp.tool()
def kb_browse(
    type: Optional[str] = None,
    category: Optional[str] = None,
    page: int = 1,
    session_id: str = "",
) -> dict:
    """Browse the knowledge base like a directory.

    Call with no params first to see the full index + directory overview.
    Then use type/category filters to narrow down.

    - type: filter by entry type (pitfall/model/guideline/process/decision)
    - category: filter by category slug (e.g. "memory", "pcie/link-training")
    - page: page number (1-based, 50 entries per page)

    Scan the titles and briefs to find entries matching the user's problem.
    Save session_id for kb_confirm calls.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_browse(
        _kb_root, type=type, category=category,
        page=page, session_id=session_id,
    )


@mcp.tool()
def kb_read(
    entry_id: str,
    full: bool = False,
    detail: str = "",
    section: str = "",
    branch: str = "",
    session_id: str = "",
) -> dict:
    """Read a KB entry with progressive disclosure.

    detail levels (mutually exclusive with full):
      - "summary" (default): structured summary + Contents (table of contents)
      - "navigate": Contents section — the structural roadmap (works for ALL types)
      - "full": complete document body with all sections

    section: read a specific ## section by name (e.g. "Root Cause", "Steps").
      Returns that section only. Works for ALL entry types.
      Use kb_read(detail='navigate') first to see available sections.

    branch: read a specific ### resolution branch by label (e.g. "电源子系统").
      Returns the branch content + Symptoms/Root Cause context.
      For pitfall entries with multiple resolution branches.

    Recommended workflow (all types):
      1. kb_read(summary) → see brief + Contents, identify relevant sections
      2. kb_read(section='<name>') → read the section you need
      3. For complex pitfalls with branches:
         kb_read(branch='<label>') → read a specific branch
      4. kb_confirm(outcome='solved'|'not_solved') when done

    Behavior tags in resolution steps:
      [api:read] = execute this read-only command (safe to auto-execute)
      [api:write] = execute this state-changing command (inform user first)
      [api:danger] = IRREVERSIBLE command (firmware flash, disk format) — MUST get user confirmation
      [physical] = ask user to perform physical action (check LED, reseat module)
      [remote] = execute this on a remote system (BMC, switch, management plane)
      [decide] = ask user which condition they observe, then branch accordingly
      [verify] = check the previous step's result — confirms diagnosis or loops back

    Expected: lines after [api:*] steps tell you what normal vs abnormal output looks like.
      Use these to interpret command results and decide the next action.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_read(
        _kb_root, entry_id, full=full, detail=detail,
        section=section, branch=branch, session_id=session_id,
    )


@mcp.tool()
def kb_confirm(entry_id: str, session_id: str, outcome: str = "solved", notes: str = "") -> dict:
    """Record the outcome after using a KB entry.

    Call this after a troubleshooting session completes.
    session_id: use the session_id from kb_browse.
    outcome: "solved" (entry helped resolve the issue) or "not_solved" (did not help).
    notes: optional free-text feedback.

    "solved" promotes the entry's maturity (draft -> verified -> proven).
    "not_solved" is neutral — the entry may still be correct, this is not a judgment.
    Entries without "solved" feedback naturally decay over time.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_confirm(_kb_root, entry_id, session_id, outcome=outcome, notes=notes)


@mcp.tool()
def kb_draft(content: str, title: Optional[str] = None, session_id: str = "") -> dict:
    """Save a draft document for later import — NO LLM processing.

    Use this when you've helped the user resolve an issue and want to capture
    the knowledge for future import. The draft is saved as-is; a human engineer
    runs 'holmes import _drafts/<file>' to structure it into a KB entry.

    content: Full natural-language description — symptoms, root cause, resolution,
             relevant context. More detail is better.
    title:   Optional filename stem (e.g. 'redis-oom-2026-06-23').
    session_id: use the session_id from kb_browse.

    Call kb_draft only when ALL of these are true:
    1. You browsed the KB and found no matching entry
    2. You successfully helped the user resolve the issue
    3. The user agrees the solution is worth preserving
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
