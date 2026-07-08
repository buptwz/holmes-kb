"""Knowledge base file system operations — entry CRUD and index management.

All entries are stored as Markdown files with YAML frontmatter.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter


# ---------------------------------------------------------------------------
# Directory exclusion helpers
# ---------------------------------------------------------------------------

_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {".history", "_trash", "_drafts", "kb-template", ".git", ".claude"}
)


def _should_skip(path: Path, kb_root: Path) -> bool:
    """Return True if *path* is inside an excluded directory relative to *kb_root*."""
    try:
        rel = path.relative_to(kb_root)
        return any(part in _EXCLUDED_DIRS for part in rel.parts)
    except ValueError:
        return False


@dataclass
class EntryMeta:
    """Lightweight metadata for a KB entry (for index / listing)."""

    id: str
    type: str
    title: str
    maturity: str
    category: Optional[str]
    tags: list[str]
    created_at: str
    updated_at: str
    file_path: str
    pending: bool = False
    kb_status: str = "active"       # defaults to "active" when field absent
    source_hash: str = ""  # SHA-256 first 16 hex chars of source document content
    source_file: str = ""  # basename of the source document
    brief: str = ""  # one-sentence summary for kb_browse preview


def find_entry(kb_root: Path, entry_id: str) -> Optional[Path]:
    """Locate a KB entry file by ID.

    Lookup strategy (in order):
    1. Read ``index.json`` at *kb_root* and look up the ID → file_path mapping.
    2. Scan ``_pending/`` directories (not covered by index.json).
    3. Fall back to full ``rglob`` filesystem scan when index is missing/stale.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID to find (case-insensitive).

    Returns:
        Absolute ``Path`` to the first matching ``.md`` file, or ``None``.
    """
    entry_id_lower = entry_id.lower()

    # --- Fast path: index.json lookup ---
    index_file = kb_root / "index.json"
    if index_file.is_file():
        try:
            index_data = json.loads(index_file.read_text(encoding="utf-8"))
            for rec in index_data.get("entries", []):
                if str(rec.get("id", "")).lower() == entry_id_lower:
                    p = Path(rec["file_path"])
                    if not p.is_absolute():
                        p = kb_root / p
                    if p.is_file():
                        return p
                    break  # index stale — fall through to scan
        except Exception:  # noqa: BLE001
            pass

    # --- Scan _pending/ directories (not in index.json) ---
    for pending_root in (kb_root / "_pending", kb_root / "contributions" / "pending"):
        if not pending_root.is_dir():
            continue
        for md_file in pending_root.rglob("*.md"):
            if md_file.name.startswith("_"):
                continue
            try:
                post = frontmatter.load(str(md_file))
                fm_id = str(post.metadata.get("id", "")).lower()
                if fm_id and fm_id == entry_id_lower:
                    return md_file
            except Exception:  # noqa: BLE001
                pass

    # --- Slow fallback: full filesystem scan ---
    for md_file in kb_root.rglob("*.md"):
        if md_file.name.startswith("_"):
            continue
        if _should_skip(md_file, kb_root):
            continue
        try:
            post = frontmatter.load(str(md_file))
            fm_id = str(post.metadata.get("id", "")).lower()
            if fm_id and fm_id == entry_id_lower:
                return md_file
            if not fm_id and md_file.stem.lower() == entry_id_lower:
                return md_file
        except Exception:  # noqa: BLE001
            pass
    return None


def read_entry(kb_root: Path, entry_id: str) -> Optional[str]:
    """Return the raw Markdown content for a KB entry by ID.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID to look up (case-insensitive).

    Returns:
        Raw Markdown string if found, or None.
    """
    entry_path = find_entry(kb_root, entry_id)
    if entry_path is None or not entry_path.exists():
        return None

    return entry_path.read_text(encoding="utf-8")


def list_entries(
    kb_root: Path,
    kb_type: Optional[str] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 0,
    offset: int = 0,
    include_pending: bool = False,
    kb_status: Optional[str] = "active",
    exclude_sub_entries: bool = False,
) -> list[EntryMeta]:
    """List all knowledge entries with optional filtering and pagination.

    Args:
        kb_root: Root directory of the knowledge base.
        kb_type: Optional type filter (pitfall/model/guideline/process/decision).
        category: Optional category filter.
        query: Optional keyword filter — matched against title and tags (case-insensitive).
        limit: Maximum number of entries to return. 0 means no limit.
        offset: Number of entries to skip (for pagination).
        include_pending: If True, also scan contributions/pending/ for pending entries.
        kb_status: Filter by kb_status field.  Pass None to skip status filtering.
            Legacy entries without a kb_status field are treated as "active".
            Default "active" hides pending/deprecated entries from normal listings.

    Returns:
        Sorted list of EntryMeta objects.
    """
    search_dirs: list[Path]
    type_names = (kb_type,) if kb_type else ("pitfall", "model", "guideline", "process", "decision")
    search_dirs = [kb_root / t for t in type_names]
    # Also scan _pending/<type>/ so imported entries are visible.
    for t in type_names:
        pending_type = kb_root / "_pending" / t
        if pending_type.is_dir():
            search_dirs.append(pending_type)

    results: list[EntryMeta] = []
    for d in search_dirs:
        if not d.is_dir():
            continue
        for md_file in sorted(d.rglob("*.md")):
            if md_file.name.startswith("_"):
                continue
            if _should_skip(md_file, kb_root):
                continue
            try:
                post = frontmatter.load(str(md_file))
                meta = post.metadata
                entry_category = meta.get("category")
                if category and entry_category != category:
                    continue
                if kb_status is not None:
                    entry_kb_status = str(meta.get("kb_status", "active"))
                    if entry_kb_status != kb_status:
                        continue
                results.append(
                    EntryMeta(
                        id=str(meta.get("id", md_file.stem)),
                        type=str(meta.get("type", "")),
                        title=str(meta.get("title", "")),
                        maturity=str(meta.get("maturity", "draft")),
                        category=entry_category,
                        tags=list(meta.get("tags", [])),
                        created_at=str(meta.get("created_at", "")),
                        updated_at=str(meta.get("updated_at", "")),
                        file_path=str(md_file),
                        kb_status=str(meta.get("kb_status", "active")),
                        source_hash=str(meta.get("source_hash", "")),
                        source_file=str(meta.get("source_file", "")),
                        brief=str(meta.get("brief", "")),
                    )
                )
            except Exception:  # noqa: BLE001
                pass

    if include_pending:
        pending_dir = kb_root / "contributions" / "pending"
        if pending_dir.is_dir():
            for md_file in sorted(pending_dir.glob("*.md")):
                if md_file.name.startswith("_"):
                    continue
                try:
                    post = frontmatter.load(str(md_file))
                    meta = post.metadata
                    results.append(
                        EntryMeta(
                            id=str(meta.get("id", md_file.stem)),
                            type=str(meta.get("type", "")),
                            title=str(meta.get("title", "")),
                            maturity=str(meta.get("maturity", "pending")),
                            category=meta.get("category"),
                            tags=list(meta.get("tags", [])),
                            created_at=str(meta.get("created_at", "")),
                            updated_at=str(meta.get("updated_at", "")),
                            file_path=str(md_file),
                            pending=True,
                            source_hash=str(meta.get("source_hash", "")),
                            source_file=str(meta.get("source_file", "")),
                            brief=str(meta.get("brief", "")),
                        )
                    )
                except Exception:  # noqa: BLE001
                    pass

    # Keyword filter across title and tags.
    if query:
        q = query.lower()
        results = [
            e for e in results
            if q in e.title.lower() or any(q in str(t).lower() for t in e.tags)
        ]

    # Pagination.
    if offset:
        results = results[offset:]
    if limit:
        results = results[:limit]

    return results


# Maturity order for conflict resolution (lower index = less mature).
MATURITY_ORDER: dict[str, int] = {"draft": 0, "verified": 1, "proven": 2}

# Sidecar directory for per-session evidence files (git-merge-friendly).
EVIDENCE_SIDECAR_DIR = "contributions/evidence"


def load_evidence(
    kb_root: Path,
    entry_id: str,
    frontmatter_evidence: Optional[list] = None,
) -> list[dict]:
    """Load all evidence records for an entry from sidecar files and frontmatter.

    Combines records from:
    1. The entry's frontmatter ``evidence`` field (passed in as ``frontmatter_evidence``).
    2. Per-session JSON sidecar files in ``contributions/evidence/<entry_id>/``.

    Deduplicates by session_id so that records present in both sources are
    counted only once.  Sidecar files take precedence on collision.

    Storing evidence in separate per-session files rather than as a YAML list
    ensures that concurrent ``update-refs`` calls in different git branches
    each produce a *new file addition*, which git can merge without conflict.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: Target entry ID.
        frontmatter_evidence: Existing evidence from the entry frontmatter (optional).

    Returns:
        Combined, deduplicated list of evidence record dicts.
    """
    # Start with frontmatter evidence (keyed by session_id for dedup).
    combined: dict[str, dict] = {}
    for record in (frontmatter_evidence or []):
        if isinstance(record, dict):
            sid = str(record.get("session_id", ""))
            combined[sid] = record

    # Overlay sidecar files (newer/explicit records win).
    sidecar_dir = kb_root / EVIDENCE_SIDECAR_DIR / entry_id
    if sidecar_dir.is_dir():
        for json_file in sorted(sidecar_dir.glob("*.json")):
            try:
                record = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(record, dict):
                    sid = str(record.get("session_id", ""))
                    combined[sid] = record
            except Exception:  # noqa: BLE001
                pass

    return list(combined.values())


def derive_maturity(evidence: list[dict]) -> str:
    """Compute maturity from the evidence array.

    Rules:
    - 0 records → 'draft'
    - ≥1 record → 'verified'
    - ≥2 distinct session_ids AND ≥2 distinct contributors → 'proven'

    Args:
        evidence: List of EvidenceRecord dicts.

    Returns:
        Derived maturity string.
    """
    if not evidence:
        return "draft"
    sessions = {str(e.get("session_id", "")) for e in evidence if e.get("session_id")}
    contributors = {str(e.get("contributor", "")) for e in evidence if e.get("contributor")}
    if len(sessions) >= 2 and len(contributors) >= 2:
        return "proven"
    return "verified"


def get_last_evidence_date(evidence: list[dict]) -> Optional[str]:
    """Return the most recent date string from an evidence array, or None.

    Args:
        evidence: List of EvidenceRecord dicts.

    Returns:
        ISO8601 date string of the most recent record, or None if array is empty.
    """
    dates = [str(e["date"]) for e in evidence if e.get("date")]
    if not dates:
        return None
    return max(dates)


def append_evidence(kb_root: Path, entry_id: str, evidence_record: dict) -> bool:
    """Append one EvidenceRecord to an entry's evidence store.

    Writes the record as a per-session JSON sidecar file at
    ``contributions/evidence/<entry_id>/<session_id>.json``.  Each record is a
    separate file addition, so concurrent ``update-refs`` calls in different
    git branches never produce merge conflicts (SC-006).

    Deduplicates by session_id — if a record with the same session_id already
    exists in either the sidecar directory or the entry frontmatter, this is a
    no-op and returns False.

    After appending, automatically recomputes maturity via derive_maturity() and
    updates the frontmatter maturity field if the entry should be promoted.
    Contributors and updated_at are intentionally NOT modified here — both
    branches of a git merge would write different values for those fields,
    causing conflicts.  The ``contributor`` field is already captured in the
    sidecar record; use ``add_contributor()`` explicitly when updating the
    contributors list is needed (e.g., during ``confirm``).

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: Target entry ID.
        evidence_record: Dict with at least session_id, contributor, date.

    Returns:
        True if the record was appended, False if it was a duplicate.
    """
    entry_path: Optional[Path] = None

    for meta in list_entries(kb_root, include_pending=True, kb_status=None):
        if meta.id == entry_id:
            entry_path = Path(meta.file_path)
            break

    if entry_path is None or not entry_path.exists():
        return False

    try:
        post = frontmatter.load(str(entry_path))
    except Exception:  # noqa: BLE001
        return False

    session_id = str(evidence_record.get("session_id", ""))

    # Load all existing evidence (frontmatter + sidecar) for dedup check.
    all_existing = load_evidence(kb_root, entry_id, post.metadata.get("evidence"))

    # Dedup by session_id.
    if session_id and any(str(e.get("session_id", "")) == session_id for e in all_existing):
        return False

    # Write new record to sidecar file (git-merge-friendly: file addition, not edit).
    sidecar_dir = kb_root / EVIDENCE_SIDECAR_DIR / entry_id
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    safe_sid = session_id.replace("/", "-").replace("\\", "-") if session_id else "unknown"
    sidecar_file = sidecar_dir / f"{safe_sid}.json"
    sidecar_file.write_text(json.dumps(evidence_record, ensure_ascii=False), encoding="utf-8")

    # P0-2: maturity auto-update is handled here.
    # Recompute maturity from all evidence (never downgrade via evidence alone).
    # Only update if the rank increases — same-value writes auto-merge in git.
    new_all_evidence = all_existing + [evidence_record]
    current_maturity = str(post.metadata.get("maturity", "draft"))
    new_maturity = derive_maturity(new_all_evidence)
    current_rank = MATURITY_ORDER.get(current_maturity, 0)
    new_rank = MATURITY_ORDER.get(new_maturity, 0)
    if new_rank > current_rank:
        from holmes.kb.atomic import atomic_write
        post.metadata["maturity"] = new_maturity
        atomic_write(entry_path, frontmatter.dumps(post))
    return True


def add_contributor(kb_root: Path, entry_id: str, contributor: str) -> None:
    """Append a contributor to an entry's contributors list (dedup, in-place update).

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: Target entry ID.
        contributor: Contributor identifier to add.
    """
    for meta in list_entries(kb_root):
        if meta.id == entry_id:
            entry_path = Path(meta.file_path)
            if not entry_path.exists():
                return
            try:
                post = frontmatter.load(str(entry_path))
                contribs = list(post.metadata.get("contributors") or [])
                if contributor not in contribs:
                    contribs.append(contributor)
                    post.metadata["contributors"] = contribs
                    entry_path.write_text(frontmatter.dumps(post), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            return


def resolve_maturity_conflict(local: str, incoming: str) -> tuple[str, bool]:
    """Resolve a concurrent maturity conflict by keeping the lower (safer) value.

    When a git merge results in conflicting maturity values (one branch upgraded,
    another downgraded), we prefer the more conservative value and flag the
    contradiction for maintainer review.

    Args:
        local: Maturity string from the local branch.
        incoming: Maturity string from the incoming branch.

    Returns:
        Tuple of (lower_maturity: str, contradiction: bool).
        contradiction is always True when this function is called.
    """
    local_rank = MATURITY_ORDER.get(local, 0)
    incoming_rank = MATURITY_ORDER.get(incoming, 0)
    lower = local if local_rank <= incoming_rank else incoming
    return lower, True


def _scan_all_entries(kb_root: Path) -> list[EntryMeta]:
    """Return EntryMeta for ALL entries: confirmed (any kb_status) + pending.

    Scans both the new-format ``_pending/<type>/<category>/`` directories introduced
    in M6a and the legacy ``contributions/pending/`` flat directory.

    Used by M2 dedup functions and M6a approve conflict detection.
    """
    # list_entries with kb_status=None already scans _pending/<type>/ dirs.
    confirmed = list_entries(kb_root, kb_status=None)
    pending: list[EntryMeta] = []

    # Legacy-format: contributions/pending/*.md
    legacy_pending_dir = kb_root / "contributions" / "pending"
    if legacy_pending_dir.is_dir():
        for md_file in sorted(legacy_pending_dir.glob("*.md")):
            if md_file.name.startswith("_"):
                continue
            try:
                post = frontmatter.load(str(md_file))
                meta = post.metadata
                pending.append(EntryMeta(
                    id=str(meta.get("id", md_file.stem)),
                    type=str(meta.get("type", "")),
                    title=str(meta.get("title", "")),
                    maturity=str(meta.get("maturity", "pending")),
                    category=meta.get("category"),
                    tags=list(meta.get("tags", [])),
                    created_at=str(meta.get("created_at", "")),
                    updated_at=str(meta.get("updated_at", "")),
                    file_path=str(md_file),
                    pending=True,
                    source_hash=str(meta.get("source_hash", "")),
                    source_file=str(meta.get("source_file", "")),
                ))
            except Exception:  # noqa: BLE001
                pass

    return confirmed + pending


def find_entries_by_source_hash(kb_root: Path, source_hash: str) -> list[EntryMeta]:
    """Return all entries (confirmed + pending) whose source_hash matches.

    Used by Step 0 dedup check to detect exact duplicate imports.
    An empty source_hash never matches anything (guards against legacy entries).

    Args:
        kb_root: Root directory of the knowledge base.
        source_hash: SHA-256 first 16 hex chars of the source document content.

    Returns:
        List of EntryMeta with matching source_hash (may be empty).
    """
    if not source_hash:
        return []
    return [e for e in _scan_all_entries(kb_root) if e.source_hash == source_hash]


def find_entries_by_source_file(kb_root: Path, source_file: str) -> list[EntryMeta]:
    """Return all entries (confirmed + pending) whose source_file path matches.

    Used by Step 0 update detection to find prior imports of the same document.
    An empty source_file never matches anything.
    Path comparison is normalised to POSIX forward-slash format.

    Args:
        kb_root: Root directory of the knowledge base.
        source_file: Relative path from kb_root to the source document
                     (e.g. ``docs/hardware/gpu.md``).

    Returns:
        List of EntryMeta with matching source_file (may be empty).
    """
    if not source_file:
        return []
    canonical = Path(source_file).as_posix()
    return [
        e for e in _scan_all_entries(kb_root)
        if e.source_file and Path(e.source_file).as_posix() == canonical
    ]


def write_pending(kb_root: Path, entry_id: str, content: str, entry_type: str, category: str) -> Path:
    """Atomically write an entry to ``_pending/<entry_type>/<category>/<entry_id>.md``.

    Creates the directory hierarchy if it does not yet exist.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID; used as the filename stem.
        content: Full Markdown content including YAML frontmatter.
        entry_type: Knowledge type (pitfall/model/guideline/process/decision).
        category: Category name (e.g. ``"hardware"``); determines the leaf subdirectory.

    Returns:
        Absolute ``Path`` to the written file.
    """
    from holmes.kb.atomic import atomic_write  # local import to avoid circular

    pending_dir = kb_root / "_pending" / entry_type / category
    pending_dir.mkdir(parents=True, exist_ok=True)
    path = pending_dir / f"{entry_id}.md"
    atomic_write(path, content)
    return path


def _find_pending_entry(kb_root: Path, entry_id: str) -> Optional[Path]:
    """Locate a file in ``_pending/<category>/`` by entry ID.

    Reads each ``*.md`` file's frontmatter ``id`` field and compares
    case-insensitively.  Falls back to stem comparison when the field is absent.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID to find.

    Returns:
        Absolute ``Path`` if found, ``None`` otherwise.
    """
    new_pending_root = kb_root / "_pending"
    if not new_pending_root.is_dir():
        return None
    entry_id_lower = entry_id.lower()
    for md_file in sorted(new_pending_root.rglob("*.md")):
        if md_file.name.startswith("_"):
            continue
        try:
            post = frontmatter.load(str(md_file))
            fm_id = str(post.metadata.get("id", "")).lower()
            if fm_id and fm_id == entry_id_lower:
                return md_file
            if not fm_id and md_file.stem.lower() == entry_id_lower:
                return md_file
        except Exception:  # noqa: BLE001
            pass
    return None


def approve_entry(kb_root: Path, entry_id: str) -> Path:
    """Move a pending entry from ``_pending/<category>/`` into ``<category>/``.

    Reads the pending file, updates ``kb_status`` to ``"active"``, writes it
    atomically to the confirmed directory, then removes the pending source file.

    Atomicity strategy: write the new file first; only delete the pending file
    once the write succeeds.  If the delete fails the pending file becomes an
    orphan (safe to clean up manually) but the approved file is intact.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID to approve (must exist in ``_pending/``).

    Returns:
        Absolute ``Path`` to the newly created confirmed entry.

    Raises:
        FileNotFoundError: If the entry is not found in ``_pending/``.
        ValueError: If the entry has no ``category`` and no parent directory
                    name can be inferred.
    """
    import logging
    import os
    from holmes.kb.atomic import atomic_write  # local import to avoid circular

    pending_path = _find_pending_entry(kb_root, entry_id)
    if pending_path is None:
        raise FileNotFoundError(
            f"Entry '{entry_id}' not found in _pending/. "
            "Use 'holmes pending' to list available pending entries."
        )

    try:
        post = frontmatter.load(str(pending_path))
    except Exception as exc:
        raise ValueError(f"Cannot parse pending entry '{entry_id}': {exc}") from exc

    # Determine target directory: <type>/<category>/ mirrors the _pending/<type>/<category>/ layout.
    # Read type from frontmatter; fall back to grandparent dir name (_pending/<type>/<cat>/<id>.md).
    kb_type = str(post.metadata.get("type", "")).strip()
    _KNOWN_TYPES = {"pitfall", "model", "guideline", "process", "decision"}
    if kb_type not in _KNOWN_TYPES:
        kb_type = pending_path.parent.parent.name
    if not kb_type:
        raise ValueError(
            f"Cannot determine target directory for entry '{entry_id}'. "
            "Set the 'type' frontmatter field to one of: pitfall, model, guideline, process, decision."
        )

    # Category: from frontmatter, or parent dir name (_pending/<type>/<category>/<id>.md).
    category = str(post.metadata.get("category", "")).strip() or pending_path.parent.name

    post.metadata["kb_status"] = "active"
    post.metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
    approved_content = frontmatter.dumps(post)

    target_dir = kb_root / kb_type / category
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{entry_id}.md"

    atomic_write(target_path, approved_content)

    # Remove pending file only after successful write.
    try:
        os.unlink(pending_path)
    except OSError as exc:
        logging.warning(
            "approve_entry: approved '%s' but failed to remove pending file %s: %s",
            entry_id,
            pending_path,
            exc,
        )

    return target_path


def deprecate_entry(kb_root: Path, entry_id: str) -> bool:
    """Mark a confirmed entry as deprecated by updating its ``kb_status`` in-place.

    Searches all confirmed type directories (pitfall / model / guideline /
    process / decision) for the entry.  When found, rewrites the file
    atomically with ``kb_status: deprecated``.  The file is **not** moved.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID to deprecate.

    Returns:
        ``True`` if the entry was found and updated, ``False`` otherwise.
    """
    import logging
    from holmes.kb.atomic import atomic_write  # local import to avoid circular

    entry_path = find_entry(kb_root, entry_id)
    if entry_path is None:
        logging.warning("deprecate_entry: entry '%s' not found", entry_id)
        return False

    # Only modify entries in confirmed space (not _pending/).
    try:
        rel = entry_path.relative_to(kb_root)
    except ValueError:
        logging.warning("deprecate_entry: '%s' is outside kb_root", entry_id)
        return False

    if rel.parts and rel.parts[0] == "_pending":
        logging.warning(
            "deprecate_entry: '%s' is in _pending/, use cancel instead", entry_id
        )
        return False

    try:
        post = frontmatter.load(str(entry_path))
    except Exception as exc:
        logging.warning("deprecate_entry: cannot parse '%s': %s", entry_id, exc)
        return False

    post.metadata["kb_status"] = "deprecated"
    atomic_write(entry_path, frontmatter.dumps(post))
    return True


def move_to_trash(
    kb_root: Path,
    entry_id: str,
) -> list[tuple[str, str]]:
    """Soft-delete a KB entry by moving it to ``_trash/<type>/<category>/``.

    The file is moved (not deleted) so it remains git-tracked and can be
    restored at any time via ``git checkout HEAD -- <original_path>``.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID to delete (case-insensitive lookup).

    Returns:
        List of ``(original_path, trash_path)`` tuples for every file moved.

    Raises:
        FileNotFoundError: If *entry_id* cannot be found in confirmed or
                           pending space.
    """
    src_path = _find_pending_entry(kb_root, entry_id) or find_entry(kb_root, entry_id)
    if src_path is None:
        raise FileNotFoundError(f"Entry '{entry_id}' not found in KB.")

    try:
        post = frontmatter.load(str(src_path))
        meta = post.metadata
        entry_type = str(meta.get("type", "")).strip() or "unknown"
        entry_category = str(meta.get("category", "")).strip() or src_path.parent.name
    except Exception as exc:
        raise ValueError(f"Cannot parse entry '{entry_id}': {exc}") from exc

    dst_dir = kb_root / "_trash" / entry_type / entry_category
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src_path.name

    # Avoid overwriting an existing trashed file by appending a timestamp.
    if dst.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        dst = dst_dir / f"{src_path.stem}-{timestamp}{src_path.suffix}"

    original = str(src_path)
    shutil.move(str(src_path), str(dst))
    return [(original, str(dst))]


def update_entry_content(kb_root: Path, entry_id: str, new_content: str) -> Path:
    """Update an existing entry's content in-place, preserving its location.

    Backs up the old version to ``.history/<id>-<timestamp>.md`` before overwriting.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID to update.
        new_content: Full Markdown content including YAML frontmatter.

    Returns:
        Path to the updated entry file.

    Raises:
        FileNotFoundError: If entry_id is not found.
    """
    from holmes.kb.atomic import atomic_write

    entry_path = find_entry(kb_root, entry_id)
    if entry_path is None:
        entry_path = _find_pending_entry(kb_root, entry_id)
    if entry_path is None:
        raise FileNotFoundError(f"Entry '{entry_id}' not found in KB.")

    # Backup old version
    history_dir = kb_root / ".history"
    history_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_path = history_dir / f"{entry_id}-{timestamp}.md"
    backup_path.write_text(entry_path.read_text(encoding="utf-8"), encoding="utf-8")

    atomic_write(entry_path, new_content)
    return entry_path


def write_entry(path: Path, content: str) -> None:
    """Write raw Markdown content to a file, creating parent directories.

    Args:
        path: Destination file path.
        content: Markdown string with YAML frontmatter.
    """
    from holmes.kb.atomic import atomic_write

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, content)


def rebuild_index_files(kb_root: Path) -> None:
    """Rebuild _index.md table files and index.json for all entry types.

    Each type directory gets an _index.md with a Markdown table of entries.
    A root-level index.json is also written with a machine-readable summary.

    Args:
        kb_root: Root directory of the knowledge base.
    """
    all_entries: list[EntryMeta] = []
    header = "| ID | Title | Category | Maturity | Updated |\n|----|-------|----------|----------|---------|\n"

    for kb_type in ("pitfall", "model", "guideline", "process", "decision"):
        type_dir = kb_root / kb_type
        if not type_dir.is_dir():
            continue

        entries = list_entries(kb_root, kb_type=kb_type)
        all_entries.extend(entries)

        rows = "\n".join(
            f"| {e.id} | {e.title} | {e.category or ''} | {e.maturity} | {e.updated_at[:10]} |"
            for e in entries
        )
        index_content = f"# {kb_type.capitalize()} Index\n\n{header}{rows}\n"
        index_path = type_dir / "_index.md"
        index_path.write_text(index_content, encoding="utf-8")

    # Write root index.json.
    index_json = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_entries": len(all_entries),
        "entries": [
            {
                "id": e.id,
                "type": e.type,
                "title": e.title,
                "maturity": e.maturity,
                "category": e.category,
                "tags": e.tags,
                "updated_at": e.updated_at,
                "file_path": e.file_path,
                "pending": e.pending,
            }
            for e in all_entries
        ],
    }
    (kb_root / "index.json").write_text(
        json.dumps(index_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Invalidate BM25 search cache so next search picks up changes.
    try:
        from holmes.kb.search import get_bm25_backend
        get_bm25_backend(kb_root).invalidate()
    except Exception:  # noqa: BLE001
        pass
