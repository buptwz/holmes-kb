"""Browse / read-only KB commands extracted from cli.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from holmes.cli import _require_kb_root, cli, kb


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

    # Validate type before passing to search.
    if kb_type:
        _known_types = {"pitfall", "model", "guideline", "process", "decision"}
        if kb_type.lower() not in _known_types:
            click.echo(
                f"Warning: unknown type '{kb_type}'. Valid types: {', '.join(sorted(_known_types))}",
                err=True,
            )

    results = search(
        kb_root,
        query,
        limit=limit,
        exclude_sub_entries=not include_all,
        active_only=not include_all,
        kb_type=kb_type.lower() if kb_type else None,
    )

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

    click.echo(content)


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
        kb_status=None if include_all else "active",
        exclude_sub_entries=not include_all_types,
    )

    # Filter by maturity if specified — before pagination.
    if kb_maturity:
        _valid_maturities = {"draft", "verified", "proven"}
        if kb_maturity.lower() not in _valid_maturities:
            click.echo(
                f"Warning: unknown maturity '{kb_maturity}'. "
                f"Valid values: {', '.join(sorted(_valid_maturities))}",
                err=True,
            )
        entries = [e for e in entries if e.maturity and e.maturity.lower() == kb_maturity.lower()]

    # Apply pagination after all filters.
    if offset:
        entries = entries[offset:]
    if limit:
        entries = entries[:limit]

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


# ---------------------------------------------------------------------------
# Top-level registration (spec 043, D8)
# ---------------------------------------------------------------------------

# Commands are also registered on the top-level CLI (`holmes <cmd>`); the
# hidden `holmes kb <cmd>` aliases stay for one version cycle.
for _cmd in (kb_overview, kb_search, kb_show, kb_read_category, kb_list, kb_history):
    cli.add_command(_cmd)
