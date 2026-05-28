"""Conflict entry management for Holmes KB.

Entries with content contradictions are isolated in contributions/conflicts/
until manually resolved.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter

from holmes.logging_config import get_logger


logger = get_logger("kb.conflict")

CONFLICTS_DIR = "contributions/conflicts"


def write_conflict(
    kb_root: Path,
    entry_a_content: str,
    entry_b_content: str,
    conflict_type: str,
    reason: str,
) -> str:
    """Write two conflicting entries to the conflicts directory.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_a_content: Markdown content of the first entry.
        entry_b_content: Markdown content of the second entry.
        conflict_type: E.g. 'content_contradiction', 'maturity_conflict'.
        reason: Human-readable description of the conflict.

    Returns:
        Conflict ID.
    """
    conflicts_dir = kb_root / CONFLICTS_DIR
    conflicts_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    conflict_id = f"conflict-{now.strftime('%Y%m%d%H%M%S')}"

    post_a = frontmatter.loads(entry_a_content)
    post_b = frontmatter.loads(entry_b_content)

    id_a = str(post_a.metadata.get("id", "unknown-a"))
    id_b = str(post_b.metadata.get("id", "unknown-b"))

    conflict_content = (
        f"---\n"
        f"conflict_id: {conflict_id}\n"
        f"conflict_type: {conflict_type}\n"
        f"entry_a_id: {id_a}\n"
        f"entry_b_id: {id_b}\n"
        f"reason: \"{reason}\"\n"
        f"created_at: {now.isoformat()}\n"
        f"resolved: false\n"
        f"---\n\n"
        f"# Conflict: {conflict_type}\n\n"
        f"**Reason**: {reason}\n\n"
        f"## Entry A ({id_a})\n\n"
        f"{entry_a_content}\n\n"
        f"## Entry B ({id_b})\n\n"
        f"{entry_b_content}\n\n"
        f"## Resolution\n\n"
        f"To resolve: edit this file, set `resolved: true`, then run `holmes kb rebuild-index`.\n"
    )

    path = conflicts_dir / f"{conflict_id}.md"
    path.write_text(conflict_content, encoding="utf-8")
    logger.info("Created conflict record %s (%s)", conflict_id, conflict_type)
    return conflict_id


def list_conflicts(kb_root: Path) -> list[dict]:
    """List all unresolved conflicts.

    Args:
        kb_root: Root directory of the knowledge base.

    Returns:
        List of dicts with conflict metadata.
    """
    conflicts_dir = kb_root / CONFLICTS_DIR
    if not conflicts_dir.exists():
        return []
    results = []
    for path in sorted(conflicts_dir.glob("*.md")):
        try:
            post = frontmatter.load(str(path))
            if not post.metadata.get("resolved", False):
                results.append({
                    "conflict_id": post.metadata.get("conflict_id", path.stem),
                    "conflict_type": post.metadata.get("conflict_type", "unknown"),
                    "entry_a_id": post.metadata.get("entry_a_id", ""),
                    "entry_b_id": post.metadata.get("entry_b_id", ""),
                    "reason": post.metadata.get("reason", ""),
                    "created_at": str(post.metadata.get("created_at", "")),
                })
        except Exception as e:
            logger.warning("Could not read conflict %s: %s", path, e)
    return results


def resolve_conflict(kb_root: Path, conflict_id: str) -> bool:
    """Mark a conflict as resolved.

    Args:
        kb_root: Root directory.
        conflict_id: ID of the conflict to resolve.

    Returns:
        True if resolved successfully, False if not found.
    """
    conflicts_dir = kb_root / CONFLICTS_DIR
    path = conflicts_dir / f"{conflict_id}.md"
    if not path.exists():
        return False
    post = frontmatter.load(str(path))
    post.metadata["resolved"] = True
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    logger.info("Resolved conflict %s", conflict_id)
    return True
