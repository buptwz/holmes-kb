"""Agent tool functions exposed to the Anthropic tool-use loop.

Each function implements one tool that the import agent may call.  All
functions accept a ``context`` dict carrying shared runtime state (kb_root,
dry_run, client, model, etc.) plus the tool-specific ``input`` dict from
the agent.

Functions return a plain dict which is JSON-serialised as the ``tool_result``
content sent back to the agent.

Tool catalogue (data-model.md Entity 6):
    check_source_hash          — idempotency key lookup
    write_kb_entry             — write structured entry to pending
    update_kb_entry            — merge-update an existing entry
    read_kb_entries_by_category — retrieve candidates for dedup
    compare_root_cause         — LLM semantic dedup
    verify_content             — self-verification pass
    evaluate_skill             — skill generation advisory
    create_skill_for_entry     — create + link skill
    report_item                — append item to ImportReport
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import frontmatter as fm

from holmes.kb.importer import compute_source_hash
from holmes.kb.pending import PENDING_DIR, write_pending
from holmes.kb.skill.manager import (
    create_skill,
    get_skill_dir,
    link_skill,
    skill_exists,
)
from holmes.kb.skill.usage import mark_agent_created
from holmes.kb.store import list_entries, read_entry

from holmes.kb.agent.doc_access import (
    DOC_ACCESS_TOOL_DEFINITIONS,
    DOC_ACCESS_TOOL_HANDLERS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_entry_by_hash(kb_root: Path, source_hash: str) -> tuple[str | None, str | None]:
    """Return (entry_id, file_path) for the first entry matching source_hash.

    Scans approved KB entries first, then contributions/pending/.
    """
    # Scan approved KB entries (existing behaviour).
    for entry in list_entries(kb_root):
        file_path = Path(entry.file_path)
        if not file_path.exists():
            continue
        try:
            post = fm.load(str(file_path))
            if str(post.metadata.get("source_hash", "")) == source_hash:
                return entry.id, entry.file_path
        except Exception:  # noqa: BLE001
            pass

    # D-5: Also scan contributions/pending/ so reimports are skipped.
    pending_dir = kb_root / PENDING_DIR
    if pending_dir.exists():
        for pending_file in sorted(pending_dir.glob("*.md")):
            try:
                post = fm.load(str(pending_file))
                if str(post.metadata.get("source_hash", "")) == source_hash:
                    return pending_file.stem, str(pending_file)
            except Exception:  # noqa: BLE001
                pass

    return None, None


def _find_all_entries_by_hash(
    kb_root: Path, source_hash: str
) -> list[tuple[str, str]]:
    """Return ALL (entry_id, file_path) pairs matching source_hash.

    US2 fix (020): used for document-level dedup pre-check in pipeline.py.
    Unlike _find_entry_by_hash, collects every match across approved + pending.
    """
    matches: list[tuple[str, str]] = []

    for entry in list_entries(kb_root):
        file_path = Path(entry.file_path)
        if not file_path.exists():
            continue
        try:
            post = fm.load(str(file_path))
            if str(post.metadata.get("source_hash", "")) == source_hash:
                matches.append((entry.id, entry.file_path))
        except Exception:  # noqa: BLE001
            pass

    pending_dir = kb_root / PENDING_DIR
    if pending_dir.exists():
        for pending_file in sorted(pending_dir.glob("*.md")):
            try:
                post = fm.load(str(pending_file))
                if str(post.metadata.get("source_hash", "")) == source_hash:
                    matches.append((pending_file.stem, str(pending_file)))
            except Exception:  # noqa: BLE001
                pass

    return matches


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def check_source_hash(
    ctx: dict[str, Any], tool_input: dict[str, Any]
) -> dict[str, Any]:
    """Check whether a source_hash already exists in the KB.

    Input:
        hash (str): 16-char source hash.

    Returns:
        match (bool): True if an entry with this hash exists.
        entry_id (str | None): Matched entry ID, or None.
        file_path (str | None): Matched entry file path, or None.
    """
    kb_root: Path = ctx["kb_root"]
    source_hash = tool_input.get("hash", "")
    entry_id, file_path = _find_entry_by_hash(kb_root, source_hash)
    return {
        "match": entry_id is not None,
        "entry_id": entry_id,
        "file_path": file_path,
    }


def write_kb_entry(
    ctx: dict[str, Any], tool_input: dict[str, Any]
) -> dict[str, Any]:
    """Write a structured KB entry to the pending area.

    Input:
        content (str): Full Markdown with YAML frontmatter.
        source_hash (str): 16-char source hash to embed.
        confidence (float): Classification confidence.
        force (bool, optional): Skip duplicate pending check.

    Returns:
        pending_id (str | None): Assigned pending ID, or None if dry_run.
        dry_run (bool): Whether this was a dry-run.
        action (str): Human-readable action description.
    """
    kb_root: Path = ctx["kb_root"]
    dry_run: bool = ctx.get("dry_run", False)
    content = tool_input.get("content", "")
    source_hash = tool_input.get("source_hash", "")
    confidence = float(tool_input.get("confidence", 0.0))
    # T009 (020): respect CLI --force propagated through ctx, not just LLM tool param.
    force = bool(tool_input.get("force", False)) or bool(ctx.get("force", False))

    # Embed source_hash and import_confidence into frontmatter.
    # C-3: Sync suggested_type with type to prevent inconsistency.
    # E-2 fix: apply force_type from ctx so Phase 3 LLM cannot override --type.
    try:
        from holmes.kb.agent.normalizer import DraftNormalizer
        post = fm.loads(content)
        post.metadata["source_hash"] = source_hash
        post.metadata["import_confidence"] = round(confidence, 4)
        force_type: str = ctx.get("force_type", "") or ""
        if force_type:
            post.metadata["type"] = force_type
        post.metadata["suggested_type"] = str(post.metadata.get("type", "pitfall"))
        # Re-normalize category: the Phase 3 LLM may re-introduce invalid categories
        # from the source text, overriding the Phase 2 normalizer's correction.
        kb_type_hint = str(post.metadata.get("type", ""))
        content = fm.dumps(post)
        content, _ = DraftNormalizer().normalize(content, kb_type=kb_type_hint)
    except Exception:  # noqa: BLE001
        pass

    action = f"Would create entry: {tool_input.get('title', '(unknown)')}"
    if dry_run:
        return {"pending_id": None, "dry_run": True, "action": action}

    # D-5 fix: enforce source_hash dedup regardless of whether LLM called
    # check_source_hash — prevents duplicate pending entries on reimport.
    if source_hash and not force:
        existing_id, existing_path = _find_entry_by_hash(kb_root, source_hash)
        if existing_id:
            return {
                "pending_id": existing_id,
                "dry_run": False,
                "action": f"Skipped: duplicate source hash already in KB ({existing_id})",
                "duplicate": True,
            }

    try:
        pending_id = write_pending(kb_root, content, source="auto")
    except Exception as exc:  # noqa: BLE001
        return {"pending_id": None, "dry_run": False, "action": action, "error": str(exc)}

    return {
        "pending_id": pending_id,
        "dry_run": False,
        "action": f"Created entry: {tool_input.get('title', pending_id)}",
    }


def update_kb_entry(
    ctx: dict[str, Any], tool_input: dict[str, Any]
) -> dict[str, Any]:
    """Merge-update an existing KB entry.

    Input:
        entry_id (str): ID of the entry to update.
        patch (dict): Frontmatter fields to update and/or body sections.

    Returns:
        success (bool): Whether the update succeeded.
        action (str): Human-readable action description.
    """
    kb_root: Path = ctx["kb_root"]
    dry_run: bool = ctx.get("dry_run", False)
    entry_id = tool_input.get("entry_id", "")
    patch: dict = tool_input.get("patch", {})

    action = f"Would update entry: {entry_id}"
    if dry_run:
        return {"success": True, "dry_run": True, "action": action}

    file_path: Path | None = None
    for entry in list_entries(kb_root):
        if entry.id.upper() == entry_id.upper():
            file_path = Path(entry.file_path)
            break

    if file_path is None or not file_path.exists():
        return {"success": False, "action": action, "error": f"Entry {entry_id} not found"}

    try:
        post = fm.load(str(file_path))
        for key, value in patch.items():
            if key == "body":
                # Append body content.
                post.content = (post.content or "").rstrip() + "\n\n" + str(value)
            elif key == "related_entries":
                existing = list(post.metadata.get("related_entries") or [])
                for v in (value if isinstance(value, list) else [value]):
                    if v not in existing:
                        existing.append(v)
                post.metadata["related_entries"] = existing
            else:
                post.metadata[key] = value
        post.metadata["updated_at"] = _now()
        file_path.write_text(fm.dumps(post), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "action": action, "error": str(exc)}

    return {"success": True, "action": f"Updated entry: {entry_id}"}


def read_kb_entries_by_category(
    ctx: dict[str, Any], tool_input: dict[str, Any]
) -> dict[str, Any]:
    """Retrieve lightweight entry metadata for dedup candidate scanning.

    Input:
        type (str): KB entry type (e.g., "pitfall").
        category (str, optional): Category filter.
        limit (int, optional): Max entries to return (default 20).

    Returns:
        entries (list): List of dicts with id, title, source_hash,
                        root_cause_preview, updated_at.
    """
    kb_root: Path = ctx["kb_root"]
    kb_type = tool_input.get("type", "")
    category = tool_input.get("category")
    limit = int(tool_input.get("limit", 20))

    entries = list_entries(kb_root, kb_type=kb_type or None, category=category)
    results = []
    for meta in entries[:limit]:
        item: dict[str, Any] = {
            "id": meta.id,
            "title": meta.title,
            "source_hash": "",
            "root_cause_preview": "",
            "updated_at": meta.updated_at,
        }
        file_path = Path(meta.file_path)
        if file_path.exists():
            try:
                post = fm.load(str(file_path))
                item["source_hash"] = str(post.metadata.get("source_hash", ""))
                body = post.content or ""
                # Extract root cause section if present.
                m = re.search(r"## Root Cause\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL)
                if m:
                    item["root_cause_preview"] = m.group(1).strip()[:300]
            except Exception:  # noqa: BLE001
                pass
        results.append(item)

    return {"entries": results}


def compare_root_cause(
    ctx: dict[str, Any], tool_input: dict[str, Any]
) -> dict[str, Any]:
    """Use LLM to semantically compare two entries' root causes.

    Input:
        new_summary (str): Description/root-cause of the new entry.
        existing_id (str): ID of the existing KB entry to compare against.
        existing_summary (str, optional): Pre-fetched root cause text.

    Returns:
        same_root_cause (bool): Whether both describe the same root cause.
        confidence (float): 0.0–1.0.
        reason (str): Brief explanation.
    """
    import json

    provider = ctx.get("provider")
    if provider is None:
        return {"same_root_cause": False, "confidence": 0.0, "reason": "no provider"}

    new_summary = tool_input.get("new_summary", "")
    existing_summary = tool_input.get("existing_summary", "")

    if not existing_summary:
        # Fetch from KB.
        raw = read_entry(ctx["kb_root"], tool_input.get("existing_id", ""))
        if raw:
            m = re.search(r"## Root Cause\s*\n(.*?)(?=\n##|\Z)", raw, re.DOTALL)
            existing_summary = m.group(1).strip()[:500] if m else raw[:500]

    system_prompt = (
        "You are comparing two KB entries to determine if they share the same root cause.\n"
        "Reply with ONLY valid JSON: "
        "{\"same_root_cause\": true/false, \"confidence\": 0.0-1.0, \"reason\": \"...\"}"
    )
    user_prompt = (
        f"Entry A (new):\n{new_summary}\n\n"
        f"Entry B (existing):\n{existing_summary}"
    )

    try:
        text = provider.simple_complete([
            {"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"},
        ]).strip()
        data = json.loads(text)
        return {
            "same_root_cause": bool(data.get("same_root_cause", False)),
            "confidence": float(data.get("confidence", 0.5)),
            "reason": str(data.get("reason", "")),
        }
    except Exception as exc:  # noqa: BLE001
        return {"same_root_cause": False, "confidence": 0.0, "reason": str(exc)}


def verify_content(
    ctx: dict[str, Any], tool_input: dict[str, Any]
) -> dict[str, Any]:
    """Self-verification: check each draft field for source text support.

    Input:
        source_text (str): The original import source text.
        draft_content (str): Full draft Markdown with frontmatter.

    Returns:
        verified_fields (list[str]): Fields with source support.
        unsupported_fields (list[dict]): Fields to clear, each with
                                         {field, reason}.
        confidence (float): Overall verification confidence.
    """
    import json

    provider = ctx.get("provider")
    if provider is None:
        return {"verified_fields": [], "unsupported_fields": [], "confidence": 1.0}

    source_text = tool_input.get("source_text", "")
    draft_content = tool_input.get("draft_content", "")

    # W1-F1: If the agent passed a truncated source, fall back to the original
    # untruncated source stored in ctx by the runner.  This prevents verify_content
    # from falsely clearing fields that exist in the original but were cut off by
    # the prompt-level truncation.
    original_source = ctx.get("source_text", "")
    if original_source and len(original_source) > len(source_text):
        source_text = original_source

    system_prompt = (
        "You are a KB quality verifier. For each key field in the draft entry, "
        "verify it has a corresponding fragment in the source text.\n"
        "Key fields: title, root_cause (## Root Cause section body), "
        "resolution (## Resolution section body).\n"
        "Reply with ONLY valid JSON: {\"verified_fields\": [...], "
        "\"unsupported_fields\": [{\"field\": \"...\", \"reason\": \"...\"}], "
        "\"confidence\": 0.0-1.0}"
    )
    user_prompt = (
        f"SOURCE TEXT:\n{source_text[:6000]}\n\n"
        f"DRAFT ENTRY:\n{draft_content[:3000]}"
    )

    try:
        text = provider.simple_complete([
            {"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"},
        ]).strip()
        data = json.loads(text)
        return {
            "verified_fields": list(data.get("verified_fields", [])),
            "unsupported_fields": list(data.get("unsupported_fields", [])),
            "confidence": float(data.get("confidence", 1.0)),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "verified_fields": [],
            "unsupported_fields": [],
            "confidence": 1.0,
            "error": str(exc),
        }


def evaluate_skill(
    ctx: dict[str, Any], tool_input: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate whether a KB entry's resolution warrants skill creation.

    Input:
        entry_id (str): KB entry ID.
        resolution_text (str): The ## Resolution section body.

    Returns:
        recommendation (str): "RECOMMENDED" | "LINK" | "SKIP".
        skill_name (str): Suggested slug for the skill, or "".
        reason (str): Brief reasoning.
        existing_skill (str | None): Name of existing skill if LINK.
    """
    kb_root: Path = ctx["kb_root"]
    resolution_text = tool_input.get("resolution_text", "")
    entry_id = tool_input.get("entry_id", "")

    # Check if existing skills already cover this entry.
    existing_skill: str | None = None
    if entry_id:
        raw = read_entry(kb_root, entry_id)
        if raw:
            try:
                post = fm.loads(raw)
                skill_refs = list(post.metadata.get("skill_refs") or [])
                if skill_refs:
                    existing_skill = skill_refs[0]
            except Exception:  # noqa: BLE001
                pass

    if existing_skill:
        return {
            "recommendation": "LINK",
            "skill_name": existing_skill,
            "reason": f"Entry already has skill_refs: {existing_skill}",
            "existing_skill": existing_skill,
        }

    # Anthropic Agent Skills standard: any entry with Resolution content warrants a skill.
    if resolution_text.strip():
        skill_name = ""
        if entry_id:
            slug = entry_id.lower().replace("-", "").replace("_", "")[:30]
            skill_name = f"skill-{slug}" if slug else ""
        return {
            "recommendation": "RECOMMENDED",
            "skill_name": skill_name,
            "reason": "Entry has Resolution content — agent instruction skill",
            "existing_skill": None,
        }

    return {
        "recommendation": "SKIP",
        "skill_name": "",
        "reason": "No Resolution content",
        "existing_skill": None,
    }


def create_skill_for_entry(
    ctx: dict[str, Any], tool_input: dict[str, Any]
) -> dict[str, Any]:
    """Create a skill and link it to a KB entry.

    Input:
        name (str): Skill slug (kebab-case).
        entry_id (str): KB entry to link to.
        description (str): One-sentence skill description.
        link_only (bool, optional): If True, only link without creating.
        instructions (str, optional): Agent instruction body for SKILL.md.
            Derived from the entry's ## Resolution section content.

    Returns:
        created (bool): Whether a new skill directory was created.
        linked (bool): Whether the skill was linked to the entry.
        skill_dir (str | None): Skill directory path.
        action (str): Human-readable action.
    """
    kb_root: Path = ctx["kb_root"]
    dry_run: bool = ctx.get("dry_run", False)
    name = tool_input.get("name", "")
    entry_id = tool_input.get("entry_id", "")
    description = tool_input.get("description", "Auto-generated skill")
    link_only = bool(tool_input.get("link_only", False))
    instructions: str = tool_input.get("instructions", "")

    action = f"Would create skill: {name}"
    if dry_run:
        return {"created": False, "linked": False, "skill_dir": None, "dry_run": True, "action": action}

    created = False
    linked = False
    skill_dir_path: Path | None = None

    if not link_only and not skill_exists(kb_root, name):
        try:
            skill_dir_path = create_skill(
                kb_root, name, description,
                instructions=instructions,
            )
            created = True
        except Exception as exc:  # noqa: BLE001
            return {"created": False, "linked": False, "skill_dir": None,
                    "error": str(exc), "action": action}

    if skill_dir_path is None:
        skill_dir_path = get_skill_dir(kb_root, name)

    if entry_id and skill_exists(kb_root, name):
        try:
            link_skill(kb_root, entry_id, name)
            linked = True
        except Exception as exc:  # noqa: BLE001
            pass  # Link failure is non-fatal

    if created and skill_dir_path:
        try:
            mark_agent_created(skill_dir_path)
        except Exception:  # noqa: BLE001
            pass

    action_desc = f"{'Created + linked' if created else 'Linked'} skill: {name}"
    return {
        "created": created,
        "linked": linked,
        "skill_dir": str(skill_dir_path) if skill_dir_path else None,
        "dry_run": False,
        "action": action_desc,
    }


def report_item(
    ctx: dict[str, Any], tool_input: dict[str, Any]
) -> dict[str, Any]:
    """Append an item to the ImportReport in the context.

    Input:
        type (str): "suggestion" | "warning" | "error" | "auto_decision".
        message (str): Human-readable message.

    Returns:
        ok (bool): Always True.
    """
    from holmes.kb.agent.report import ImportReport

    report: ImportReport = ctx.get("report")
    if report is None:
        return {"ok": False, "error": "no report in context"}

    item_type = tool_input.get("type", "suggestion")
    message = tool_input.get("message", "")

    if item_type == "suggestion":
        report.suggestions.append(message)
    elif item_type == "warning":
        report.warnings.append(message)
    elif item_type == "error":
        report.errors.append(message)
    elif item_type == "auto_decision":
        report.auto_decisions.append(message)

    return {"ok": True}


# ---------------------------------------------------------------------------
# Tool dispatch table
# ---------------------------------------------------------------------------

TOOL_HANDLERS: dict[str, Any] = {
    "check_source_hash": check_source_hash,
    "write_kb_entry": write_kb_entry,
    "update_kb_entry": update_kb_entry,
    "read_kb_entries_by_category": read_kb_entries_by_category,
    "compare_root_cause": compare_root_cause,
    "verify_content": verify_content,
    "evaluate_skill": evaluate_skill,
    "create_skill_for_entry": create_skill_for_entry,
    "report_item": report_item,
    **DOC_ACCESS_TOOL_HANDLERS,
}


# ---------------------------------------------------------------------------
# Anthropic tool definition schemas
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "check_source_hash",
        "description": "Check whether a source_hash already exists in the KB for idempotency.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hash": {"type": "string", "description": "16-char source hash"},
            },
            "required": ["hash"],
        },
    },
    {
        "name": "write_kb_entry",
        "description": "Write a structured KB entry to the pending area.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Full Markdown with YAML frontmatter"},
                "source_hash": {"type": "string", "description": "16-char source hash"},
                "confidence": {"type": "number", "description": "Classification confidence 0–1"},
                "title": {"type": "string", "description": "Entry title for logging"},
                "force": {"type": "boolean", "description": "Skip duplicate pending check"},
            },
            "required": ["content", "source_hash", "confidence"],
        },
    },
    {
        "name": "update_kb_entry",
        "description": "Merge-update an existing KB entry with new fields or body content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string", "description": "ID of entry to update"},
                "patch": {"type": "object", "description": "Fields/body to merge"},
            },
            "required": ["entry_id", "patch"],
        },
    },
    {
        "name": "read_kb_entries_by_category",
        "description": "Retrieve existing KB entries for semantic deduplication candidate scanning.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "KB entry type"},
                "category": {"type": "string", "description": "Category filter"},
                "limit": {"type": "integer", "description": "Max entries (default 20)"},
            },
            "required": ["type"],
        },
    },
    {
        "name": "compare_root_cause",
        "description": "Use LLM to semantically compare two entries' root causes for deduplication.",
        "input_schema": {
            "type": "object",
            "properties": {
                "new_summary": {"type": "string", "description": "New entry root cause"},
                "existing_id": {"type": "string", "description": "Existing entry ID"},
                "existing_summary": {"type": "string", "description": "Pre-fetched root cause text"},
            },
            "required": ["new_summary", "existing_id"],
        },
    },
    {
        "name": "verify_content",
        "description": "Self-verification: check each draft field for source text support.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_text": {"type": "string", "description": "Original source text"},
                "draft_content": {"type": "string", "description": "Draft Markdown with frontmatter"},
            },
            "required": ["source_text", "draft_content"],
        },
    },
    {
        "name": "evaluate_skill",
        "description": "Evaluate whether an entry's resolution warrants skill creation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string", "description": "KB entry ID"},
                "resolution_text": {"type": "string", "description": "Resolution section body"},
            },
            "required": ["resolution_text"],
        },
    },
    {
        "name": "create_skill_for_entry",
        "description": "Create a skill and link it to a KB entry.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill slug (kebab-case)"},
                "entry_id": {"type": "string", "description": "KB entry to link"},
                "description": {"type": "string", "description": "One-sentence skill description"},
                "link_only": {"type": "boolean", "description": "Only link, do not create"},
                "instructions": {
                    "type": "string",
                    "description": (
                        "Agent instruction body for the SKILL.md. "
                        "Derive from the entry's ## Resolution section. "
                        "Use imperative markdown — explain what to do and why. "
                        "Leave empty to use the default three-section placeholder."
                    ),
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "report_item",
        "description": "Append a suggestion, warning, error, or auto_decision to the ImportReport.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["suggestion", "warning", "error", "auto_decision"],
                },
                "message": {"type": "string", "description": "Human-readable message"},
            },
            "required": ["type", "message"],
        },
    },
    *DOC_ACCESS_TOOL_DEFINITIONS,
]
