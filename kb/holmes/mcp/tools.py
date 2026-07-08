"""MCP tool handler implementations for the Holmes KB server.

042 redesign: kb_browse (directory-style browsing with pagination),
two-layer kb_read, simplified kb_confirm (solved/not_solved), kb_draft.

Design principle: MCP is a passthrough — agent browses KB like a local
directory. No search engine, no ranking. Agent uses its own judgment.
"""

from __future__ import annotations

import re
import socket
import subprocess
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
    """Sanitize a draft title for use as a filename, preventing path traversal."""
    sanitized = title.replace("/", "_").replace("\\", "_").replace("..", "_")
    return sanitized or "untitled"


# ---------------------------------------------------------------------------
# Brief extraction helper
# ---------------------------------------------------------------------------


def _clean_brief_from_body(body: str, max_len: int = 150) -> str:
    """Extract a clean brief from Markdown body, stripping headings and markers.

    Skips ## headings, blank lines, and code fences. Takes the first meaningful
    content lines and joins them into a single sentence-like string.
    """
    lines = body.strip().splitlines()
    parts: list[str] = []
    in_code = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if stripped.startswith("#"):
            continue
        if not stripped:
            if parts:
                break  # stop at first blank line after collecting content
            continue
        parts.append(stripped)
        if sum(len(p) for p in parts) >= max_len:
            break
    text = " ".join(parts)
    if len(text) <= max_len:
        return text
    # Truncate at sentence boundary
    for i in range(max_len - 1, max(max_len - 80, 0), -1):
        if text[i] in ".。;；":
            return text[: i + 1]
    return text[:max_len] + "…"


# ---------------------------------------------------------------------------
# handle_kb_browse — directory-style browsing with pagination
# ---------------------------------------------------------------------------

# Lean entries: ~50-60 tokens each. 50 per page ≈ 3000 tokens.
PAGE_SIZE = 50


def handle_kb_browse(
    kb_root: Path,
    type: Optional[str] = None,
    category: Optional[str] = None,
    page: int = 1,
    session_id: str = "",
) -> dict:
    """Browse the knowledge base like a directory.

    - No params: page 1 of full index + directory overview (type/category counts)
    - type: filter by type (pitfall/model/guideline/process/decision)
    - category: filter by category slug
    - page: page number (1-based, 50 entries per page)
    """
    all_entries = list_entries(
        kb_root, kb_type=type, category=category,
        kb_status=None,
    )
    all_entries = [e for e in all_entries if e.kb_status in ("active", "pending")]

    # Sort by maturity (proven > verified > draft) then by updated_at descending.
    # Agent sees the most trusted, most recent entries first.
    _MATURITY_ORDER = {"proven": 0, "verified": 1, "draft": 2, "deprecated": 3}
    all_entries.sort(key=lambda e: (
        _MATURITY_ORDER.get(e.maturity, 9),
        e.updated_at or "",
    ), reverse=False)
    # reverse=False because maturity order is ascending (0=proven first),
    # but we want updated_at descending within same maturity group.
    # Use two-pass: stable sort by updated_at desc, then by maturity asc.
    all_entries.sort(key=lambda e: e.updated_at or "", reverse=True)
    all_entries.sort(key=lambda e: _MATURITY_ORDER.get(e.maturity, 9))

    total = len(all_entries)

    # Pagination
    page = max(1, page)
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_entries = all_entries[start:end]
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    # Lean entry format: id + type + title + brief. ~50-60 tokens each.
    entries = []
    for meta in page_entries:
        brief = meta.brief
        if not brief:
            try:
                fp = Path(meta.file_path)
                if fp.is_file():
                    post = frontmatter.load(str(fp))
                    brief = _clean_brief_from_body(post.content or "")
            except Exception:
                pass
        entries.append({
            "id": meta.id,
            "type": meta.type,
            "title": meta.title,
            "brief": brief,
        })

    if not session_id:
        session_id = str(uuid4())[:8]

    _logger.write_span(session_id, "mcp.kb_browse", "INFO", "ok", total=total, page=page)

    result: dict = {
        "entries": entries,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "session_id": session_id,
    }

    # Directory overview: type and category counts (only on first unfiltered page)
    if page == 1 and not type and not category:
        # Build type → count and category → count from all entries
        type_counts: dict[str, int] = {}
        cat_counts: dict[str, int] = {}
        for meta in all_entries:
            type_counts[meta.type] = type_counts.get(meta.type, 0) + 1
            cat = meta.category or "uncategorized"
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        result["directory"] = {
            "by_type": type_counts,
            "by_category": cat_counts,
        }
        result["guide"] = (
            "Scan titles and briefs to find entries matching the user's problem. "
            "Use kb_browse(type=...) or kb_browse(category=...) to narrow down. "
            "Then kb_read(id) for summary, kb_read(id, full=true) for complete steps. "
            "Behavior tags in steps: [api]=run command, [physical]=check hardware, [decide]=branch point. "
            "After resolution: kb_confirm(id, session_id, outcome='solved'|'not_solved')."
        )

    # Pagination hint
    if page < total_pages:
        result["next_page"] = f"kb_browse(page={page + 1})"

    return result


# ---------------------------------------------------------------------------
# handle_kb_read — two-layer: summary (default) + full
# ---------------------------------------------------------------------------


def handle_kb_read(
    kb_root: Path,
    entry_id: str,
    full: bool = False,
    session_id: str = "",
) -> dict:
    """Read a KB entry. Default returns a structured summary; full=true returns complete document."""
    content = read_entry(kb_root, entry_id)
    if content is None:
        return {"error": f"Entry not found: {entry_id}"}

    try:
        post = frontmatter.loads(content)
        meta = post.metadata
        entry_type = str(meta.get("type", ""))
        entry_maturity = str(meta.get("maturity", ""))
        is_pending = bool(meta.get("pending", False)) or entry_id.startswith("pending-")
    except Exception:
        # If we can't parse, return raw content
        return {"id": entry_id, "content": content}

    _logger.write_span(
        session_id or "session-unknown", "mcp.kb_read", "INFO", "ok",
        entry_id=entry_id, full=full,
    )

    if full:
        # Full layer: return body only (frontmatter already shown in summary layer)
        body = post.content or ""
        result: dict = {
            "id": entry_id,
            "type": entry_type,
            "title": str(meta.get("title", "")),
            "maturity": entry_maturity,
            "content": body.strip(),
            "next": f"After applying the resolution, call kb_confirm(id='{entry_id}', session_id, outcome='solved'|'not_solved').",
        }
        if is_pending:
            result["pending"] = True
        return result

    # Summary layer: parse structured summary from Markdown
    summary = _parse_entry_summary(entry_type, post.content, meta)
    if is_pending:
        summary["pending"] = True
    return summary


def _parse_entry_summary(entry_type: str, body: str, meta: dict) -> dict:
    """Parse a structured summary from Markdown body. Extracts different fields per type."""
    entry_id = str(meta.get("id", ""))
    summary: dict = {
        "id": entry_id,
        "type": entry_type,
        "title": str(meta.get("title", "")),
        "brief": str(meta.get("brief", "")),
        "maturity": str(meta.get("maturity", "")),
        "category": str(meta.get("category", "")),
        "tags": list(meta.get("tags", [])),
    }

    if entry_type == "pitfall":
        # Symptoms may be bullet list or plain paragraphs
        symptoms = _extract_bullet_list(body, "## Symptoms")
        if not symptoms:
            # Fallback: extract all non-empty lines under ## Symptoms as items
            symptoms = _extract_paragraph_lines(body, "## Symptoms")
        summary["symptoms"] = symptoms
        summary["root_cause"] = _extract_first_paragraph(body, "## Root Cause")
        summary["resolution_overview"] = _extract_subsection_overview(body, "## Resolution")
        summary["commands_count"] = body.count("```")
    elif entry_type == "model":
        summary["overview"] = _extract_first_paragraph(body, "## Overview")
        # Try bullet list first, fallback to ### subsection headings
        concepts = _extract_bullet_list(body, "## Key Concepts")
        if not concepts:
            concepts = _extract_subsection_titles(body, "## Key Concepts")
        summary["key_concepts"] = concepts
    elif entry_type == "process":
        summary["purpose"] = _extract_first_paragraph(body, "## Purpose")
        # Count steps: numbered list items (1.) OR ### Step N subsection headings
        numbered = len(re.findall(r"^\d+\.", body, re.MULTILINE))
        subsection_steps = len(re.findall(r"^###\s+Step\s+\d+", body, re.MULTILINE | re.IGNORECASE))
        summary["steps_count"] = max(numbered, subsection_steps)
        # Extract prerequisites (bullet list after **Prerequisites:** or ## Prerequisites)
        prereqs = _extract_bullet_list(body, "## Prerequisites")
        if not prereqs:
            # Try inline Prerequisites within Purpose section
            prereqs = _extract_inline_bullet_list(body, "Prerequisites")
        if prereqs:
            summary["prerequisites"] = prereqs
        # Extract critical warnings
        warnings = [
            line.strip() for line in body.splitlines()
            if line.strip().upper().startswith("**CRITICAL") or line.strip().startswith("**WARNING")
               or line.strip().startswith("**注意") or line.strip().startswith("**警告")
        ]
        if warnings:
            summary["warnings"] = [
                w.strip("* ").replace("**:", ":").replace("**", "").strip()
                for w in warnings
            ]
        # Check if rollback exists
        if "rollback" in body.lower() or "回滚" in body:
            summary["has_rollback"] = True
    elif entry_type == "guideline":
        # Guideline entries may use ## Context or ## Overview for context
        context = _extract_first_paragraph(body, "## Context")
        if not context:
            context = _extract_first_paragraph(body, "## Overview")
        summary["context"] = context
        # Guideline body may be under ## Guideline or ## Rule
        guideline = _extract_first_paragraph(body, "## Guideline")
        if not guideline:
            guideline = _extract_first_paragraph(body, "## Rule")
        summary["guideline"] = guideline
    elif entry_type == "decision":
        summary["context"] = _extract_first_paragraph(body, "## Context")
        summary["decision"] = _extract_first_paragraph(body, "## Decision")

    summary["next"] = f"Call kb_read(id='{entry_id}', full=true) to get the complete document."
    return summary


def _extract_first_paragraph(body: str, heading: str) -> str:
    """Extract the first non-empty paragraph after a heading."""
    heading_lower = heading.strip().lower()
    lines = body.split("\n")
    found = False
    para_lines: list[str] = []
    for line in lines:
        if not found and line.strip().lower() == heading_lower:
            found = True
            continue
        if found:
            stripped = line.strip()
            if stripped.startswith("##"):
                break  # next heading
            if stripped:
                para_lines.append(stripped)
            elif para_lines:
                break  # end of first paragraph
    if not para_lines:
        return ""
    text = " ".join(para_lines)
    if len(text) <= 300:
        return text
    # Try to break at sentence boundary (. or 。) within 200-300 range
    for i in range(299, 199, -1):
        if text[i] in ".。":
            return text[:i + 1]
    return text[:300] + "…"


def _extract_inline_bullet_list(body: str, keyword: str) -> list[str]:
    """Extract bullet list items that follow a **keyword:** or keyword: line (inline within a section)."""
    lines = body.split("\n")
    found = False
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not found and keyword.lower() in stripped.lower() and stripped.rstrip("*").endswith(":"):
            found = True
            continue
        if found:
            if stripped.startswith("- ") or stripped.startswith("* "):
                items.append(stripped[2:].strip())
            elif stripped and not stripped.startswith("-") and not stripped.startswith("*"):
                break  # end of bullet list
    return items


def _extract_paragraph_lines(body: str, heading: str) -> list[str]:
    """Extract all non-empty lines under a heading until the next heading.

    Unlike _extract_first_paragraph (which joins into one string),
    this returns each line as a separate list item — useful for symptoms
    written as plain text lines rather than bullet lists.
    """
    heading_lower = heading.strip().lower()
    lines = body.split("\n")
    found = False
    items: list[str] = []
    for line in lines:
        if not found and line.strip().lower() == heading_lower:
            found = True
            continue
        if found:
            stripped = line.strip()
            if stripped.startswith("##"):
                break
            if stripped:
                items.append(stripped)
    return items


def _extract_bullet_list(body: str, heading: str) -> list[str]:
    """Extract bullet list items after a heading."""
    heading_lower = heading.strip().lower()
    lines = body.split("\n")
    found = False
    items: list[str] = []
    for line in lines:
        if not found and line.strip().lower() == heading_lower:
            found = True
            continue
        if found:
            stripped = line.strip()
            if stripped.startswith("##"):
                break
            if stripped.startswith("- ") or stripped.startswith("* "):
                items.append(stripped[2:].strip())
    return items


def _extract_subsection_titles(body: str, heading: str) -> list[str]:
    """Extract ### subsection titles under a ## heading."""
    heading_lower = heading.strip().lower()
    lines = body.split("\n")
    found = False
    titles: list[str] = []
    for line in lines:
        if not found and line.strip().lower() == heading_lower:
            found = True
            continue
        if found:
            stripped = line.strip()
            if stripped.startswith("## ") and not stripped.startswith("### "):
                break
            if stripped.startswith("### "):
                titles.append(stripped.lstrip("#").strip())
    return titles


def _extract_subsection_overview(body: str, heading: str) -> str:
    """Extract an overview of ### subsections under a ## heading."""
    heading_lower = heading.strip().lower()
    lines = body.split("\n")
    found = False
    subsections: list[str] = []
    step_count = 0
    for line in lines:
        if not found and line.strip().lower() == heading_lower:
            found = True
            continue
        if found:
            stripped = line.strip()
            if stripped.startswith("## ") and not stripped.startswith("### "):
                break  # next h2
            if stripped.startswith("### "):
                subsections.append(stripped[4:].strip())
            if re.match(r"^\d+\.", stripped):
                step_count += 1

    if subsections:
        branches = ", ".join(subsections)
        return f"{len(subsections)} branches: {branches} ({step_count} total steps)"
    if step_count:
        return f"{step_count} steps"
    return ""


# ---------------------------------------------------------------------------
# handle_kb_confirm — simplified: solved / not_solved
# ---------------------------------------------------------------------------


def handle_kb_confirm(
    kb_root: Path,
    entry_id: str,
    session_id: str,
    outcome: str = "solved",
    notes: str = "",
) -> dict:
    """Record usage feedback for a KB entry.

    outcome: "solved" or "not_solved".
    "solved" triggers maturity promotion. "not_solved" is neutral — no penalty.
    """
    from holmes.kb.store import find_entry as _find_entry_for_confirm
    entry_path = _find_entry_for_confirm(kb_root, entry_id)
    if entry_path is None:
        return {
            "ok": False,
            "reason": "not_found",
            "hint": f"'{entry_id}' not found in KB.",
        }

    # Reject confirm on pending entries
    try:
        _pending_dirs = (kb_root / "_pending", kb_root / "contributions" / "pending")
        for _pd in _pending_dirs:
            if entry_path.is_relative_to(_pd):
                return {
                    "ok": False,
                    "reason": "pending",
                    "hint": (
                        f"'{entry_id}' is still pending review. "
                        "Only approved entries can receive feedback."
                    ),
                }
    except Exception:  # noqa: BLE001
        pass

    # Validate outcome
    valid_outcomes = ("solved", "not_solved")
    if outcome not in valid_outcomes:
        return {"ok": False, "reason": "invalid_outcome", "hint": f"outcome must be one of: {valid_outcomes}"}

    contributor = _get_contributor(kb_root)

    # Get current maturity before writing
    old_maturity = ""
    try:
        content = read_entry(kb_root, entry_id)
        if content:
            post = frontmatter.loads(content)
            old_maturity = str(post.metadata.get("maturity", "draft"))
    except Exception:
        pass

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

    # Maturity promotion only on solved
    new_maturity = old_maturity
    promoted = False
    if outcome == "solved":
        try:
            content = read_entry(kb_root, entry_id)
            if content:
                post = frontmatter.loads(content)
                new_maturity = str(post.metadata.get("maturity", old_maturity))
        except Exception:
            pass
        promoted = new_maturity != old_maturity

    _logger.write_span(
        session_id, "mcp.kb_confirm", "INFO", "ok",
        entry_id=entry_id, outcome=outcome, promoted=promoted,
    )
    return {
        "ok": True,
        "entry_id": entry_id,
        "outcome": outcome,
        "maturity": new_maturity,
        "promoted": promoted,
        "contributor": contributor,
    }


# ---------------------------------------------------------------------------
# handle_kb_draft — unchanged
# ---------------------------------------------------------------------------


def handle_kb_draft(
    kb_root: Path,
    content: str,
    title: Optional[str],
    config: HolmesConfig,
    session_id: str = "",
) -> dict:
    """Save a draft document to _drafts/ without running any LLM."""
    if not config.username:
        return {
            "error": "config.username not set, run: holmes config set username <name>"
        }

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
