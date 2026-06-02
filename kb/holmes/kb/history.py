"""Knowledge base version snapshot management.

Stores immutable snapshots of KB entries in $KB_ROOT/.history/ whenever an entry
is replaced (via correction workflow) or demoted (via decay).

Snapshot filename: {entry_id}-{YYYYMMDD-HHmmss}.md
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter

HISTORY_DIR = ".history"


def save_snapshot(
    kb_root: Path,
    entry_id: str,
    original_content: str,
    replaced_by: str,
    reason: str = "correction",
) -> Path:
    """Save a VersionSnapshot of an entry before it is modified or demoted.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: ID of the entry being snapshotted (e.g. PT-DB-001).
        original_content: Raw Markdown string (with frontmatter) of the original entry.
        replaced_by: Identifier of what is replacing this entry:
                     - pending entry ID for corrections (e.g. pending-20260601-153045-ab12)
                     - "decay" for maturity demotion
        reason: "correction" or "decay". Stored in snapshot frontmatter.

    Returns:
        Path to the created snapshot file.
    """
    history_dir = kb_root / HISTORY_DIR
    history_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    snapshot_filename = f"{entry_id}-{timestamp}.md"
    snapshot_path = history_dir / snapshot_filename

    # Inject snapshot metadata into a copy of the original frontmatter.
    post = frontmatter.loads(original_content)
    post.metadata["replaced_at"] = now.isoformat()
    post.metadata["replaced_by"] = replaced_by
    post.metadata["snapshot_reason"] = reason

    snapshot_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return snapshot_path


def list_snapshots(kb_root: Path, entry_id: str) -> list[Path]:
    """List all snapshots for a given entry ID, sorted by timestamp (oldest first).

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: Entry ID to look up snapshots for.

    Returns:
        Sorted list of snapshot Paths (oldest → newest).
    """
    history_dir = kb_root / HISTORY_DIR
    if not history_dir.is_dir():
        return []

    prefix = f"{entry_id}-"
    snapshots = [
        p for p in history_dir.glob("*.md")
        if p.name.startswith(prefix)
    ]
    # Sort by filename (timestamp suffix gives natural chronological order).
    snapshots.sort(key=lambda p: p.name)
    return snapshots


def read_snapshot(snapshot_path: Path) -> Optional[str]:
    """Return raw Markdown content of a snapshot file.

    Args:
        snapshot_path: Absolute path to the snapshot file.

    Returns:
        Raw Markdown string, or None if file does not exist.
    """
    if not snapshot_path.exists():
        return None
    return snapshot_path.read_text(encoding="utf-8")
