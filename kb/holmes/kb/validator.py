"""KB entry validation — 3 gates used by `holmes confirm`.

Gate 1: Schema — required frontmatter fields and type-specific body sections.
Gate 2: Duplicate detection — Jaccard title similarity > 85% blocks confirmation.
Gate 3: (Interactive) Forced preview — handled by CLI, not this module.

Also provides generate_id() for permanent ID assignment.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import frontmatter

from holmes.kb.schema import ValidationResult
from holmes.kb.schema import validate_entry as schema_validate
from holmes.kb.store import list_entries

_SIMILARITY_THRESHOLD = 0.85

TYPE_PREFIXES = {
    "pitfall": "PT",
    "model": "MD",
    "guideline": "GL",
    "process": "PR",
    "decision": "DC",
}
PITFALL_CAT_PREFIXES = {
    "network": "NET",
    "system": "SYS",
    "application": "APP",
    "database": "DB",
}


def _derive_cat_prefix(category: str) -> str:
    """Derive a category prefix programmatically for open-world categories.

    PITFALL_CAT_PREFIXES is a closed map, but real categories are open-ended
    (``serdes/pll``, ``bmc-firmware-upgrade``...) — everything unmapped used
    to collapse to ``GEN`` (spec 043, T048). Rules:

    - multi-segment slug: first letter of each segment, e.g.
      ``serdes/pll`` → ``SP``, ``bmc-firmware-upgrade`` → ``BFU``
    - single segment: first 2-3 consonant-heavy letters, e.g. ``memory`` → ``MEM``
    - capped at 4 chars; falls back to ``GEN`` only when nothing usable
      remains or the derived prefix collides with a mapped prefix of a
      DIFFERENT known category
    """
    segments = [s for s in re.split(r"[/\-_]+", category.lower()) if s]
    if not segments:
        return "GEN"
    if len(segments) >= 2:
        prefix = "".join(s[0] for s in segments if s[0].isalpha())[:4].upper()
    else:
        word = segments[0]
        prefix = word[:3].upper() if len(word) >= 3 else word.upper()
    if len(prefix) < 2:
        return "GEN"
    # Collision with a mapped prefix belonging to a different category.
    if prefix in PITFALL_CAT_PREFIXES.values():
        for known_cat, known_prefix in PITFALL_CAT_PREFIXES.items():
            if known_prefix == prefix and known_cat != category.lower():
                return "GEN"
    return prefix


@dataclass
class DuplicateResult:
    """Result of the duplicate detection gate."""

    blocked: bool
    similar_entries: list[dict] = field(default_factory=list)


def validate_schema(content: str, kb_root: Optional[Path] = None) -> ValidationResult:
    """Run Gate 1 — schema validation on raw Markdown content.

    Args:
        content: Raw Markdown string with YAML frontmatter.
        kb_root: If provided, also checks that the entry ID does not already
                 exist in the official KB (uniqueness gate).

    Returns:
        ValidationResult.
    """
    existing_ids: Optional[frozenset[str]] = None
    if kb_root is not None:
        existing_ids = frozenset(e.id for e in list_entries(kb_root))
    return schema_validate(content, existing_ids=existing_ids)


def check_duplicate(
    kb_root: Path,
    content: str,
    threshold: float = _SIMILARITY_THRESHOLD,
) -> DuplicateResult:
    """Run Gate 2 — Jaccard similarity duplicate detection.

    Args:
        kb_root: Root directory of the knowledge base.
        content: Raw Markdown of the pending entry.
        threshold: Similarity threshold (default 0.85).

    Returns:
        DuplicateResult with similar_entries list.
    """
    try:
        post = frontmatter.loads(content)
    except Exception:  # noqa: BLE001
        return DuplicateResult(blocked=False)

    kb_type = str(post.metadata.get("type", ""))
    title = str(post.metadata.get("title", ""))

    existing = list_entries(kb_root, kb_type=kb_type if kb_type else None)
    similar: list[dict] = []
    for entry in existing:
        sim = _jaccard_similarity(title, entry.title)
        if sim >= threshold:
            similar.append({
                "id": entry.id,
                "title": entry.title,
                "similarity": round(sim, 3),
            })

    return DuplicateResult(blocked=len(similar) > 0, similar_entries=similar)


_MAX_ID_RETRIES = 5


def generate_id(
    kb_root: Path,
    kb_type: str,
    category: Optional[str] = None,
) -> str:
    """Generate a new permanent ID with a random hex suffix.

    Random suffixes avoid ID collisions when multiple local copies approve
    entries concurrently (spec 043, D2).

    Format: {TYPE_PREFIX}-{CAT_ABBR}-{6 lowercase hex}  e.g. PT-DB-a3f8c2

    The generated ID is checked against all existing KB entries; on a
    collision the generation is retried up to 5 times.

    Args:
        kb_root: Root directory of the knowledge base.
        kb_type: Entry type (pitfall, model, guideline, process, decision).
        category: Subcategory (relevant for pitfall type).

    Returns:
        New ID string.

    Raises:
        RuntimeError: If a unique ID could not be generated within
            _MAX_ID_RETRIES attempts.
    """
    type_prefix = TYPE_PREFIXES.get(kb_type, "XX")
    cat_prefix = "GEN"
    if kb_type == "pitfall" and category:
        cat_prefix = PITFALL_CAT_PREFIXES.get(category) or _derive_cat_prefix(category)

    existing_ids = {e.id for e in list_entries(kb_root)}
    for _ in range(_MAX_ID_RETRIES):
        new_id = f"{type_prefix}-{cat_prefix}-{secrets.token_hex(3)}"
        if new_id not in existing_ids:
            return new_id

    raise RuntimeError(
        f"generate_id: could not generate a unique ID after {_MAX_ID_RETRIES} attempts"
    )


def jaccard_similarity(a: str, b: str) -> float:
    """Compute Jaccard word-set similarity between two strings.

    Args:
        a: First string.
        b: Second string.

    Returns:
        Score between 0.0 and 1.0.
    """
    def tokenize(s: str) -> set:
        return set(re.findall(r"\w+", s.lower()))

    tokens_a = tokenize(a)
    tokens_b = tokenize(b)
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


# Backward-compatible alias.
_jaccard_similarity = jaccard_similarity
