"""Knowledge base file operations and data model.

KnowledgeEntry: parsed from Markdown files with YAML frontmatter.
Supports 5 types: pitfall, model, guideline, process, decision.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Optional

import frontmatter

from holmes.logging_config import get_logger


logger = get_logger("kb.store")

KBType = Literal["pitfall", "model", "guideline", "process", "decision"]
Maturity = Literal["draft", "verified", "proven"]

REQUIRED_FRONTMATTER = {"id", "type", "title", "maturity"}
TYPE_REQUIRED_SECTIONS: dict[str, list[str]] = {
    "pitfall": ["## Symptoms", "## Root Cause", "## Resolution"],
    "model": ["## Definition"],
    "guideline": ["## Rule"],
    "process": ["## Steps"],
    "decision": ["## Context", "## Decision"],
}


class KnowledgeEntry:
    """A single knowledge base entry parsed from a Markdown file."""

    def __init__(
        self,
        id: str,
        type: KBType,
        title: str,
        maturity: Maturity,
        category: Optional[str],
        tags: list[str],
        created_at: str,
        updated_at: str,
        body: str,
        source_path: Optional[Path] = None,
    ) -> None:
        self.id = id
        self.type = type
        self.title = title
        self.maturity = maturity
        self.category = category
        self.tags = tags
        self.created_at = created_at
        self.updated_at = updated_at
        self.body = body
        self.source_path = source_path

    @classmethod
    def from_file(cls, path: Path) -> "KnowledgeEntry":
        """Parse a KnowledgeEntry from a Markdown file with YAML frontmatter.

        Args:
            path: Path to the .md file.

        Returns:
            Parsed KnowledgeEntry.

        Raises:
            ValueError: If required frontmatter fields are missing.
        """
        post = frontmatter.load(str(path))
        meta = post.metadata
        missing = REQUIRED_FRONTMATTER - set(meta.keys())
        if missing:
            raise ValueError(f"Missing required frontmatter fields in {path}: {missing}")

        return cls(
            id=str(meta["id"]),
            type=meta["type"],
            title=str(meta["title"]),
            maturity=meta.get("maturity", "draft"),
            category=meta.get("category"),
            tags=meta.get("tags", []),
            created_at=str(meta.get("created_at", "")),
            updated_at=str(meta.get("updated_at", "")),
            body=post.content,
            source_path=path,
        )

    def to_frontmatter_str(self) -> str:
        """Serialize entry to Markdown string with YAML frontmatter."""
        post = frontmatter.Post(
            self.body,
            id=self.id,
            type=self.type,
            title=self.title,
            maturity=self.maturity,
            category=self.category,
            tags=self.tags,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
        return frontmatter.dumps(post)

    def to_dict(self) -> dict:
        """Convert entry to a plain dictionary."""
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "maturity": self.maturity,
            "category": self.category,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "body": self.body,
        }


def list_entries(kb_root: Path, kb_type: Optional[KBType] = None) -> list[KnowledgeEntry]:
    """List all knowledge entries in the KB, optionally filtered by type.

    Args:
        kb_root: Root directory of the knowledge base.
        kb_type: Optional type filter.

    Returns:
        List of parsed KnowledgeEntry objects.
    """
    entries: list[KnowledgeEntry] = []
    search_dirs = [kb_root / kb_type] if kb_type else [
        kb_root / t for t in ("pitfall", "model", "guideline", "process", "decision")
    ]
    for d in search_dirs:
        if not d.is_dir():
            continue
        for md_file in sorted(d.rglob("*.md")):
            if md_file.name.startswith("_"):
                continue
            try:
                entry = KnowledgeEntry.from_file(md_file)
                entries.append(entry)
            except (ValueError, KeyError) as e:
                logger.warning("Skipping %s: %s", md_file, e)
    return entries


def get_entry(kb_root: Path, entry_id: str) -> Optional[KnowledgeEntry]:
    """Find a single entry by ID.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID to find.

    Returns:
        KnowledgeEntry if found, None otherwise.
    """
    for entry in list_entries(kb_root):
        if entry.id == entry_id:
            return entry
    return None


def write_entry(kb_root: Path, entry: KnowledgeEntry) -> Path:
    """Write an entry to the knowledge base.

    Determines path from type and category. Creates directories as needed.

    Args:
        kb_root: Root directory of the knowledge base.
        entry: The entry to write.

    Returns:
        Path where the entry was written.
    """
    if entry.category:
        target_dir = kb_root / entry.type / entry.category
    else:
        target_dir = kb_root / entry.type
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "-", entry.id)
    path = target_dir / f"{safe_id}.md"
    path.write_text(entry.to_frontmatter_str(), encoding="utf-8")
    logger.info("Wrote entry %s to %s", entry.id, path)
    return path
