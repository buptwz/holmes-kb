"""Governance commands: lint, decay, archive-orphans, doctor."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from holmes.cli import cli, kb, _require_kb_root
from holmes.config import load_config


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
# decay
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# archive-orphans
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


@kb.command("doctor")
@click.option("--fix", is_flag=True, help="Apply safe auto-fixes (create dirs, rebuild index, upgrade maturity).")
@click.option("--verbose", is_flag=True, help="Show per-entry detail for each finding.")
@click.option("--check-api", is_flag=True, help="Test LLM API connectivity (sends a small request).")
@click.option("--json", "as_json", is_flag=True, help="Output results as JSON.")
@click.pass_context
def kb_doctor(ctx: click.Context, fix: bool, verbose: bool, check_api: bool, as_json: bool) -> None:
    """Comprehensive self-diagnostic for the Holmes KB system.

    Checks configuration, directory structure, entry integrity, index
    consistency, search health, skill validation, evidence/maturity
    correctness, and git state.

    \b
    Without --fix: read-only diagnosis.
    With --fix:    apply safe, idempotent fixes (create dirs, rebuild
                   indexes, fix tags, upgrade maturity).
    """
    from holmes.kb.doctor import run_doctor

    kb_path = ctx.obj.get("kb_path") or load_config().kb_path
    kb_root = Path(kb_path) if kb_path else None

    click.echo("⠿ 正在运行诊断...", err=True)
    report = run_doctor(
        kb_root=kb_root,
        fix=fix,
        verbose=verbose,
        check_api=check_api,
    )
    click.echo(f"✓ 诊断完成（{report.elapsed_ms}ms）", err=True)

    if as_json:
        click.echo(json.dumps({
            "items": [
                {"category": i.category, "level": i.level, "message": i.message}
                for i in report.items
            ],
            "summary": {
                "errors": report.error_count,
                "warnings": report.warn_count,
                "fixes": report.fix_count,
                "elapsed_ms": report.elapsed_ms,
            },
        }, ensure_ascii=False, indent=2))
        return

    # Human-readable output
    SYMBOLS = {"ok": "✓", "fixed": "✓ fixed", "warn": "⚠", "error": "✗"}
    current_cat = ""
    for item in report.items:
        if item.category != current_cat:
            current_cat = item.category
            click.echo(f"\n{current_cat.upper()}")
        sym = SYMBOLS.get(item.level, "?")
        click.echo(f"  {sym}  {item.message}")

    # Summary
    click.echo(f"\n{'─' * 60}")
    parts = []
    if report.error_count:
        parts.append(f"{report.error_count} errors")
    if report.warn_count:
        parts.append(f"{report.warn_count} warnings")
    if report.fix_count:
        parts.append(f"{report.fix_count} fixes applied")
    if not parts:
        parts.append("all checks passed")
    click.echo(f"  {', '.join(parts)}  ({report.elapsed_ms}ms)")

    if report.error_count or report.warn_count:
        click.echo()
        if not fix and (report.warn_count or report.error_count):
            click.echo("  Tip: run 'holmes doctor --fix' to apply auto-fixes")
        if report.error_count:
            sys.exit(1)


# ---------------------------------------------------------------------------
# Top-level registration (spec 043, D8)
# ---------------------------------------------------------------------------

# Commands are also registered on the top-level CLI (`holmes <cmd>`); the
# hidden `holmes kb <cmd>` aliases stay for one version cycle.
for _cmd in (kb_lint, kb_decay, kb_archive_orphans, kb_doctor):
    cli.add_command(_cmd)
