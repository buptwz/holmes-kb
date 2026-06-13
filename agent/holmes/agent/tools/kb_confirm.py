"""KB confirm tool for the Holmes Agent.

Records that a KB entry successfully helped resolve the current issue.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Optional

from holmes.agent.tools.base import BaseTool, ToolResult
from holmes.logging_config import get_logger


logger = get_logger("tools.kb_confirm")


class KbConfirmEntryTool(BaseTool):
    """Record that a KB entry helped resolve the current issue."""

    name = "kb_confirm_entry"
    description = (
        "Record that a KB entry successfully helped resolve the current issue. "
        "MUST be called only after the user explicitly confirms the problem is resolved. "
        "MUST NOT be called if the resolution failed or the entry was not used. "
        "For skill entries, call this immediately after successful script execution "
        "and user confirmation."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "entry_id": {
                "type": "string",
                "description": "The KB entry ID that helped resolve the issue.",
            }
        },
        "required": ["entry_id"],
    }
    requires_confirmation = False

    def __init__(self, kb_root: Path, session_id: str) -> None:
        self._kb_root = kb_root
        self._session_id = session_id

    async def execute(self, entry_id: str, **kwargs: Any) -> ToolResult:  # noqa: ARG002
        from holmes.kb.store import append_evidence, derive_maturity, load_evidence

        contributor = os.environ.get("HOLMES_CONTRIBUTOR", "agent")
        record = {
            "session_id": self._session_id,
            "contributor": contributor,
            "date": date.today().isoformat(),
        }
        appended = append_evidence(self._kb_root, entry_id, record)
        if not appended:
            return ToolResult(
                f"Duplicate: evidence for entry '{entry_id}' already recorded in this session.",
            )

        # Reload entry to get updated maturity.
        from holmes.kb.store import get_entry

        new_maturity: Optional[str] = None
        entry = get_entry(self._kb_root, entry_id)
        if entry is not None:
            new_maturity = str(entry.maturity)

        maturity_str = new_maturity or "verified"
        logger.info("kb_confirm_entry: entry=%s contributor=%s maturity=%s", entry_id, contributor, maturity_str)
        return ToolResult(
            f"Evidence recorded for '{entry_id}'. Maturity: {maturity_str}."
        )
