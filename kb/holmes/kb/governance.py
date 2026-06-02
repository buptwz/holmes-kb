"""Knowledge base governance — write-protection and title duplicate guards.

Enforces soft-constraint write protection at the CLI layer:
- verified/proven entries are write-protected (Agent cannot modify them directly)
- All writes go through the write-pending → confirm flow
- check_title_duplicate prevents accidental duplicate submissions
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import frontmatter

from holmes.kb.store import list_entries

WRITE_PROTECTED_MATURITIES = frozenset({"verified", "proven"})


class DuplicateTitleError(Exception):
    """Raised when write_pending() detects a title that matches an existing verified/proven entry."""

    def __init__(self, title: str, existing_id: str) -> None:
        self.title = title
        self.existing_id = existing_id
        super().__init__(
            f"Duplicate title: {title!r} matches {existing_id!r} (verified/proven). "
            f"Use --corrects {existing_id} to submit a correction."
        )


def check_title_duplicate(
    kb_root: Path,
    title: str,
    exclude_corrects: Optional[str] = None,
) -> Optional[str]:
    """Return matching entry ID if title matches a verified/proven entry, else None.

    Args:
        kb_root: Root directory of the knowledge base.
        title: Title string to check (case-insensitive exact match).
        exclude_corrects: If provided, skip this entry ID (used in correction workflow
                          so a corrects-annotated pending entry can share the target's title).

    Returns:
        Matching entry ID string, or None if no duplicate found.
    """
    title_lower = title.strip().lower()
    if not title_lower:
        return None

    for entry in list_entries(kb_root):
        if entry.id == exclude_corrects:
            continue
        if entry.maturity in WRITE_PROTECTED_MATURITIES:
            if entry.title.strip().lower() == title_lower:
                return entry.id
    return None


def is_write_protected(kb_root: Path, entry_id: str) -> tuple[bool, str]:
    """Check whether a KB entry is write-protected (maturity is verified or proven).

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: The entry ID to check.

    Returns:
        Tuple of (protected: bool, error_message: str).
        If protected=False, error_message is empty string.
    """
    from holmes.kb.store import read_entry

    content = read_entry(kb_root, entry_id)
    if content is None:
        return False, ""  # Entry not found — allow create

    post = frontmatter.loads(content)
    maturity = str(post.metadata.get("maturity", "draft"))
    if maturity in WRITE_PROTECTED_MATURITIES:
        return True, (
            f"Write blocked: entry {entry_id!r} has maturity {maturity!r}. "
            f"Use --corrects {entry_id} to submit a correction."
        )
    return False, ""
