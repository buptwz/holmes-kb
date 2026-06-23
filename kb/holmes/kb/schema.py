"""Knowledge base entry schema — required fields and section rules.

Defines the validation contract for all five KB entry types:
  pitfall, model, guideline, process, decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, TypedDict

import frontmatter

KBType = Literal["pitfall", "model", "guideline", "process", "decision"]
Maturity = Literal["draft", "verified", "proven", "deprecated"]

# KB management workflow status (M1: 037-dag-import-pipeline).
# Distinct from `decay_status` (knowledge quality lifecycle) — the two are orthogonal.
#   pending    — awaiting review after import (lives in contributions/pending/)
#   active     — current and valid; participates in agent retrieval (default for legacy entries)
#   deprecated — superseded by a newer version; excluded from retrieval
KBStatus = Literal["pending", "active", "deprecated"]

# Optional frontmatter fields added in M1 (all backwards-compatible):
#   kb_status        : KBStatus  — defaults to "active" when field is absent (legacy entries)
#   source_file      : str       — path relative to KB root of the source document
#   source_hash      : str       — sha256 prefix of source document content
#   description      : str       — 1-2 sentence human-readable summary of the entry
#   import_trace_id  : str       — source filename stem, used for log correlation
#   pitfall_structure: str       — "tree" (new DAG routing) | "flat" (legacy self-contained)
#   child_entry_ids  : list[str] — ordered list of child node IDs (tree navigation)
#   parent_id        : str       — parent entry ID (process sub-entries only)


class EvidenceRecord(TypedDict, total=False):
    """A single session reference/validation record in an entry's evidence array."""

    session_id: str        # Required: unique session identifier
    contributor: str       # Required: user/agent identifier
    date: str              # Required: ISO8601 timestamp
    project: str           # Optional: project context
    context: str           # Optional: how the entry was used

# Fields required in every entry's YAML frontmatter.
REQUIRED_FRONTMATTER_FIELDS: frozenset[str] = frozenset(
    {"id", "type", "title", "maturity", "category", "tags", "created_at", "updated_at"}
)

# Markdown section headings that must be present in each type's body.
TYPE_REQUIRED_SECTIONS: dict[str, list[str]] = {
    "pitfall": ["## Symptoms", "## Root Cause", "## Resolution"],
    "model": ["## Overview"],
    "guideline": ["## Guideline"],
    "process": ["## Steps"],
    "decision": ["## Context", "## Decision"],
}

VALID_TYPES: frozenset[str] = frozenset(TYPE_REQUIRED_SECTIONS.keys())
VALID_MATURITY: frozenset[str] = frozenset({"draft", "verified", "proven", "deprecated"})
VALID_PITFALL_CATEGORIES: frozenset[str] = frozenset(
    {
        "network", "system", "application", "database",
        "kubernetes", "messaging", "cache", "monitoring",  # expanded in 018
    }
)

TITLE_MAX_LENGTH = 100


@dataclass
class ValidationResult:
    """Result of a schema validation check."""

    valid: bool
    errors: list[str] = field(default_factory=list)


def validate_entry(content: str, existing_ids: frozenset[str] | None = None) -> ValidationResult:
    """Validate a KB entry's schema (frontmatter fields + required body sections).

    Args:
        content: Raw Markdown string with YAML frontmatter.
        existing_ids: Set of IDs already in the official KB (for uniqueness check).
                      Pass None to skip the uniqueness check.

    Returns:
        ValidationResult with valid=True and empty errors list on success.
    """
    errors: list[str] = []

    try:
        post = frontmatter.loads(content)
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(valid=False, errors=[f"YAML parse error: {exc}"])

    meta = post.metadata

    # Check required frontmatter fields.
    for required_field in sorted(REQUIRED_FRONTMATTER_FIELDS):
        if required_field not in meta:
            errors.append(f"Missing required frontmatter field: {required_field!r}")

    # Validate type value.
    kb_type = str(meta.get("type", ""))
    if kb_type and kb_type not in VALID_TYPES:
        errors.append(f"Invalid type {kb_type!r}. Must be one of: {sorted(VALID_TYPES)}")

    # Validate maturity value.
    maturity = str(meta.get("maturity", ""))
    if maturity and maturity not in VALID_MATURITY:
        errors.append(f"Invalid maturity {maturity!r}. Must be one of: {sorted(VALID_MATURITY)}")

    # Validate category for pitfall entries.
    if kb_type == "pitfall":
        category = str(meta.get("category", ""))
        if category and category not in VALID_PITFALL_CATEGORIES:
            errors.append(
                f"Invalid pitfall category {category!r}. "
                f"Must be one of: {sorted(VALID_PITFALL_CATEGORIES)}"
            )

    # Check required body sections for the entry type.
    if kb_type in TYPE_REQUIRED_SECTIONS:
        body_lower = post.content.lower()
        for section in TYPE_REQUIRED_SECTIONS[kb_type]:
            if section.lower() not in body_lower:
                errors.append(
                    f"Missing required section for {kb_type!r}: {section}"
                )

    # Validate title length.
    title = str(meta.get("title", ""))
    if title and len(title) > TITLE_MAX_LENGTH:
        errors.append(
            f"Title too long: {len(title)} characters (max {TITLE_MAX_LENGTH})"
        )

    # Validate created_at <= updated_at.
    created_str = str(meta.get("created_at", "")).strip()
    updated_str = str(meta.get("updated_at", "")).strip()
    if created_str and updated_str:
        try:
            created_dt = datetime.fromisoformat(created_str)
            updated_dt = datetime.fromisoformat(updated_str)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=timezone.utc)
            if created_dt > updated_dt:
                errors.append(
                    f"created_at ({created_str[:10]}) must not be later than "
                    f"updated_at ({updated_str[:10]})"
                )
        except ValueError:
            pass  # invalid dates already caught by required-field checks

    # Validate optional skill_refs field.
    skill_refs = meta.get("skill_refs")
    if skill_refs is not None:
        if not isinstance(skill_refs, list):
            errors.append("'skill_refs' must be a list of skill name strings")
        else:
            skill_name_re = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]{1,2}$")
            for ref in skill_refs:
                if not isinstance(ref, str) or not skill_name_re.match(str(ref)):
                    errors.append(
                        f"Invalid skill_refs entry {ref!r}: must match [a-z0-9-]"
                    )

    # Validate id uniqueness against existing official entries.
    if existing_ids is not None:
        entry_id = str(meta.get("id", "")).strip()
        if entry_id and entry_id in existing_ids:
            errors.append(f"ID {entry_id!r} already exists in the knowledge base")

    return ValidationResult(valid=len(errors) == 0, errors=errors)
