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
    last_referenced: str = ""   # ISO timestamp of last session reference
    reference_count: int = 0    # cumulative session reference count


def read_entry(kb_root: Path, entry_id: str) -> Optional[str]:
    """Return the raw Markdown content for a KB entry by ID.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID to look up.

    Returns:
        Raw Markdown string if found, or None.
    """
    for meta in list_entries(kb_root):
        if meta.id == entry_id:
            p = Path(meta.file_path)
            if p.exists():
                return p.read_text(encoding="utf-8")
    return None


def list_entries(
    kb_root: Path,
    kb_type: Optional[str] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 0,
    offset: int = 0,
) -> list[EntryMeta]:
    """List all knowledge entries with optional filtering and pagination.

    Args:
        kb_root: Root directory of the knowledge base.
        kb_type: Optional type filter (pitfall/model/guideline/process/decision).
        category: Optional category filter (for pitfall entries).
        query: Optional keyword filter — matched against title and tags (case-insensitive).
        limit: Maximum number of entries to return. 0 means no limit.
        offset: Number of entries to skip (for pagination).

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
                        last_referenced=str(meta.get("last_referenced", "")),
                        reference_count=int(meta.get("reference_count", 0)),
                    )
                )
            except Exception:  # noqa: BLE001
                pass

    # Keyword filter across title and tags.
    if query:
        q = query.lower()
        results = [
            e for e in results
            if q in e.title.lower() or any(q in t.lower() for t in e.tags)
        ]

    # Pagination.
    if offset:
        results = results[offset:]
    if limit:
        results = results[:limit]

    return results


MATURITY_UPGRADE_THRESHOLDS = {
    "draft": ("verified", 1),    # reference_count >= 1 → verified
    "verified": ("proven", 3),   # reference_count >= 3 → proven
}


def update_references(kb_root: Path, entry_ids: list[str]) -> list[str]:
    """Record a session reference for each entry ID and promote maturity if thresholds are met.

    Called at /holmes-resolve time (end of session) to batch-update all KB entries
    that were consulted during the troubleshooting session.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_ids: List of entry IDs referenced in the session.

    Returns:
        List of IDs whose maturity was promoted.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    promoted: list[str] = []

    for entry_id in entry_ids:
        entry = None
        for meta in list_entries(kb_root):
            if meta.id == entry_id:
                entry = meta
                break
        if entry is None or not entry.file_path:
            continue

        path = Path(entry.file_path)
        if not path.exists():
            continue

        try:
            post = frontmatter.load(str(path))
            post.metadata["last_referenced"] = now_iso
            new_count = int(post.metadata.get("reference_count", 0)) + 1
            post.metadata["reference_count"] = new_count

            current_maturity = str(post.metadata.get("maturity", "draft"))
            if current_maturity in MATURITY_UPGRADE_THRESHOLDS:
                next_maturity, threshold = MATURITY_UPGRADE_THRESHOLDS[current_maturity]
                if new_count >= threshold:
                    post.metadata["maturity"] = next_maturity
                    promoted.append(entry_id)

            path.write_text(frontmatter.dumps(post), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    return promoted


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
