"""Holmes KB MCP server — exposes 4 tools via streamable-http transport.

kb_browse (directory-style pagination), kb_read (two-layer), kb_confirm, kb_draft.
MCP is a passthrough — agent browses KB like a local directory.

Deployment modes (spec 043 D4):
  local   — loopback bind, git-config identity fallback, no auth (default)
  central — external bind, contributor param enforced on kb_confirm/kb_draft,
            static bearer token auth via FastMCP's TokenVerifier mechanism
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
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
_mode: str = "local"


class StaticTokenVerifier(TokenVerifier):
    """Verify a bearer token against a single static token from config.

    Central mode is a small trusted deployment — one shared token, no OAuth.
    """

    def __init__(self, token: str):
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != self._token:
            return None
        return AccessToken(token=token, client_id="holmes-central", scopes=[])


@mcp.tool()
def kb_browse(
    type: Optional[str] = None,
    category: Optional[str] = None,
    page: int = 1,
    session_id: str = "",
    contributor: str = "",
    product_line: Optional[str] = None,
    test_stage: Optional[str] = None,
    strict: bool = False,
) -> dict:
    """Browse the knowledge base like a directory — ALWAYS the first call of a session.

    Start here with no params: you get page 1 of the index, a directory
    overview (type/category counts), and a `guide` field with the full
    troubleshooting methodology — read it. Then narrow down with filters.

    - type: filter by entry type (pitfall/model/guideline/process/decision)
    - category: filter by category slug (e.g. "memory", "pcie/link-training")
    - page: page number (1-based, 50 entries per page)
    - session_id: leave empty on the first call — the response returns a new
      session_id (a full uuid). Carry that exact value on EVERY follow-up
      call (kb_read/kb_confirm/kb_draft); kb_confirm rejects empty session_id.
    - contributor: your identity (e.g. your agent/product name); declare it on
      every call — kb_confirm/kb_draft require it in central mode
    - product_line / test_stage: applicability filter — entries whose
      applies_to matches rank first; entries without applies_to are universal
      and always returned
    - strict: when True, hard-filter out entries whose applies_to does not
      match (default False: they are only ranked lower)

    Scan the titles and briefs to find entries matching the user's problem.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_browse(
        _kb_root, type=type, category=category,
        page=page, session_id=session_id, contributor=contributor,
        product_line=product_line, test_stage=test_stage, strict=strict,
    )


@mcp.tool()
def kb_read(
    entry_id: str,
    full: bool = False,
    detail: str = "",
    section: str = "",
    branch: str = "",
    session_id: str = "",
    contributor: str = "",
) -> dict:
    """Read a KB entry — use progressive disclosure, cheapest first.

    Read strategy (stop as soon as you have what you need):
      1. summary (default): brief + structured summary + Contents — enough to
         judge relevance. Never read full content before a summary.
      2. section='<name>': one ## section by name (works for ALL types).
         Use detail='navigate' to list available sections first.
      3. branch='<label>': one ### resolution branch of a pitfall entry —
         returns that branch plus Symptoms/Root Cause context.
      4. detail='full' (or full=True): the complete document. Last resort.

    detail levels (mutually exclusive with full): "summary" (default),
    "navigate" (Contents only), "full" (complete body).

    session_id: pass the session_id from kb_browse — a full read records a
    reference for that session, which a later kb_confirm upgrades.
    contributor: your identity — recorded as the evidence author.

    Behavior tags in resolution steps:
      [api:read] = read-only command — you may run it directly
      [api:write] = state-changing command — tell the user before running
      [api:danger] = IRREVERSIBLE command (firmware flash, disk format) — MUST get user confirmation
      [physical] = physical action (check LED, reseat module) — ask the user to do it
      [remote] = run on a remote system (BMC, switch, management plane)
      [decide] = branch point — ask the user which condition they observe
      [verify] = check the previous step's result — confirms diagnosis or loops back

    Expected: lines after [api:*] steps tell you what normal vs abnormal output looks like.
      Use these to interpret command results and decide the next action.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_read(
        _kb_root, entry_id, full=full, detail=detail,
        section=section, branch=branch, session_id=session_id,
        contributor=contributor,
    )


@mcp.tool()
def kb_confirm(
    entry_id: str,
    session_id: str,
    outcome: str = "solved",
    notes: str = "",
    contributor: str = "",
) -> dict:
    """Record the outcome after using a KB entry — call this every time.

    Call after a troubleshooting session completes, whether or not the entry
    helped. Feedback is what keeps the KB trustworthy.

    session_id: REQUIRED — pass the session_id returned by kb_browse. Empty
      session_id is rejected (call kb_browse first to get one). If you did a
      full kb_read in the same session, this confirm UPGRADES that recorded
      reference instead of being rejected as a duplicate.
    outcome: "solved" (entry helped resolve the issue) or "not_solved" (did not help).
    notes: optional free-text feedback.
    contributor: REQUIRED in central mode — your identity (e.g. your
      agent/product name); in local mode it falls back to git config /
      hostname. Maturity promotion counts distinct contributors, so always
      declare it.

    "solved" promotes the entry's maturity (draft -> verified -> proven).
    "not_solved" is neutral — the entry may still be correct, this is not a judgment.
    Entries without "solved" feedback naturally decay over time.
    """
    assert _kb_root is not None, "KB root not set — call run_server() first"
    return handle_kb_confirm(
        _kb_root, entry_id, session_id, outcome=outcome, notes=notes,
        contributor=contributor, require_contributor=(_mode == "central"),
    )


@mcp.tool()
def kb_draft(
    content: str,
    title: Optional[str] = None,
    session_id: str = "",
    contributor: str = "",
) -> dict:
    """Save a draft document for later import — NO LLM processing.

    Use this when you've helped the user resolve an issue and want to capture
    the knowledge for future import. The draft is saved as-is; a human engineer
    runs 'holmes import _drafts/<file>' to structure it into a KB entry.

    content: Full natural-language description — symptoms, root cause, resolution,
             relevant context. More detail is better.
    title:   Optional filename stem (e.g. 'redis-oom-2026-06-23').
    session_id: pass the session_id from kb_browse.
    contributor: your identity — recorded as the draft author; REQUIRED in
      central mode.

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
        contributor=contributor,
        require_contributor=(_mode == "central"),
    )


def run_server(
    kb_root: Path,
    port: int = 8765,
    host: str = "127.0.0.1",
    mode: str = "local",
) -> None:
    """Start the Holmes KB MCP server.

    Args:
        kb_root: Path to the knowledge base root directory.
        port: HTTP port to listen on (default 8765).
        host: Interface to bind (default 127.0.0.1; central default 0.0.0.0
              is resolved by the CLI before calling).
        mode: "local" (no auth, git-config identity fallback) or "central"
              (bearer token auth, contributor param enforced). Central mode
              requires config.mcp_token to be set.
    """
    global _kb_root, _config, _mode

    if not kb_root.exists():
        raise ValueError(f"KB root does not exist: {kb_root}")
    if mode not in ("local", "central"):
        raise ValueError(f"Unknown mode: {mode!r} (expected 'local' or 'central')")

    _kb_root = kb_root
    _config = load_config()
    _mode = mode

    if mode == "central":
        token = _config.mcp_token
        if not token:
            raise ValueError(
                "central mode requires a token — run: holmes config set mcp_token <token>"
            )
        mcp.settings.auth = AuthSettings(
            issuer_url=f"http://{host}:{port}",
            resource_server_url=f"http://{host}:{port}",
        )
        # FastMCP wires this into BearerAuthMiddleware on the HTTP routes.
        mcp._token_verifier = StaticTokenVerifier(token)

    # Rebuild index.json on startup so it reflects any git-pulled changes.
    try:
        from holmes.kb.store import rebuild_index_files
        rebuild_index_files(kb_root)
    except Exception:
        pass  # Non-fatal — find_entry has rglob fallback

    mcp.settings.host = host
    mcp.settings.port = port
    mcp.settings.stateless_http = True
    mcp.run(transport="streamable-http")
