"""Persistent memory loading for Holmes Agent.

Loads from two sources (in priority order):
1. ~/.holmes/MEMORY.md  — user-level memory (highest priority)
2. {kb_root}/HOLMES.md  — project-level context

Both are injected into the system prompt at session start.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import os

from holmes.logging_config import get_logger


logger = get_logger("agent.memory")

_HOLMES_DIR = Path(os.environ.get("HOLMES_HOME", Path.home() / ".holmes"))
USER_MEMORY_PATH = _HOLMES_DIR / "MEMORY.md"


def load_memory(kb_root: Optional[Path] = None) -> str:
    """Load and combine persistent memory from both sources.

    User memory takes priority — it is appended after project memory.

    Args:
        kb_root: Root directory of the knowledge base (for HOLMES.md).

    Returns:
        Combined memory text, or empty string if no memory files exist.
    """
    parts: list[str] = []

    # Project-level context (lower priority)
    if kb_root:
        holmes_md = kb_root / "HOLMES.md"
        if holmes_md.exists():
            text = holmes_md.read_text(encoding="utf-8").strip()
            if text:
                parts.append(f"### Project Context (HOLMES.md)\n\n{text}")
                logger.debug("Loaded project memory from %s", holmes_md)

    # User-level memory (higher priority)
    if USER_MEMORY_PATH.exists():
        text = USER_MEMORY_PATH.read_text(encoding="utf-8").strip()
        if text:
            parts.append(f"### User Preferences (MEMORY.md)\n\n{text}")
            logger.debug("Loaded user memory from %s", USER_MEMORY_PATH)

    return "\n\n".join(parts)


def append_to_memory(content: str) -> None:
    """Append new content to the user-level MEMORY.md.

    Creates the file if it does not exist.

    Args:
        content: Text to append.
    """
    USER_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with USER_MEMORY_PATH.open("a", encoding="utf-8") as f:
        if USER_MEMORY_PATH.stat().st_size > 0:
            f.write("\n\n")
        f.write(content.strip())
    logger.info("Appended to user memory: %s...", content[:50])
