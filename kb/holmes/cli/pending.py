"""Holmes CLI — pending management, approve, rebuild-index, drafts, delete commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import click

from holmes.cli import _require_kb_root, cli, kb
from holmes.config import _holmes_home, load_config

if TYPE_CHECKING:
    from holmes.config import HolmesConfig
    from holmes.kb.agent.provider.base import LLMProvider


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

    Scans the canonical ``contributions/pending/`` area and the legacy
    ``_pending/<type>/<category>/`` layout (read-only compatibility).
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
    if new_entries:
        from collections import defaultdict

        by_cat: dict[str, list[dict]] = defaultdict(list)
        for e in new_entries:
            by_cat[e["category"]].append(e)

        for cat in sorted(by_cat):
            click.echo(f"\n[{cat}]")
            for e in by_cat[cat]:
                date_str = str(e["created_at"])[:10]
                entry_title = e.get("title", "")[:50]
                click.echo(f"  {e['id']:<42} [{e['type']}]  {entry_title}")
                click.echo(f"  {'':42} {'':12} {date_str} import")

        click.echo(f"\n_pending/ ({len(new_entries)} {'entry' if len(new_entries) == 1 else 'entries'})")

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
    click.echo(f"\u2713 Amended: {pending_id}")


# ---------------------------------------------------------------------------
# approve helpers
# ---------------------------------------------------------------------------


def _rebuild_index_if_needed(kb_root: Path, logging_mod: object) -> None:
    """Rebuild category index files if any _index.md exists."""
    try:
        has_index = any(
            (kb_root / t / "_index.md").exists()
            for t in ("pitfall", "model", "guideline", "process", "decision")
        )
        if has_index:
            from holmes.kb.store import rebuild_index_files
            rebuild_index_files(kb_root)
    except Exception as exc:
        import logging as _logging
        _logging.warning("approve: index rebuild failed: %s", exc)


def _log_approve_span(cfg: "HolmesConfig", entry_id: str, duration_ms: int) -> None:
    """Write a kb.approve log span if logger is available."""
    try:
        from holmes.kb.logger import HolmesLogger, derive_trace_id
        _log_dir = _holmes_home() / "logs"
        _logger = HolmesLogger(_log_dir)
        _trace_id = derive_trace_id(entry_id)
        _logger.write_span(
            _trace_id, "kb.approve", "INFO", "entry approved",
            entry_id=entry_id,
            user=getattr(cfg, "username", None) or "unknown",
            duration_ms=duration_ms,
        )
    except Exception:
        pass


class _DedupClientAdapter:
    """Adapt an LLMProvider to the Anthropic-shaped client SemanticDeduplicator expects.

    SemanticDeduplicator calls ``client.messages.create(...)`` and reads
    ``response.content[0].text``; LLMProvider exposes ``simple_complete``.
    """

    def __init__(self, provider: "LLMProvider") -> None:
        self._provider = provider
        self.messages = self  # client.messages.create(...)

    def create(self, model: str, max_tokens: int, messages: list) -> object:
        from types import SimpleNamespace
        text = self._provider.simple_complete(list(messages), max_tokens=max_tokens)
        return SimpleNamespace(content=[SimpleNamespace(text=text)])


def _entry_summary(post: object) -> str:
    """Root-cause text for dedup comparison; falls back to the entry title."""
    import re
    m = re.search(r"## Root Cause\s*\n(.*?)(?=\n##|\Z)", post.content or "", re.DOTALL)
    if m and m.group(1).strip():
        return m.group(1).strip()[:500]
    return str(post.metadata.get("title", ""))


def _lookup_entry_title(kb_root: Path, entry_id: str) -> Optional[str]:
    """Return the title of an existing entry, or None if not found."""
    from holmes.kb.store import list_entries
    for meta in list_entries(kb_root):
        if meta.id == entry_id:
            return meta.title
    return None


def _semantic_dedup_check(
    kb_root: Path, post: object, cfg: "HolmesConfig"
) -> tuple[Optional[object], Optional[str], Optional[str]]:
    """Run SemanticDeduplicator against active entries in the same category.

    Returns (result, candidate_title, error). ``error`` is not None when the
    check could not run (provider/LLM failure) — callers must treat that as
    "skipped", never as a block.
    """
    try:
        from holmes.kb.agent.dedup import SemanticDeduplicator
        from holmes.kb.agent.provider.factory import create_provider

        provider = create_provider(cfg)
        dedup = SemanticDeduplicator(
            kb_root,
            client=_DedupClientAdapter(provider),
            model=str(getattr(cfg, "model", "") or ""),
        )
        meta = post.metadata
        result = dedup.check(
            source_hash=str(meta.get("source_hash", "")).strip(),
            new_summary=_entry_summary(post),
            kb_type=str(meta.get("type", "")).strip(),
            category=str(meta.get("category", "")).strip() or None,
        )
    except Exception as exc:  # noqa: BLE001
        return None, None, str(exc)

    title = None
    if result.entry_id:
        title = _lookup_entry_title(kb_root, result.entry_id)
    return result, title, None


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------


@kb.command("approve")
@click.argument("entry_id")
@click.option("--no-interactive", is_flag=True, help="Skip all confirmation prompts (auto-accept Y).")
@click.option("--skip-dedup", is_flag=True, help="Skip the semantic dedup gate.")
@click.pass_context
def kb_approve(ctx: click.Context, entry_id: str, no_interactive: bool, skip_dedup: bool) -> None:
    """Approve a pending entry: move from contributions/pending/ to confirmed space.

    \b
    Step 1 -- Detect old pending/confirmed entries from the same source file.
    Step 2 -- Show summary and confirm.
    Step 3 -- Cancel old pending + deprecate old confirmed + approve new entry.
    Step 4 -- Rebuild index.

    A semantic dedup gate (spec 043, D2/P13) runs before Step 2: suspected
    duplicates require human confirmation; --skip-dedup bypasses it.
    """
    import logging
    import time

    import frontmatter as fm

    from holmes.kb.agent.dedup import DeduResultKind
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
        click.echo(f"Error: '{entry_id}' not found in the pending area. Run 'holmes pending' to list entries.", err=True)
        sys.exit(1)

    try:
        post = fm.load(str(pending_path))
    except Exception as exc:
        click.echo(f"Error: cannot parse pending entry: {exc}", err=True)
        sys.exit(1)

    source_file = str(post.metadata.get("source_file", "")).strip()
    kb_type = str(post.metadata.get("type", "")).strip()
    entry_title = str(post.metadata.get("title", "")).strip()

    click.echo(f"\n\u6e96\u5099 approve: {entry_id}")
    click.echo(f"  [{kb_type}]  {entry_title}")

    old_pending = []
    if source_file:
        all_same_src = find_entries_by_source_file(kb_root, source_file)
        old_pending = [e for e in all_same_src if e.kb_status == "pending" and e.id != entry_id]

    cancel_old_pending = False
    if old_pending:
        click.echo("\n[pending \u7a7a\u9593] \u767c\u73fe\u540c\u6587\u6a94\u7684\u820a pending entries\uff1a")
        for e in old_pending:
            date_str = (e.created_at or "")[:10] or "\u672a\u77e5\u65e5\u671f"
            click.echo(f"  - {e.id}  ({date_str} import\uff0c\u672a\u5be9\u6838)")
        if no_interactive:
            cancel_old_pending = True
            click.echo("  \u53d6\u6d88\u820a pending\uff1f\u2192 Y\uff08--no-interactive\uff09")
        else:
            ans = click.prompt("  \u53d6\u6d88\u820a pending", default="Y", show_default=True)
            cancel_old_pending = ans.strip().upper() in ("Y", "YES", "")

    old_confirmed = []
    if source_file:
        old_confirmed = [e for e in find_entries_by_source_file(kb_root, source_file) if e.kb_status == "active"]

    deprecate_old = False
    if old_confirmed:
        click.echo("\n[confirmed \u7a7a\u9593] \u767c\u73fe\u540c\u6587\u6a94\u7684 active entries\uff1a")
        for e in old_confirmed:
            date_str = (e.updated_at or e.created_at or "")[:10] or "\u672a\u77e5\u65e5\u671f"
            click.echo(f"  - {e.id}  ({date_str} import\uff0c\u5df2 approve)")
        if no_interactive:
            deprecate_old = True
            click.echo("  \u6a19\u8a18\u70ba deprecated\uff1f\u2192 Y\uff08--no-interactive\uff09")
        else:
            ans = click.prompt("  \u6a19\u8a18\u70ba deprecated", default="Y", show_default=True)
            deprecate_old = ans.strip().upper() in ("Y", "YES", "")

    # --- Semantic dedup gate (spec 043, D2/P13) ---
    dedup_result = None
    if skip_dedup:
        click.echo("\n[\u8a9e\u610f\u67e5\u91cd] \u5df2\u8df3\u904e\uff08--skip-dedup\uff09")
    else:
        dedup_result, dedup_title, dedup_error = _semantic_dedup_check(kb_root, post, cfg)
        if dedup_error is not None:
            click.echo(f"\n\u26a0 [\u8a9e\u610f\u67e5\u91cd] \u7121\u6cd5\u57f7\u884c\uff08{dedup_error}\uff09\uff0c\u8df3\u904e\u67e5\u91cd\u7e7c\u7e8c")
        elif dedup_result is not None and dedup_result.kind != DeduResultKind.CREATE:
            click.echo("\n\u26a0 [\u8a9e\u610f\u67e5\u91cd] \u767c\u73fe\u7591\u4f3c\u91cd\u8907\u7684 active entry\uff1a")
            click.echo(f"  - {dedup_result.entry_id}  {dedup_title or ''}")
            click.echo(f"    \u5224\u5b9a\uff1a{dedup_result.kind.value}\uff08confidence {dedup_result.confidence:.0%}\uff09")
            click.echo(f"    LLM \u7406\u7531\uff1a{dedup_result.reason}")
            if no_interactive:
                click.echo("  \u7591\u4f3c\u91cd\u8907\u4ecd\u7e7c\u7e8c approve\uff08--no-interactive\uff09")
            else:
                ans = click.prompt("  \u4ecd\u8981 approve", default="N", show_default=True)
                if ans.strip().upper() not in ("Y", "YES"):
                    click.echo("\u5df2\u53d6\u6d88\u3002")
                    return

    n_cancel = len(old_pending) if cancel_old_pending else 0
    n_deprecate = len(old_confirmed) if deprecate_old else 0
    summary = f"\u53d6\u6d88 {n_cancel} \u500b\u820a pending + deprecate {n_deprecate} \u500b\u820a confirmed + approve 1 \u500b\u65b0 entry"
    click.echo(f"\n\u57f7\u884c\uff1a{summary}")

    if not no_interactive:
        ans = click.prompt("\u78ba\u8a8d", default="Y", show_default=True)
        if ans.strip().upper() not in ("Y", "YES", ""):
            click.echo("\u5df2\u53d6\u6d88\u3002")
            return

    t_start = time.monotonic()
    errors: list[str] = []

    click.echo("  \u2800\u283f \u6b63\u5728 approve...", err=True)
    try:
        new_path = approve_entry(kb_root, entry_id)
    except Exception as exc:
        click.echo(f"Error: approve failed: {exc}", err=True)
        sys.exit(2)

    if cancel_old_pending:
        click.echo(f"  \u2800\u283f \u53d6\u6d88 {len(old_pending)} \u500b\u820a pending...", err=True)
        import os
        for e in old_pending:
            try:
                os.unlink(e.file_path)
            except OSError as exc:
                errors.append(f"Failed to cancel pending {e.id}: {exc}")
                logging.warning("approve: failed to remove pending %s: %s", e.file_path, exc)

    if deprecate_old:
        click.echo(f"  \u2800\u283f \u6a19\u8a18 {len(old_confirmed)} \u500b\u820a confirmed \u70ba deprecated...", err=True)
        for e in old_confirmed:
            ok = deprecate_entry(kb_root, e.id)
            if not ok:
                errors.append(f"Failed to deprecate {e.id}")

    click.echo("  \u2800\u283f \u91cd\u5efa\u7d22\u5f15...", err=True)
    duration_ms = int((time.monotonic() - t_start) * 1000)
    _rebuild_index_if_needed(kb_root, logging)
    new_id = new_path.stem  # permanent ID minted by approve_entry (spec 043, T021b)
    _log_approve_span(cfg, new_id, duration_ms)

    click.echo(f"\n\u2713 Approved: {new_id} \u2192 {new_path.relative_to(kb_root)}")
    if new_id != entry_id:
        click.echo(f"  (former temporary id: {entry_id})")
    if dedup_result is not None and dedup_result.kind != DeduResultKind.CREATE:
        click.echo(
            f"\u26a0 dedup: {dedup_result.kind.value} \u2192 {dedup_result.entry_id}"
            f" ({dedup_result.reason})"
        )
    if errors:
        click.echo("\u26a0 Partial errors (entry was approved):")
        for err in errors:
            click.echo(f"  - {err}", err=True)


# ---------------------------------------------------------------------------
# rebuild-index
# ---------------------------------------------------------------------------


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
    click.echo(f"\u2713 Index rebuilt: {count} entries")


# ---------------------------------------------------------------------------
# drafts
# ---------------------------------------------------------------------------


@kb.command("drafts")
@click.pass_context
def kb_drafts(ctx: click.Context) -> None:
    """List draft documents in _drafts/ waiting to be imported."""
    import frontmatter as _fm

    kb_root = _require_kb_root(ctx)
    drafts_dir = kb_root / "_drafts"
    imported_dir = drafts_dir / "_imported"

    if not drafts_dir.exists():
        click.echo("\u6682\u65e0\u5f85 import \u7684\u8349\u7a3f")
        return

    files = [
        f for f in sorted(drafts_dir.iterdir())
        if f.is_file() and f.suffix == ".md" and f.resolve() != imported_dir.resolve()
    ]
    # Also exclude anything inside _imported/
    files = [f for f in files if not str(f).startswith(str(imported_dir))]

    if not files:
        click.echo("\u6682\u65e0\u5f85 import \u7684\u8349\u7a3f")
        return

    # Read frontmatter metadata per file; sort by saved_at descending
    entries = []
    for f in files:
        try:
            post = _fm.load(str(f))
            saved_at = str(post.metadata.get("saved_at", ""))
            source = str(post.metadata.get("source", "unknown"))
        except Exception:
            saved_at = ""
            source = "unknown"
        entries.append((f.name, saved_at, source))

    # Sort by saved_at descending (ISO timestamps sort lexicographically)
    entries.sort(key=lambda x: x[1], reverse=True)

    click.echo(f"_drafts/ ({len(entries)} pending)")
    for name, saved_at, source in entries:
        date_str = saved_at[:10] if saved_at else "(unknown date)"
        click.echo(f"  {name:<45} {date_str}  [via {source}]")
    click.echo()
    click.echo("\u904b\u884c holmes import _drafts/<file> \u6b63\u5f0f\u5c0e\u5165\u3002")


# ---------------------------------------------------------------------------
# soft delete
# ---------------------------------------------------------------------------


@kb.command("delete")
@click.argument("entry_id")
@click.option("--force", is_flag=True,
              help="Skip confirmation prompt and delete immediately.")
@click.pass_context
def kb_delete(ctx: click.Context, entry_id: str, force: bool) -> None:
    """Soft-delete a KB entry by moving it to _trash/<type>/<category>/.

    Deleted files are git-tracked and can be restored via 'git checkout'.
    """
    import time

    from holmes.kb.store import (
        _find_pending_entry,
        find_entry,
        move_to_trash,
    )

    kb_root = _require_kb_root(ctx)

    # --- Phase 1: Preview ---
    src_path = _find_pending_entry(kb_root, entry_id) or find_entry(kb_root, entry_id)
    if src_path is None:
        click.echo(f"Error: Entry not found: {entry_id}", err=True)
        sys.exit(1)

    click.echo(f"Will move to _trash/:")
    click.echo(f"  {src_path}")

    # --- Phase 2: Confirm ---
    if not force:
        confirmed = click.confirm("Proceed?", default=True)
        if not confirmed:
            click.echo("Aborted.")
            return

    # --- Phase 3: Execute ---
    cfg = load_config()
    t0 = time.time()

    try:
        moved = move_to_trash(kb_root, entry_id)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"Error: Deletion failed: {exc}", err=True)
        sys.exit(1)

    duration_ms = int((time.time() - t0) * 1000)

    # --- Phase 4: Report ---
    click.echo(f"Moved {len(moved)} file(s) to _trash/. Recoverable via:")
    for original_path, trash_path in moved:
        click.echo(f"  {trash_path}")
        click.echo(f"    restore: git checkout HEAD -- {original_path}")

    # --- Phase 5: Log ---
    try:
        from holmes.kb.logger import HolmesLogger, derive_trace_id
        _log_dir = _holmes_home() / "logs"
        _logger = HolmesLogger(_log_dir)
        _trace_id = derive_trace_id(entry_id)
        _logger.write_span(
            _trace_id,
            "kb.delete",
            "INFO",
            "deleted",
            entry_id=entry_id,
            user=cfg.username or "unknown",
            duration_ms=duration_ms,
        )
    except Exception:  # noqa: BLE001
        pass  # Logging failure must not affect the delete outcome.


# ---------------------------------------------------------------------------
# Top-level registration (spec 043, D8)
# ---------------------------------------------------------------------------

# Commands are also registered on the top-level CLI (`holmes <cmd>`); the
# hidden `holmes kb <cmd>` aliases stay for one version cycle.
for _cmd in (kb_pending, kb_write_pending, kb_amend_pending, kb_approve,
             kb_rebuild_index, kb_drafts, kb_delete):
    cli.add_command(_cmd)
