"""Holmes CLI entry point.

Commands:
  holmes                    — start TUI (alias for 'holmes tui')
  holmes tui                — start TUI
  holmes agent start        — start agent IPC server
  holmes config init        — interactive config wizard
  holmes config show        — display current config
  holmes config set <key> <value> — set a config value
  holmes import <file>      — import a knowledge document
  holmes kb pending         — list pending entries
  holmes kb pending show <id> — show a pending entry
  holmes kb confirm <id>    — confirm (3-gate validate) a pending entry
  holmes kb reject <id>     — reject a pending entry
  holmes kb merge <id>      — merge a pending entry into the KB
  holmes kb resolve <id>    — resolve a conflict
  holmes kb lint            — run KB health check
  holmes kb rebuild-index   — rebuild index.json and _index.md
  holmes kb list            — list all KB entries
  holmes kb show <id>       — show a KB entry
  holmes session list       — list sessions
  holmes session show <id>  — show a session
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click

from holmes.config import HolmesConfig, load_config, save_config, update_config, HOLMES_DIR
from holmes.kb.index_builder import rebuild_index
from holmes.kb.linter import lint
from holmes.kb.pending import (
    get_pending,
    list_pending,
    reject_pending,
    _next_sequential_id,
    _append_log,
)
from holmes.kb.store import get_entry, list_entries
from holmes.kb.validator import validate_entry, ValidationError
from holmes.kb.merger import merge_entry
from holmes.kb.conflict import list_conflicts, resolve_conflict as _resolve_conflict
from holmes.agent.session import list_sessions, load_session
from holmes.logging_config import configure_logging, get_logger


logger = get_logger("cli")


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Holmes — AI-powered troubleshooting assistant backed by a knowledge base."""
    configure_logging()
    if ctx.invoked_subcommand is None:
        # Default: start TUI
        ctx.invoke(tui)


@cli.command()
def tui() -> None:
    """Start the Holmes TUI."""
    config = load_config()
    if not config.kb_path:
        click.echo(
            "⚠  Knowledge base path not configured.\n"
            "   Run: holmes config init",
            err=True,
        )
        sys.exit(1)

    # Start agent server in background and launch TUI
    import signal
    import tempfile

    socket_path = f"/tmp/holmes-{os.getpid()}.sock"

    # Start agent subprocess
    agent_proc = subprocess.Popen(
        [sys.executable, "-m", "holmes.agent_server", f"--socket={socket_path}"],
        env=os.environ.copy(),
    )

    # Wait until socket is ready (up to 8 seconds)
    import time
    deadline = time.time() + 8.0
    while not os.path.exists(socket_path):
        if time.time() > deadline:
            click.echo("Error: agent failed to start within 8 seconds.", err=True)
            agent_proc.terminate()
            sys.exit(1)
        if agent_proc.poll() is not None:
            click.echo("Error: agent process exited unexpectedly.", err=True)
            sys.exit(1)
        time.sleep(0.1)

    # Find bun
    bun = os.path.expanduser("~/.bun/bin/bun")
    if not os.path.exists(bun):
        bun = "bun"  # fallback to PATH

    # Start TUI subprocess (Bun)
    tui_dir = Path(__file__).parent.parent.parent / "tui"
    tui_script = tui_dir / "src" / "main.tsx"

    if not tui_script.exists():
        click.echo(f"TUI not found at {tui_script}.", err=True)
        agent_proc.terminate()
        sys.exit(1)

    try:
        subprocess.run(
            [bun, "run", str(tui_script), f"--socket={socket_path}"],
            cwd=str(tui_dir),
        )
    finally:
        agent_proc.terminate()
        agent_proc.wait()


# ---- Config commands ----

@cli.group()
def config() -> None:
    """Manage Holmes configuration."""


@config.command("init")
def config_init() -> None:
    """Interactive configuration wizard."""
    click.echo("Holmes Configuration Setup\n")
    current = load_config()

    kb_path = click.prompt(
        "Knowledge base path (local clone of KB git repository)",
        default=current.kb_path or str(Path.home() / "holmes-kb"),
    )
    kb_path_obj = Path(kb_path).expanduser().resolve()
    if not kb_path_obj.exists():
        if click.confirm(f"Directory {kb_path_obj} does not exist. Create it?", default=True):
            kb_path_obj.mkdir(parents=True)
    else:
        click.echo(f"  ✓ Found {kb_path_obj}")

    api_base_url = click.prompt(
        "API base URL (OpenAI-compatible endpoint)",
        default=current.api_base_url or "https://api.openai.com/v1",
    )
    api_key = click.prompt(
        "API key",
        default=current.api_key or "",
        hide_input=True,
    )
    model = click.prompt(
        "Model name",
        default=current.model or "gpt-4o",
    )

    HOLMES_DIR.mkdir(parents=True, exist_ok=True)
    new_config = HolmesConfig(
        kb_path=str(kb_path_obj),
        model=model,
        api_base_url=api_base_url,
        api_key=api_key,
        mcp_servers=current.mcp_servers,
    )
    save_config(new_config)
    click.echo(f"\n✓ Configuration saved to {HOLMES_DIR / 'config.json'}")


@config.command("show")
def config_show() -> None:
    """Display current configuration."""
    cfg = load_config()
    click.echo(f"KB path:     {cfg.kb_path or '(not set)'}")
    click.echo(f"API URL:     {cfg.api_base_url or '(not set)'}")
    click.echo(f"Model:       {cfg.model}")
    click.echo(f"Log level:   {cfg.log_level}")
    click.echo(f"MCP servers: {len(cfg.mcp_servers)}")


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a configuration value."""
    try:
        cfg = update_config({key: value})
        click.echo(f"✓ Set {key} = {value}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# ---- Import command ----

@cli.command("import")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--type", "kb_type", default=None, help="Force KB type (pitfall/model/guideline/process/decision)")
@click.option("--category", default=None, help="Force category (for pitfall: network/system/application/database)")
@click.option("--dry-run", is_flag=True, help="Preview without writing")
def import_cmd(file: Path, kb_type: Optional[str], category: Optional[str], dry_run: bool) -> None:
    """Import a knowledge document into the KB pending area."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured. Run: holmes config init", err=True)
        sys.exit(1)

    from holmes.kb.importer import import_document

    async def _run():
        return await import_document(
            Path(cfg.kb_path),
            file,
            model=cfg.model,
            api_base_url=cfg.api_base_url,
            api_key=cfg.api_key,
            kb_type=kb_type,
            category=category,
            dry_run=dry_run,
        )

    result = asyncio.run(_run())
    click.echo(f"Type:     {result.kb_type}")
    click.echo(f"Title:    {result.title}")
    click.echo(f"Category: {result.category or '(none)'}")
    if dry_run:
        click.echo("\n--- Preview (dry run, not saved) ---")
        click.echo(result.content_preview)
    else:
        click.echo(f"\n✓ Saved as pending entry: {result.pending_id}")
        click.echo(f"  Review with: holmes kb pending show {result.pending_id}")
        click.echo(f"  Confirm with: holmes kb confirm {result.pending_id}")


# ---- KB commands ----

@cli.group()
def kb() -> None:
    """Knowledge base management commands."""


@kb.command("pending")
def kb_pending() -> None:
    """List all pending entries awaiting confirmation."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    entries = list_pending(Path(cfg.kb_path))
    if not entries:
        click.echo("No pending entries.")
        return
    click.echo(f"{'ID':<40} {'TYPE':<12} {'TITLE':<40} CREATED")
    click.echo("-" * 100)
    for e in entries:
        click.echo(f"{e['id']:<40} {e['type']:<12} {e['title'][:38]:<40} {e['created_at'][:10]}")


@kb.command("pending-show")
@click.argument("pending_id")
def kb_pending_show(pending_id: str) -> None:
    """Show the full content of a pending entry."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    result = get_pending(Path(cfg.kb_path), pending_id)
    if result is None:
        click.echo(f"Pending entry not found: {pending_id}", err=True)
        sys.exit(1)
    path, post = result
    import frontmatter
    click.echo(frontmatter.dumps(post))


@kb.command("confirm")
@click.argument("pending_id")
def kb_confirm(pending_id: str) -> None:
    """Confirm a pending entry (runs 3-gate validation)."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    kb_root = Path(cfg.kb_path)
    result = get_pending(kb_root, pending_id)
    if result is None:
        click.echo(f"Pending entry not found: {pending_id}", err=True)
        sys.exit(1)

    path, post = result
    import frontmatter
    content = frontmatter.dumps(post)

    # Gate 1 + 2: Schema + duplicate detection
    click.echo("Gate 1: Schema validation...")
    try:
        validation = validate_entry(kb_root, content)
    except ValidationError as e:
        click.echo(f"✗ Schema validation failed: {e}", err=True)
        sys.exit(1)
    click.echo("  ✓ Schema valid")

    if validation["duplicates"]["similar_entries"]:
        click.echo("Gate 2: Similar entries found:")
        for sim in validation["duplicates"]["similar_entries"]:
            click.echo(f"  - {sim['id']} ({sim['title']}) — similarity: {sim['similarity']:.0%}")
        if not click.confirm("Duplicates detected. Confirm anyway?", default=False):
            click.echo("Aborted.")
            sys.exit(0)
    else:
        click.echo("  ✓ No duplicates")

    # Gate 3: Forced preview
    click.echo("\nGate 3: Entry preview:")
    click.echo("─" * 60)
    click.echo(content[:800])
    if len(content) > 800:
        click.echo(f"... ({len(content) - 800} more chars)")
    click.echo("─" * 60)
    if not click.confirm("Confirm this entry?", default=True):
        click.echo("Aborted.")
        sys.exit(0)

    # Assign permanent ID
    kb_type = str(post.metadata.get("type", "pitfall"))
    category = post.metadata.get("category")
    new_id = _next_sequential_id(kb_root, kb_type, category)
    post.metadata["id"] = new_id

    # Write to proper location
    from holmes.kb.store import KnowledgeEntry, write_entry
    from datetime import datetime, timezone

    entry = KnowledgeEntry(
        id=new_id,
        type=kb_type,  # type: ignore[arg-type]
        title=str(post.metadata.get("title", "")),
        maturity=str(post.metadata.get("maturity", "draft")),  # type: ignore[arg-type]
        category=post.metadata.get("category"),
        tags=post.metadata.get("tags", []),
        created_at=str(post.metadata.get("created_at", datetime.now(timezone.utc).isoformat())),
        updated_at=datetime.now(timezone.utc).isoformat(),
        body=post.content,
    )
    write_entry(kb_root, entry)

    # Remove from pending
    path.unlink()
    rebuild_index(kb_root)
    _append_log(kb_root, "confirmed", new_id, entry.title)
    click.echo(f"\n✓ Entry confirmed: {new_id}")
    click.echo(f"  View with: holmes kb show {new_id}")


@kb.command("reject")
@click.argument("pending_id")
@click.option("--reason", default="", help="Rejection reason")
def kb_reject(pending_id: str, reason: str) -> None:
    """Reject and delete a pending entry."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    ok = reject_pending(Path(cfg.kb_path), pending_id, reason)
    if ok:
        click.echo(f"✓ Rejected and deleted: {pending_id}")
    else:
        click.echo(f"Entry not found: {pending_id}", err=True)
        sys.exit(1)


@kb.command("merge")
@click.argument("pending_id")
def kb_merge(pending_id: str) -> None:
    """Merge a pending entry into the KB (handles 5 conflict scenarios)."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    kb_root = Path(cfg.kb_path)
    result = get_pending(kb_root, pending_id)
    if result is None:
        click.echo(f"Pending entry not found: {pending_id}", err=True)
        sys.exit(1)
    path, post = result
    import frontmatter
    content = frontmatter.dumps(post)
    merge_result = merge_entry(kb_root, content)
    scenario = merge_result["scenario"]
    click.echo(f"✓ Merge completed (scenario: {scenario})")
    if scenario == "content_contradiction":
        click.echo(f"  Conflict ID: {merge_result.get('conflict_id')}")
        click.echo("  Resolve with: holmes kb resolve <conflict_id>")
    else:
        click.echo(f"  Entry ID: {merge_result.get('entry_id')}")
    # Remove pending entry after merge
    path.unlink()


@kb.command("resolve")
@click.argument("conflict_id")
def kb_resolve(conflict_id: str) -> None:
    """Mark a conflict as resolved."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    ok = _resolve_conflict(Path(cfg.kb_path), conflict_id)
    if ok:
        click.echo(f"✓ Conflict {conflict_id} marked as resolved")
    else:
        click.echo(f"Conflict not found: {conflict_id}", err=True)
        sys.exit(1)


@kb.command("lint")
@click.option("--fix", is_flag=True, help="Auto-fix issues where possible")
def kb_lint(fix: bool) -> None:
    """Run knowledge base health check."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    results = lint(Path(cfg.kb_path), fix=fix)
    click.echo(f"Entries: {results['total_entries']}  Pending: {results['pending_count']}  Conflicts: {results['conflict_count']}")
    if results["warnings"]:
        click.echo("\nWarnings:")
        for w in results["warnings"]:
            click.echo(f"  ⚠ {w}")
    if results["errors"]:
        click.echo("\nErrors:")
        for e in results["errors"]:
            click.echo(f"  ✗ {e}")
    if results["fixes_applied"]:
        click.echo("\nFixes applied:")
        for f in results["fixes_applied"]:
            click.echo(f"  ✓ {f}")
    if not results["warnings"] and not results["errors"]:
        click.echo("\n✓ Knowledge base is healthy")


@kb.command("rebuild-index")
def kb_rebuild_index() -> None:
    """Rebuild index.json and all _index.md files."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    index = rebuild_index(Path(cfg.kb_path))
    click.echo(f"✓ Index rebuilt: {index['total_entries']} entries")


@kb.command("list")
@click.option("--type", "kb_type", default=None)
@click.option("--limit", default=50)
def kb_list(kb_type: Optional[str], limit: int) -> None:
    """List knowledge base entries."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    entries = list_entries(Path(cfg.kb_path), kb_type)  # type: ignore[arg-type]
    entries = entries[:limit]
    if not entries:
        click.echo("No entries found.")
        return
    click.echo(f"{'ID':<20} {'TYPE':<12} {'MATURITY':<10} TITLE")
    click.echo("-" * 80)
    for e in entries:
        click.echo(f"{e.id:<20} {e.type:<12} {e.maturity:<10} {e.title[:40]}")


@kb.command("show")
@click.argument("entry_id")
def kb_show(entry_id: str) -> None:
    """Show a KB entry's full content."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    entry = get_entry(Path(cfg.kb_path), entry_id)
    if entry is None:
        click.echo(f"Entry not found: {entry_id}", err=True)
        sys.exit(1)
    click.echo(entry.to_frontmatter_str())


# ---- Session commands ----

@cli.group()
def session() -> None:
    """Session management commands."""


@session.command("list")
@click.option("--status", default=None, help="Filter by status: active/resolved/abandoned")
@click.option("--limit", default=20)
def session_list(status: Optional[str], limit: int) -> None:
    """List sessions."""
    sessions = list_sessions(status=status, limit=limit)
    if not sessions:
        click.echo("No sessions found.")
        return
    click.echo(f"{'ID':<12} {'STATUS':<12} {'MSGS':<6} {'UPDATED':<22} TITLE")
    click.echo("-" * 90)
    for s in sessions:
        click.echo(
            f"{s['id'][:8]:<12} {s['status']:<12} {s['message_count']:<6} "
            f"{s['updated_at'][:19]:<22} {s['title'][:30]}"
        )


@session.command("show")
@click.argument("session_id")
def session_show(session_id: str) -> None:
    """Show a session's messages."""
    s = load_session(session_id)
    if s is None:
        # Try prefix match
        from holmes.agent.session import SESSIONS_DIR
        matches = list(SESSIONS_DIR.glob(f"{session_id}*.json"))
        if len(matches) == 1:
            import json
            with matches[0].open() as f:
                data = json.load(f)
            from holmes.agent.session import Session
            s = Session(**data)
        else:
            click.echo(f"Session not found: {session_id}", err=True)
            sys.exit(1)

    click.echo(f"Session: {s.id}")
    click.echo(f"Status:  {s.status}")
    click.echo(f"Title:   {s.title}")
    click.echo(f"Created: {s.created_at}")
    click.echo(f"Updated: {s.updated_at}")
    click.echo()
    for msg in s.messages:
        role_label = "You" if msg.role == "user" else "Holmes"
        click.echo(f"[{msg.timestamp[:19]}] {role_label}:")
        click.echo(f"  {msg.content[:200]}")
        click.echo()


# ---- MCP server ----


@cli.command("start")
@click.option("--kb-path", envvar="HOLMES_KB_PATH", default=None,
              help="Path to the knowledge base directory.")
@click.option("--port", default=8765, help="Port for MCP server (default: 8765)")
def start(kb_path: Optional[str], port: int) -> None:
    """Start the Holmes KB MCP server (streamable-http transport).

    Client config: {"url": "http://localhost:<port>"}
    """
    from pathlib import Path as _Path

    if not kb_path:
        cfg = load_config()
        kb_path = cfg.kb_path
    if not kb_path:
        click.echo("KB path not configured. Set --kb-path or run: holmes config init", err=True)
        sys.exit(1)

    kb_root = _Path(kb_path).expanduser().resolve()
    click.echo(f"Holmes KB MCP server running at http://localhost:{port}")
    from holmes.mcp.server import run_server
    run_server(kb_root, port=port)


if __name__ == "__main__":
    cli()
