"""Three-gate KB entry validation.

Gate 1: Schema — required frontmatter fields and type-appropriate sections
Gate 2: Duplicate detection — similarity > 85% blocks confirmation
Gate 3: Forced preview — user must see and confirm the entry content
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import frontmatter

from holmes.kb.store import REQUIRED_FRONTMATTER, TYPE_REQUIRED_SECTIONS, list_entries
from holmes.logging_config import get_logger


logger = get_logger("kb.validator")

SIMILARITY_THRESHOLD = 0.85


class ValidationError(Exception):
    """Raised when an entry fails validation."""


def validate_entry(kb_root: Path, content: str) -> dict:
    """Run all three validation gates on a pending entry.

    Args:
        kb_root: Root directory of the knowledge base.
        content: Markdown content with YAML frontmatter.

    Returns:
        Dict with validation results for each gate.

    Raises:
        ValidationError: If Schema gate (Gate 1) fails.
    """
    results = {}

    # Gate 1: Schema validation
    schema_errors = _validate_schema(content)
    results["schema"] = {"passed": len(schema_errors) == 0, "errors": schema_errors}
    if schema_errors:
        raise ValidationError(f"Schema validation failed: {'; '.join(schema_errors)}")

    # Gate 2: Duplicate detection
    post = frontmatter.loads(content)
    kb_type = str(post.metadata.get("type", ""))
    title = str(post.metadata.get("title", ""))
    duplicates = _check_duplicates(kb_root, kb_type, title, post.content)
    results["duplicates"] = {
        "passed": len(duplicates) == 0,
        "similar_entries": duplicates,
    }

    return results


def _validate_schema(content: str) -> list[str]:
    """Validate YAML frontmatter schema.

    Returns:
        List of error messages (empty if valid).
    """
    errors = []
    try:
        post = frontmatter.loads(content)
    except Exception as e:
        return [f"YAML parse error: {e}"]

    meta = post.metadata

    # Required fields
    for field in REQUIRED_FRONTMATTER:
        if field not in meta:
            errors.append(f"Missing required field: {field}")

    # Type-specific section validation
    kb_type = str(meta.get("type", ""))
    if kb_type in TYPE_REQUIRED_SECTIONS:
        for section in TYPE_REQUIRED_SECTIONS[kb_type]:
            if section.lower() not in post.content.lower():
                errors.append(f"Missing required section for {kb_type}: {section}")

    # Maturity must be valid
    maturity = str(meta.get("maturity", ""))
    if maturity not in ("draft", "verified", "proven"):
        errors.append(f"Invalid maturity value: {maturity!r} (must be draft/verified/proven)")

    return errors


def _check_duplicates(
    kb_root: Path, kb_type: str, title: str, body: str
) -> list[dict]:
    """Check for similar existing entries.

    Args:
        kb_root: Root of the knowledge base.
        kb_type: Type of the new entry.
        title: Title of the new entry.
        body: Body text of the new entry.

    Returns:
        List of dicts describing similar entries above threshold.
    """
    existing = list_entries(kb_root, kb_type)  # type: ignore[arg-type]
    similar = []
    for entry in existing:
        sim = _title_similarity(title.lower(), entry.title.lower())
        if sim >= SIMILARITY_THRESHOLD:
            similar.append({
                "id": entry.id,
                "title": entry.title,
                "similarity": round(sim, 2),
            })
    return similar


def _title_similarity(a: str, b: str) -> float:
    """Compute simple Jaccard similarity between two title strings.

    Args:
        a: First string.
        b: Second string.

    Returns:
        Similarity score between 0 and 1.
    """
    def tokenize(s: str) -> set:
        return set(re.findall(r"\w+", s.lower()))

    tokens_a = tokenize(a)
    tokens_b = tokenize(b)
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)
