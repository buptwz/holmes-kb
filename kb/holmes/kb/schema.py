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


@dataclass
class DecisionMapEntry:
    """One row in the decision_map: symptom → branch mapping."""

    symptom: str     # observable condition that triggers this branch
    branch: str      # branch label (matches ### heading in Resolution)


def parse_decision_map(raw: list | None) -> list[DecisionMapEntry]:
    """Parse decision_map from frontmatter YAML (list of dicts) into typed objects."""
    if not raw or not isinstance(raw, list):
        return []
    entries: list[DecisionMapEntry] = []
    for item in raw:
        if isinstance(item, dict):
            symptom = str(item.get("symptom", "")).strip()
            branch = str(item.get("branch", "")).strip()
            if symptom and branch:
                entries.append(DecisionMapEntry(symptom=symptom, branch=branch))
    return entries


def serialize_decision_map(entries: list[DecisionMapEntry]) -> list[dict[str, str]]:
    """Serialize DecisionMapEntry list back to YAML-friendly dicts."""
    return [{"symptom": e.symptom, "branch": e.branch} for e in entries]

# KB management workflow status.
#   pending    — awaiting review after import (lives in contributions/pending/)
#   active     — current and valid; participates in agent retrieval (default for legacy entries)
#   deprecated — superseded by a newer version; excluded from retrieval
KBStatus = Literal["pending", "active", "deprecated"]

# Optional frontmatter fields:
#   kb_status        : KBStatus  — defaults to "active" when field is absent
#   source_file      : str       — basename of the source document
#   source_hash      : str       — sha256 prefix of source document content
#   brief            : str       — one-sentence summary for kb_browse preview
#   import_trace_id  : str       — source filename stem, used for log correlation


class EvidenceRecord(TypedDict, total=False):
    """A single session reference/validation record in an entry's evidence array."""

    session_id: str        # Required: unique session identifier
    contributor: str       # Required: user/agent identifier
    date: str              # Required: ISO8601 timestamp
    outcome: str           # Required: "solved" or "not_solved" — drives maturity promotion
    project: str           # Optional: project context
    context: str           # Optional: how the entry was used
    notes: str             # Optional: free-text feedback

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
# Category validation: free-form (model-decided). Only enforce non-empty + slug format.
# Supports hierarchy via `/` separator (e.g. "hardware/gpu", "network/switch").
_CATEGORY_RE = re.compile(r"^[a-z0-9][a-z0-9_/-]*[a-z0-9]$|^[a-z0-9]$")

TITLE_MAX_LENGTH = 100


@dataclass
class ValidationResult:
    """Result of a schema validation check."""

    valid: bool
    errors: list[str] = field(default_factory=list)


def validate_entry(
    content: str,
    existing_ids: frozenset[str] | None = None,
    required_fields: frozenset[str] | None = None,
) -> ValidationResult:
    """Validate a KB entry's schema (frontmatter fields + required body sections).

    Args:
        content: Raw Markdown string with YAML frontmatter.
        existing_ids: Set of IDs already in the official KB (for uniqueness check).
                      Pass None to skip the uniqueness check.
        required_fields: Override set of required frontmatter fields.
                         Defaults to REQUIRED_FRONTMATTER_FIELDS when None.
                         Use a smaller set for draft entries where some fields
                         (e.g. id, created_at, updated_at) are auto-populated later.

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
    fields_to_check = required_fields if required_fields is not None else REQUIRED_FRONTMATTER_FIELDS
    for required_field in sorted(fields_to_check):
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

    # Validate category format (free-form slug, supports hierarchy like "hardware/gpu").
    category = str(meta.get("category", ""))
    if category and not _CATEGORY_RE.match(category):
        errors.append(
            f"Invalid category format {category!r}. "
            f"Must be lowercase slug (a-z0-9, hyphens, underscores, / for hierarchy)."
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

    # Validate id uniqueness against existing official entries.
    if existing_ids is not None:
        entry_id = str(meta.get("id", "")).strip()
        if entry_id and entry_id in existing_ids:
            errors.append(f"ID {entry_id!r} already exists in the knowledge base")

    return ValidationResult(valid=len(errors) == 0, errors=errors)
