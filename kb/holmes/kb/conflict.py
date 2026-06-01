"""Conflict entry management — contributions/conflicts/ CRUD.

Content-contradiction conflicts that cannot be auto-resolved are isolated
here for manual adjudication via `holmes kb resolve <id> --keep A|B`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

CONFLICTS_DIR = "contributions/conflicts"
CONFLICT_LOG = "contributions/log.md"


def _extract_branch_name(path: Path, side: str) -> str:
    """Best-effort: extract branch name from git conflict markers in the original file.

    Returns empty string when git context is unavailable (e.g. markers already removed).
    """
    try:
        text = path.read_text(encoding="utf-8")
        import re
        if side == "local":
            m = re.search(r"^<{7}\s+(.+)$", text, re.MULTILINE)
        else:
            m = re.search(r"^>{7}\s+(.+)$", text, re.MULTILINE)
        return m.group(1).strip() if m else ""
    except Exception:  # noqa: BLE001
        return ""


@dataclass
class ConflictFile:
    """Represents a file with git conflict markers detected by merger.py."""

    path: Path
    local_content: str
    remote_content: str


@dataclass
class ConflictEntry:
    """A stored conflict entry awaiting manual resolution."""

    conflict_id: str
    original_path: str
    side_a: str
    side_b: str
    status: Literal["pending_review", "resolved"]
    created_at: str
    local_author: str = ""
    remote_author: str = ""


def write_conflict_entry(kb_root: Path, cf: ConflictFile) -> str:
    """Write a ConflictFile to contributions/conflicts/ for human review.

    Args:
        kb_root: Root directory of the knowledge base.
        cf: ConflictFile with both sides of the conflict.

    Returns:
        The assigned conflict_id.
    """
    conflicts_dir = kb_root / CONFLICTS_DIR
    conflicts_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    conflict_id = f"conflict-{now.strftime('%Y%m%d-%H%M%S')}"

    entry_data = {
        "conflict_id": conflict_id,
        "original_path": str(cf.path),
        "status": "pending_review",
        "created_at": now.isoformat(),
        "local_author": _extract_branch_name(cf.path, "local"),
        "remote_author": _extract_branch_name(cf.path, "remote"),
    }

    # Write side A.
    (conflicts_dir / f"{conflict_id}-A.md").write_text(cf.local_content, encoding="utf-8")
    # Write side B.
    (conflicts_dir / f"{conflict_id}-B.md").write_text(cf.remote_content, encoding="utf-8")
    # Write metadata.
    meta_path = conflicts_dir / f"{conflict_id}.json"
    import json
    meta_path.write_text(json.dumps(entry_data, indent=2), encoding="utf-8")

    return conflict_id


def list_conflicts(kb_root: Path) -> list[ConflictEntry]:
    """List open conflict entries.

    Args:
        kb_root: Root directory of the knowledge base.

    Returns:
        List of ConflictEntry objects with status='open'.
    """
    import json

    conflicts_dir = kb_root / CONFLICTS_DIR
    if not conflicts_dir.exists():
        return []

    results: list[ConflictEntry] = []
    for json_file in sorted(conflicts_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            conflict_id = data["conflict_id"]
            side_a_path = conflicts_dir / f"{conflict_id}-A.md"
            side_b_path = conflicts_dir / f"{conflict_id}-B.md"
            results.append(
                ConflictEntry(
                    conflict_id=conflict_id,
                    original_path=data.get("original_path", ""),
                    side_a=side_a_path.read_text(encoding="utf-8") if side_a_path.exists() else "",
                    side_b=side_b_path.read_text(encoding="utf-8") if side_b_path.exists() else "",
                    status=data.get("status", "pending_review"),
                    created_at=data.get("created_at", ""),
                    local_author=data.get("local_author", ""),
                    remote_author=data.get("remote_author", ""),
                )
            )
        except Exception:  # noqa: BLE001
            pass

    return [e for e in results if e.status != "resolved"]


def resolve_conflict(
    kb_root: Path,
    conflict_id: str,
    keep: Literal["A", "B"],
) -> Optional[str]:
    """Resolve a conflict by promoting the chosen side to the official KB.

    Args:
        kb_root: Root directory of the knowledge base.
        conflict_id: ID of the conflict to resolve.
        keep: 'A' for local version, 'B' for remote version.

    Returns:
        The path where the entry was written, or None if not found.
    """
    import json

    from holmes.kb.store import write_entry

    conflicts_dir = kb_root / CONFLICTS_DIR
    meta_path = conflicts_dir / f"{conflict_id}.json"
    if not meta_path.exists():
        return None

    data = json.loads(meta_path.read_text(encoding="utf-8"))
    chosen_path = conflicts_dir / f"{conflict_id}-{keep}.md"
    if not chosen_path.exists():
        return None

    content = chosen_path.read_text(encoding="utf-8")
    original_path = Path(data["original_path"])
    write_entry(original_path, content)

    # Mark as resolved.
    data["status"] = "resolved"
    data["resolved_at"] = datetime.now(timezone.utc).isoformat()
    data["kept"] = keep
    meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Clean up side files.
    (conflicts_dir / f"{conflict_id}-A.md").unlink(missing_ok=True)
    (conflicts_dir / f"{conflict_id}-B.md").unlink(missing_ok=True)

    return str(original_path)


def append_conflict_log(kb_root: Path, conflict_id: str, kept: str) -> None:
    """Append a resolution record to contributions/log.md.

    Args:
        kb_root: Root directory of the knowledge base.
        conflict_id: Resolved conflict ID.
        kept: Which side was kept ('A' or 'B').
    """
    log_path = kb_root / CONFLICT_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    line = f"\n{now} | conflict_resolved | {conflict_id} | kept={kept}"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)
