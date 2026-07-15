"""Holmes CLI — confirm, reject, merge, conflict resolution commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from holmes.cli import kb, _require_kb_root


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
        "outcome": "solved",
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
    """3-gate confirm: schema -> duplicate check -> preview -> promote to KB.

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
        click.echo("\u2717 Schema errors:")
        for err in result.errors:
            click.echo(f"  - {err}")
        sys.exit(1)
    click.echo("  \u2713 Schema valid")

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
                click.echo(f"\u26a0 Already confirmed as: {_existing_id}")
                click.echo(f"  Cleaned up stale pending: {pending_id}")
                delete_pending(kb_root, pending_id)
                return

    # Gate 2: Duplicate detection (skipped for correction proposals).
    _corrects_check = str(post.metadata.get("corrects", "")).strip()
    click.echo("Gate 2: Duplicate detection...")
    if _corrects_check:
        click.echo("  \u2713 Skipped (correction proposal)")
    else:
        dup = check_duplicate(kb_root, raw)
        if dup.similar_entries and not force:
            click.echo("  Similar entries found:")
            for sim in dup.similar_entries:
                click.echo(f"    [{sim['id']}] {sim['title']} \u2014 {sim['similarity']:.0%}")
            if not click.confirm("  Duplicates detected. Confirm anyway?", default=False):
                sys.exit(0)
        else:
            click.echo("  \u2713 No duplicates")

    # Gate 3: Forced preview (strip internal fields before display).
    _internal_fields = {"pending", "pending_since", "source", "source_session",
                        "suggested_type", "suggested_category"}
    _preview_post = fm.loads(raw)
    for _f in _internal_fields:
        _preview_post.metadata.pop(_f, None)
    _preview_raw = fm.dumps(_preview_post)

    click.echo("\nGate 3: Entry preview:")
    click.echo("\u2500" * 60)
    if len(_preview_raw) > 800:
        click.echo("Content exceeds 800 chars. To review full content:")
        click.echo(f"  holmes pending --show {pending_id}")
        click.echo("")
        click.echo("\u2500" * 60)
        _answer = click.prompt("Type 'yes' to confirm this entry")
        if _answer.lower() != "yes":
            click.echo("Aborted.")
            sys.exit(0)
    else:
        click.echo(_preview_raw if _preview_raw.strip() else "(empty content)")
        click.echo("\u2500" * 60)
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
        click.echo(f"\n\u2713 Correction applied: {corrects_id} (snapshot: {snapshot_path.name})")
        # US7: maturity change notification
        new_maturity = "verified"
        click.echo(f"  maturity: {orig_maturity} \u2192 {new_maturity}")
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
        "outcome": "solved",
        "context": f"confirmed from pending {pending_id}",
    }
    append_evidence(kb_root, new_id, evidence_record)
    add_contributor(kb_root, new_id, confirming_contributor)

    click.echo(f"\n\u2713 Entry confirmed: {new_id}")


@kb.command("reject")
@click.argument("pending_id", required=False, default=None)
@click.option("--reason", default="", help="Rejection reason.")
@click.option("--stale-days", "stale_days", default=None, type=int,
              help="Batch reject all pending entries older than N days.")
@click.option("--dry-run", "dry_run", is_flag=True,
              help="Preview entries to be rejected without deleting (requires --stale-days).")
@click.option("--force", "force", is_flag=True,
              help="Skip confirmation prompt.")
@click.pass_context
def kb_reject(ctx: click.Context, pending_id: Optional[str], reason: str,
              stale_days: Optional[int], dry_run: bool, force: bool) -> None:
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
        candidates = []
        for entry in list_pending(kb_root):
            time_ref = entry.get("pending_since") or entry.get("created_at") or ""
            if time_ref and time_ref < cutoff:
                candidates.append(entry)
        if not candidates:
            click.echo("No stale entries found.")
            return
        # Show what will be rejected and confirm.
        click.echo(f"Will reject {len(candidates)} stale entries (>{stale_days} days):")
        for entry in candidates:
            title = entry.get("title", "")[:50] or "(untitled)"
            click.echo(f"  {entry['id']}  {title}")
        if dry_run:
            click.echo(f"(dry run \u2014 {len(candidates)} entries would be rejected)")
            return
        if not force:
            if not click.confirm(f"Reject {len(candidates)} entries?", default=False):
                click.echo("Aborted.")
                return
        for entry in candidates:
            delete_pending(kb_root, entry["id"])
            append_log(kb_root, "rejected", entry["id"], reason or "stale")
        click.echo(f"\u2713 Rejected: {len(candidates)} stale entries")
        return

    # Single-entry mode.
    if not pending_id:
        click.echo("Error: provide a pending_id or use --stale-days N for batch reject.", err=True)
        sys.exit(1)
    raw = get_pending(kb_root, pending_id)
    if raw is None:
        click.echo(f"Pending entry not found: {pending_id}", err=True)
        sys.exit(1)

    if dry_run:
        click.echo(pending_id)
        click.echo(f"\u2713 Rejected: {pending_id} (dry run)")
        return

    # Show entry title and confirm.
    _title = ""
    try:
        import yaml as _yaml
        _parts = raw.split("---", 2)
        if len(_parts) >= 3:
            _fm = _yaml.safe_load(_parts[1])
            _title = _fm.get("title", "") if isinstance(_fm, dict) else ""
    except Exception:
        pass
    click.echo(f"Will reject: {pending_id}")
    if _title:
        click.echo(f"  title: {_title}")
    if not force:
        if not click.confirm("Proceed?", default=True):
            click.echo("Aborted.")
            return

    delete_pending(kb_root, pending_id)
    append_log(kb_root, "rejected", pending_id, reason or "no reason given")
    click.echo(f"\u2713 Rejected: {pending_id}")


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

    click.echo(f"\u2713 Resolved: {auto_count} auto, {isolated_count} isolated to contributions/conflicts/")
    if isolated_count > 0:
        click.echo("Run 'holmes resolve <id> --keep [A|B]' to resolve.")


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
        click.echo(f"\u2713 Conflict {conflict_id} resolved manually")
        from holmes.kb.store import rebuild_index_files as _rebuild
        _rebuild(kb_root)
        click.echo("\u2713 Index rebuilt.")
        return

    result = resolve_conflict(kb_root, conflict_id, keep)  # type: ignore[arg-type]
    if result is None:
        click.echo(f"Conflict not found: {conflict_id}", err=True)
        sys.exit(1)
    append_conflict_log(kb_root, conflict_id, keep)  # type: ignore[arg-type]
    from holmes.kb.store import rebuild_index_files as _rebuild
    _rebuild(kb_root)
    click.echo(f"\u2713 Conflict {conflict_id} resolved (kept side {keep})")
    click.echo("\u2713 Index rebuilt.")


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
        click.echo(f"  [{c['id']}] {c['title']} ({c['maturity']}) \u2014 {c['file']}")
