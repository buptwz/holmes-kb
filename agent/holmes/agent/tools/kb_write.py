"""KB write tool — writes a new knowledge entry to the pending area.

Requires user confirmation before execution (requires_confirmation=True).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from holmes.agent.tools.base import BaseTool, ToolResult
from holmes.kb.pending import write_pending
from holmes.logging_config import get_logger


logger = get_logger("tools.kb_write")


class KbWriteEntryTool(BaseTool):
    """Write a new knowledge entry to the KB pending area.

    Requires user confirmation. Entries are placed in contributions/pending/
    and must be reviewed with 'holmes kb confirm <id>' before becoming active.
    """

    name = "kb_write_entry"
    description = (
        "Write a new knowledge entry to the knowledge base pending area for review. "
        "The entry must be in Markdown format with valid YAML frontmatter. "
        "Required frontmatter: type, title, maturity (use 'draft'), tags, category (for pitfall). "
        "The entry will be placed in contributions/pending/ and must be confirmed before use."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Complete Markdown content with YAML frontmatter.",
            }
        },
        "required": ["content"],
    }
    requires_confirmation = True

    def __init__(self, kb_root: Path) -> None:
        self._kb_root = kb_root

    async def execute(self, content: str, **kwargs: Any) -> ToolResult:  # noqa: ARG002
        """Write entry to pending area.

        Args:
            content: Markdown with YAML frontmatter.

        Returns:
            ToolResult with the pending entry ID.
        """
        try:
            pending_id = write_pending(self._kb_root, content)
            logger.info("Wrote pending entry %s", pending_id)
            return ToolResult(
                f"Entry saved to pending area with ID: {pending_id}\n"
                f"Review and confirm with: holmes kb confirm {pending_id}",
                artifact=pending_id,
            )
        except Exception as e:
            logger.error("Failed to write pending entry: %s", e)
            return ToolResult(f"Failed to write entry: {e}", is_error=True)
