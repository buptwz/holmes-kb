"""Holmes CLI entry point.

Commands:
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

import sys
from pathlib import Path
from typing import Optional

import click

from holmes.config import HolmesConfig, load_config, save_config, update_config, HOLMES_DIR
from holmes.kb.linter import lint, LintReport
from holmes.kb.pending import get_pending, list_pending, delete_pending, append_log
from holmes.kb.store import read_entry, list_entries, write_entry, rebuild_index_files
from holmes.kb.validator import validate_schema, check_duplicate, generate_id
from holmes.kb.merger import merge_pending_entry
from holmes.kb.conflict import list_conflicts, resolve_conflict
from holmes.agent.session import list_sessions, load_session
from holmes.logging_config import configure_logging, get_logger


logger = get_logger("cli")


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Holmes — AI-powered troubleshooting assistant backed by a knowledge base."""
    configure_logging()


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
@click.option("--dry-run", is_flag=True, help="Preview without writing")
@click.option("--force", is_flag=True, help="Skip duplicate pending check.")
@click.option("--no-interactive", is_flag=True, help="Suppress confirmation gates.")
def import_cmd(file: Path, kb_type: Optional[str], dry_run: bool, force: bool, no_interactive: bool) -> None:
    """Import a knowledge document into the KB via the agent pipeline."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured. Run: holmes setup --kb-path <path>", err=True)
        sys.exit(1)

    kb_root = Path(cfg.kb_path)
    if not kb_root.exists():
        click.echo(f"KB path does not exist: {kb_root}", err=True)
        sys.exit(2)

    source_text = file.read_text(encoding="utf-8")
    if len(source_text.strip()) < 50:
        click.echo(
            f"Content too short ({len(source_text.strip())} chars). Minimum is 50 characters.",
            err=True,
        )
        sys.exit(1)

    from holmes.kb.agent.runner import ImportAgentRunner

    runner = ImportAgentRunner(
        kb_root=kb_root,
        cfg=cfg,
        no_interactive=no_interactive,
        dry_run=dry_run,
        force_type=kb_type,
        force=force,
    )

    try:
        report = runner.run(source_text, file_path=file)
    except Exception as exc:
        click.echo(f"Import failed: {exc}", err=True)
        sys.exit(1)

    if report.errors:
        for err in report.errors:
            click.echo(f"  error: {err}", err=True)
    if dry_run:
        click.echo("(dry run — no files written)")
    else:
        click.echo(report.format_summary())


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
    content = get_pending(Path(cfg.kb_path), pending_id)
    if content is None:
        click.echo(f"Pending entry not found: {pending_id}", err=True)
        sys.exit(1)
    click.echo(content)


@kb.command("confirm")
@click.argument("pending_id")
def kb_confirm(pending_id: str) -> None:
    """Confirm a pending entry (runs 3-gate validation)."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    import frontmatter
    from datetime import datetime, timezone

    kb_root = Path(cfg.kb_path)
    content = get_pending(kb_root, pending_id)
    if content is None:
        click.echo(f"Pending entry not found: {pending_id}", err=True)
        sys.exit(1)

    post = frontmatter.loads(content)

    # Gate 1: Schema validation
    click.echo("Gate 1: Schema validation...")
    schema_result = validate_schema(content, kb_root)
    if schema_result.errors:
        click.echo(f"✗ Schema validation failed: {'; '.join(schema_result.errors)}", err=True)
        sys.exit(1)
    click.echo("  ✓ Schema valid")

    # Gate 2: Duplicate detection
    dup_result = check_duplicate(kb_root, content)
    if dup_result.similar_entries:
        click.echo("Gate 2: Similar entries found:")
        for sim in dup_result.similar_entries:
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

    # Assign permanent ID and write to KB
    kb_type = str(post.metadata.get("type", "pitfall"))
    category = post.metadata.get("category")
    new_id = generate_id(kb_root, kb_type, category)
    post.metadata["id"] = new_id
    post.metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
    new_content = frontmatter.dumps(post)

    if kb_type == "pitfall" and category:
        entry_path = kb_root / kb_type / str(category) / f"{new_id}.md"
    else:
        entry_path = kb_root / kb_type / f"{new_id}.md"
    write_entry(entry_path, new_content)

    # Remove from pending, rebuild index, log
    delete_pending(kb_root, pending_id)
    rebuild_index_files(kb_root)
    title = str(post.metadata.get("title", new_id))
    append_log(kb_root, "confirmed", new_id, title)
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
    ok = delete_pending(Path(cfg.kb_path), pending_id)
    if ok:
        if reason:
            append_log(Path(cfg.kb_path), "rejected", pending_id, reason)
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
    content = get_pending(kb_root, pending_id)
    if content is None:
        click.echo(f"Pending entry not found: {pending_id}", err=True)
        sys.exit(1)
    merge_result = merge_pending_entry(kb_root, content)
    scenario = merge_result["scenario"]
    click.echo(f"✓ Merge completed (scenario: {scenario})")
    if scenario == "content_contradiction":
        click.echo(f"  Conflict ID: {merge_result.get('conflict_id')}")
        click.echo("  Resolve with: holmes kb resolve <conflict_id>")
    else:
        click.echo(f"  Entry ID: {merge_result.get('entry_id')}")
    # Remove pending entry after merge
    delete_pending(kb_root, pending_id)


@kb.command("resolve")
@click.argument("conflict_id")
@click.option("--keep", default="A", type=click.Choice(["A", "B"]), help="Which version to keep: A (local) or B (remote)")
def kb_resolve(conflict_id: str, keep: str) -> None:
    """Resolve a conflict by choosing which version to keep."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    result_path = resolve_conflict(Path(cfg.kb_path), conflict_id, keep=keep)  # type: ignore[arg-type]
    if result_path:
        click.echo(f"✓ Conflict {conflict_id} resolved (kept version {keep})")
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
    report = lint(Path(cfg.kb_path), fix=fix)
    click.echo(f"Entries: {report.total_entries}  Pending: {report.pending_count}  Conflicts: {report.conflict_count}")
    if report.warnings:
        click.echo("\nWarnings:")
        for w in report.warnings:
            click.echo(f"  ⚠ {w}")
    if report.errors:
        click.echo("\nErrors:")
        for e in report.errors:
            click.echo(f"  ✗ {e}")
    if report.fixes_applied:
        click.echo("\nFixes applied:")
        for f in report.fixes_applied:
            click.echo(f"  ✓ {f}")
    if not report.warnings and not report.errors:
        click.echo("\n✓ Knowledge base is healthy")


@kb.command("rebuild-index")
def kb_rebuild_index() -> None:
    """Rebuild index.json and all _index.md files."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    kb_root = Path(cfg.kb_path)
    rebuild_index_files(kb_root)
    total = len(list_entries(kb_root))
    click.echo(f"✓ Index rebuilt: {total} entries")


@kb.command("list")
@click.option("--type", "kb_type", default=None)
@click.option("--limit", default=50)
def kb_list(kb_type: Optional[str], limit: int) -> None:
    """List knowledge base entries."""
    cfg = load_config()
    if not cfg.kb_path:
        click.echo("KB path not configured.", err=True)
        sys.exit(1)
    entries = list_entries(Path(cfg.kb_path), kb_type=kb_type)
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
    content = read_entry(Path(cfg.kb_path), entry_id)
    if content is None:
        click.echo(f"Entry not found: {entry_id}", err=True)
        sys.exit(1)
    click.echo(content)


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


if __name__ == "__main__":
    cli()
