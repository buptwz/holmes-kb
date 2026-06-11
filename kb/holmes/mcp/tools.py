"""MCP tool handler implementations for the Holmes KB server."""

from __future__ import annotations

import json
import socket
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

from holmes.kb.pending import write_pending
from holmes.kb.store import append_evidence, list_entries, read_entry


def _get_contributor(kb_root: Path) -> str:
    """Get contributor identity from git config, falling back to hostname.

    Args:
        kb_root: Root directory of the knowledge base (must be a git repo).

    Returns:
        Email, name, or hostname string.
    """
    for field in ("user.email", "user.name"):
        try:
            result = subprocess.run(
                ["git", "-C", str(kb_root), "config", field],
                capture_output=True,
                text=True,
                timeout=5,
            )
            value = result.stdout.strip()
            if value:
                return value
        except Exception:
            pass
    return socket.gethostname()


def handle_kb_overview(kb_root: Path) -> dict:
    """Get a structural overview of the knowledge base.

    Args:
        kb_root: Root directory of the knowledge base.

    Returns:
        Dict with total, types, categories, top_tags.
    """
    entries = list_entries(kb_root)

    type_counts: dict[str, int] = {}
    categories: set[str] = set()
    tag_counter: Counter = Counter()

    for entry in entries:
        type_counts[entry.type] = type_counts.get(entry.type, 0) + 1
        if entry.category:
            categories.add(entry.category)
        for tag in entry.tags:
            tag_counter[str(tag)] += 1

    top_tags = [tag for tag, _ in tag_counter.most_common(10)]

    return {
        "total": len(entries),
        "types": type_counts,
        "categories": sorted(categories),
        "top_tags": top_tags,
    }


def handle_kb_list(
    kb_root: Path,
    type: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """List knowledge entries with filtering and pagination.

    Args:
        kb_root: Root directory of the knowledge base.
        type: Optional entry type filter.
        category: Optional category filter.
        limit: Max entries to return (default 20, max 100).
        offset: Number of entries to skip.

    Returns:
        Dict with entries list, total, offset, limit.
    """
    limit = min(max(1, limit), 100)
    all_entries = list_entries(kb_root, kb_type=type, category=category)
    total = len(all_entries)
    page = all_entries[offset : offset + limit]

    entry_list = []
    for meta in page:
        brief = ""
        try:
            content = read_entry(kb_root, meta.id)
            if content:
                # Strip frontmatter delimiter and get first 150 chars of body
                lines = content.split("\n")
                body_lines = []
                in_frontmatter = False
                fm_end = False
                for line in lines:
                    if line.strip() == "---" and not fm_end:
                        if not in_frontmatter:
                            in_frontmatter = True
                        else:
                            fm_end = True
                        continue
                    if fm_end:
                        body_lines.append(line)
                body = "\n".join(body_lines).strip()
                brief = body[:150]
        except Exception:
            pass

        entry_list.append({
            "id": meta.id,
            "title": meta.title,
            "type": meta.type,
            "category": meta.category,
            "maturity": meta.maturity,
            "brief": brief,
        })

    return {
        "entries": entry_list,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def handle_kb_read(kb_root: Path, entry_id: str) -> dict:
    """Read the full content of a KB entry by ID.

    Does NOT record any evidence — reading is not a signal of usefulness.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: Target entry ID.

    Returns:
        Dict with id, type, maturity, content — or error dict.
    """
    content = read_entry(kb_root, entry_id)
    if content is None:
        return {"error": f"Entry not found: {entry_id}"}

    # Parse type and maturity from frontmatter
    entry_type = ""
    entry_maturity = ""
    try:
        import frontmatter
        post = frontmatter.loads(content)
        entry_type = str(post.metadata.get("type", ""))
        entry_maturity = str(post.metadata.get("maturity", ""))
    except Exception:
        pass

    return {
        "id": entry_id,
        "type": entry_type,
        "maturity": entry_maturity,
        "content": content,
    }


def handle_kb_confirm(kb_root: Path, entry_id: str, session_id: str) -> dict:
    """Record that a KB entry successfully helped resolve the current issue.

    Writes evidence sidecar and auto-updates maturity.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: Target entry ID.
        session_id: Current session ID (for deduplication).

    Returns:
        Dict with ok, entry_id, maturity, promoted, contributor — or duplicate indicator.
    """
    contributor = _get_contributor(kb_root)

    # Get current maturity before writing
    old_maturity = ""
    try:
        content = read_entry(kb_root, entry_id)
        if content:
            import frontmatter
            post = frontmatter.loads(content)
            old_maturity = str(post.metadata.get("maturity", "draft"))
    except Exception:
        pass

    record = {
        "session_id": session_id,
        "contributor": contributor,
        "date": date.today().isoformat(),
    }
    appended = append_evidence(kb_root, entry_id, record)
    if not appended:
        return {"ok": False, "reason": "duplicate", "entry_id": entry_id}

    # Reload to get updated maturity
    new_maturity = old_maturity
    try:
        content = read_entry(kb_root, entry_id)
        if content:
            import frontmatter
            post = frontmatter.loads(content)
            new_maturity = str(post.metadata.get("maturity", old_maturity))
    except Exception:
        pass

    return {
        "ok": True,
        "entry_id": entry_id,
        "maturity": new_maturity,
        "promoted": new_maturity != old_maturity,
        "contributor": contributor,
    }


def handle_kb_submit(
    kb_root: Path,
    title: str,
    type: str,
    content: str,
    session_id: str,
    category: Optional[str] = None,
    tags: Optional[list] = None,
) -> dict:
    """Submit a new knowledge entry for human review.

    Creates a pending entry and writes submitter evidence.

    Args:
        kb_root: Root directory of the knowledge base.
        title: Entry title.
        type: Entry type (pitfall/model/guideline/process/decision).
        content: Entry body Markdown (sections only, no frontmatter required).
        session_id: Current session ID.
        category: Optional category.
        tags: Optional tags list.

    Returns:
        Dict with id, status, message.
    """
    from datetime import datetime, timezone

    contributor = _get_contributor(kb_root)

    # Assemble frontmatter header + content
    tag_list = tags or []
    cat_str = f'category: "{category}"' if category else "category: ~"
    tags_yaml = json.dumps(tag_list)
    now_iso = datetime.now(timezone.utc).isoformat()

    frontmatter_block = (
        f"---\n"
        f"type: {type}\n"
        f"title: \"{title}\"\n"
        f"maturity: draft\n"
        f"{cat_str}\n"
        f"tags: {tags_yaml}\n"
        f"created_at: \"{now_iso}\"\n"
        f"---\n\n"
    )

    # If content already has frontmatter, use it as-is; otherwise prepend
    stripped = content.strip()
    if stripped.startswith("---"):
        full_markdown = stripped
    else:
        full_markdown = frontmatter_block + stripped

    try:
        pending_id = write_pending(kb_root, full_markdown, source="agent", source_session=session_id)
    except Exception as exc:
        # Catches DuplicateTitleError and ValueError from write_pending
        return {"error": str(exc), "status": "rejected"}

    # Write submitter evidence (Phase 2 fix makes this work for pending entries)
    append_evidence(kb_root, pending_id, {
        "session_id": session_id,
        "contributor": contributor,
        "date": date.today().isoformat(),
    })

    return {
        "id": pending_id,
        "status": "pending",
        "message": f"Entry submitted for review. Publish with: holmes kb confirm {pending_id}",
    }
