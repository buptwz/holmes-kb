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
    # Two-pass stable sort: first by updated_at desc, then by maturity asc.
    _MATURITY_ORDER = {"proven": 0, "verified": 1, "draft": 2, "deprecated": 3}
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
            "Then: kb_read(id) → summary + Contents; "
            "kb_read(id, section='<name>') → read specific section; "
            "kb_read(id, branch='<label>') → read specific branch. "
            "Behavior tags: [api:read]=run read-only command (safe to auto-execute), "
            "[api:write]=run state-changing command (tell user first), "
            "[api:danger]=irreversible command (MUST get user confirmation), "
            "[physical]=check hardware, "
            "[decide]=ask user which condition matches, [verify]=check result. "
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
    detail: str = "",
    section: str = "",
    branch: str = "",
    session_id: str = "",
) -> dict:
    """Read a KB entry with progressive disclosure.

    detail levels:
      - "" or "summary" (default): structured summary + Contents (table of contents)
      - "navigate": Contents section only — the structural roadmap for all types
      - "full": complete document body

    section: read a specific ## section by name (e.g. "Root Cause", "Steps").
             Returns the section content only. Works for ALL entry types.

    branch: read a specific ### branch section under ## Resolution
            (plus Symptoms + Root Cause for context). For pitfall entries with branches.
    """
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

    # Normalize detail parameter
    if full and not detail:
        detail = "full"
    if not detail:
        detail = "summary"

    _logger.write_span(
        session_id or "session-unknown", "mcp.kb_read", "INFO", "ok",
        entry_id=entry_id, detail=detail, section=section, branch=branch,
    )

    body = (post.content or "").strip()

    # --- Section-level read: return a specific ## section ---
    if section:
        section_text = _extract_full_section(body, f"## {section}")
        if not section_text:
            return {
                "error": f"Section '## {section}' not found in entry {entry_id}",
                "available_sections": _list_sections(body),
            }
        result: dict = {
            "id": entry_id,
            "type": entry_type,
            "title": str(meta.get("title", "")),
            "section": section,
            "content": section_text,
            "next": (
                f"Read another section: kb_read(id='{entry_id}', section='<name>'). "
                f"See Contents for available sections: kb_read(id='{entry_id}', detail='navigate')."
            ),
        }
        if is_pending:
            result["pending"] = True
        return result

    # --- Branch-level read: return specific ### section + shared context ---
    if branch:
        branch_content = _extract_branch_section(body, branch)
        if branch_content is None:
            return {
                "error": f"Branch '{branch}' not found in entry {entry_id}",
                "available_branches": _list_branch_labels(body),
            }
        # Include Symptoms + Root Cause as shared context
        context_parts = []
        for section_name in ("Symptoms", "Root Cause"):
            section_text = _extract_full_section(body, f"## {section_name}")
            if section_text:
                context_parts.append(f"## {section_name}\n\n{section_text}")

        result = {
            "id": entry_id,
            "type": entry_type,
            "title": str(meta.get("title", "")),
            "branch": branch,
            "context": "\n\n".join(context_parts) if context_parts else "",
            "content": branch_content,
            "next": (
                "After completing this branch, check Contents for next steps: "
                f"kb_read(id='{entry_id}', detail='navigate'). "
                f"Or confirm resolution: kb_confirm(id='{entry_id}', session_id, outcome='solved'|'not_solved')."
            ),
        }
        if is_pending:
            result["pending"] = True
        return result

    # --- Navigate level: Contents section (universal for all types) ---
    if detail == "navigate":
        contents_section = _extract_full_section(body, "## Contents")
        if not contents_section:
            # Legacy fallback: try Diagnostic Flow
            contents_section = _extract_full_section(body, "## Diagnostic Flow")
        if not contents_section:
            # Last resort: build a section list from headings
            contents_section = _build_section_list(body)

        branches = _list_branch_labels(body)
        sections = _list_sections(body)

        result = {
            "id": entry_id,
            "type": entry_type,
            "title": str(meta.get("title", "")),
            "contents": contents_section or "(no contents section found)",
            "sections": sections,
        }
        if branches:
            result["branches"] = branches
            result["next"] = (
                f"Read a specific section: kb_read(id='{entry_id}', section='<name>'). "
                f"Or read a branch: kb_read(id='{entry_id}', branch='<label>')."
            )
        else:
            result["next"] = (
                f"Read a specific section: kb_read(id='{entry_id}', section='<name>')."
            )
        if is_pending:
            result["pending"] = True
        return result

    # --- Full level: complete body ---
    if detail == "full":
        result = {
            "id": entry_id,
            "type": entry_type,
            "title": str(meta.get("title", "")),
            "maturity": entry_maturity,
            "content": body,
            "next": f"After applying the resolution, call kb_confirm(id='{entry_id}', session_id, outcome='solved'|'not_solved').",
        }
        if is_pending:
            result["pending"] = True
        return result

    # --- Summary level (default) ---
    summary = _parse_entry_summary(entry_type, post.content, meta)
    if is_pending:
        summary["pending"] = True
    return summary


# ---------------------------------------------------------------------------
# Branch / section extraction helpers
# ---------------------------------------------------------------------------


def _extract_full_section(body: str, heading: str) -> str:
    """Extract the full content of a ## section (until the next ## heading or EOF)."""
    heading_lower = heading.strip().lower()
    lines = body.split("\n")
    found = False
    content_lines: list[str] = []
    for line in lines:
        if not found:
            if line.strip().lower().startswith(heading_lower):
                found = True
            continue
        if line.strip().startswith("## ") and not line.strip().startswith("### "):
            break
        content_lines.append(line)
    return "\n".join(content_lines).strip()


def _extract_branch_section(body: str, branch_label: str) -> str | None:
    """Extract a ### branch section by label (fuzzy match on heading text).

    Returns the full content of the matching ### section, or None if not found.
    """
    branch_lower = branch_label.strip().lower()
    lines = body.split("\n")
    found = False
    content_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            if found:
                break  # hit the next ### heading — done
            heading_text = stripped[4:].strip().lower()
            # Fuzzy match: branch label appears in heading, or heading appears in label
            if branch_lower in heading_text or heading_text in branch_lower:
                found = True
                content_lines.append(line)
                continue
            # Also try matching after stripping common prefixes like "分支 A："
            # or "[A]" or "Branch A:"
            import re
            cleaned = re.sub(r"^(分支|branch)\s*[a-z]?\s*[:：]?\s*", "", heading_text, flags=re.IGNORECASE)
            if branch_lower in cleaned or cleaned in branch_lower:
                found = True
                content_lines.append(line)
                continue
        elif stripped.startswith("## ") and found:
            break  # hit the next ## heading — done
        elif found:
            content_lines.append(line)
    return "\n".join(content_lines).strip() if content_lines else None


def _list_branch_labels(body: str) -> list[str]:
    """List all ### subsection headings under ## Resolution."""
    in_resolution = False
    labels: list[str] = []
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("## resolution"):
            in_resolution = True
            continue
        if stripped.startswith("## ") and not stripped.startswith("### "):
            if in_resolution:
                break
            continue
        if in_resolution and stripped.startswith("### "):
            labels.append(stripped[4:].strip())
    return labels


def _extract_navigation_table(body: str) -> str:
    """Extract the markdown table at the start of ## Resolution (if any)."""
    in_resolution = False
    table_lines: list[str] = []
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("## resolution"):
            in_resolution = True
            continue
        if in_resolution:
            if stripped.startswith("|") or stripped.startswith("---"):
                table_lines.append(line)
            elif stripped.startswith("### ") or (stripped and not stripped.startswith("|") and table_lines):
                break
            elif not stripped and not table_lines:
                continue  # skip leading blank lines
    return "\n".join(table_lines).strip()


def _list_sections(body: str) -> list[str]:
    """List all ## section heading names (excluding Contents itself)."""
    sections: list[str] = []
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            name = stripped[3:].strip()
            if name.lower() != "contents":
                sections.append(name)
    return sections


def _build_section_list(body: str) -> str:
    """Build a fallback section list from ## headings when no Contents section exists."""
    sections = _list_sections(body)
    if not sections:
        return ""
    lines = ["| Section | Available |", "|---|---|"]
    for s in sections:
        lines.append(f"| {s} | yes |")
    return "\n".join(lines)


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
        # Indicate whether resolution is linear or branching
        branch_labels = _list_branch_labels(body)
        summary["resolution_structure"] = "branching" if branch_labels else "linear"
        summary["commands_count"] = body.count("```") // 2  # paired fences
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
        # Step titles: ### subsection headings under ## Steps (or ## Procedure)
        step_titles = _extract_subsection_titles(body, "## Steps")
        if not step_titles:
            step_titles = _extract_subsection_titles(body, "## Procedure")
        if step_titles:
            summary["step_titles"] = step_titles
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
        # Rule titles: ### subsections under ## Guideline (or ## Rule)
        rule_titles = _extract_subsection_titles(body, "## Guideline")
        if not rule_titles:
            rule_titles = _extract_subsection_titles(body, "## Rule")
        if rule_titles:
            summary["rule_count"] = len(rule_titles)
            summary["rule_titles"] = rule_titles
    elif entry_type == "decision":
        summary["context"] = _extract_first_paragraph(body, "## Context")
        summary["decision"] = _extract_first_paragraph(body, "## Decision")

    # Include Contents in summary — agent sees the TOC upfront
    body = (body or "").strip() if isinstance(body, str) else ""
    contents_section = _extract_full_section(body, "## Contents")
    if contents_section:
        summary["contents"] = contents_section

    # Include decision_map if present (complex branching entries)
    decision_map = meta.get("decision_map")
    if decision_map and isinstance(decision_map, list):
        summary["decision_map"] = decision_map

    # Navigation hints — universal flow: navigate → section/branch → confirm
    branches = _list_branch_labels(body)
    sections = _list_sections(body)

    if branches:
        summary["branches"] = branches
        if decision_map and isinstance(decision_map, list):
            summary["next"] = (
                "Match the user's symptom against decision_map above to pick the right branch. "
                f"Then: kb_read(id='{entry_id}', branch='<matched_branch>'). "
                f"Or see full structure: kb_read(id='{entry_id}', detail='navigate')."
            )
        else:
            summary["next"] = (
                f"See structure: kb_read(id='{entry_id}', detail='navigate'). "
                f"Read a section: kb_read(id='{entry_id}', section='<name>'). "
                f"Read a branch: kb_read(id='{entry_id}', branch='<label>')."
            )
    elif sections:
        summary["sections"] = sections
        summary["next"] = (
            f"See structure: kb_read(id='{entry_id}', detail='navigate'). "
            f"Read a section: kb_read(id='{entry_id}', section='<name>')."
        )
    else:
        summary["next"] = (
            f"Read full: kb_read(id='{entry_id}', detail='full')."
        )

    return summary


def _extract_first_paragraph(body: str, heading: str) -> str:
    """Extract the first non-empty paragraph after a heading."""
    heading_lower = heading.strip().lower()
    lines = body.split("\n")
    found = False
    para_lines: list[str] = []
    for line in lines:
        if not found and line.strip().lower().startswith(heading_lower):
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
        if not found and line.strip().lower().startswith(heading_lower):
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
        if not found and line.strip().lower().startswith(heading_lower):
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
        if not found and line.strip().lower().startswith(heading_lower):
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
        if not found and line.strip().lower().startswith(heading_lower):
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
