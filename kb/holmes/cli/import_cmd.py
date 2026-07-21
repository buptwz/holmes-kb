"""Import command for Holmes CLI."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Optional

import click

from holmes.cli import cli
from holmes.config import _holmes_home, load_config
from holmes.kb.logger import HolmesLogger, derive_trace_id


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
    type=click.Choice(["pitfall", "model", "guideline", "process", "decision"]),
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
@click.option("--dag", "use_dag", is_flag=True, hidden=True, help="Deprecated (DAG pipeline removed).")
@click.option("--retry-entry", "retry_entry", default=None, hidden=True,
              help="Deprecated (DAG pipeline removed).")
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
    use_dag: bool,
    retry_entry: Optional[str],
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
    if retry_entry is not None and import_dir is not None:
        click.echo("Error: --retry-entry requires FILE, not --dir.", err=True)
        sys.exit(1)
    if retry_entry is not None and file is None:
        click.echo("Error: --retry-entry requires a source FILE argument.", err=True)
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

    from holmes.kb.agent.observability import init_langfuse_from_config
    init_langfuse_from_config(cfg)

    from holmes.kb.agent.runner import ImportAgentRunner
    from holmes.kb.progress import ProgressReporter

    _reporter = ProgressReporter.from_click()

    def _make_runner() -> "ImportAgentRunner":
        return ImportAgentRunner(
            kb_root=kb_root,
            cfg=cfg,
            no_interactive=no_interactive,
            verbose=verbose,
            dry_run=dry_run,
            force_type=force_type,
            force=force,
            use_dag=use_dag,
            reporter=_reporter,
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
                click.echo("  Review: holmes pending")

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
        click.echo(f"Done: {total_entries} pending {'entries' if total_entries != 1 else 'entry'}{summary_suffix}. Review: holmes pending")
        if failed_files == len(importable):
            sys.exit(1)
        return

    # ------------------------------------------------------------------
    # Single-file import mode
    # ------------------------------------------------------------------
    try:
        source_text = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        click.echo(f"Error: file not found: {file}", err=True)
        sys.exit(1)
    except UnicodeDecodeError:
        click.echo(f"Error: {file} is not valid UTF-8 text.", err=True)
        sys.exit(1)
    except OSError as exc:
        click.echo(f"Error: cannot read {file}: {exc}", err=True)
        sys.exit(1)
    if len(source_text.strip()) < 50:
        click.echo(
            f"Content too short ({len(source_text.strip())} chars). Minimum is 50 characters.",
            err=True,
        )
        sys.exit(1)

    # --retry-entry removed in 042 (DAG pipeline deleted).
    if retry_entry is not None:
        click.echo("Error: --retry-entry is no longer supported (DAG pipeline removed).", err=True)
        sys.exit(1)

    runner = _make_runner()
    _reporter.start(f"开始导入: {file.name if file else '(stdin)'}")

    try:
        report = runner.run(source_text, file_path=file)
    except Exception as exc:
        msg = str(exc) or repr(exc)
        # Dry-run without LLM credentials: show hint instead of crashing.
        if dry_run and ("api_key" in msg.lower() or "credentials" in msg.lower()):
            click.echo(f"LLM not configured — dry-run will skip LLM phases.")
            click.echo("(dry run — no files written)")
            return
        click.echo(f"✗ Import failed: {msg}", err=True)
        sys.exit(1)

    _print_report(report, source_file=file)
    if not dry_run and report.created:
        n = len(report.created)
        entries_word = "entries" if n != 1 else "entry"
        click.echo(f"✓ Created {n} pending {entries_word}")

    # Draft archiving: if source is under _drafts/ (but not _imported/), move it.
    if not dry_run and not report.errors and file is not None:
        try:
            file_resolved = file.resolve()
            drafts_dir = kb_root / "_drafts"
            imported_dir = drafts_dir / "_imported"
            if (
                str(file_resolved).startswith(str(drafts_dir.resolve()))
                and "_imported" not in file_resolved.parts
            ):
                imported_dir.mkdir(parents=True, exist_ok=True)
                dest = imported_dir / file.name
                shutil.move(str(file_resolved), str(dest))
                click.echo(f"  archived: _drafts/_imported/{file.name}")
        except Exception as exc:
            click.echo(f"  warn: could not archive draft: {exc}", err=True)
