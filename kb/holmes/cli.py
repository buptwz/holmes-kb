"""Holmes CLI entry point.

Commands::

    holmes setup          — configure KB path and model settings
    holmes import <file>  — import a document into KB pending area
    holmes kb overview    — show KB overview (README + index)
    holmes kb search      — full-text search
    holmes kb show        — show a KB entry by ID
    holmes kb read-category — read a type _index.md
    holmes kb pending     — list pending entries
    holmes kb confirm     — 3-gate confirm a pending entry
    holmes kb reject      — reject a pending entry
    holmes kb merge       — resolve git conflict markers in KB
    holmes kb resolve     — choose a side for a content contradiction
    holmes kb lint        — health check
    holmes kb list        — list all KB entries
    holmes kb write-pending — internal: write content to pending (for tool calls)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from holmes.config import HolmesConfig, load_config, save_config

# ---------------------------------------------------------------------------
# Main group
# ---------------------------------------------------------------------------


@click.group(invoke_without_command=True)
@click.option("--kb-path", envvar="HOLMES_KB_PATH", default=None,
              help="Path to the knowledge base directory.")
@click.pass_context
def cli(ctx: click.Context, kb_path: Optional[str]) -> None:
    """Holmes — knowledge-based troubleshooting assistant."""
    ctx.ensure_object(dict)
    if kb_path:
        ctx.obj["kb_path"] = kb_path
    else:
        cfg = load_config()
        ctx.obj["kb_path"] = cfg.kb_path or None


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


@cli.command("setup")
@click.option("--kb-path", required=True, help="Local path to the cloned KB repository.")
@click.option("--model", default="gpt-4o", help="Model name (e.g. gpt-4o).")
@click.option("--api-key", default="", help="API key for the LLM provider.")
@click.option("--api-base-url", default="", help="Base URL for OpenAI-compatible API.")
def setup_cmd(kb_path: str, model: str, api_key: str, api_base_url: str) -> None:
    """Configure Holmes: KB path and model settings.

    Writes KB path to ~/.holmes/settings.json and model config to
    ~/.holmes/config.json.
    """
    from holmes.config import _holmes_home

    kb_root = Path(kb_path).expanduser().resolve()
    if not kb_root.exists():
        kb_root.mkdir(parents=True)
        click.echo(f"Created KB directory: {kb_root}")

    # Write config.json.
    cfg = HolmesConfig(
        kb_path=str(kb_root),
        model=model,
        api_key=api_key,
        api_base_url=api_base_url,
    )
    save_config(cfg)
    click.echo(f"✓ Config saved to {_holmes_home() / 'config.json'}")

    # Write settings.json with HOLMES_KB_PATH env var and KB tool permissions.
    home = _holmes_home()
    settings_path = home / "settings.json"
    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    env_dict: dict = settings.setdefault("env", {})
    env_dict["HOLMES_KB_PATH"] = str(kb_root)
    # Force OpenAI-compatible provider so Anthropic sessions don't take over.
    if api_base_url or api_key:
        settings["modelType"] = "openai"
    # Allow KB tools to run without per-call confirmation.
    permissions: dict = settings.setdefault("permissions", {})
    allow_list: list = permissions.setdefault("allow", [])
    kb_tools = [
        "KbReadOverview", "KbSearch", "KbReadCategoryIndex", "KbReadEntry",
        "KbListPending", "KbExtractAndSave", "KbWriteEntry",
        "KbReadSkill",
    ]
    for tool in kb_tools:
        if tool not in allow_list:
            allow_list.append(tool)
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    click.echo(f"✓ HOLMES_KB_PATH written to {settings_path}")

    # Write CLAUDE.md into KB root (agent loads CLAUDE.md, not HOLMES.md).
    claude_md = kb_root / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(_CLAUDE_MD_TEMPLATE, encoding="utf-8")
        click.echo(f"✓ CLAUDE.md written to {claude_md}")
    # Also write to ~/.holmes/CLAUDE.md so it loads from any working directory.
    home_claude_md = home / "CLAUDE.md"
    if not home_claude_md.exists():
        home_claude_md.write_text(_CLAUDE_MD_TEMPLATE, encoding="utf-8")
        click.echo(f"✓ CLAUDE.md written to {home_claude_md}")

    # Deploy skills to ~/.holmes/skills/.
    skills_dir = home / "skills"
    skills_dir.mkdir(exist_ok=True)
    search_skill = skills_dir / "holmes-search.md"
    if not search_skill.exists():
        search_skill.write_text(_HOLMES_SEARCH_SKILL, encoding="utf-8")
        click.echo(f"✓ /holmes-search skill deployed to {search_skill}")


_HOLMES_SEARCH_SKILL = """\
# /holmes-search

Use this skill to perform a targeted knowledge base search.

## Execution Steps

1. Ask the user for search keywords if not already provided.
2. Call **KbSearch** with the provided keywords.
3. For each result, display: ID, title, type, category, maturity, and a short snippet.
4. If results are found, ask the user whether they want to read the full content of any entry.
5. If the user selects an entry, call **KbReadEntry** with that ID and display the full content.
6. If no results are found, suggest alternative keywords or inform the user the KB has no
   matching entry.
"""

_CLAUDE_MD_TEMPLATE = """\
# Holmes — AI Troubleshooting Assistant

You are **Holmes**, an expert troubleshooting assistant backed by a structured knowledge base (KB).

## MANDATORY: Always Search the KB First

**Before answering ANY troubleshooting question**, you MUST follow these steps in order:

1. **KbReadOverview** — Call this tool first to understand the KB structure and available knowledge.
2. **KbSearch** — Search with keywords from the user's symptoms/error.
3. **KbReadEntry** — Read the full content of any matching entry found.
4. Only THEN synthesize an answer, combining KB knowledge with your reasoning.

Do NOT answer from general knowledge alone when KB tools are available.

## KB Tool Reference

| Tool | Purpose |
|------|---------|
| `KbReadOverview` | Get KB structure and README (no args) |
| `KbSearch` | Full-text search by keywords |
| `KbReadCategoryIndex` | List all entries of a type (pitfall/model/guideline/process/decision) |
| `KbReadEntry` | Read a specific entry by ID (e.g. PT-DB-001) |
| `KbExtractAndSave` | Save resolved session findings to KB pending |
| `KbListPending` | List KB entries awaiting confirmation |

## After Successfully Resolving an Issue

When the user confirms the issue is resolved:
1. Summarize the symptoms, root cause, and resolution.
2. Call **KbExtractAndSave** with a structured Markdown summary.
3. Tell the user: "I've saved this troubleshooting session to the KB pending area. Run `holmes kb confirm <pending_id>` to publish it."

## Troubleshooting Approach

- Ask clarifying questions if symptoms are vague.
- Reference specific KB entry IDs in your answers (e.g. "Per KB entry PT-DB-001...").
- If the KB has no matching entry, note this explicitly and answer from general knowledge.
"""


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


@cli.command("import")
@click.argument("file", type=click.Path(exists=False, path_type=Path))
@click.option("--type", "kb_type", default=None)
@click.option("--category", default=None)
@click.option("--title", default=None, help="Override LLM-generated title.")
@click.option("--tags", default=None, help="Comma-separated tags (overrides LLM output).")
@click.option("--dry-run", is_flag=True)
@click.option("--force", is_flag=True, help="Skip duplicate pending check.")
@click.pass_context
def import_cmd(
    ctx: click.Context,
    file: Path,
    kb_type: Optional[str],
    category: Optional[str],
    title: Optional[str],
    tags: Optional[str],
    dry_run: bool,
    force: bool,
) -> None:
    """Import a document into the KB pending area via LLM classification."""
    # Validate file existence manually so we control the exit code (1, not 2).
    if not file.exists():
        click.echo(f"File not found: {file}", err=True)
        sys.exit(1)

    cfg = load_config()
    kb_path_str = ctx.obj.get("kb_path") or cfg.kb_path
    if not kb_path_str:
        click.echo(
            "HOLMES_KB_PATH not configured. Run: holmes setup --kb-path <path>", err=True
        )
        sys.exit(2)
    kb_root = Path(kb_path_str)
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
        no_interactive=True,
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
    if report.warnings:
        for w in report.warnings:
            click.echo(f"  warn:  {w}")
    if dry_run:
        click.echo("(dry run — no files written)")
        if report.suggestions:
            for s in report.suggestions:
                click.echo(f"  suggest: {s}")
    else:
        for title in report.created:
            click.echo(f"✓ Created: {title}")
        for entry_id in report.updated:
            click.echo(f"✓ Updated: {entry_id}")
        for name in report.skills_generated:
            click.echo(f"  skill:   {name}")
        if not report.created and not report.updated:
            click.echo("No new entries created (duplicate or empty source).")
        if report.created:
            click.echo("  Confirm with: holmes kb confirm <pending-id>")


# ---------------------------------------------------------------------------
# kb group
# ---------------------------------------------------------------------------


@cli.group("kb")
@click.option("--kb-path", envvar="HOLMES_KB_PATH", default=None)
@click.pass_context
def kb(ctx: click.Context, kb_path: Optional[str]) -> None:
    """Knowledge base management commands."""
    ctx.ensure_object(dict)
    if kb_path:
        ctx.obj["kb_path"] = kb_path


def _require_kb_root(ctx: click.Context) -> Path:
    kb_path = ctx.obj.get("kb_path") or load_config().kb_path
    if not kb_path:
        click.echo("KB path not configured. Run: holmes setup --kb-path <path>", err=True)
        sys.exit(1)
    return Path(kb_path)


# ---------------------------------------------------------------------------
# kb read commands (called by TypeScript KB tools via subprocess)
# ---------------------------------------------------------------------------


@kb.command("overview")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def kb_overview(ctx: click.Context, as_json: bool) -> None:
    """Show KB overview: README + index summary."""
    kb_root = _require_kb_root(ctx)
    readme_path = kb_root / "README.md"
    index_path = kb_root / "index.json"

    readme_text = (
        readme_path.read_text(encoding="utf-8") if readme_path.exists()
        else "# Knowledge Base\n\n(No README.md)"
    )

    if index_path.exists():
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index_data = {"total_entries": 0, "entries": []}

    if as_json:
        click.echo(json.dumps({
            "readme": readme_text,
            "total_entries": index_data.get("total_entries", 0),
            "entries": index_data.get("entries", []),
        }, ensure_ascii=False))
    else:
        click.echo(readme_text)
        click.echo(f"\nTotal entries: {index_data.get('total_entries', 0)}")


@kb.command("search")
@click.argument("query")
@click.option("--limit", default=5, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def kb_search(ctx: click.Context, query: str, limit: int, as_json: bool) -> None:
    """Full-text search across all KB entries."""
    from holmes.kb.search import search

    kb_root = _require_kb_root(ctx)
    results = search(kb_root, query, limit=limit)

    if as_json:
        click.echo(json.dumps([
            {
                "id": r.entry_id,
                "title": r.title,
                "type": r.kb_type,
                "category": r.category,
                "maturity": r.maturity,
                "tags": r.tags,
                "snippet": r.snippet,
                "score": r.score,
            }
            for r in results
        ], ensure_ascii=False))
        return

    if not results:
        click.echo("No results found.")
        return

    for r in results:
        click.echo(f"\n[{r.entry_id}] {r.title}  ({r.kb_type}/{r.category or '—'}  {r.maturity})")
        click.echo(f"  {r.snippet}")


@kb.command("show")
@click.argument("entry_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def kb_show(ctx: click.Context, entry_id: str, as_json: bool) -> None:
    """Show full content of a KB entry by ID."""
    import frontmatter as fm

    from holmes.kb.store import read_entry

    kb_root = _require_kb_root(ctx)
    content = read_entry(kb_root, entry_id)
    if content is None:
        if as_json:
            click.echo(json.dumps({"error": f"Entry not found: {entry_id}"}))
        else:
            click.echo(f"Entry not found: {entry_id}", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"id": entry_id, "content": content}, ensure_ascii=False))
        return

    click.echo(content)

    # Show skill refs if present.
    try:
        post = fm.loads(content)
        skill_refs = list(post.metadata.get("skill_refs") or [])
        if skill_refs:
            from holmes.kb.skill.manager import parse_skill_md as _parse_skill_md
            click.echo("\n── Skills ──")
            for sname in skill_refs:
                skill_dir = kb_root / "skills" / str(sname)
                if skill_dir.is_dir():
                    skill_md = skill_dir / "SKILL.md"
                    try:
                        defn = _parse_skill_md(skill_md)
                        desc = f": {defn.description}" if defn.description else ""
                    except Exception:  # noqa: BLE001
                        desc = ""
                    click.echo(f"  {sname} [skill]{desc}")
                else:
                    click.echo(f"  Warning: skill '{sname}' not found in skills/")
    except Exception:  # noqa: BLE001
        pass


@kb.command("read-category")
@click.argument("kb_type")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def kb_read_category(ctx: click.Context, kb_type: str, as_json: bool) -> None:
    """Read the _index.md for a KB type (e.g. pitfall, model)."""
    kb_root = _require_kb_root(ctx)
    index_path = kb_root / kb_type / "_index.md"

    if not index_path.exists():
        if as_json:
            click.echo(json.dumps({"error": f"Category not found: {kb_type}"}))
        else:
            click.echo(f"Category not found: {kb_type}", err=True)
        sys.exit(1)

    content = index_path.read_text(encoding="utf-8")
    if as_json:
        click.echo(json.dumps({"type": kb_type, "content": content}, ensure_ascii=False))
    else:
        click.echo(content)


# ---------------------------------------------------------------------------
# pending management
# ---------------------------------------------------------------------------


@kb.command("pending")
@click.option("--json", "as_json", is_flag=True)
@click.option("--show", "show_id", default=None,
              help="Show full Markdown content of a specific pending entry.")
@click.pass_context
def kb_pending(ctx: click.Context, as_json: bool, show_id: Optional[str]) -> None:
    """List all pending entries, or show full content of one."""
    from holmes.kb.pending import get_pending, list_pending

    kb_root = _require_kb_root(ctx)

    if show_id:
        raw = get_pending(kb_root, show_id)
        if raw is None:
            click.echo(f"Pending entry not found: {show_id}", err=True)
            sys.exit(1)
        click.echo(raw)
        return

    entries = list_pending(kb_root)

    if as_json:
        click.echo(json.dumps(entries, ensure_ascii=False, default=str))
        return

    if not entries:
        click.echo("No pending entries.")
        return

    click.echo(f"{'ID':<40} {'TYPE':<12} {'TITLE':<35} CREATED")
    click.echo("-" * 100)
    for e in entries:
        click.echo(
            f"{e['id']:<40} {e['type']:<12} {e['title'][:33]:<35} "
            f"{str(e['created_at'])[:10]}"
        )


@kb.command("write-pending")
@click.option("--content", required=True, help="Markdown content with frontmatter.")
@click.option("--corrects", default=None,
              help="Entry ID this proposal intends to replace (correction workflow).")
@click.pass_context
def kb_write_pending(ctx: click.Context, content: str, corrects: Optional[str]) -> None:
    """Write content to pending area. Use --corrects to submit a correction proposal."""
    from holmes.kb.governance import DuplicateTitleError
    from holmes.kb.pending import write_pending

    kb_root = _require_kb_root(ctx)
    try:
        pending_id = write_pending(kb_root, content, corrects=corrects)
    except DuplicateTitleError as exc:
        click.echo(json.dumps({"error": str(exc)}), err=False)
        sys.exit(1)
    except ValueError as exc:
        click.echo(json.dumps({"error": str(exc)}), err=False)
        sys.exit(1)
    click.echo(json.dumps({"pending_id": pending_id}))


@kb.command("update-refs")
@click.option("--ids", required=True,
              help="Comma-separated list of entry IDs referenced in the session.")
@click.option("--session-id", "session_id", required=True,
              help="Unique session identifier for deduplication.")
@click.option("--contributor", required=True,
              help="Contributor identifier, e.g. username.")
@click.option("--project", default=None, help="Optional project context.")
@click.option("--context", "ctx_note", default=None, help="Optional usage context description.")
@click.pass_context
def kb_update_refs(
    ctx: click.Context,
    ids: str,
    session_id: str,
    contributor: str,
    project: Optional[str],
    ctx_note: Optional[str],
) -> None:
    """Batch append EvidenceRecord to entries at session end. Drives maturity promotion."""
    from datetime import datetime as _dt, timezone as _tz

    from holmes.kb.store import append_evidence, derive_maturity, list_entries, read_entry
    import frontmatter as fm

    kb_root = _require_kb_root(ctx)
    entry_ids = [e.strip() for e in ids.split(",") if e.strip()]
    now_iso = _dt.now(_tz.utc).isoformat()

    evidence_record: dict = {
        "session_id": session_id,
        "contributor": contributor,
        "date": now_iso,
    }
    if project:
        evidence_record["project"] = project
    if ctx_note:
        evidence_record["context"] = ctx_note

    updated: list[str] = []
    skipped_duplicate: list[str] = []
    not_found: list[str] = []
    maturity_promoted: list[dict] = []

    # Build a quick lookup of existing entry maturities for promotion tracking.
    existing_maturities: dict[str, str] = {}
    for meta in list_entries(kb_root):
        existing_maturities[meta.id] = meta.maturity

    for entry_id in entry_ids:
        if entry_id not in existing_maturities:
            not_found.append(entry_id)
            continue

        old_maturity = existing_maturities[entry_id]
        appended = append_evidence(kb_root, entry_id, evidence_record)
        if appended:
            updated.append(entry_id)
            # Check if maturity was promoted.
            content = read_entry(kb_root, entry_id)
            if content:
                post = fm.loads(content)
                new_maturity = str(post.metadata.get("maturity", old_maturity))
                if new_maturity != old_maturity:
                    maturity_promoted.append({
                        "id": entry_id,
                        "old": old_maturity,
                        "new": new_maturity,
                    })
        else:
            skipped_duplicate.append(entry_id)

    click.echo(json.dumps({
        "updated": updated,
        "skipped_duplicate": skipped_duplicate,
        "not_found": not_found,
        "maturity_promoted": maturity_promoted,
    }, ensure_ascii=False))


@kb.command("confirm")
@click.argument("pending_id")
@click.option("--force", is_flag=True, help="Skip duplicate check.")
@click.option("--category", "category_override", default=None, help="Override entry category.")
@click.option("--type", "type_override", default=None, help="Override entry type.")
@click.option("--contributor", default=None,
              help="Contributor identifier for the confirming user (added to evidence).")
@click.pass_context
def kb_confirm(
    ctx: click.Context,
    pending_id: str,
    force: bool,
    category_override: Optional[str],
    type_override: Optional[str],
    contributor: Optional[str],
) -> None:
    """3-gate confirm: schema → duplicate check → preview → promote to KB.

    For correction proposals (entries with corrects: <id>), replaces the original
    entry and saves a VersionSnapshot to .history/.
    """
    import uuid
    from datetime import datetime as _dt, timezone as _tz

    import frontmatter as fm

    from holmes.kb.history import save_snapshot
    from holmes.kb.pending import append_log, delete_pending, get_pending
    from holmes.kb.store import add_contributor, append_evidence, rebuild_index_files, write_entry
    from holmes.kb.validator import check_duplicate, generate_id, validate_schema

    kb_root = _require_kb_root(ctx)
    raw = get_pending(kb_root, pending_id)
    if raw is None:
        click.echo(f"Pending entry not found: {pending_id}", err=True)
        sys.exit(1)

    # Gate 1: Schema validation (includes id-uniqueness check against official KB).
    click.echo("Gate 1: Schema validation...")
    result = validate_schema(raw, kb_root=kb_root)
    if not result.valid:
        click.echo("✗ Schema errors:")
        for err in result.errors:
            click.echo(f"  - {err}")
        sys.exit(1)
    click.echo("  ✓ Schema valid")

    # Gate 2: Duplicate detection.
    click.echo("Gate 2: Duplicate detection...")
    dup = check_duplicate(kb_root, raw)
    if dup.similar_entries and not force:
        click.echo("  Similar entries found:")
        for sim in dup.similar_entries:
            click.echo(f"    [{sim['id']}] {sim['title']} — {sim['similarity']:.0%}")
        if not click.confirm("  Duplicates detected. Confirm anyway?", default=False):
            sys.exit(0)
    else:
        click.echo("  ✓ No duplicates")

    # Gate 3: Forced preview.
    click.echo("\nGate 3: Entry preview:")
    click.echo("─" * 60)
    click.echo(raw[:800])
    if len(raw) > 800:
        click.echo(f"  ... ({len(raw) - 800} more chars)")
    click.echo("─" * 60)
    if not click.confirm("Confirm this entry?", default=True):
        sys.exit(0)

    post = fm.loads(raw)
    corrects_id = str(post.metadata.get("corrects", "")).strip()
    now_iso = _dt.now(_tz.utc).isoformat()

    # --- Correction path ---
    if corrects_id:
        from holmes.kb.store import read_entry as _read_entry

        original_content = _read_entry(kb_root, corrects_id)
        if original_content is None:
            click.echo(f"Correction target not found: {corrects_id}", err=True)
            sys.exit(1)

        snapshot_path = save_snapshot(
            kb_root, corrects_id, original_content, pending_id, reason="correction"
        )

        # Find original entry path.
        from holmes.kb.store import list_entries as _list_entries
        orig_path: Optional[Path] = None
        for m in _list_entries(kb_root):
            if m.id == corrects_id:
                orig_path = Path(m.file_path)
                break
        if orig_path is None:
            click.echo(f"Could not locate file for entry: {corrects_id}", err=True)
            sys.exit(1)

        # Preserve original evidence and contributors.
        orig_post = fm.loads(original_content)
        post.metadata["id"] = corrects_id
        post.metadata["maturity"] = "verified"
        post.metadata["updated_at"] = now_iso
        post.metadata["evidence"] = orig_post.metadata.get("evidence") or []
        post.metadata["contributors"] = orig_post.metadata.get("contributors") or []
        del post.metadata["corrects"]

        write_entry(orig_path, fm.dumps(post))
        delete_pending(kb_root, pending_id)
        rebuild_index_files(kb_root)
        append_log(kb_root, "correction", corrects_id, f"replaced by {pending_id}")
        click.echo(f"\n✓ Correction applied: {corrects_id} (snapshot: {snapshot_path.name})")
        return

    # --- Normal confirm path ---
    if type_override:
        post.metadata["type"] = type_override
    if category_override:
        post.metadata["category"] = category_override
    kb_type = str(post.metadata.get("type", "pitfall"))
    category = post.metadata.get("category")
    new_id = generate_id(kb_root, kb_type, category)
    post.metadata["id"] = new_id
    post.metadata["maturity"] = "draft"  # will be promoted via evidence below
    post.metadata.setdefault("evidence", [])
    post.metadata.setdefault("contributors", [])
    post.metadata.pop("pending", None)
    post.metadata.pop("pending_since", None)
    post.metadata.pop("source_session", None)

    if category:
        target_path = kb_root / kb_type / category / f"{new_id}.md"
    else:
        target_path = kb_root / kb_type / f"{new_id}.md"

    write_entry(target_path, fm.dumps(post))
    delete_pending(kb_root, pending_id)
    rebuild_index_files(kb_root)

    # Append first EvidenceRecord (the confirm action itself is the first evidence).
    confirming_contributor = contributor or "maintainer"
    session_id = f"confirm-{pending_id}"
    evidence_record = {
        "session_id": session_id,
        "contributor": confirming_contributor,
        "date": now_iso,
        "context": f"confirmed from pending {pending_id}",
    }
    append_evidence(kb_root, new_id, evidence_record)
    add_contributor(kb_root, new_id, confirming_contributor)

    click.echo(f"\n✓ Entry confirmed: {new_id}")


@kb.command("reject")
@click.argument("pending_id")
@click.option("--reason", default="", help="Rejection reason.")
@click.pass_context
def kb_reject(ctx: click.Context, pending_id: str, reason: str) -> None:
    """Reject and delete a pending entry."""
    from holmes.kb.pending import append_log, delete_pending, get_pending

    kb_root = _require_kb_root(ctx)
    raw = get_pending(kb_root, pending_id)
    if raw is None:
        click.echo(f"Pending entry not found: {pending_id}", err=True)
        sys.exit(1)

    delete_pending(kb_root, pending_id)
    append_log(kb_root, "rejected", pending_id, reason or "no reason given")
    click.echo(f"✓ Rejected: {pending_id}")


# ---------------------------------------------------------------------------
# merge / conflict resolution
# ---------------------------------------------------------------------------


@kb.command("merge")
@click.pass_context
def kb_merge(ctx: click.Context) -> None:
    """Detect and resolve git conflict markers across the KB."""
    from holmes.kb.merger import auto_resolve, parse_conflicts

    kb_root = _require_kb_root(ctx)
    conflicts = parse_conflicts(kb_root)
    if not conflicts:
        click.echo("No git conflict markers found.")
        return

    auto_count = 0
    isolated_count = 0
    for cf in conflicts:
        resolved = auto_resolve(cf)
        if resolved is not None:
            cf.path.write_text(resolved, encoding="utf-8")
            auto_count += 1
        else:
            _isolate_conflict(kb_root, cf)
            isolated_count += 1

    click.echo(f"✓ Resolved: {auto_count} auto, {isolated_count} isolated to contributions/conflicts/")
    if isolated_count > 0:
        sys.exit(1)


def _isolate_conflict(kb_root: Path, cf) -> None:  # noqa: ANN001
    """Move a content-contradiction conflict to contributions/conflicts/."""
    from holmes.kb.conflict import write_conflict_entry

    write_conflict_entry(kb_root, cf)
    cf.path.unlink(missing_ok=True)


@kb.command("resolve")
@click.argument("conflict_id")
@click.option("--keep", type=click.Choice(["A", "B"]), default=None,
              help="Choose side A (local) or B (remote) to keep.")
@click.option("--manual", is_flag=True,
              help="Accept manually edited conflict file (no remaining conflict markers).")
@click.pass_context
def kb_resolve_conflict(
    ctx: click.Context,
    conflict_id: str,
    keep: Optional[str],
    manual: bool,
) -> None:
    """Resolve a content contradiction conflict by choosing side A or B, or accepting a manual edit."""
    import re as _re

    from holmes.kb.conflict import append_conflict_log, resolve_conflict

    kb_root = _require_kb_root(ctx)

    if not keep and not manual:
        click.echo("Specify --keep A|B or --manual.", err=True)
        sys.exit(2)

    if manual:
        # Validate that the original file no longer contains conflict markers.
        conflicts_dir = kb_root / "contributions" / "conflicts"
        meta_path = conflicts_dir / f"{conflict_id}.json"
        if not meta_path.exists():
            click.echo(f"Conflict not found: {conflict_id}", err=True)
            sys.exit(1)
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        orig = Path(data["original_path"])
        if not orig.exists():
            click.echo(f"Original file not found: {orig}", err=True)
            sys.exit(1)
        text = orig.read_text(encoding="utf-8")
        if _re.search(r"^<{7} ", text, _re.MULTILINE):
            click.echo(
                "Conflict markers still present in the file. "
                "Resolve them manually first, then re-run --manual.",
                err=True,
            )
            sys.exit(2)
        data["status"] = "resolved"
        data["resolved_at"] = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        data["kept"] = "manual"
        meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        append_conflict_log(kb_root, conflict_id, "manual")
        click.echo(f"✓ Conflict {conflict_id} resolved manually")
        return

    result = resolve_conflict(kb_root, conflict_id, keep)  # type: ignore[arg-type]
    if result is None:
        click.echo(f"Conflict not found: {conflict_id}", err=True)
        sys.exit(1)
    append_conflict_log(kb_root, conflict_id, keep)  # type: ignore[arg-type]
    click.echo(f"✓ Conflict {conflict_id} resolved (kept side {keep})")


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------


@kb.command("lint")
@click.option("--fix", is_flag=True)
@click.option("--report", "as_report", is_flag=True,
              help="Output lint results as JSON instead of human-readable text.")
@click.pass_context
def kb_lint(ctx: click.Context, fix: bool, as_report: bool) -> None:
    """Run KB health check and optionally auto-fix issues."""
    from holmes.kb.linter import lint

    kb_root = _require_kb_root(ctx)
    report = lint(kb_root, fix=fix)

    if as_report:
        click.echo(json.dumps({
            "total_entries": report.total_entries,
            "pending_count": report.pending_count,
            "conflict_count": report.conflict_count,
            "warnings": report.warnings,
            "errors": report.errors,
            "fixes_applied": report.fixes_applied,
        }, ensure_ascii=False))
        return

    click.echo(
        f"Entries: {report.total_entries}  "
        f"Pending: {report.pending_count}  "
        f"Conflicts: {report.conflict_count}"
    )
    for w in report.warnings:
        click.echo(f"  ⚠ {w}")
    for e in report.errors:
        click.echo(f"  ✗ {e}")
    if fix and report.fixes_applied:
        for f in report.fixes_applied:
            click.echo(f"  ✓ fixed: {f}")
    if not report.warnings and not report.errors:
        click.echo("✓ Knowledge base is healthy")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@kb.command("list")
@click.option("--type", "kb_type", default=None, help="Filter by entry type.")
@click.option("--category", default=None, help="Filter by category.")
@click.option("--query", default=None, help="Keyword filter (title and tags).")
@click.option("--limit", default=0, type=int, help="Maximum entries to return (0 = unlimited).")
@click.option("--offset", default=0, type=int, help="Number of entries to skip.")
@click.option("--format", "fmt", default="table",
              type=click.Choice(["table", "json", "id-only"]),
              help="Output format (default: table).")
@click.option("--json", "as_json", is_flag=True, help="Shorthand for --format json.")
@click.pass_context
def kb_list(
    ctx: click.Context,
    kb_type: Optional[str],
    category: Optional[str],
    query: Optional[str],
    limit: int,
    offset: int,
    fmt: str,
    as_json: bool,
) -> None:
    """List all KB entries (reads index.json, rebuilds if missing)."""
    from holmes.kb.store import list_entries, rebuild_index_files

    kb_root = _require_kb_root(ctx)
    index_path = kb_root / "index.json"
    if not index_path.exists():
        rebuild_index_files(kb_root)

    entries = list_entries(
        kb_root, kb_type=kb_type, category=category, query=query, limit=limit, offset=offset
    )

    # --json flag overrides --format.
    if as_json:
        fmt = "json"

    if fmt == "json":
        click.echo(json.dumps(
            [{"id": e.id, "type": e.type, "maturity": e.maturity, "title": e.title,
              "category": e.category, "tags": e.tags}
             for e in entries],
            ensure_ascii=False,
        ))
        return

    if fmt == "id-only":
        for e in entries:
            click.echo(e.id)
        return

    # Default: table.
    if not entries:
        click.echo("No entries found.")
        return

    click.echo(f"{'ID':<20} {'TYPE':<12} {'MATURITY':<10} TITLE")
    click.echo("-" * 80)
    for e in entries:
        click.echo(f"{e.id:<20} {e.type:<12} {e.maturity:<10} {e.title[:40]}")


@kb.command("history")
@click.argument("entry_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def kb_history(ctx: click.Context, entry_id: str, as_json: bool) -> None:
    """List version snapshots for a KB entry (.history/ directory)."""
    import frontmatter as fm

    from holmes.kb.history import list_snapshots

    kb_root = _require_kb_root(ctx)
    snapshots = list_snapshots(kb_root, entry_id)

    if as_json:
        rows = []
        for p in snapshots:
            try:
                post = fm.load(str(p))
                rows.append({
                    "file": p.name,
                    "replaced_at": str(post.metadata.get("replaced_at", "")),
                    "replaced_by": str(post.metadata.get("replaced_by", "")),
                    "snapshot_reason": str(post.metadata.get("snapshot_reason", "")),
                })
            except Exception:  # noqa: BLE001
                rows.append({"file": p.name})
        click.echo(json.dumps(rows, ensure_ascii=False))
        return

    if not snapshots:
        click.echo(f"No snapshots found for {entry_id}.")
        return

    click.echo(f"Snapshots for {entry_id}:")
    click.echo(f"{'FILE':<45} {'REPLACED_AT':<30} REASON")
    click.echo("-" * 95)
    for p in snapshots:
        try:
            post = fm.load(str(p))
            replaced_at = str(post.metadata.get("replaced_at", ""))[:25]
            reason = str(post.metadata.get("snapshot_reason", ""))
        except Exception:  # noqa: BLE001
            replaced_at = ""
            reason = ""
        click.echo(f"{p.name:<45} {replaced_at:<30} {reason}")


@kb.command("decay")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing.")
@click.option("--type", "kb_type", default=None,
              help="Limit to one entry type (pitfall/model/guideline/process/decision).")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.pass_context
def kb_decay(ctx: click.Context, dry_run: bool, kb_type: Optional[str], as_json: bool) -> None:
    """Run maturity decay check across all public KB entries."""
    from holmes.kb.decay import run_decay

    kb_root = _require_kb_root(ctx)
    result = run_decay(kb_root, dry_run=dry_run, kb_type=kb_type)

    if as_json:
        click.echo(json.dumps({
            "scanned": result.scanned,
            "decayed": result.decayed,
            "dry_run": dry_run,
            "changes": [
                {
                    "id": c.id,
                    "old_maturity": c.old_maturity,
                    "new_maturity": c.new_maturity,
                    "last_evidence_date": c.last_evidence_date,
                    "months_unreferenced": c.months_unreferenced,
                }
                for c in result.changes
            ],
            "errors": result.errors,
        }, ensure_ascii=False))
    else:
        prefix = "[DRY RUN] " if dry_run else ""
        click.echo(f"{prefix}Scanned: {result.scanned} entries")
        if result.decayed == 0:
            click.echo(f"{prefix}Decayed: 0 entries — nothing to do")
        else:
            click.echo(f"{prefix}Decayed: {result.decayed} entries")
            for c in result.changes:
                ref = f", last evidence: {c.last_evidence_date[:10]}" if c.last_evidence_date else ""
                click.echo(
                    f"  [{c.id}] {c.old_maturity} → {c.new_maturity} "
                    f"({c.months_unreferenced} months{ref})"
                )
        if result.errors:
            click.echo("Errors:")
            for e in result.errors:
                click.echo(f"  ✗ {e}")
            sys.exit(1)


@kb.command("archive-orphans")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.pass_context
def kb_archive_orphans(ctx: click.Context, as_json: bool) -> None:
    """Move orphaned draft entries (no evidence) to contributions/archive/."""
    import frontmatter as fm

    from holmes.kb.decay import archive_orphan
    from holmes.kb.store import list_entries, load_evidence

    kb_root = _require_kb_root(ctx)

    orphans: list[str] = []
    for entry in list_entries(kb_root):
        if entry.maturity != "draft":
            continue
        try:
            content = (kb_root / entry.file_path).read_text(encoding="utf-8") \
                if not Path(entry.file_path).is_absolute() \
                else Path(entry.file_path).read_text(encoding="utf-8")
            post = fm.loads(content)
            evidence = load_evidence(kb_root, entry.id, post.metadata.get("evidence"))
            if not evidence:
                orphans.append(entry.id)
        except Exception:  # noqa: BLE001
            pass

    archived: list[str] = []
    errors: list[str] = []
    for entry_id in orphans:
        try:
            archive_orphan(kb_root, entry_id)
            archived.append(entry_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{entry_id}: {exc}")

    if as_json:
        click.echo(json.dumps({"archived": archived, "errors": errors}, ensure_ascii=False))
    else:
        if not archived:
            click.echo("No orphan draft entries found.")
        else:
            click.echo(f"Archived {len(archived)} orphan draft(s):")
            for eid in archived:
                click.echo(f"  {eid} → contributions/archive/")
        if errors:
            for e in errors:
                click.echo(f"  ✗ {e}", err=True)


@kb.command("check-conflicts")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def kb_check_conflicts(ctx: click.Context, as_json: bool) -> None:
    """Scan for entries with contradiction: true (pending maintainer resolution)."""
    import frontmatter as fm

    from holmes.kb.store import list_entries

    kb_root = _require_kb_root(ctx)
    contradictions: list[dict] = []

    for entry in list_entries(kb_root):
        try:
            path = Path(entry.file_path)
            if path.exists():
                post = fm.load(str(path))
                if post.metadata.get("contradiction"):
                    contradictions.append({
                        "id": entry.id,
                        "title": entry.title,
                        "maturity": entry.maturity,
                        "file": str(path),
                    })
        except Exception:  # noqa: BLE001
            pass

    if as_json:
        click.echo(json.dumps(contradictions, ensure_ascii=False))
        return

    if not contradictions:
        click.echo("No maturity contradictions found.")
        return

    click.echo(f"Found {len(contradictions)} contradiction(s) requiring maintainer review:")
    for c in contradictions:
        click.echo(f"  [{c['id']}] {c['title']} ({c['maturity']}) — {c['file']}")


@kb.command("rebuild-index")
@click.pass_context
def kb_rebuild_index(ctx: click.Context) -> None:
    """Rebuild index.json and all _index.md files from disk."""
    from holmes.kb.store import rebuild_index_files

    kb_root = _require_kb_root(ctx)
    rebuild_index_files(kb_root)
    index_path = kb_root / "index.json"
    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    count = index_data.get("total_entries", 0)
    click.echo(f"✓ Index rebuilt: {count} entries")


# ---------------------------------------------------------------------------
# skill subgroup
# ---------------------------------------------------------------------------


@kb.group("skill")
def kb_skill() -> None:
    """Manage KB agent skills (read-only)."""


@kb_skill.command("list")
@click.argument("entry_id", required=False, default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def skill_list(ctx: click.Context, entry_id: Optional[str], as_json: bool) -> None:
    """List all skills in the KB, or skills linked to a specific entry."""
    from holmes.kb.skill.manager import list_skills

    kb_root = _require_kb_root(ctx)
    skills = list_skills(kb_root, entry_id=entry_id)

    if as_json:
        click.echo(json.dumps([
            {
                "name": s.name,
                "description": s.description,
                "linked_entries": s.linked_entries,
            }
            for s in skills
        ], ensure_ascii=False))
        return

    if not skills:
        click.echo("No skills found.")
        return

    click.echo(f"{'NAME':<25} {'DESCRIPTION':<35} REFS")
    click.echo("-" * 80)
    for s in skills:
        refs = ", ".join(s.linked_entries) if s.linked_entries else "—"
        click.echo(f"{s.name:<25} {s.description[:33]:<35} {refs}")


@kb_skill.command("read")
@click.argument("skill_name")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def skill_read(ctx: click.Context, skill_name: str, as_json: bool) -> None:
    """Return the SKILL.md content for a named skill."""
    from holmes.kb.skill.manager import get_skill_dir, skill_exists

    kb_root = _require_kb_root(ctx)
    if not skill_exists(kb_root, skill_name):
        msg = {"error": f"Skill '{skill_name}' not found."}
        if as_json:
            click.echo(json.dumps(msg))
        else:
            click.echo(f"Error: {msg['error']}", err=True)
        sys.exit(1)

    skill_dir = get_skill_dir(kb_root, skill_name)
    skill_md = skill_dir / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8") if skill_md.exists() else ""

    if as_json:
        click.echo(json.dumps({
            "name": skill_name,
            "content": content,
        }, ensure_ascii=False))
    else:
        click.echo(content)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


@cli.group("config")
def config_group() -> None:
    """View and update Holmes configuration."""


@config_group.command("show")
def config_show() -> None:
    """Display current configuration."""
    from holmes.config import _holmes_home

    cfg = load_config()
    home = _holmes_home()
    click.echo(json.dumps({
        "kb_path": cfg.kb_path,
        "model": cfg.model,
        "api_base_url": cfg.api_base_url,
        "config_file": str(home / "config.json"),
        "settings_file": str(home / "settings.json"),
    }, indent=2, ensure_ascii=False))


@config_group.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a configuration value (kb_path, model, api_key, api_base_url)."""
    from holmes.config import save_config

    cfg = load_config()
    allowed_keys = {"kb_path", "model", "api_key", "api_base_url"}
    if key not in allowed_keys:
        click.echo(f"Unknown config key: {key!r}. Allowed: {sorted(allowed_keys)}", err=True)
        sys.exit(1)
    setattr(cfg, key, value)
    save_config(cfg)
    click.echo(f"✓ {key} = {value}")


if __name__ == "__main__":
    cli()
