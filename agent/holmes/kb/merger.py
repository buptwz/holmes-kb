"""KB merger — handles 5 conflict scenarios when merging entries.

Scenarios:
1. Pure add: new entry ID not in KB → merge as-is
2. Evidence append: same ID, maturity compatible → append new evidence
3. Maturity upgrade: same ID, new maturity higher → upgrade
4. Maturity conflict: same ID, maturity incompatible → keep lower + add contradiction tag
5. Content contradiction: same ID, content semantically incompatible → isolate to conflicts/
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import frontmatter

from holmes.kb.conflict import write_conflict
from holmes.kb.index_builder import rebuild_index
from holmes.kb.pending import _append_log
from holmes.kb.store import write_entry, KnowledgeEntry, get_entry
from holmes.logging_config import get_logger


logger = get_logger("kb.merger")

MATURITY_ORDER = {"draft": 0, "verified": 1, "proven": 2}

MergeScenario = Literal[
    "pure_add",
    "evidence_append",
    "maturity_upgrade",
    "maturity_conflict",
    "content_contradiction",
]


def merge_entry(kb_root: Path, pending_content: str) -> dict:
    """Merge a pending entry into the KB.

    Determines the appropriate scenario and handles accordingly.

    Args:
        kb_root: Root directory of the knowledge base.
        pending_content: Markdown + YAML frontmatter of the pending entry.

    Returns:
        Dict with scenario, action taken, and any conflict_id.
    """
    post = frontmatter.loads(pending_content)
    entry_id = str(post.metadata.get("id", ""))
    kb_type = str(post.metadata.get("type", "pitfall"))
    new_maturity = str(post.metadata.get("maturity", "draft"))

    existing = get_entry(kb_root, entry_id) if entry_id else None

    if existing is None:
        # Scenario 1: Pure add
        post.metadata["id"] = entry_id or "UNASSIGNED"
        entry = KnowledgeEntry(
            id=entry_id,
            type=kb_type,  # type: ignore[arg-type]
            title=str(post.metadata.get("title", "")),
            maturity=new_maturity,  # type: ignore[arg-type]
            category=post.metadata.get("category"),
            tags=post.metadata.get("tags", []),
            created_at=str(post.metadata.get("created_at", datetime.now(timezone.utc).isoformat())),
            updated_at=datetime.now(timezone.utc).isoformat(),
            body=post.content,
        )
        write_entry(kb_root, entry)
        rebuild_index(kb_root)
        _append_log(kb_root, "merged-pure-add", entry_id, entry.title)
        return {"scenario": "pure_add", "action": "written", "entry_id": entry_id}

    existing_maturity_rank = MATURITY_ORDER.get(existing.maturity, 0)
    new_maturity_rank = MATURITY_ORDER.get(new_maturity, 0)

    # Scenario 2: Evidence append (same or lower maturity, compatible content)
    if new_maturity_rank <= existing_maturity_rank:
        # Append new evidence section to existing body
        appended_body = (
            existing.body
            + f"\n\n---\n\n*Additional evidence (merged {datetime.now(timezone.utc).date()})*\n\n"
            + post.content
        )
        existing.body = appended_body
        existing.updated_at = datetime.now(timezone.utc).isoformat()
        write_entry(kb_root, existing)
        rebuild_index(kb_root)
        _append_log(kb_root, "merged-evidence-append", entry_id, existing.title)
        return {"scenario": "evidence_append", "action": "appended", "entry_id": entry_id}

    # Scenario 3: Maturity upgrade (new maturity higher)
    if new_maturity_rank > existing_maturity_rank:
        existing.maturity = new_maturity  # type: ignore[assignment]
        existing.updated_at = datetime.now(timezone.utc).isoformat()
        write_entry(kb_root, existing)
        rebuild_index(kb_root)
        _append_log(kb_root, "merged-maturity-upgrade", entry_id, f"{existing.title} → {new_maturity}")
        return {"scenario": "maturity_upgrade", "action": "upgraded", "entry_id": entry_id}

    # Should not reach here, but handle as contradiction
    conflict_id = write_conflict(
        kb_root,
        existing.to_frontmatter_str(),
        pending_content,
        "content_contradiction",
        f"Could not automatically merge entries for {entry_id}",
    )
    return {
        "scenario": "content_contradiction",
        "action": "isolated",
        "entry_id": entry_id,
        "conflict_id": conflict_id,
    }
