"""KB entry validation — 3 gates used by `holmes kb confirm`.

Gate 1: Schema — required frontmatter fields and type-specific body sections.
Gate 2: Duplicate detection — Jaccard title similarity > 85% blocks confirmation.
Gate 3: (Interactive) Forced preview — handled by CLI, not this module.

Also provides generate_id() for permanent ID assignment.
"""

from __future__ import annotations

import re
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


def generate_id(
    kb_root: Path,
    kb_type: str,
    category: Optional[str] = None,
) -> str:
    """Generate the next permanent sequential ID for an entry.

    Scans existing entries in the relevant directory to find the highest
    existing sequence number and increments by 1.

    Format: {TYPE_PREFIX}-{CAT_ABBR}-{NNN}  e.g. PT-DB-001

    Args:
        kb_root: Root directory of the knowledge base.
        kb_type: Entry type (pitfall, model, guideline, process, decision).
        category: Subcategory (relevant for pitfall type).

    Returns:
        New ID string.
    """
    type_prefix = TYPE_PREFIXES.get(kb_type, "XX")
    cat_prefix = "GEN"
    if kb_type == "pitfall" and category:
        cat_prefix = PITFALL_CAT_PREFIXES.get(category, "GEN")

    type_dir = kb_root / kb_type
    max_num = 0
    if type_dir.exists():
        for md_file in type_dir.rglob("*.md"):
            if md_file.name.startswith("_"):
                continue
            try:
                post = frontmatter.load(str(md_file))
                entry_id = str(post.metadata.get("id", ""))
                parts = entry_id.split("-")
                if (
                    len(parts) >= 3
                    and parts[0] == type_prefix
                    and parts[1] == cat_prefix
                ):
                    num = int(parts[2])
                    max_num = max(max_num, num)
            except (ValueError, KeyError, Exception):  # noqa: BLE001
                pass

    return f"{type_prefix}-{cat_prefix}-{max_num + 1:03d}"


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
