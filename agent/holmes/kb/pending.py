"""Pending entry management for Holmes KB.

All new entries (from agent writes or CLI imports) are placed in
contributions/pending/ with temporary IDs.

Temporary ID format: pending-{YYYYMMDD}-{HHMMSS}-{random4}
Permanent ID format: {TYPE_PREFIX}-{CAT_PREFIX}-{NNN}
  e.g. PT-DB-001, MD-SVC-003
"""

from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter

from holmes.logging_config import get_logger


logger = get_logger("kb.pending")

PENDING_DIR = "contributions/pending"
LOG_PATH = "contributions/log.md"

TYPE_PREFIXES = {
    "pitfall": "PT",
    "model": "MD",
    "guideline": "GL",
    "process": "PR",
    "decision": "DC",
}


def _make_pending_id() -> str:
    """Generate a temporary pending entry ID.

    Format: pending-{YYYYMMDD}-{HHMMSS}-{random4}
    """
    now = datetime.now(timezone.utc)
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"pending-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{rand}"


def write_pending(kb_root: Path, content: str) -> str:
    """Write a new pending entry to contributions/pending/.

    Assigns a temporary ID and patches the frontmatter.

    Args:
        kb_root: Root directory of the knowledge base.
        content: Markdown content with YAML frontmatter.

    Returns:
        The assigned temporary pending ID.
    """
    pending_dir = kb_root / PENDING_DIR
    pending_dir.mkdir(parents=True, exist_ok=True)

    pending_id = _make_pending_id()
    post = frontmatter.loads(content)
    post.metadata["id"] = pending_id
    if "created_at" not in post.metadata:
        post.metadata["created_at"] = datetime.now(timezone.utc).isoformat()
    post.metadata["updated_at"] = datetime.now(timezone.utc).isoformat()

    path = pending_dir / f"{pending_id}.md"
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    logger.info("Created pending entry %s at %s", pending_id, path)

    _append_log(
        kb_root,
        action="pending",
        entry_id=pending_id,
        summary=str(post.metadata.get("title", "Untitled")),
    )
    return pending_id


def list_pending(kb_root: Path) -> list[dict]:
    """List all pending entries.

    Args:
        kb_root: Root directory of the knowledge base.

    Returns:
        List of dicts with id, type, title, created_at.
    """
    pending_dir = kb_root / PENDING_DIR
    if not pending_dir.exists():
        return []
    results = []
    for path in sorted(pending_dir.glob("*.md")):
        try:
            post = frontmatter.load(str(path))
            results.append({
                "id": post.metadata.get("id", path.stem),
                "type": post.metadata.get("type", "unknown"),
                "title": post.metadata.get("title", "Untitled"),
                "created_at": str(post.metadata.get("created_at", "")),
                "path": str(path),
            })
        except Exception as e:
            logger.warning("Could not read pending entry %s: %s", path, e)
    return results


def get_pending(kb_root: Path, pending_id: str) -> Optional[tuple[Path, frontmatter.Post]]:
    """Get a pending entry by ID.

    Args:
        kb_root: Root directory of the knowledge base.
        pending_id: The pending entry ID.

    Returns:
        Tuple of (path, parsed post) or None if not found.
    """
    pending_dir = kb_root / PENDING_DIR
    path = pending_dir / f"{pending_id}.md"
    if not path.exists():
        return None
    try:
        post = frontmatter.load(str(path))
        return path, post
    except Exception as e:
        logger.error("Could not parse pending entry %s: %s", pending_id, e)
        return None


def reject_pending(kb_root: Path, pending_id: str, reason: str = "") -> bool:
    """Delete a pending entry (reject it).

    Args:
        kb_root: Root directory of the knowledge base.
        pending_id: ID to reject.
        reason: Optional rejection reason for the log.

    Returns:
        True if deleted, False if not found.
    """
    result = get_pending(kb_root, pending_id)
    if result is None:
        return False
    path, post = result
    title = str(post.metadata.get("title", "Untitled"))
    path.unlink()
    _append_log(kb_root, "rejected", pending_id, f"{title} — {reason}")
    logger.info("Rejected pending entry %s", pending_id)
    return True


def _next_sequential_id(kb_root: Path, kb_type: str, category: Optional[str]) -> str:
    """Determine the next sequential permanent ID for an entry type.

    Args:
        kb_root: Root directory of the knowledge base.
        kb_type: Entry type (pitfall, model, etc.).
        category: Subcategory for pitfall type.

    Returns:
        New permanent ID string, e.g. 'PT-DB-001'.
    """
    type_prefix = TYPE_PREFIXES.get(kb_type, "XX")
    cat_prefix = "GEN"
    if kb_type == "pitfall" and category:
        cat_map = {
            "network": "NET",
            "system": "SYS",
            "application": "APP",
            "database": "DB",
        }
        cat_prefix = cat_map.get(category, "GEN")

    # Scan existing entries for highest number
    type_dir = kb_root / kb_type
    max_num = 0
    if type_dir.exists():
        for md_file in type_dir.rglob("*.md"):
            if md_file.name.startswith("_"):
                continue
            stem = md_file.stem
            parts = stem.split("-")
            if len(parts) >= 3 and parts[0] == type_prefix and parts[1] == cat_prefix:
                try:
                    num = int(parts[2])
                    max_num = max(max_num, num)
                except ValueError:
                    pass

    new_num = max_num + 1
    return f"{type_prefix}-{cat_prefix}-{new_num:03d}"


def _append_log(kb_root: Path, action: str, entry_id: str, summary: str) -> None:
    """Append an action to contributions/log.md."""
    log_path = kb_root / LOG_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    line = f"\n{now} | {action} | {entry_id} | {summary}"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)
