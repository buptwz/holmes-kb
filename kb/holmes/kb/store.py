"""Knowledge base file system operations — entry CRUD and index management.

All entries are stored as Markdown files with YAML frontmatter.
"""

from __future__ import annotations

import json
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
