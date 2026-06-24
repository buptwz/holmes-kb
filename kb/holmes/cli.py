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

from holmes.config import HolmesConfig, _holmes_home, load_config, save_config
from holmes.kb.logger import HolmesLogger, derive_trace_id

# ---------------------------------------------------------------------------
# Main group
# ---------------------------------------------------------------------------


def _get_version() -> str:
    try:
        from importlib.metadata import version as _meta_version
        from importlib.metadata import PackageNotFoundError
        return _meta_version("holmes-kb")
    except Exception:
        return "0.1.0"


@click.group(invoke_without_command=True)
@click.version_option(_get_version(), "--version", "-v", prog_name="holmes")
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
@click.option(
    "--provider",
    type=click.Choice(["anthropic", "openai"], case_sensitive=False),
    default="anthropic",
    help="LLM provider: 'anthropic' (Anthropic SDK) or 'openai' (OpenAI-compatible API).",
)
def setup_cmd(kb_path: str, model: str, api_key: str, api_base_url: str, provider: str) -> None:
    """Configure Holmes: KB path and model settings.

    Writes KB path to ~/.holmes/settings.json and model config to
    ~/.holmes/config.json.
    """
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
        provider=provider,
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
| `kb_confirm_entry` | Record that a KB entry directly helped resolve the issue (explicit, evidence-writing) |
| `KbExtractAndSave` | Save a new troubleshooting finding to KB pending |
| `KbListPending` | List KB entries awaiting confirmation |

## After Successfully Resolving an Issue

When the user confirms the issue is resolved:

**If an existing KB entry led to the resolution:**
1. Call **`kb_confirm_entry`** with that entry's ID.
   - MUST only call this after the user explicitly confirms the issue is resolved.
   - MUST NOT call this if you only read the entry but did not apply its guidance.

**If no matching KB entry existed:**
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
@click.argument("file", required=False, default=None, type=click.Path(exists=False, path_type=Path),
               metavar="FILE|TEXT|-")
@click.option("--dir", "import_dir", default=None, type=click.Path(file_okay=False, path_type=Path),
              help="Import all .md/.txt/.rst files in a directory.")
@click.option(
    "--type", "force_type",
    type=click.Choice(["pitfall"]),
    default=None,
    help="强制指定文档类型，跳过 Classifier 判断。",
)
@click.option("--category", default=None)
@click.option("--title", default=None, help="Override LLM-generated title.")
@click.option("--tags", default=None, help="Comma-separated tags (overrides LLM output).")
@click.option("--dry-run", is_flag=True)
@click.option("--force", is_flag=True, help="Skip duplicate pending check.")
@click.option("--no-interactive", is_flag=True, help="Suppress all confirmation gates.")
@click.option("--verbose", is_flag=True, help="Show per-decision reasoning trace.")
@click.pass_context
def import_cmd(
    ctx: click.Context,
    file: Optional[Path],
    import_dir: Optional[Path],
    force_type: Optional[str],
    category: Optional[str],
    title: Optional[str],
    tags: Optional[str],
    dry_run: bool,
    force: bool,
    no_interactive: bool,
    verbose: bool,
) -> None:
    """Import into the KB via the autonomous agent pipeline.

    FILE|TEXT|-: path to a file, inline text (no path separators / extensions),
    or - to read from stdin.  Use --dir to import all files in a directory.
    """
    # Mutual exclusivity check.
    if file is not None and import_dir is not None:
        click.echo("Error: FILE and --dir are mutually exclusive.", err=True)
        sys.exit(1)
    if file is None and import_dir is None:
        click.echo("Error: Provide FILE or --dir.", err=True)
        sys.exit(1)

    cfg = load_config()

    # M8: Set up logger + rotate old logs.
    _log_dir = _holmes_home() / "logs"
    _logger = HolmesLogger(_log_dir, verbose=verbose)
    _logger.rotate()

    # M8: Derive trace_id from source file (or placeholder for batch/stdin).
    _source_for_trace = str(file) if file is not None else (str(import_dir) if import_dir is not None else "import")
    _trace_id = derive_trace_id(_source_for_trace)

    # M8: Require username before doing any work.
    if not cfg.username:
        _logger.write_span(
            _trace_id,
            "import.start",
            "ERROR",
            "config.username not set, run: holmes config set username <name>",
        )
        click.echo("Error: config.username not set", err=True)
        click.echo("run: holmes config set username <name>", err=True)
        sys.exit(1)

    _logger.write_span(_trace_id, "import.start", "INFO", "import started", source=_source_for_trace)

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

    from holmes.kb.agent.runner import ImportAgentRunner

    def _make_runner() -> "ImportAgentRunner":
        return ImportAgentRunner(
            kb_root=kb_root,
            cfg=cfg,
            no_interactive=no_interactive,
            verbose=verbose,
            dry_run=dry_run,
            force_type=force_type,
            force=force,
        )

    def _print_report(report: "ImportReport", source_file: Optional[Path] = None) -> None:
        if report.errors:
            for err in report.errors:
                click.echo(f"  error: {err}", err=True)
        if report.warnings:
            for w in report.warnings:
                for line in w.splitlines():
                    click.echo(f"  warn: {line}")
        if dry_run:
            click.echo("(dry run — no files written)")
            if report.suggestions:
                for s in report.suggestions:
                    click.echo(f"  suggest: {s}")
        else:
            for t in report.created:
                click.echo(f"✓ Created: {t}")
            for entry_id in report.updated:
                click.echo(f"✓ Updated: {entry_id}")
            for name in report.skills_generated:
                click.echo(f"  skill:   {name}")
            if not report.created and not report.updated and not report.warnings:
                click.echo("No new entries created (duplicate or empty source).")
            if report.created:
                click.echo("  Review: holmes kb pending")

    # ------------------------------------------------------------------
    # Directory batch import mode
    # ------------------------------------------------------------------
    if import_dir is not None:
        import_dir_path = Path(import_dir)
        if not import_dir_path.exists():
            click.echo(f"Error: Directory does not exist: {import_dir_path}", err=True)
            sys.exit(1)
        importable = sorted(
            f for f in import_dir_path.iterdir()
            if f.is_file() and f.suffix.lower() in (".md", ".txt", ".rst")
        )
        if not importable:
            click.echo(f"No .md/.txt/.rst files found in {import_dir_path}", err=True)
            sys.exit(1)

        click.echo(f"Importing {len(importable)} file(s) from {import_dir_path}")
        total_entries = 0
        failed_files = 0
        runner = _make_runner()
        for idx, f in enumerate(importable, 1):
            prefix = f"[{idx}/{len(importable)}] {f.name}"
            try:
                source_text = f.read_text(encoding="utf-8")
                if len(source_text.strip()) < 50:
                    click.echo(f"{prefix} → warn: non-kb document, skipped")
                    continue
                report = runner.run(source_text, file_path=f)
                if report.errors:
                    click.echo(f"{prefix} → ✗ Import failed: {report.errors[0]}")
                    failed_files += 1
                else:
                    n = len(report.created)
                    if n == 0 and report.warnings:
                        click.echo(f"{prefix} → warn: {report.warnings[0]}")
                    else:
                        entries_word = "entry" if n == 1 else "entries"
                        click.echo(f"{prefix} → ✓ {n} {entries_word}")
                    total_entries += n
            except Exception as exc:
                click.echo(f"{prefix} → ✗ Import failed: {exc}")
                failed_files += 1

        summary_suffix = f" ({failed_files} file{'s' if failed_files != 1 else ''} failed)" if failed_files else ""
        click.echo(f"Done: {total_entries} pending {'entries' if total_entries != 1 else 'entry'}{summary_suffix}. Review: holmes kb pending")
        if failed_files == len(importable):
            sys.exit(1)
        return

    # ------------------------------------------------------------------
    # Single-file import mode
    # ------------------------------------------------------------------
    source_text = file.read_text(encoding="utf-8")
    if len(source_text.strip()) < 50:
        click.echo(
            f"Content too short ({len(source_text.strip())} chars). Minimum is 50 characters.",
            err=True,
        )
        sys.exit(1)

    runner = _make_runner()

    try:
        report = runner.run(source_text, file_path=file)
    except Exception as exc:
        msg = str(exc) or repr(exc)
        click.echo(f"✗ Import failed: {msg}", err=True)
        sys.exit(1)

    _print_report(report, source_file=file)
    if not dry_run and report.created:
        n = len(report.created)
        entries_word = "entries" if n != 1 else "entry"
        click.echo(f"✓ Created {n} pending {entries_word}")


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
@click.option("--type", "kb_type", default=None,
              help="Filter results by entry type (e.g. pitfall, model).")
@click.option("--all", "include_all", is_flag=True,
              help="Include deprecated entries and process sub-entries.")
@click.pass_context
def kb_search(
    ctx: click.Context,
    query: str,
    limit: int,
    as_json: bool,
    kb_type: Optional[str],
    include_all: bool,
) -> None:
    """Full-text search across all KB entries."""
    from holmes.kb.search import search

    kb_root = _require_kb_root(ctx)
    results = search(
        kb_root,
        query,
        limit=limit,
        exclude_sub_entries=not include_all,
        active_only=not include_all,
    )

    # Post-filter by type if requested; warn on unknown type.
    if kb_type:
        valid_types = {
            d.name for d in kb_root.iterdir()
            if d.is_dir() and not d.name.startswith(".")
            and d.name not in ("contributions", "skills")
        }
        if kb_type.lower() not in {t.lower() for t in valid_types}:
            click.echo(
                f"Warning: unknown type '{kb_type}'. Valid types: {', '.join(sorted(valid_types))}",
                err=True,
            )
        results = [r for r in results if r.kb_type.lower() == kb_type.lower()]

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
@click.option("--with-evidence", "with_evidence", is_flag=True,
              help="Show evidence summary from sidecar files.")
@click.pass_context
def kb_show(ctx: click.Context, entry_id: str, as_json: bool, with_evidence: bool) -> None:
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

    # Show evidence summary before content so it's visible without scrolling.
    if with_evidence:
        from holmes.kb.store import load_evidence
        evidence = load_evidence(kb_root, entry_id, [])
        if not evidence:
            click.echo("Evidence: none")
        else:
            contributors = sorted({str(e.get("contributor", "")) for e in evidence if e.get("contributor")})
            dates = sorted(str(e.get("date", "")) for e in evidence if e.get("date"))
            last_date = dates[-1] if dates else "unknown"
            contrib_str = ", ".join(contributors) if contributors else "unknown"
            click.echo(f"Evidence: {len(evidence)} sessions ({contrib_str}) — last: {last_date}")

    # M1: show [sub-entry of: <parent_id>] tag for process sub-entries.
    try:
        _post = fm.loads(content)
        _parent_id = _post.metadata.get("parent_id")
        if _parent_id:
            click.echo(f"[sub-entry of: {_parent_id}]")
    except Exception:  # noqa: BLE001
        pass

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
    """List all pending entries grouped by category, or show content of one.

    Scans new-format ``_pending/<category>/`` directories first, then the
    legacy ``contributions/pending/`` area for backwards compatibility.
    """
    from holmes.kb.pending import get_pending, list_pending

    kb_root = _require_kb_root(ctx)

    if show_id:
        # Try new format first, then legacy.
        from holmes.kb.store import _find_pending_entry
        new_path = _find_pending_entry(kb_root, show_id)
        if new_path is not None:
            click.echo(new_path.read_text(encoding="utf-8"))
            return
        raw = get_pending(kb_root, show_id)
        if raw is None:
            click.echo(f"Pending entry not found: {show_id}", err=True)
            sys.exit(1)
        click.echo(raw)
        return

    # --- Collect new-format entries (grouped by category) ---
    new_entries: list[dict] = []
    new_pending_root = kb_root / "_pending"
    if new_pending_root.is_dir():
        import frontmatter as _fm
        from datetime import timezone as _tz
        for md_file in sorted(new_pending_root.rglob("*.md")):
            if md_file.name.startswith("_"):
                continue
            try:
                post = _fm.load(str(md_file))
                meta = post.metadata
                cat = str(meta.get("category", "")) or md_file.parent.name
                created = str(meta.get("created_at", ""))
                if not created:
                    import datetime as _dt
                    created = _dt.datetime.fromtimestamp(
                        md_file.stat().st_mtime, tz=_tz.utc
                    ).isoformat()
                new_entries.append({
                    "id": str(meta.get("id", md_file.stem)),
                    "type": str(meta.get("type", "unknown")),
                    "title": str(meta.get("title", "Untitled")),
                    "category": cat,
                    "created_at": created,
                    "path": str(md_file),
                    "format": "new",
                })
            except Exception:  # noqa: BLE001
                pass

    # --- Collect legacy entries ---
    legacy_raw = list_pending(kb_root)
    legacy_entries = [
        {**e, "format": "legacy", "category": str(e.get("type", "unknown"))}
        for e in legacy_raw
    ]

    all_entries = new_entries + legacy_entries

    if as_json:
        click.echo(json.dumps(all_entries, ensure_ascii=False, default=str))
        return

    if not all_entries:
        click.echo("No pending entries.")
        return

    # --- Display: new entries grouped by category ---
    from collections import defaultdict
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for e in new_entries:
        by_cat[e["category"]].append(e)

    for cat in sorted(by_cat):
        group = by_cat[cat]
        click.echo(f"\n=== {cat} ({len(group)} {'entry' if len(group) == 1 else 'entries'}) ===")
        click.echo(f"  {'ID':<40} {'TYPE':<12} {'TITLE':<35} CREATED")
        click.echo("  " + "-" * 96)
        for e in group:
            click.echo(
                f"  {e['id']:<40} {e['type']:<12} {e['title'][:33]:<35} "
                f"{str(e['created_at'])[:10]}"
            )

    # --- Display: legacy entries ---
    if legacy_entries:
        click.echo(f"\n--- legacy ({len(legacy_entries)} {'entry' if len(legacy_entries) == 1 else 'entries'}) ---")
        click.echo(f"  {'ID':<40} {'TYPE':<12} {'TITLE':<35} CREATED")
        click.echo("  " + "-" * 96)
        for e in legacy_entries:
            click.echo(
                f"  {e['id']:<40} {e['type']:<12} {e['title'][:33]:<35} "
                f"{str(e.get('pending_since', e.get('created_at', '')))[:10]}"
            )


@kb.command("write-pending")
@click.option("--content", default=None, help="Markdown content with frontmatter.")
@click.option("--file", "file_path", default=None, type=click.Path(),
              help="Path to a Markdown file to read content from (alternative to --content).")
@click.option("--corrects", default=None,
              help="Entry ID this proposal intends to replace (correction workflow).")
@click.pass_context
def kb_write_pending(ctx: click.Context, content: Optional[str], file_path: Optional[str],
                     corrects: Optional[str]) -> None:
    """Write content to pending area. Use --corrects to submit a correction proposal."""
    from holmes.kb.governance import DuplicateTitleError
    from holmes.kb.pending import write_pending

    if content is not None and file_path is not None:
        click.echo("Error: --content and --file are mutually exclusive.", err=True)
        sys.exit(1)
    if content is None and file_path is None:
        click.echo("Error: one of --content or --file is required.", err=True)
        sys.exit(1)
    if file_path is not None:
        fp = Path(file_path)
        if not fp.exists():
            click.echo(f"Error: file not found: {file_path}", err=True)
            sys.exit(1)
        content = fp.read_text(encoding="utf-8")

    # Validate frontmatter presence before writing.
    if not (content or "").strip().startswith("---"):
        click.echo(
            'Error: content must include YAML frontmatter (starting with "---").',
            err=True,
        )
        sys.exit(1)

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


@kb.command("amend-pending")
@click.argument("pending_id")
@click.option("--content", default=None, help="New Markdown content with frontmatter.")
@click.option("--file", "file_path", default=None, type=click.Path(),
              help="Path to a Markdown file to read new content from.")
@click.pass_context
def kb_amend_pending(ctx: click.Context, pending_id: str, content: Optional[str],
                     file_path: Optional[str]) -> None:
    """Replace the content of a pending entry while preserving its system metadata."""
    import frontmatter as fm

    from holmes.kb.pending import get_pending

    if content is not None and file_path is not None:
        click.echo("Error: --content and --file are mutually exclusive.", err=True)
        sys.exit(1)
    if content is None and file_path is None:
        click.echo("Error: one of --content or --file is required.", err=True)
        sys.exit(1)
    if file_path is not None:
        fp = Path(file_path)
        if not fp.exists():
            click.echo(f"Error: file not found: {file_path}", err=True)
            sys.exit(1)
        content = fp.read_text(encoding="utf-8")

    kb_root = _require_kb_root(ctx)
    raw = get_pending(kb_root, pending_id)
    if raw is None:
        click.echo(f"Pending entry not found: {pending_id}", err=True)
        sys.exit(1)

    # Parse original to extract system metadata.
    original = fm.loads(raw)
    _system_keys = ("id", "pending_since", "source", "source_session", "pending")
    preserved = {k: original.metadata[k] for k in _system_keys if k in original.metadata}

    # Parse new content and overlay system metadata.
    new_post = fm.loads(content)
    new_post.metadata.update(preserved)
    # Inject required system timestamps.
    from datetime import datetime as _dt, timezone as _tz
    new_post.metadata["updated_at"] = _dt.now(_tz.utc).isoformat()
    new_post.metadata.setdefault("created_at", original.metadata.get("created_at", ""))
    # Re-derive suggested_type/suggested_category from new content.
    new_post.metadata["suggested_type"] = str(new_post.metadata.get("type", "pitfall"))
    new_post.metadata["suggested_category"] = str(new_post.metadata.get("category", ""))

    # Write back to original pending file path.
    pending_dir = kb_root / "contributions" / "pending"
    pending_path = pending_dir / f"{pending_id}.md"
    pending_path.write_text(fm.dumps(new_post), encoding="utf-8")
    click.echo(f"✓ Amended: {pending_id}")


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

    post = fm.loads(raw)

    # Idempotency check: if source_hash already exists in a confirmed entry,
    # clean up the stale pending file and exit 0 — no duplicate created.
    if not force:
        _source_hash = str(post.metadata.get("source_hash", "")).strip()
        if _source_hash:
            from holmes.kb.agent.tools import _find_all_entries_by_hash
            from holmes.kb.pending import PENDING_DIR
            _all = _find_all_entries_by_hash(kb_root, _source_hash)
            _confirmed = [(eid, fp) for eid, fp in _all if PENDING_DIR not in fp]
            if _confirmed:
                _existing_id = _confirmed[0][0]
                click.echo(f"⚠ Already confirmed as: {_existing_id}")
                click.echo(f"  Cleaned up stale pending: {pending_id}")
                delete_pending(kb_root, pending_id)
                return

    # Gate 2: Duplicate detection (skipped for correction proposals).
    _corrects_check = str(post.metadata.get("corrects", "")).strip()
    click.echo("Gate 2: Duplicate detection...")
    if _corrects_check:
        click.echo("  ✓ Skipped (correction proposal)")
    else:
        dup = check_duplicate(kb_root, raw)
        if dup.similar_entries and not force:
            click.echo("  Similar entries found:")
            for sim in dup.similar_entries:
                click.echo(f"    [{sim['id']}] {sim['title']} — {sim['similarity']:.0%}")
            if not click.confirm("  Duplicates detected. Confirm anyway?", default=False):
                sys.exit(0)
        else:
            click.echo("  ✓ No duplicates")

    # Gate 3: Forced preview (strip internal fields before display).
    _internal_fields = {"pending", "pending_since", "source", "source_session",
                        "suggested_type", "suggested_category"}
    _preview_post = fm.loads(raw)
    for _f in _internal_fields:
        _preview_post.metadata.pop(_f, None)
    _preview_raw = fm.dumps(_preview_post)

    click.echo("\nGate 3: Entry preview:")
    click.echo("─" * 60)
    if len(_preview_raw) > 800:
        click.echo("Content exceeds 800 chars. To review full content:")
        click.echo(f"  holmes kb pending --show {pending_id}")
        click.echo("")
        click.echo("─" * 60)
        _answer = click.prompt("Type 'yes' to confirm this entry")
        if _answer.lower() != "yes":
            click.echo("Aborted.")
            sys.exit(0)
    else:
        click.echo(_preview_raw if _preview_raw.strip() else "(empty content)")
        click.echo("─" * 60)
        if not click.confirm("Confirm this entry?", default=True):
            sys.exit(0)

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
        orig_maturity = str(orig_post.metadata.get("maturity", "draft"))
        post.metadata["id"] = corrects_id
        post.metadata["maturity"] = "verified"
        post.metadata["updated_at"] = now_iso
        post.metadata["evidence"] = orig_post.metadata.get("evidence") or []
        post.metadata["contributors"] = orig_post.metadata.get("contributors") or []
        # US3: inherit created_at from original entry
        orig_created = orig_post.metadata.get("created_at")
        if orig_created:
            post.metadata["created_at"] = orig_created
        # US4: append new contributor (deduplicated, order-preserving)
        if contributor:
            existing = list(post.metadata["contributors"])
            if contributor not in existing:
                post.metadata["contributors"] = list(dict.fromkeys(existing + [contributor]))
        del post.metadata["corrects"]
        for _f in ("pending", "pending_since", "source_session", "source",
                   "suggested_type", "suggested_category"):
            post.metadata.pop(_f, None)

        write_entry(orig_path, fm.dumps(post))
        delete_pending(kb_root, pending_id)
        rebuild_index_files(kb_root)
        append_log(kb_root, "correction", corrects_id, f"replaced by {pending_id}")
        click.echo(f"\n✓ Correction applied: {corrects_id} (snapshot: {snapshot_path.name})")
        # US7: maturity change notification
        new_maturity = "verified"
        click.echo(f"  maturity: {orig_maturity} → {new_maturity}")
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
    post.metadata.pop("source", None)
    post.metadata.pop("suggested_type", None)
    post.metadata.pop("suggested_category", None)

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
@click.argument("pending_id", required=False, default=None)
@click.option("--reason", default="", help="Rejection reason.")
@click.option("--stale-days", "stale_days", default=None, type=int,
              help="Batch reject all pending entries older than N days.")
@click.option("--dry-run", "dry_run", is_flag=True,
              help="Preview entries to be rejected without deleting (requires --stale-days).")
@click.pass_context
def kb_reject(ctx: click.Context, pending_id: Optional[str], reason: str,
              stale_days: Optional[int], dry_run: bool) -> None:
    """Reject and delete a pending entry. Use --stale-days N for batch reject."""
    from holmes.kb.pending import append_log, delete_pending, get_pending, list_pending

    kb_root = _require_kb_root(ctx)

    if stale_days is not None:
        # Batch reject mode.
        if stale_days < 0:
            click.echo("Error: --stale-days must be non-negative.", err=True)
            sys.exit(1)
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        cutoff = (_dt.now(_tz.utc) - _td(days=stale_days)).isoformat()
        count = 0
        for entry in list_pending(kb_root):
            time_ref = entry.get("pending_since") or entry.get("created_at") or ""
            if time_ref and time_ref < cutoff:
                if dry_run:
                    click.echo(entry["id"])
                else:
                    delete_pending(kb_root, entry["id"])
                    append_log(kb_root, "rejected", entry["id"], reason or "stale")
                count += 1
        suffix = " (dry run)" if dry_run else ""
        click.echo(f"Rejected: {count} stale entries{suffix}")
        return

    # Single-entry mode (original behavior).
    if not pending_id:
        click.echo("Error: provide a pending_id or use --stale-days N for batch reject.", err=True)
        sys.exit(1)
    raw = get_pending(kb_root, pending_id)
    if raw is None:
        click.echo(f"Pending entry not found: {pending_id}", err=True)
        sys.exit(1)

    if dry_run:
        click.echo(pending_id)
        click.echo(f"✓ Rejected: {pending_id} (dry run)")
        return

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
        click.echo("Run 'holmes kb resolve <id> --keep [A|B]' to resolve.")


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
        from holmes.kb.store import rebuild_index_files as _rebuild
        _rebuild(kb_root)
        click.echo("✓ Index rebuilt.")
        return

    result = resolve_conflict(kb_root, conflict_id, keep)  # type: ignore[arg-type]
    if result is None:
        click.echo(f"Conflict not found: {conflict_id}", err=True)
        sys.exit(1)
    append_conflict_log(kb_root, conflict_id, keep)  # type: ignore[arg-type]
    from holmes.kb.store import rebuild_index_files as _rebuild
    _rebuild(kb_root)
    click.echo(f"✓ Conflict {conflict_id} resolved (kept side {keep})")
    click.echo("✓ Index rebuilt.")


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
@click.option("--maturity", "kb_maturity", default=None, help="Filter by maturity level (draft/verified/proven).")
@click.option("--limit", default=0, type=int, help="Maximum entries to return (0 = unlimited).")
@click.option("--offset", default=0, type=int, help="Number of entries to skip.")
@click.option("--format", "fmt", default="table",
              type=click.Choice(["table", "json", "id-only"]),
              help="Output format (default: table).")
@click.option("--json", "as_json", is_flag=True, help="Shorthand for --format json.")
@click.option("--all", "include_all", is_flag=True,
              help="Include deprecated entries (default: active only).")
@click.option("--all-types", "include_all_types", is_flag=True,
              help="Include process sub-entries (default: hidden).")
@click.pass_context
def kb_list(
    ctx: click.Context,
    kb_type: Optional[str],
    category: Optional[str],
    query: Optional[str],
    kb_maturity: Optional[str],
    limit: int,
    offset: int,
    fmt: str,
    as_json: bool,
    include_all: bool,
    include_all_types: bool,
) -> None:
    """List all KB entries (reads index.json, rebuilds if missing)."""
    from holmes.kb.store import list_entries, rebuild_index_files

    kb_root = _require_kb_root(ctx)
    index_path = kb_root / "index.json"
    if not index_path.exists():
        rebuild_index_files(kb_root)

    # Warn on unknown type before filtering.
    if kb_type:
        valid_types = {
            d.name for d in kb_root.iterdir()
            if d.is_dir() and not d.name.startswith(".")
            and d.name not in ("contributions", "skills")
        }
        if kb_type.lower() not in {t.lower() for t in valid_types}:
            click.echo(
                f"Warning: unknown type '{kb_type}'. Valid types: {', '.join(sorted(valid_types))}",
                err=True,
            )

    # M1: --all disables kb_status filter (shows active + deprecated).
    # M1: --all-types shows process sub-entries too.
    entries = list_entries(
        kb_root,
        kb_type=kb_type,
        category=category,
        query=query,
        limit=limit,
        offset=offset,
        kb_status=None if include_all else "active",
        exclude_sub_entries=not include_all_types,
    )

    # Filter by maturity if specified.
    if kb_maturity:
        _valid_maturities = {"draft", "verified", "proven"}
        if kb_maturity.lower() not in _valid_maturities:
            click.echo(
                f"Warning: unknown maturity '{kb_maturity}'. "
                f"Valid values: {', '.join(sorted(_valid_maturities))}",
                err=True,
            )
        entries = [e for e in entries if e.maturity and e.maturity.lower() == kb_maturity.lower()]

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
@click.option("--show", "show_snapshot", default=None,
              help="Show full content of a named snapshot file.")
@click.pass_context
def kb_history(ctx: click.Context, entry_id: str, as_json: bool, show_snapshot: Optional[str]) -> None:
    """List version snapshots for a KB entry (.history/ directory)."""
    import frontmatter as fm

    from holmes.kb.history import HISTORY_DIR, list_snapshots

    kb_root = _require_kb_root(ctx)

    # --show: display snapshot content with path-traversal safety check.
    if show_snapshot is not None:
        from pathlib import Path as _Path
        if _Path(show_snapshot).name != show_snapshot:
            click.echo("Error: invalid snapshot name (no path separators allowed).", err=True)
            sys.exit(1)
        snap_path = kb_root / HISTORY_DIR / show_snapshot
        if not snap_path.exists():
            click.echo(f"Snapshot not found: {show_snapshot}", err=True)
            sys.exit(1)
        raw = snap_path.read_text(encoding="utf-8")
        # Strip internal snapshot fields before display.
        _snap_post = fm.loads(raw)
        for _f in ("replaced_at", "replaced_by", "snapshot_reason"):
            _snap_post.metadata.pop(_f, None)
        click.echo(fm.dumps(_snap_post))
        return

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
        sys.exit(1)

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
@click.option("--dry-run", "dry_run", is_flag=True,
              help="Preview entries to be archived without moving them.")
@click.pass_context
def kb_archive_orphans(ctx: click.Context, as_json: bool, dry_run: bool) -> None:
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
        if dry_run:
            archived.append(entry_id)
        else:
            try:
                archive_orphan(kb_root, entry_id)
                archived.append(entry_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{entry_id}: {exc}")

    suffix = " (dry run)" if dry_run else ""
    if as_json:
        payload: dict = {"archived": archived, "errors": errors}
        if dry_run:
            payload["dry_run"] = True
        click.echo(json.dumps(payload, ensure_ascii=False))
    else:
        if not archived:
            click.echo(f"No orphan draft entries found.{suffix}")
        else:
            for eid in archived:
                click.echo(eid)
            click.echo(f"Archived {len(archived)} orphan draft(s){suffix}")
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


@kb.command("approve")
@click.argument("entry_id")
@click.option("--no-interactive", is_flag=True, help="Skip all confirmation prompts (auto-accept Y).")
@click.pass_context
def kb_approve(ctx: click.Context, entry_id: str, no_interactive: bool) -> None:
    """Approve a pending entry: move from _pending/ to confirmed space.

    Runs a 4-step flow:

    \b
    Step 1 — Detect stale pending entries for the same source_file.
    Step 2 — Detect active confirmed entries for the same source_file.
    Step 3 — Atomically execute: cancel old pending + deprecate old confirmed + approve.
    Step 4 — Rebuild category index if _index.md exists.
    """
    import logging
    import time

    import frontmatter as fm

    from holmes.kb.store import (
        _find_pending_entry,
        approve_entry,
        deprecate_entry,
        find_entries_by_source_file,
        rebuild_index_files,
    )

    kb_root = _require_kb_root(ctx)
    cfg = load_config()

    # --- Locate pending entry ---
    pending_path = _find_pending_entry(kb_root, entry_id)
    if pending_path is None:
        click.echo(f"Error: '{entry_id}' not found in _pending/. Run 'holmes kb pending' to list entries.", err=True)
        sys.exit(1)

    try:
        post = fm.load(str(pending_path))
    except Exception as exc:
        click.echo(f"Error: cannot parse pending entry: {exc}", err=True)
        sys.exit(1)

    source_file = str(post.metadata.get("source_file", "")).strip()
    click.echo(f"\n準備 approve: {entry_id}")

    # --- Step 1: Detect stale pending entries ---
    old_pending = []
    if source_file:
        all_same_src = find_entries_by_source_file(kb_root, source_file)
        old_pending = [
            e for e in all_same_src
            if e.kb_status == "pending" and e.id != entry_id
        ]

    cancel_old_pending = False
    if old_pending:
        click.echo("\n[pending 空间] 发现同文档的旧 pending entries：")
        for e in old_pending:
            date_str = (e.created_at or "")[:10] or "未知日期"
            click.echo(f"  - {e.id}  ({date_str} import，未审核)")
        if no_interactive:
            cancel_old_pending = True
            click.echo("  取消旧 pending？→ Y（--no-interactive）")
        else:
            ans = click.prompt("  取消旧 pending", default="Y", show_default=True)
            cancel_old_pending = ans.strip().upper() in ("Y", "YES", "")

    # --- Step 2: Detect active confirmed entries ---
    old_confirmed = []
    if source_file:
        old_confirmed = [
            e for e in find_entries_by_source_file(kb_root, source_file)
            if e.kb_status == "active"
        ]

    deprecate_old = False
    if old_confirmed:
        click.echo("\n[confirmed 空间] 发现同文档的 active entries：")
        for e in old_confirmed:
            date_str = (e.updated_at or e.created_at or "")[:10] or "未知日期"
            click.echo(f"  - {e.id}  ({date_str} import，已 approve)")
        if no_interactive:
            deprecate_old = True
            click.echo("  标记为 deprecated？→ Y（--no-interactive）")
        else:
            ans = click.prompt("  标记为 deprecated", default="Y", show_default=True)
            deprecate_old = ans.strip().upper() in ("Y", "YES", "")

    # --- Step 3: Final confirmation and atomic execution ---
    n_cancel = len(old_pending) if cancel_old_pending else 0
    n_deprecate = len(old_confirmed) if deprecate_old else 0
    summary = f"取消 {n_cancel} 个旧 pending + deprecate {n_deprecate} 个旧 confirmed + approve 1 个新 entry"
    click.echo(f"\n执行：{summary}")

    if not no_interactive:
        ans = click.prompt("确认", default="Y", show_default=True)
        if ans.strip().upper() not in ("Y", "YES", ""):
            click.echo("已取消。")
            return

    t_start = time.monotonic()
    errors: list[str] = []

    # Approve first (write new file) — most important step.
    try:
        new_path = approve_entry(kb_root, entry_id)
    except Exception as exc:
        click.echo(f"Error: approve failed: {exc}", err=True)
        sys.exit(2)

    # Cancel old pending (delete files).
    if cancel_old_pending:
        import os
        for e in old_pending:
            try:
                os.unlink(e.file_path)
            except OSError as exc:
                errors.append(f"Failed to cancel pending {e.id}: {exc}")
                logging.warning("approve: failed to remove pending %s: %s", e.file_path, exc)

    # Deprecate old confirmed (in-place kb_status update).
    if deprecate_old:
        for e in old_confirmed:
            ok = deprecate_entry(kb_root, e.id)
            if not ok:
                errors.append(f"Failed to deprecate {e.id}")

    duration_ms = int((time.monotonic() - t_start) * 1000)

    # --- Step 4: Rebuild category index ---
    try:
        # Rebuild only if any _index.md exists under kb_root type dirs.
        has_index = any(
            (kb_root / t / "_index.md").exists()
            for t in ("pitfall", "model", "guideline", "process", "decision")
        )
        if has_index:
            rebuild_index_files(kb_root)
    except Exception as exc:  # noqa: BLE001
        logging.warning("approve: index rebuild failed: %s", exc)

    # --- Log span ---
    try:
        from holmes.kb.logger import HolmesLogger, derive_trace_id
        _log_dir = _holmes_home() / "logs"
        _logger = HolmesLogger(_log_dir)
        _trace_id = derive_trace_id(entry_id)
        _logger.write_span(
            _trace_id, "kb.approve", "INFO", "entry approved",
            entry_id=entry_id,
            user=cfg.username or "unknown",
            duration_ms=duration_ms,
        )
    except Exception:  # noqa: BLE001
        pass

    # --- Report ---
    click.echo(f"\n✓ Approved: {entry_id} → {new_path.relative_to(kb_root)}")
    if errors:
        click.echo("⚠ Partial errors (entry was approved):")
        for err in errors:
            click.echo(f"  - {err}", err=True)


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
    cfg = load_config()
    home = _holmes_home()
    click.echo(json.dumps({
        "kb_path": cfg.kb_path,
        "model": cfg.model,
        "api_base_url": cfg.api_base_url,
        "username": cfg.username,
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
    allowed_keys = {"kb_path", "model", "api_key", "api_base_url", "username"}
    if key not in allowed_keys:
        click.echo(f"Unknown config key: {key!r}. Allowed: {sorted(allowed_keys)}", err=True)
        sys.exit(1)
    setattr(cfg, key, value)
    save_config(cfg)
    click.echo(f"✓ {key} = {value}")


# ---------------------------------------------------------------------------
# holmes start — MCP server
# ---------------------------------------------------------------------------


@cli.command("start")
@click.option("--port", default=8765, help="Port for MCP server (default: 8765)")
@click.pass_context
def start_cmd(ctx: click.Context, port: int) -> None:
    """Start the Holmes KB MCP server (streamable-http transport).

    Client config: {"url": "http://localhost:<port>"}
    """
    kb_root = _require_kb_root(ctx)
    click.echo(f"Holmes KB MCP server running at http://localhost:{port}")
    from holmes.mcp.server import run_server
    run_server(kb_root, port=port)


# ---------------------------------------------------------------------------
# log group  (M8 — observability)
# ---------------------------------------------------------------------------


@cli.group("log")
def log_group() -> None:
    """View Holmes operation logs (traces and spans)."""


@log_group.command("list")
def log_list() -> None:
    """List all traces with a one-line summary each.

    Traces are classified as: import / draft / session / ? based on their spans.
    """
    log_dir = _holmes_home() / "logs"
    if not log_dir.exists():
        click.echo("No log entries found.")
        return

    # Collect all events grouped by trace_id.
    traces: dict[str, list[dict]] = {}
    for jsonl_file in sorted(log_dir.glob("*.jsonl")):
        for line in jsonl_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                tid = str(rec.get("trace", ""))
                if tid:
                    traces.setdefault(tid, []).append(rec)
            except json.JSONDecodeError:
                pass

    if not traces:
        click.echo("No log entries found.")
        return

    def _classify(events: list[dict]) -> str:
        spans = {str(e.get("span", "")) for e in events}
        trace_id = str(events[0].get("trace", "")) if events else ""
        if trace_id.startswith("session-"):
            return "session"
        for sp in spans:
            if sp.startswith("agent1.") or sp.startswith("agent2.") or sp == "lint":
                return "import"
        if "mcp.draft" in spans:
            return "draft"
        return "?"

    def _summary(events: list[dict], kind: str) -> str:
        if kind == "import":
            created = sum(1 for e in events if e.get("span") == "lint" and "created" in str(e.get("msg", "")))
            warns = sum(1 for e in events if e.get("level") == "WARN")
            parts = []
            if created:
                parts.append(f"created={created}")
            if warns:
                parts.append(f"warnings={warns}")
            return " ".join(parts) if parts else "in progress"
        if kind == "draft":
            return "pending import"
        if kind == "session":
            reads = sum(1 for e in events if str(e.get("span", "")).startswith("mcp.kb_read"))
            confirms = sum(1 for e in events if e.get("span") == "mcp.kb_confirm")
            drafts = sum(1 for e in events if e.get("span") == "mcp.draft")
            parts = []
            if reads:
                parts.append(f"read={reads}")
            if confirms:
                parts.append(f"confirmed={confirms}")
            if drafts:
                parts.append(f"draft={drafts}")
            return " ".join(parts) if parts else ""
        return ""

    click.echo(f"{'TRACE':<35} {'TYPE':<10} {'LAST DATE':<12} SUMMARY")
    click.echo("-" * 75)
    for tid, events in sorted(traces.items()):
        kind = _classify(events)
        last_ts = max(str(e.get("ts", "")) for e in events)
        last_date = last_ts[:10] if last_ts else "?"
        summary = _summary(events, kind)
        click.echo(f"{tid:<35} {kind:<10} {last_date:<12} {summary}")


@log_group.command("show")
@click.argument("trace_id")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON Lines.")
@click.option("--since", "since_date", default=None,
              help="Only show events from this date onwards (YYYY-MM-DD).")
def log_show(trace_id: str, as_json: bool, since_date: Optional[str]) -> None:
    """Show the full span timeline for a trace.

    TRACE_ID: The trace identifier (e.g. gpu-troubleshooting or session-a3f1).
    """
    from datetime import date as _date

    log_dir = _holmes_home() / "logs"

    # Validate --since date.
    since: Optional[_date] = None
    if since_date:
        try:
            since = _date.fromisoformat(since_date)
        except ValueError:
            click.echo("Error: --since must be YYYY-MM-DD format", err=True)
            sys.exit(1)

    # Collect matching events from all .jsonl files.
    events: list[dict] = []
    if log_dir.exists():
        for jsonl_file in sorted(log_dir.glob("*.jsonl")):
            # Quick skip: if --since provided and file date is before since, skip.
            if since:
                try:
                    from datetime import date as _d
                    file_date = _d.fromisoformat(jsonl_file.stem)
                    if file_date < since:
                        continue
                except ValueError:
                    pass
            for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if str(rec.get("trace", "")) != trace_id:
                        continue
                    if since:
                        event_date_str = str(rec.get("ts", ""))[:10]
                        try:
                            if _date.fromisoformat(event_date_str) < since:
                                continue
                        except ValueError:
                            pass
                    events.append(rec)
                except json.JSONDecodeError:
                    pass

    if not events:
        click.echo(f"No events found for trace: {trace_id}")
        return

    # Sort by timestamp.
    events.sort(key=lambda e: str(e.get("ts", "")))

    if as_json:
        for e in events:
            click.echo(json.dumps(e, ensure_ascii=False))
        return

    # Human-readable span tree.
    click.echo(f"trace: {trace_id}")
    click.echo("")

    for e in events:
        ts_str = str(e.get("ts", ""))
        # Format timestamp: remove T and trailing Z for readability.
        display_ts = ts_str.replace("T", " ").replace("Z", "").replace("+00:00", "")[:19]
        span = str(e.get("span", ""))
        level = str(e.get("level", "INFO"))
        msg = str(e.get("msg", ""))
        # Build extra summary from remaining fields.
        skip = {"ts", "trace", "span", "level", "msg"}
        extras = {k: v for k, v in e.items() if k not in skip}
        extra_str = "  ".join(f"{k}={v}" for k, v in extras.items())
        # Duration in seconds if available.
        dur = e.get("duration_ms")
        dur_str = f"{int(dur) // 1000}s" if dur is not None else ""
        level_tag = f" [{level}]" if level in ("WARN", "ERROR") else ""
        line = f"  {display_ts}  {span:<22} {dur_str:<5} {msg}"
        if extra_str:
            line = f"{line}  {extra_str}"
        if level_tag:
            line = f"{line}{level_tag}"
        click.echo(line)


if __name__ == "__main__":
    cli()
