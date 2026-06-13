"""MCP tool handler implementations for the Holmes KB server."""

from __future__ import annotations

import json
import re
import socket
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional
from uuid import uuid4

from holmes.kb.pending import write_pending
from holmes.kb.store import append_evidence, list_entries, read_entry

# ---------------------------------------------------------------------------
# Foundational helpers
# ---------------------------------------------------------------------------

# Extensions that are safe to read as text in skill subdirectories.
_TEXT_EXTENSIONS = frozenset({
    ".sh", ".bash", ".py", ".rb", ".js", ".ts", ".go", ".rs", ".java",
    ".md", ".txt", ".yaml", ".yml", ".json", ".toml", ".ini", ".conf", ".env",
    ".sql", ".xml", ".html", ".css",
})

# Regex for KB entry IDs: e.g. PT-DB-001, MD-SVC-003
_ENTRY_ID_PATTERN = re.compile(r"^[A-Z]{2,3}-[A-Z]{2,3}-\d{3}$")

# Regex for skill names: lowercase kebab, 3-64 chars
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]{3,64}$")


def _is_entry_id(id_str: str) -> bool:
    """Return True if id_str matches the KB entry ID format (e.g. PT-DB-001)."""
    return bool(_ENTRY_ID_PATTERN.match(id_str))


def _is_text_file(path: Path) -> bool:
    """Return True if the file has a text-safe extension."""
    return path.suffix.lower() in _TEXT_EXTENSIONS


def _get_contributor(kb_root: Path) -> str:
    """Get contributor identity from git config, falling back to hostname."""
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


# ---------------------------------------------------------------------------
# handle_kb_overview
# ---------------------------------------------------------------------------


def handle_kb_overview(kb_root: Path) -> dict:
    """Get a structural overview of the knowledge base.

    Returns dict with entries (per-type counts), skill_count, categories,
    top_tags, session_id, and hint.
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

    # Count skills
    skill_count = 0
    skills_dir = kb_root / "skills"
    if skills_dir.is_dir():
        skill_count = sum(
            1 for d in skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        )

    # Generate a session_id for this client session (use in kb_confirm)
    session_id = str(uuid4())[:8]

    return {
        "entries": type_counts,
        "skill_count": skill_count,
        "categories": sorted(categories),
        "top_tags": top_tags,
        "session_id": session_id,
        "hint": (
            f"Save session_id='{session_id}' and pass it to kb_confirm to record evidence. "
            "Next: call kb_list to browse entries by type, or kb_search to find specific entries."
        ),
    }


# ---------------------------------------------------------------------------
# handle_kb_list
# ---------------------------------------------------------------------------


def handle_kb_list(
    kb_root: Path,
    type: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """List knowledge entries or skills with filtering and pagination.

    When type='skill', returns skill names and descriptions.
    For all other types, returns entry metadata with brief previews.
    """
    if type == "skill":
        return _list_skills(kb_root, limit=limit, offset=offset)

    limit = min(max(1, limit), 100)
    all_entries = list_entries(kb_root, kb_type=type, category=category)
    total = len(all_entries)
    page = all_entries[offset: offset + limit]

    entry_list = []
    for meta in page:
        brief = ""
        try:
            content = read_entry(kb_root, meta.id)
            if content:
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
        "hint": "Call kb_read(id=<entry_id>) to read the full content of any entry.",
    }


def _list_skills(kb_root: Path, limit: int = 20, offset: int = 0) -> dict:
    """List all skills in the KB."""
    from holmes.kb.skill.manager import list_skills

    all_skills = list_skills(kb_root)
    total = len(all_skills)
    page = all_skills[offset: offset + limit]

    return {
        "entries": [
            {"id": s.name, "description": s.description}
            for s in page
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
        "hint": "Call kb_read(id=<skill_name>) to read the full SKILL.md and linked entries.",
    }


# ---------------------------------------------------------------------------
# handle_kb_read
# ---------------------------------------------------------------------------


def handle_kb_read(kb_root: Path, entry_id: str, path: Optional[str] = None) -> dict:
    """Read a KB entry or skill by ID, with optional subfile access.

    Routes by ID format:
    - Entry IDs (PT-DB-001): returns entry content + skill_refs
    - Skill names (redis-oom-recovery): returns SKILL.md + linked_entries + files list
    - Skill name + path: returns subfile content
    """
    if _is_entry_id(entry_id):
        if path is not None:
            return {"error": "The 'path' parameter is only valid for skill IDs, not entry IDs."}
        return _read_entry(kb_root, entry_id)

    # Treat as skill name
    return _read_skill(kb_root, entry_id, path)


def _read_entry(kb_root: Path, entry_id: str) -> dict:
    """Read a KB entry by ID and return its content with skill_refs."""
    content = read_entry(kb_root, entry_id)
    if content is None:
        return {"error": f"Entry not found: {entry_id}"}

    entry_type = ""
    entry_maturity = ""
    skill_refs: list[str] = []
    try:
        import frontmatter
        post = frontmatter.loads(content)
        entry_type = str(post.metadata.get("type", ""))
        entry_maturity = str(post.metadata.get("maturity", ""))
        skill_refs = [str(s) for s in (post.metadata.get("skill_refs") or [])]
    except Exception:
        pass

    result: dict = {
        "id": entry_id,
        "type": entry_type,
        "maturity": entry_maturity,
        "content": content,
        "skill_refs": skill_refs,
    }
    if skill_refs:
        result["hint"] = (
            f"This entry links to {len(skill_refs)} skill(s). "
            "Call kb_read(id=<skill_name>) to read any skill's instructions and files."
        )
    return result


def _read_skill(kb_root: Path, skill_name: str, subpath: Optional[str] = None) -> dict:
    """Read a skill's SKILL.md or a subfile within the skill directory."""
    skill_dir = kb_root / "skills" / skill_name
    if not skill_dir.is_dir():
        return {"error": f"Skill not found: {skill_name}"}

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return {"error": f"Skill '{skill_name}' has no SKILL.md"}

    # Reading a subfile
    if subpath is not None:
        return _read_skill_subfile(kb_root, skill_name, skill_dir, subpath)

    # Reading the main SKILL.md
    try:
        from holmes.kb.skill.manager import parse_skill_md
        defn = parse_skill_md(skill_md)
    except Exception as exc:
        return {"error": f"Failed to parse SKILL.md: {exc}"}

    # Compute linked_entries by scanning all KB entries for skill_refs
    linked_entries = _compute_linked_entries(kb_root, skill_name)

    # List text files in skill directory (relative paths, excluding SKILL.md)
    files = _list_skill_files(skill_dir)

    # Body = SKILL.md content without frontmatter
    body = defn.content
    try:
        import frontmatter
        post = frontmatter.loads(defn.content)
        body = post.content
    except Exception:
        pass

    result: dict = {
        "id": skill_name,
        "type": "skill",
        "description": defn.description,
        "content": body,
        "linked_entries": linked_entries,
        "files": files,
    }
    hints = []
    if linked_entries:
        hints.append(f"Linked entries: {linked_entries}. Call kb_read(id=<entry_id>) to read them.")
    if files:
        hints.append(f"Skill files available. Call kb_read(id='{skill_name}', path='<file>') to read any file.")
    if hints:
        result["hint"] = " ".join(hints)
    return result


def _read_skill_subfile(
    kb_root: Path, skill_name: str, skill_dir: Path, subpath: str
) -> dict:
    """Read a file within a skill directory with path safety checks."""
    # Prevent path traversal
    try:
        target = (skill_dir / subpath).resolve()
        skill_dir_resolved = skill_dir.resolve()
        target.relative_to(skill_dir_resolved)  # raises ValueError if outside
    except (ValueError, OSError):
        return {"error": f"Invalid path: '{subpath}' — must be within the skill directory."}

    if not target.exists():
        return {"error": f"File not found: '{subpath}' in skill '{skill_name}'"}

    if not target.is_file():
        return {"error": f"'{subpath}' is a directory, not a file."}

    if not _is_text_file(target):
        return {"error": f"'{subpath}' is a binary file and cannot be read via MCP."}

    try:
        content = target.read_text(encoding="utf-8")
    except Exception as exc:
        return {"error": f"Failed to read file: {exc}"}

    return {
        "id": skill_name,
        "path": subpath,
        "content": content,
    }


def _compute_linked_entries(kb_root: Path, skill_name: str) -> list[str]:
    """Scan all KB entries and return IDs of those with skill_refs containing skill_name."""
    import frontmatter

    linked: list[str] = []
    for kb_type in ("pitfall", "model", "guideline", "process", "decision"):
        type_dir = kb_root / kb_type
        if not type_dir.is_dir():
            continue
        for md_file in sorted(type_dir.rglob("*.md")):
            if md_file.name.startswith("_"):
                continue
            try:
                post = frontmatter.load(str(md_file))
                refs = [str(r) for r in (post.metadata.get("skill_refs") or [])]
                if skill_name in refs:
                    eid = str(post.metadata.get("id", md_file.stem))
                    linked.append(eid)
            except Exception:
                pass
    return linked


def _list_skill_files(skill_dir: Path) -> list[str]:
    """Return relative paths of text files in a skill directory (excluding SKILL.md)."""
    files: list[str] = []
    for f in sorted(skill_dir.rglob("*")):
        if not f.is_file():
            continue
        if f.name == "SKILL.md":
            continue
        if not _is_text_file(f):
            continue
        rel = f.relative_to(skill_dir)
        files.append(str(rel))
    return files


# ---------------------------------------------------------------------------
# handle_kb_search
# ---------------------------------------------------------------------------


def handle_kb_search(
    kb_root: Path,
    query: str,
    type: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """Search KB entries by keyword query.

    Note: skills are not included in the search index. Use kb_list(type='skill')
    to browse skills, or kb_read(id=<skill_name>) to read a specific skill.
    """
    from holmes.kb.search import search

    limit = min(max(1, limit), 50)
    results = search(kb_root, query, limit=limit * 2 if type else limit)

    if type and type != "skill":
        results = [r for r in results if r.kb_type == type]

    results = results[:limit]

    items = [
        {
            "id": r.entry_id,
            "title": r.title,
            "type": r.kb_type,
            "maturity": r.maturity,
            "score": round(r.score, 3),
            "brief": r.snippet,
        }
        for r in results
    ]

    return {
        "items": items,
        "total": len(items),
        "hint": (
            "Call kb_read(id=<entry_id>) to read the full content of any result. "
            "Check skill_refs in the entry response to navigate to related skills."
        ),
    }


# ---------------------------------------------------------------------------
# handle_kb_confirm
# ---------------------------------------------------------------------------


def handle_kb_confirm(kb_root: Path, entry_id: str, session_id: str) -> dict:
    """Record that a KB entry successfully helped resolve the current issue.

    Writes evidence sidecar and auto-updates maturity.
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


# ---------------------------------------------------------------------------
# handle_kb_submit
# ---------------------------------------------------------------------------


def handle_kb_submit(
    kb_root: Path,
    title: str,
    type: str,
    content: str,
    session_id: str,
    category: Optional[str] = None,
    tags: Optional[list] = None,
) -> dict:
    """Submit a new knowledge entry for human review."""
    from datetime import datetime, timezone

    contributor = _get_contributor(kb_root)

    tag_list = tags or []
    cat_str = f'category: "{category}"' if category else "category: ~"
    tags_yaml = json.dumps(tag_list)
    now_iso = datetime.now(timezone.utc).isoformat()

    frontmatter_block = (
        f"---\n"
        f"type: {type}\n"
        f'title: "{title}"\n'
        f"maturity: draft\n"
        f"{cat_str}\n"
        f"tags: {tags_yaml}\n"
        f'created_at: "{now_iso}"\n'
        f"---\n\n"
    )

    stripped = content.strip()
    if stripped.startswith("---"):
        end_idx = stripped.find("---", 3)
        if end_idx != -1:
            fm_text = stripped[3:end_idx]
            body = stripped[end_idx + 3:]
            if "title:" not in fm_text:
                fm_text = f'\ntitle: "{title}"\n' + fm_text.lstrip("\n")
            full_markdown = f"---{fm_text}---{body}"
        else:
            full_markdown = frontmatter_block + stripped
    else:
        full_markdown = frontmatter_block + stripped

    try:
        pending_id = write_pending(kb_root, full_markdown, source="agent", source_session=session_id)
    except Exception as exc:
        return {"error": str(exc), "status": "rejected"}

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
