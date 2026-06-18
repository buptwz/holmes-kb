"""Pending entry management — contributions/pending/ CRUD.

Pending entries are KB entries awaiting 3-gate confirmation.
They use temporary IDs until confirmed into the official KB.

Temporary ID format:  pending-{YYYYMMDD}-{HHMMSS}-{random4}
Permanent ID format:  {TYPE_PREFIX}-{CAT_ABBR}-{NNN}  e.g. PT-DB-001
"""

from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter

from holmes.kb.atomic import atomic_write

PENDING_DIR = "contributions/pending"
LOG_PATH = "contributions/log.md"


def _make_pending_id() -> str:
    """Generate a unique temporary pending entry ID."""
    now = datetime.now(timezone.utc)
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"pending-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{rand}"


def write_pending(
    kb_root: Path,
    content: str,
    source: str = "auto",
    source_session: str = "",
    corrects: Optional[str] = None,
) -> str:
    """Write a new pending entry, assigning a temporary ID.

    Args:
        kb_root: Root directory of the knowledge base.
        content: Markdown with YAML frontmatter.
        source: Origin of the entry — "auto" (import) or "agent" (KbExtractAndSave).
        source_session: Caller session identifier (timestamp or session ID).
        corrects: Optional entry ID that this proposal intends to correct/replace.
                  When provided, skips the title duplicate check.

    Returns:
        Assigned temporary pending ID.

    Raises:
        DuplicateTitleError: If title matches a verified/proven entry and corrects is not set.
        ValueError: If corrects is provided but the target entry does not exist.
    """
    from holmes.kb.governance import DuplicateTitleError as _DupErr
    from holmes.kb.governance import check_title_duplicate
    from holmes.kb.store import list_entries as _list_entries

    pending_dir = kb_root / PENDING_DIR
    pending_dir.mkdir(parents=True, exist_ok=True)

    post = frontmatter.loads(content)

    # Ensure maturity is always set — Gate 1 requires it, and agents may omit it.
    post.metadata.setdefault("maturity", "draft")

    # Title duplicate check — skip only when a valid corrects target is provided.
    if corrects:
        # Validate that corrects target exists.
        found = any(m.id == corrects for m in _list_entries(kb_root))
        if not found:
            raise ValueError(f"Correction target not found: {corrects!r}")
        post.metadata["corrects"] = corrects
    else:
        title = str(post.metadata.get("title", "")).strip()
        if title:
            dup_id = check_title_duplicate(kb_root, title)
            if dup_id:
                raise _DupErr(title, dup_id)

    pending_id = _make_pending_id()
    post.metadata["id"] = pending_id
    now_iso = datetime.now(timezone.utc).isoformat()
    if "created_at" not in post.metadata:
        post.metadata["created_at"] = now_iso
    post.metadata["updated_at"] = now_iso

    # PendingEntry specialized fields (data-model.md §1.5).
    post.metadata["pending"] = True
    post.metadata["pending_since"] = now_iso
    post.metadata["source"] = source
    post.metadata["source_session"] = source_session or now_iso
    post.metadata["suggested_type"] = str(post.metadata.get("type", "pitfall"))
    post.metadata["suggested_category"] = str(post.metadata.get("category", ""))

    path = pending_dir / f"{pending_id}.md"
    atomic_write(path, frontmatter.dumps(post))
    append_log(
        kb_root,
        action="pending",
        entry_id=pending_id,
        summary=str(post.metadata.get("title", "Untitled")),
    )
    return pending_id


def list_pending(kb_root: Path) -> list[dict]:
    """List all pending entries as plain dicts.

    Args:
        kb_root: Root directory of the knowledge base.

    Returns:
        List of dicts with keys: id, type, title, created_at, path.
    """
    pending_dir = kb_root / PENDING_DIR
    if not pending_dir.exists():
        return []
    results: list[dict] = []
    for path in sorted(pending_dir.glob("*.md")):
        try:
            post = frontmatter.load(str(path))
            raw_pending_since = str(post.metadata.get("pending_since", ""))
            if raw_pending_since:
                pending_since = raw_pending_since
                pending_since_source = "field"
            else:
                created_at = str(post.metadata.get("created_at", ""))
                if created_at:
                    pending_since = created_at
                    pending_since_source = "created_at"
                else:
                    # Fall back to file mtime.
                    from datetime import datetime as _dt
                    pending_since = _dt.fromtimestamp(
                        path.stat().st_mtime, tz=timezone.utc
                    ).isoformat()
                    pending_since_source = "mtime"
            results.append({
                "id": post.metadata.get("id") or path.stem,
                "type": post.metadata.get("type", "unknown"),
                "title": post.metadata.get("title", "Untitled"),
                "created_at": str(post.metadata.get("created_at", "")),
                "pending_since": pending_since,
                "pending_since_source": pending_since_source,
                "path": str(path),
            })
        except Exception:  # noqa: BLE001
            pass
    return results


def get_pending(kb_root: Path, pending_id: str) -> Optional[str]:
    """Return raw Markdown content for a pending entry by ID.

    Args:
        kb_root: Root directory of the knowledge base.
        pending_id: The pending entry ID.

    Returns:
        Raw Markdown string or None if not found.
    """
    path = kb_root / PENDING_DIR / f"{pending_id}.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def delete_pending(kb_root: Path, pending_id: str) -> bool:
    """Delete a pending entry file.

    Args:
        kb_root: Root directory of the knowledge base.
        pending_id: The pending entry ID.

    Returns:
        True if deleted, False if not found.
    """
    path = kb_root / PENDING_DIR / f"{pending_id}.md"
    if not path.exists():
        return False
    path.unlink()
    return True


def append_log(kb_root: Path, action: str, entry_id: str, summary: str) -> None:
    """Append an action record to contributions/log.md.

    Args:
        kb_root: Root directory of the knowledge base.
        action: Action name (e.g. pending, confirmed, rejected).
        entry_id: Entry ID involved.
        summary: Short description for the log line.
    """
    log_path = kb_root / LOG_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    line = f"\n{now} | {action} | {entry_id} | {summary}"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)
