"""Knowledge base file operations and data model.

KnowledgeEntry: parsed from Markdown files with YAML frontmatter.
Supports 5 types: pitfall, model, guideline, process, decision.
"""

from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# Evidence sidecar support (P0-1/P0-2)
# ---------------------------------------------------------------------------

# Directory for per-session evidence JSON files (git-merge-friendly).
EVIDENCE_SIDECAR_DIR = "contributions/evidence"

# Maturity rank for promotion decisions (never downgrade via evidence alone).
_MATURITY_ORDER: dict[str, int] = {"draft": 0, "verified": 1, "proven": 2}


def load_evidence(
    kb_root: Path,
    entry_id: str,
    frontmatter_evidence: Optional[list] = None,
) -> list[dict]:
    """Load all evidence records for an entry from sidecar files and frontmatter.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: Target entry ID.
        frontmatter_evidence: Existing evidence from the entry frontmatter (optional).

    Returns:
        Combined, deduplicated list of evidence record dicts.
    """
    combined: dict[str, dict] = {}
    for record in (frontmatter_evidence or []):
        if isinstance(record, dict):
            sid = str(record.get("session_id", ""))
            combined[sid] = record

    sidecar_dir = kb_root / EVIDENCE_SIDECAR_DIR / entry_id
    if sidecar_dir.is_dir():
        for json_file in sorted(sidecar_dir.glob("*.json")):
            try:
                record = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(record, dict):
                    sid = str(record.get("session_id", ""))
                    combined[sid] = record
            except Exception:  # noqa: BLE001
                pass

    return list(combined.values())


def derive_maturity(evidence: list[dict]) -> str:
    """Compute maturity from the evidence array.

    Rules:
    - 0 records → 'draft'
    - ≥1 record → 'verified'
    - ≥2 distinct session_ids AND ≥2 distinct contributors → 'proven'

    Args:
        evidence: List of evidence record dicts.

    Returns:
        Derived maturity string.
    """
    if not evidence:
        return "draft"
    sessions = {str(e.get("session_id", "")) for e in evidence if e.get("session_id")}
    contributors = {str(e.get("contributor", "")) for e in evidence if e.get("contributor")}
    if len(sessions) >= 2 and len(contributors) >= 2:
        return "proven"
    return "verified"


def get_last_evidence_date(evidence: list[dict]) -> Optional[str]:
    """Return the most recent date string from an evidence array, or None.

    Args:
        evidence: List of evidence record dicts.

    Returns:
        ISO8601 date string of the most recent record, or None.
    """
    dates = [str(e["date"]) for e in evidence if e.get("date")]
    if not dates:
        return None
    return max(dates)


def append_evidence(kb_root: Path, entry_id: str, evidence_record: dict) -> bool:
    """Append one evidence record to an entry's evidence store.

    Writes the record as a per-session JSON sidecar file.
    Deduplicates by session_id.  After appending, auto-promotes maturity.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: Target entry ID.
        evidence_record: Dict with at least session_id, contributor, date.

    Returns:
        True if the record was appended, False if it was a duplicate.
    """
    entry = get_entry(kb_root, entry_id)
    if entry is None or entry.source_path is None:
        return False

    entry_path = entry.source_path
    try:
        post = frontmatter.load(str(entry_path))
    except Exception:  # noqa: BLE001
        return False

    session_id = str(evidence_record.get("session_id", ""))

    all_existing = load_evidence(kb_root, entry_id, post.metadata.get("evidence"))

    if session_id and any(
        str(e.get("session_id", "")) == session_id for e in all_existing
    ):
        return False

    sidecar_dir = kb_root / EVIDENCE_SIDECAR_DIR / entry_id
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    safe_sid = session_id.replace("/", "-").replace("\\", "-") if session_id else "unknown"
    sidecar_file = sidecar_dir / f"{safe_sid}.json"
    sidecar_file.write_text(json.dumps(evidence_record, ensure_ascii=False), encoding="utf-8")

    # P0-2: auto-update maturity (never downgrade via evidence).
    new_all_evidence = all_existing + [evidence_record]
    current_maturity = str(post.metadata.get("maturity", "draft"))
    new_maturity = derive_maturity(new_all_evidence)
    current_rank = _MATURITY_ORDER.get(current_maturity, 0)
    new_rank = _MATURITY_ORDER.get(new_maturity, 0)
    if new_rank > current_rank:
        post.metadata["maturity"] = new_maturity
        entry_path.write_text(frontmatter.dumps(post), encoding="utf-8")

    logger.info("Evidence appended: entry=%s session=%s", entry_id, session_id)
    return True


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
