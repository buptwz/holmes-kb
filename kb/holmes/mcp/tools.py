"""MCP tool handler implementations for the Holmes KB server."""

from __future__ import annotations

import re
import socket
import subprocess
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

import frontmatter

from holmes.config import HolmesConfig
from holmes.kb.atomic import atomic_write
from holmes.kb.logger import HolmesLogger
from holmes.kb.store import append_evidence, list_entries, read_entry

# Module-level logger — writes to ~/.holmes/logs/<today>.{log,jsonl}
_logger = HolmesLogger(Path.home() / ".holmes" / "logs")

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


def _is_entry_id(id_str: str) -> bool:
    """Return True if id_str matches the KB entry ID format (e.g. PT-DB-001)."""
    return bool(_ENTRY_ID_PATTERN.match(id_str))


def _is_text_file(path: Path) -> bool:
    """Return True if the file has a text-safe extension."""
    return path.suffix.lower() in _TEXT_EXTENSIONS


# Cached LLM provider for search query expansion (MCP server is long-lived).
_search_provider: Optional[object] = None
_search_provider_loaded = False


def _get_search_provider():
    """Return a cached LLM provider for query expansion, or None if unavailable."""
    global _search_provider, _search_provider_loaded
    if not _search_provider_loaded:
        _search_provider_loaded = True
        try:
            from holmes.config import load_config
            from holmes.kb.agent.provider import create_provider

            cfg = load_config()
            if cfg.api_key:
                _search_provider = create_provider(cfg)
        except Exception:  # noqa: BLE001
            pass
    return _search_provider


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


def _sanitize_title(title: str) -> str:
    """Sanitize a draft title for use as a filename, preventing path traversal.

    Replaces path separators and ``..`` sequences with underscores.
    """
    sanitized = title.replace("/", "_").replace("\\", "_").replace("..", "_")
    return sanitized or "untitled"


# ---------------------------------------------------------------------------
# handle_kb_overview
# ---------------------------------------------------------------------------


def handle_kb_overview(kb_root: Path) -> dict:
    """Get a full structural overview of the knowledge base.

    Returns a complete entry index grouped by type → category, so the agent
    can browse the KB like a filesystem and decide which entries to read.
    """
    entries = list_entries(kb_root)

    # Build index: type → category → [{id, title, maturity}]
    index: dict[str, dict[str, list[dict]]] = {}
    for entry in entries:
        t = entry.type or "unknown"
        c = entry.category or "uncategorized"
        if t not in index:
            index[t] = {}
        if c not in index[t]:
            index[t][c] = []
        child_count = len(entry.child_entry_ids) if entry.child_entry_ids else 0
        item: dict = {"id": entry.id, "title": entry.title, "maturity": entry.maturity}
        if child_count > 0:
            item["children"] = child_count
        index[t][c].append(item)

    # Count skills
    skill_count = 0
    skills_dir = kb_root / "skills"
    if skills_dir.is_dir():
        skill_count = sum(
            1 for d in skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        )

    # Generate a session_id for this client session
    session_id = str(uuid4())[:8]

    _logger.write_span(f"session-{session_id}", "mcp.kb_overview", "INFO", "ok")

    return {
        "total_entries": len(entries),
        "skill_count": skill_count,
        "index": index,
        "session_id": session_id,
        "troubleshooting_protocol": (
            "When a user reports a hardware/system issue, follow this protocol:\n"
            "\n"
            "1. MATCH: Browse the index above. Find pitfall entries whose title matches "
            "the user's symptoms. Pitfall entries with 'children' have diagnostic trees.\n"
            "\n"
            "2. READ ROOT: Call kb_read(id=<pitfall_id>). Read the Symptoms and Root Cause "
            "sections. If the symptoms match, the 'children' field lists diagnostic procedures.\n"
            "\n"
            "3. WALK THE TREE: Read child process entries one at a time. Each step is tagged:\n"
            "   - [api]: Execute this command/API call and report the output to the user\n"
            "   - [remote]: Execute this state-changing command (restart, delete, etc.)\n"
            "   - [physical]: Ask the user to perform this physical action (check LED, reseat module)\n"
            "   - [observe]: Ask the user to visually inspect and report what they see\n"
            "   - [decide]: Based on previous step results, choose the next branch\n"
            "\n"
            "4. GUIDE STEP BY STEP: Present ONE step at a time. Wait for the user's result "
            "before proceeding. At [decide] points, ask the user which condition matches, "
            "then follow the corresponding branch link.\n"
            "\n"
            "5. RECORD: When resolved → kb_confirm(entry_id, session_id, outcome='solved'). "
            "If the entry was wrong or incomplete → kb_confirm(..., outcome='wrong', notes='...'). "
            "If no KB entry matched → kb_draft() to save the new knowledge.\n"
        ),
        "entry_types": {
            "pitfall": "Known failure pattern: Symptoms → Root Cause → Resolution. May have child process entries.",
            "process": "Step-by-step diagnostic procedure. Steps use behavior tags: [api], [remote], [physical], [observe], [decide].",
            "model": "Mental model or decision framework for problem analysis.",
            "guideline": "Operational best practice or standard procedure.",
            "decision": "Architecture/design decision record with context and rationale.",
        },
        "hint": (
            f"session_id='{session_id}' — pass to kb_confirm/kb_draft. "
            "Maturity: draft (unverified) → verified (confirmed once) → proven (multiple confirmations)."
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
    session_id: str = "",
) -> dict:
    """List knowledge entries or skills with filtering and pagination.

    When type='skill', returns skill names and descriptions.
    For all other types, returns entry metadata with brief previews.
    """
    if type == "skill":
        result = _list_skills(kb_root, limit=limit, offset=offset)
        _logger.write_span(
            session_id or "session-unknown", "mcp.kb_list", "INFO", "ok",
            type="skill", total=result.get("total", 0),
        )
        return result

    limit = min(max(1, limit), 100)
    # Show active + pending entries, hide draft/deprecated; hide process sub-entries.
    all_entries = list_entries(
        kb_root, kb_type=type, category=category,
        kb_status=None, exclude_sub_entries=True,
    )
    all_entries = [e for e in all_entries if e.kb_status in ("active", "pending")]
    total = len(all_entries)
    page = all_entries[offset: offset + limit]

    entry_list = []
    for meta in page:
        brief = ""
        try:
            # Read file directly — list_entries already found the path, skip find_entry round-trip.
            fp = Path(meta.file_path)
            if fp.is_file():
                post = frontmatter.load(str(fp))
                body = (post.content or "").strip()
                brief = body[:150]
        except Exception:
            pass

        entry_list.append({
            "id": meta.id,
            "title": meta.title,
            "type": meta.type,
            "category": meta.category or "",
            "maturity": meta.maturity,
            "tags": [str(t) for t in meta.tags],
            "updated_at": meta.updated_at,
            "brief": brief,
        })

    response = {
        "entries": entry_list,
        "total": total,
        "offset": offset,
        "limit": limit,
        "hint": "Call kb_read(id=<entry_id>) to read the full content of any entry.",
    }
    _logger.write_span(
        session_id or "session-unknown", "mcp.kb_list", "INFO", "ok",
        type=type or "", total=total,
    )
    return response


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


def handle_kb_read(kb_root: Path, entry_id: str, path: Optional[str] = None, session_id: str = "") -> dict:
    """Read a KB entry or skill by ID, with optional subfile access.

    Routes by ID format:
    - Entry IDs (PT-DB-001): returns entry content + skill_refs
    - Pending entry IDs (pending-YYYYMMDD-...): returns pending entry content + pending: true
    - Skill names (redis-oom-recovery): returns SKILL.md + linked_entries + files list
    - Skill name + path: returns subfile content
    """
    # M1: use find_entry() for ID-format-agnostic routing.
    # This supports both legacy IDs (PT-DB-001) and new-style IDs
    # (gpu-init-failure-root-001) without relying on a fixed regex.
    from holmes.kb.store import find_entry as _find_entry
    if _find_entry(kb_root, entry_id) is not None:
        if path is not None:
            return {"error": "The 'path' parameter is only valid for skill IDs, not entry IDs."}
        result = _read_entry(kb_root, entry_id)
        _logger.write_span(session_id or "session-unknown", "mcp.kb_read", "INFO", "ok", entry_id=entry_id)
        return result

    # Pending entries may not yet exist in confirmed directories; fall back to
    # read_entry() which scans contributions/pending/ as well.
    if entry_id.startswith("pending-"):
        if path is not None:
            return {"error": "The 'path' parameter is only valid for skill IDs, not entry IDs."}
        result = _read_entry(kb_root, entry_id)
        _logger.write_span(session_id or "session-unknown", "mcp.kb_read", "INFO", "ok", entry_id=entry_id)
        return result

    # Treat as skill name
    _logger.write_span(session_id or "session-unknown", "mcp.kb_read", "INFO", "ok", entry_id=entry_id)
    return _read_skill(kb_root, entry_id, path)


def _read_entry(kb_root: Path, entry_id: str) -> dict:
    """Read a KB entry (confirmed or pending) by ID and return its content with skill_refs."""
    content = read_entry(kb_root, entry_id)
    if content is None:
        return {"error": f"Entry not found: {entry_id}"}

    entry_type = ""
    entry_maturity = ""
    raw_refs: list[str] = []
    is_pending = False
    children: list[dict] = []
    parent_info: Optional[dict] = None
    try:
        import frontmatter
        post = frontmatter.loads(content)
        entry_type = str(post.metadata.get("type", ""))
        entry_maturity = str(post.metadata.get("maturity", ""))
        raw_refs = [str(s) for s in (post.metadata.get("skill_refs") or [])]
        # Bug-3 fix: detect pending entries via frontmatter flag or ID prefix.
        is_pending = bool(post.metadata.get("pending", False)) or entry_id.startswith("pending-")
        # Resolve child_entry_ids into [{id, title, type, description}] for tree navigation.
        from holmes.kb.store import find_entry as _find_entry
        for child_id in (post.metadata.get("child_entry_ids") or []):
            child_id_str = str(child_id)
            child_path = _find_entry(kb_root, child_id_str)
            if child_path is not None and child_path.exists():
                try:
                    child_post = frontmatter.load(str(child_path))
                    child_meta = child_post.metadata
                    children.append({
                        "id": child_id_str,
                        "title": str(child_meta.get("title", child_id_str)),
                        "type": str(child_meta.get("type", "")),
                        "description": str(child_meta.get("description", "")),
                    })
                except Exception:  # noqa: BLE001
                    children.append({"id": child_id_str, "title": child_id_str})
            else:
                children.append({"id": child_id_str, "title": "(not found)"})
        # Resolve parent_id for upward navigation.
        parent_id = post.metadata.get("parent_id")
        if parent_id:
            parent_id_str = str(parent_id)
            parent_path = _find_entry(kb_root, parent_id_str)
            if parent_path is not None and parent_path.exists():
                try:
                    parent_post = frontmatter.load(str(parent_path))
                    parent_info = {
                        "id": parent_id_str,
                        "title": str(parent_post.metadata.get("title", parent_id_str)),
                        "type": str(parent_post.metadata.get("type", "")),
                    }
                except Exception:  # noqa: BLE001
                    parent_info = {"id": parent_id_str, "title": parent_id_str}
    except Exception:
        pass

    # Enrich skill_refs with descriptions; skip refs pointing to missing skills.
    skill_refs: list[dict] = []
    for sname in raw_refs:
        skill_md = kb_root / "skills" / sname / "SKILL.md"
        desc = ""
        if skill_md.exists():
            try:
                import frontmatter as _fm_skill
                sp = _fm_skill.load(str(skill_md))
                desc = str(sp.metadata.get("description", ""))
            except Exception:  # noqa: BLE001
                pass
            skill_refs.append({"name": sname, "description": desc})
        # Skip refs to non-existent skills (stale links)

    result: dict = {
        "id": entry_id,
        "type": entry_type,
        "maturity": entry_maturity,
        "content": content,
        "skill_refs": skill_refs,
    }
    if children:
        result["children"] = children
    if parent_info:
        result["parent"] = parent_info
    if is_pending:
        result["pending"] = True

    # Type-aware usage guidance
    hints: list[str] = []
    if entry_type == "pitfall" and children:
        hints.append(
            f"This pitfall has {len(children)} diagnostic procedure(s). "
            "Read the Symptoms section first to confirm this matches the user's issue. "
            "Then read child entries one by one to walk through the diagnostic steps."
        )
    elif entry_type == "process":
        hints.append(
            "This is a step-by-step procedure. Each step is tagged with a behavior type:\n"
            "  [api] = execute this command and check output\n"
            "  [remote] = execute this state-changing action\n"
            "  [physical] = ask user to perform physical action (check LED, reseat module)\n"
            "  [observe] = ask user to visually inspect and report\n"
            "  [decide] = branch point — ask user which condition matches, then follow the link\n"
            "Present steps ONE AT A TIME. Wait for user feedback before proceeding."
        )
        if parent_info:
            hints.append(
                f"Parent entry: {parent_info['id']} ({parent_info.get('title', '')}). "
                "Read it for the overall failure pattern context."
            )
    if skill_refs:
        hints.append(
            f"Linked skill(s): {', '.join(s['name'] for s in skill_refs)}. "
            "Call kb_read(id=<skill_name>) for executable instructions."
        )
    if hints:
        result["usage_guide"] = "\n".join(hints)
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
    """Scan all KB entries (confirmed + pending) and return IDs of those with skill_refs containing skill_name.

    Bug-3 fix: also scans contributions/pending/ so newly imported entries are
    visible in linked_entries before human confirmation.
    """
    import frontmatter

    linked: list[str] = []

    # Scan confirmed entry type directories.
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

    # Bug-3 fix: also scan contributions/pending/ for newly imported entries.
    pending_dir = kb_root / "contributions" / "pending"
    if pending_dir.is_dir():
        for md_file in sorted(pending_dir.glob("*.md")):
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
    session_id: str = "",
    expand: bool = True,
) -> dict:
    """Search KB entries by keyword query with optional LLM query expansion.

    Note: skills are not included in the search index. Use kb_list(type='skill')
    to browse skills, or kb_read(id=<skill_name>) to read a specific skill.
    """
    from holmes.kb.search import search, expand_query

    # US-6: LLM query expansion (default on for MCP, silent fallback on error).
    effective_query = query
    if expand:
        try:
            provider = _get_search_provider()
            if provider is not None:
                effective_query = expand_query(query, provider)
        except Exception:  # noqa: BLE001
            pass  # fallback to original query

    limit = min(max(1, limit), 50)
    results = search(
        kb_root, effective_query, limit=limit,
        kb_type=type if type and type != "skill" else None,
    )

    items = [
        {
            "id": r.entry_id,
            "title": r.title,
            "type": r.kb_type,
            "category": r.category or "",
            "maturity": r.maturity,
            "tags": r.tags,
            "score": round(r.score, 3),
            "brief": r.snippet,
        }
        for r in results
    ]

    response: dict = {
        "items": items,
        "total": len(items),
    }
    if not items:
        response["hint"] = (
            "No results found. Try kb_list(type='pitfall'|'model'|'guideline'|'process'|'decision') "
            "to browse by type, or broaden your search terms."
        )
    else:
        response["hint"] = (
            "Call kb_read(id=<entry_id>) to read the full content of any result. "
            "Check skill_refs in the entry response to navigate to related skills."
        )
    _logger.write_span(
        session_id or "session-unknown", "mcp.kb_search", "INFO", "ok",
        query=query, results=len(items),
    )
    return response


# ---------------------------------------------------------------------------
# handle_kb_confirm
# ---------------------------------------------------------------------------


def handle_kb_confirm(
    kb_root: Path,
    entry_id: str,
    session_id: str,
    outcome: str = "solved",
    notes: str = "",
) -> dict:
    """Record usage feedback for a KB entry.

    Args:
        outcome: "solved" (default), "partial" (helped but incomplete), or "wrong" (incorrect/misleading).
        notes: Optional free-text feedback from the engineer.

    Writes evidence sidecar. Only "solved" outcome triggers maturity promotion.
    """
    from holmes.kb.store import find_entry as _find_entry_for_confirm
    entry_path = _find_entry_for_confirm(kb_root, entry_id)
    if entry_path is None:
        return {
            "ok": False,
            "reason": "not_found",
            "hint": (
                f"'{entry_id}' not found in KB. "
                "Pass a valid entry ID (e.g. PT-DB-001 or minimal-pitfall-root-001)."
            ),
        }

    # Reject confirm on pending entries — only approved (active) entries can receive evidence.
    try:
        _pending_dirs = (kb_root / "_pending", kb_root / "contributions" / "pending")
        for _pd in _pending_dirs:
            if entry_path.is_relative_to(_pd):
                return {
                    "ok": False,
                    "reason": "pending",
                    "hint": (
                        f"'{entry_id}' is still pending review. "
                        "Only approved entries can receive evidence. "
                        "Ask the KB maintainer to run: holmes approve " + entry_id
                    ),
                }
    except Exception:  # noqa: BLE001
        pass

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

    # Validate outcome
    valid_outcomes = ("solved", "partial", "wrong")
    if outcome not in valid_outcomes:
        return {"ok": False, "reason": "invalid_outcome", "hint": f"outcome must be one of: {valid_outcomes}"}

    record: dict = {
        "session_id": session_id,
        "contributor": contributor,
        "date": date.today().isoformat(),
        "outcome": outcome,
    }
    if notes:
        record["notes"] = notes
    appended = append_evidence(kb_root, entry_id, record)
    if not appended:
        return {"ok": False, "reason": "duplicate", "entry_id": entry_id}

    # Maturity promotion only on positive outcome
    new_maturity = old_maturity
    promoted = False
    if outcome == "solved":
        try:
            content = read_entry(kb_root, entry_id)
            if content:
                import frontmatter
                post = frontmatter.loads(content)
                new_maturity = str(post.metadata.get("maturity", old_maturity))
        except Exception:
            pass
        promoted = new_maturity != old_maturity

    _logger.write_span(
        session_id, "mcp.kb_confirm", "INFO", "ok",
        entry_id=entry_id, outcome=outcome, promoted=promoted,
    )
    result: dict = {
        "ok": True,
        "entry_id": entry_id,
        "outcome": outcome,
        "maturity": new_maturity,
        "promoted": promoted,
        "contributor": contributor,
    }
    if outcome == "wrong":
        result["hint"] = (
            "Feedback recorded. The KB maintainer will review this entry. "
            "Consider using kb_draft() to contribute a corrected version."
        )
    return result


# ---------------------------------------------------------------------------
# handle_kb_draft
# ---------------------------------------------------------------------------


def handle_kb_draft(
    kb_root: Path,
    content: str,
    title: Optional[str],
    config: HolmesConfig,
    session_id: str = "",
) -> dict:
    """Save a draft document to _drafts/ without running any LLM.

    Args:
        kb_root:    Path to the KB root directory.
        content:    Raw natural-language content from the agent.
        title:      Optional filename stem.  If omitted, a timestamp is used.
        config:     Holmes config (must have username set).
        session_id: MCP session ID for log correlation (optional).

    Returns:
        On success: {"saved": "_drafts/<file>", "next_step": "holmes import _drafts/<file>"}
        On error:   {"error": "<message>"}
    """
    if not config.username:
        return {
            "error": "config.username not set, run: holmes config set username <name>"
        }

    # Build safe filename
    if title:
        stem = _sanitize_title(title)
        filename = f"{stem}.md"
    else:
        filename = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S") + ".md"

    draft_dir = kb_root / "_drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)

    saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    draft_content = (
        f"---\n"
        f"author: {config.username}\n"
        f"saved_at: {saved_at}\n"
        f"source: mcp.draft\n"
        f"---\n\n"
        f"{content}\n"
    )
    atomic_write(draft_dir / filename, draft_content)

    stem = Path(filename).stem
    _logger.write_span(
        stem,
        "mcp.draft",
        "INFO",
        "draft saved",
        file=f"_drafts/{filename}",
        session=session_id,
    )

    return {
        "saved": f"_drafts/{filename}",
        "next_step": f"holmes import _drafts/{filename}",
    }
