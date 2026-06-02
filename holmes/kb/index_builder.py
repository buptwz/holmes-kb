"""Knowledge base index builder.

Rebuilds index.json (machine-readable) and {type}/_index.md (human-readable)
from the current state of the KB directory tree.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from holmes.kb.store import KBType, KnowledgeEntry, list_entries
from holmes.logging_config import get_logger


logger = get_logger("kb.index_builder")

KB_TYPES: list[KBType] = ["pitfall", "model", "guideline", "process", "decision"]


def rebuild_index(kb_root: Path) -> dict:
    """Rebuild index.json and all {type}/_index.md files.

    Args:
        kb_root: Root directory of the knowledge base.

    Returns:
        The rebuilt index as a dict.
    """
    all_entries: list[KnowledgeEntry] = []
    category_counts: dict[str, dict] = {}

    for kb_type in KB_TYPES:
        entries = list_entries(kb_root, kb_type)
        all_entries.extend(entries)
        subcategories: list[str] = []
        type_dir = kb_root / kb_type
        if type_dir.is_dir():
            subcategories = [
                d.name
                for d in sorted(type_dir.iterdir())
                if d.is_dir() and not d.name.startswith(".")
            ]
        category_counts[kb_type] = {
            "count": len(entries),
            "subcategories": subcategories,
        }
        _rebuild_type_index(kb_root, kb_type, entries)

    index = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_entries": len(all_entries),
        "categories": category_counts,
        "entries": [
            {
                "id": e.id,
                "type": e.type,
                "title": e.title,
                "maturity": e.maturity,
                "category": e.category,
                "tags": e.tags,
                "updated_at": e.updated_at,
            }
            for e in all_entries
        ],
    }

    index_path = kb_root / "index.json"
    with index_path.open("w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    logger.info("Rebuilt index.json with %d entries", len(all_entries))

    return index


def _rebuild_type_index(kb_root: Path, kb_type: KBType, entries: list[KnowledgeEntry]) -> None:
    """Rebuild the _index.md for a specific KB type.

    Args:
        kb_root: Root directory of the knowledge base.
        kb_type: The KB type to rebuild.
        entries: All entries of this type.
    """
    type_dir = kb_root / kb_type
    type_dir.mkdir(parents=True, exist_ok=True)
    index_path = type_dir / "_index.md"

    rows = []
    for e in sorted(entries, key=lambda x: x.id):
        cat = e.category or ""
        tags = ", ".join(e.tags) if e.tags else ""
        rows.append(f"| {e.id} | {e.title} | {cat} | {e.maturity} | {tags} |")

    rows_str = "\n".join(rows) if rows else "| — | — | — | — | — |"
    content = (
        f"---\ntype: {kb_type}\n---\n"
        f"# {kb_type.capitalize()} Index\n\n"
        f"| ID | Title | Category | Maturity | Tags |\n"
        f"|----|-------|----------|----------|------|\n"
        f"{rows_str}\n"
    )
    index_path.write_text(content, encoding="utf-8")
    logger.debug("Rebuilt _index.md for type=%s (%d entries)", kb_type, len(entries))
