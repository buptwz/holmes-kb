"""Knowledge base file system operations — entry CRUD and index management.

All entries are stored as Markdown files with YAML frontmatter.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter


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
    # M1 fields (all optional for backwards-compatibility with legacy entries)
    kb_status: str = "active"       # defaults to "active" when field absent
    parent_id: Optional[str] = None  # set for process sub-entries
    # M2 fields (all optional for backwards-compatibility with legacy entries)
    source_hash: str = ""  # SHA-256 first 16 hex chars of source document content
    source_file: str = ""  # path relative to KB root of the source document


def find_entry(kb_root: Path, entry_id: str) -> Optional[Path]:
    """Locate a KB entry file by ID using a filesystem scan.

    Supports both legacy IDs (``PT-DB-001``) and new-style IDs
    (``gpu-init-failure-root-001``) without relying on regex or fixed formats.

    Lookup strategy (in order):
    1. Read each ``.md`` file's frontmatter ``id`` field; compare case-insensitively.
    2. Fall back to file-stem comparison when the frontmatter has no ``id`` field.

    Scan covers all type directories (pitfall/model/guideline/process/decision) and
    ``contributions/pending/``.  Files whose names start with ``_`` are skipped.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID to find (case-insensitive).

    Returns:
        Absolute ``Path`` to the first matching ``.md`` file, or ``None``.
    """
    entry_id_lower = entry_id.lower()
    for md_file in kb_root.rglob("*.md"):
        if md_file.name.startswith("_"):
            continue
        try:
            post = frontmatter.load(str(md_file))
            fm_id = str(post.metadata.get("id", "")).lower()
            if fm_id and fm_id == entry_id_lower:
                return md_file
            # Fall back: compare file stem (covers entries that have no id field)
            if not fm_id and md_file.stem.lower() == entry_id_lower:
                return md_file
        except Exception:  # noqa: BLE001
            pass
    return None


def read_entry(kb_root: Path, entry_id: str) -> Optional[str]:
    """Return the raw Markdown content for a KB entry by ID.

    When the entry's frontmatter contains a non-empty ``child_entry_ids`` list,
    a ``## Children`` navigation table is appended to the returned content.
    This is additive-only — the original frontmatter and body are not modified.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID to look up (case-insensitive; supports old and new formats).

    Returns:
        Raw Markdown string (possibly with appended Children section) if found, or None.
    """
    # M1: use find_entry() for ID-format-agnostic lookup (replaces list_entries iteration).
    entry_path = find_entry(kb_root, entry_id)
    if entry_path is None or not entry_path.exists():
        return None

    content = entry_path.read_text(encoding="utf-8")

    # M1: append ## Children table when child_entry_ids is present and non-empty.
    try:
        post = frontmatter.loads(content)
        child_ids: list = list(post.metadata.get("child_entry_ids") or [])
        if child_ids:
            rows: list[str] = []
            for child_id in child_ids:
                child_path = find_entry(kb_root, str(child_id))
                if child_path is not None and child_path.exists():
                    try:
                        child_post = frontmatter.load(str(child_path))
                        child_title = str(child_post.metadata.get("title", child_id))
                    except Exception:  # noqa: BLE001
                        child_title = str(child_id)
                else:
                    child_title = "(not found)"
                rows.append(f"| {child_id} | {child_title} |")
            children_section = (
                "\n\n## Children\n\n"
                "| ID | Title |\n"
                "|----|-------|\n"
                + "\n".join(rows)
            )
            content = content.rstrip() + children_section
    except Exception:  # noqa: BLE001
        pass

    return content


def list_entries(
    kb_root: Path,
    kb_type: Optional[str] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 0,
    offset: int = 0,
    include_pending: bool = False,
    kb_status: Optional[str] = "active",
    exclude_sub_entries: bool = True,
) -> list[EntryMeta]:
    """List all knowledge entries with optional filtering and pagination.

    Args:
        kb_root: Root directory of the knowledge base.
        kb_type: Optional type filter (pitfall/model/guideline/process/decision).
        category: Optional category filter (for pitfall entries).
        query: Optional keyword filter — matched against title and tags (case-insensitive).
        limit: Maximum number of entries to return. 0 means no limit.
        offset: Number of entries to skip (for pagination).
        include_pending: If True, also scan contributions/pending/ for pending entries.
        kb_status: Filter by kb_status field.  Pass None to skip status filtering.
            Legacy entries without a kb_status field are treated as "active".
            Default "active" hides pending/deprecated entries from normal listings.
        exclude_sub_entries: When True (default), filter out process entries that have
            a parent_id set (i.e. DAG tree sub-entries).  Pass False for admin views.

    Returns:
        Sorted list of EntryMeta objects.
    """
    search_dirs: list[Path]
    if kb_type:
        search_dirs = [kb_root / kb_type]
    else:
        search_dirs = [
            kb_root / t
            for t in ("pitfall", "model", "guideline", "process", "decision")
        ]

    results: list[EntryMeta] = []
    for d in search_dirs:
        if not d.is_dir():
            continue
        for md_file in sorted(d.rglob("*.md")):
            if md_file.name.startswith("_"):
                continue
            try:
                post = frontmatter.load(str(md_file))
                meta = post.metadata
                entry_category = meta.get("category")
                if category and entry_category != category:
                    continue
                # M1: kb_status filter — legacy entries without the field default to "active".
                if kb_status is not None:
                    entry_kb_status = str(meta.get("kb_status", "active"))
                    if entry_kb_status != kb_status:
                        continue
                # M1: exclude process sub-entries (type=process AND parent_id set).
                if exclude_sub_entries:
                    if str(meta.get("type", "")) == "process" and meta.get("parent_id"):
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
                        parent_id=meta.get("parent_id") or None,
                        # M2: populate source tracking fields
                        source_hash=str(meta.get("source_hash", "")),
                        source_file=str(meta.get("source_file", "")),
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
                            # M2: populate source tracking fields
                            source_hash=str(meta.get("source_hash", "")),
                            source_file=str(meta.get("source_file", "")),
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

    for meta in list_entries(kb_root, include_pending=True):
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
        post.metadata["maturity"] = new_maturity
        entry_path.write_text(frontmatter.dumps(post), encoding="utf-8")
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
    confirmed = list_entries(kb_root, kb_status=None, exclude_sub_entries=False)
    pending: list[EntryMeta] = []

    # New-format: _pending/<category>/*.md (M6a)
    new_pending_root = kb_root / "_pending"
    if new_pending_root.is_dir():
        for md_file in sorted(new_pending_root.rglob("*.md")):
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
                    category=meta.get("category") or md_file.parent.name,
                    tags=list(meta.get("tags", [])),
                    created_at=str(meta.get("created_at", "")),
                    updated_at=str(meta.get("updated_at", "")),
                    file_path=str(md_file),
                    pending=True,
                    kb_status="pending",
                    parent_id=meta.get("parent_id") or None,
                    source_hash=str(meta.get("source_hash", "")),
                    source_file=str(meta.get("source_file", "")),
                ))
            except Exception:  # noqa: BLE001
                pass

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
            "Use 'holmes kb pending' to list available pending entries."
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


def collect_tree(kb_root: Path, root_id: str) -> list[str]:
    """From root_id, DFS-traverse child_entry_ids collecting all entry IDs.

    Searches ``_pending/`` first, then confirmed space for each entry.
    Cycle-safe: already-visited IDs (case-insensitive) are skipped.

    Args:
        kb_root: Root directory of the knowledge base.
        root_id: The starting entry ID (pitfall root or process entry).

    Returns:
        Ordered list of entry IDs with root_id first (DFS pre-order).
    """
    visited: set[str] = set()
    result: list[str] = []

    def _visit(entry_id: str) -> None:
        key = entry_id.lower()
        if key in visited:
            return
        visited.add(key)
        result.append(entry_id)

        entry_path = _find_pending_entry(kb_root, entry_id)
        if entry_path is None:
            entry_path = find_entry(kb_root, entry_id)
        if entry_path is None:
            return
        try:
            post = frontmatter.load(str(entry_path))
            for child_id in list(post.metadata.get("child_entry_ids") or []):
                _visit(str(child_id))
        except Exception:  # noqa: BLE001
            pass

    _visit(root_id)
    return result


def approve_tree(kb_root: Path, root_id: str) -> list[str]:
    """Atomically approve all entries in a pending tree starting from root_id.

    Approves in topological order (leaves first, root last).
    Rolls back all approved entries on any failure.

    Args:
        kb_root: Root directory of the knowledge base.
        root_id: The pitfall root entry ID.

    Returns:
        List of confirmed file paths (str) for all approved entries.

    Raises:
        FileNotFoundError: If any tree entry is not found in ``_pending/``.
        RuntimeError: If any approve step fails (includes rollback attempt).
    """
    import os

    from holmes.kb.atomic import atomic_write as _aw

    tree_ids = collect_tree(kb_root, root_id)

    # Pre-validate: all entries must be in _pending/ before any approve
    for entry_id in tree_ids:
        if _find_pending_entry(kb_root, entry_id) is None:
            raise FileNotFoundError(
                f"approve_tree: '{entry_id}' not found in _pending/. "
                "All tree entries must be pending before approve."
            )

    # Approve leaves-first (reversed BFS/DFS order)
    approved: list[tuple[str, Path]] = []

    for entry_id in reversed(tree_ids):
        try:
            confirmed_path = approve_entry(kb_root, entry_id)
            approved.append((entry_id, confirmed_path))
        except Exception as exc:
            # Rollback: move already-approved entries back to _pending/
            for rollback_id, rollback_path in approved:
                try:
                    if rollback_path.exists():
                        rb_post = frontmatter.load(str(rollback_path))
                        rb_type = str(rb_post.metadata.get("type", "")).strip()
                        rb_cat = (
                            str(rb_post.metadata.get("category", "")).strip()
                            or rollback_path.parent.name
                        )
                        rb_post.metadata["kb_status"] = "pending"
                        rb_pending_dir = kb_root / "_pending" / rb_type / rb_cat
                        rb_pending_dir.mkdir(parents=True, exist_ok=True)
                        rb_pending_path = rb_pending_dir / f"{rollback_id}.md"
                        _aw(rb_pending_path, frontmatter.dumps(rb_post))
                        os.unlink(rollback_path)
                except Exception:  # noqa: BLE001
                    pass
            raise RuntimeError(
                f"approve_tree: failed on '{entry_id}': {exc}. "
                f"Rolled back {len(approved)} entries."
            ) from exc

    return [str(p) for _, p in approved]


def deprecate_tree(kb_root: Path, root_id: str) -> list[str]:
    """Deprecate all entries in a confirmed tree starting from root_id.

    Args:
        kb_root: Root directory of the knowledge base.
        root_id: The pitfall root entry ID (must be in confirmed space).

    Returns:
        List of entry IDs that were successfully deprecated.
    """
    tree_ids = collect_tree(kb_root, root_id)
    deprecated: list[str] = []
    for entry_id in tree_ids:
        if deprecate_entry(kb_root, entry_id):
            deprecated.append(entry_id)
    return deprecated


def cancel_pending_tree(kb_root: Path, root_id: str) -> list[str]:
    """Delete all pending entries in a tree rooted at root_id.

    Removes files directly from ``_pending/`` without using ``_trash/``.

    Args:
        kb_root: Root directory of the knowledge base.
        root_id: The pitfall root entry ID (must be in ``_pending/``).

    Returns:
        List of cancelled file paths (str).
    """
    import os

    tree_ids = collect_tree(kb_root, root_id)
    cancelled: list[str] = []
    for entry_id in tree_ids:
        pending_path = _find_pending_entry(kb_root, entry_id)
        if pending_path is not None:
            try:
                os.unlink(pending_path)
                cancelled.append(str(pending_path))
            except OSError:
                pass
    return cancelled


def move_to_trash(
    kb_root: Path,
    entry_id: str,
    cascade: bool = True,
) -> list[str]:
    """Soft-delete a KB entry by moving it to ``_trash/<type>/<category>/``.

    The file is moved (not deleted) so it remains git-tracked and can be
    restored at any time via ``git checkout``.

    Cascade behaviour (only when ``cascade=True`` AND the entry is a pitfall
    root with ``pitfall_structure: tree`` and non-empty ``child_entry_ids``):
    all descendant entries collected by ``collect_tree()`` are moved as well.

    For legacy pitfall entries (``pitfall_structure: flat`` or the field is
    absent, or ``child_entry_ids`` is empty) only the single root file is moved
    even when ``cascade=True``.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID to delete (case-insensitive lookup).
        cascade: When True, cascade-delete the whole tree for pitfall roots
                 that use the new tree format. Default True.

    Returns:
        List of absolute destination paths (strings) for every file moved.

    Raises:
        FileNotFoundError: If *entry_id* cannot be found in confirmed or
                           pending space.
    """
    src_path = _find_pending_entry(kb_root, entry_id) or find_entry(kb_root, entry_id)
    if src_path is None:
        raise FileNotFoundError(f"Entry '{entry_id}' not found in KB.")

    try:
        root_post = frontmatter.load(str(src_path))
    except Exception as exc:
        raise ValueError(f"Cannot parse entry '{entry_id}': {exc}") from exc

    root_meta = root_post.metadata
    root_type = str(root_meta.get("type", "")).strip()
    root_parent_id = root_meta.get("parent_id")
    root_pitfall_structure = str(root_meta.get("pitfall_structure", "")).strip()
    root_child_ids: list = list(root_meta.get("child_entry_ids") or [])

    # Determine cascade: only for new-format pitfall root nodes.
    is_cascade_root = (
        cascade
        and root_type == "pitfall"
        and not root_parent_id
        and root_pitfall_structure == "tree"
        and bool(root_child_ids)
    )

    ids_to_move: list[str] = (
        collect_tree(kb_root, entry_id) if is_cascade_root else [entry_id]
    )

    moved: list[str] = []
    for eid in ids_to_move:
        file_path = _find_pending_entry(kb_root, eid) or find_entry(kb_root, eid)
        if file_path is None:
            logging.warning("move_to_trash: '%s' not found on disk, skipping.", eid)
            continue

        try:
            post = frontmatter.load(str(file_path))
            meta = post.metadata
            entry_type = str(meta.get("type", "")).strip() or "unknown"
            entry_category = str(meta.get("category", "")).strip() or file_path.parent.name
        except Exception:  # noqa: BLE001
            entry_type = file_path.parent.parent.name
            entry_category = file_path.parent.name

        dst_dir = kb_root / "_trash" / entry_type / entry_category
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / file_path.name

        # Avoid overwriting an existing trashed file by appending a timestamp.
        if dst.exists():
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            dst = dst_dir / f"{file_path.stem}-{timestamp}{file_path.suffix}"

        shutil.move(str(file_path), str(dst))
        moved.append(str(dst))

    return moved


def write_entry(path: Path, content: str) -> None:
    """Write raw Markdown content to a file, creating parent directories.

    Args:
        path: Destination file path.
        content: Markdown string with YAML frontmatter.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
