"""File read tool for @-mention context injection.

Reads local files. For files > 1MB or > 500 lines, returns a range selection
prompt rather than the full content.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from holmes.agent.tools.base import BaseTool, ToolResult
from holmes.logging_config import get_logger


logger = get_logger("tools.file_read")

MAX_SIZE_BYTES = 1024 * 1024  # 1MB
MAX_LINES = 500


class FileReadTool(BaseTool):
    """Read a local file and inject its content into the conversation.

    For large files (> 1MB or > 500 lines), returns a prompt asking the user
    to specify a line range via tail_lines or line_range parameters.
    """

    name = "file_read"
    description = (
        "Read a local file and return its content. "
        "Use this to inspect log files, configuration files, or application code "
        "during troubleshooting. "
        "For large files, specify tail_lines (last N lines) or line_range (start, end)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file.",
            },
            "tail_lines": {
                "type": "integer",
                "description": "Read only the last N lines. Useful for logs.",
            },
            "line_start": {
                "type": "integer",
                "description": "Start line number (1-indexed) for range reading.",
            },
            "line_end": {
                "type": "integer",
                "description": "End line number (1-indexed, inclusive) for range reading.",
            },
        },
        "required": ["path"],
    }
    requires_confirmation = False

    async def execute(
        self,
        path: str,
        tail_lines: Optional[int] = None,
        line_start: Optional[int] = None,
        line_end: Optional[int] = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Read file content.

        Args:
            path: File path to read.
            tail_lines: If set, read last N lines.
            line_start: Start of line range (1-indexed).
            line_end: End of line range (inclusive).

        Returns:
            ToolResult with file content or range selection prompt.
        """
        file_path = Path(path).resolve()
        if not file_path.exists():
            return ToolResult(f"File not found: {path}", is_error=True)
        if not file_path.is_file():
            return ToolResult(f"Not a file: {path}", is_error=True)

        size_bytes = file_path.stat().st_size
        try:
            raw = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ToolResult(f"Could not read file: {e}", is_error=True)

        lines = raw.split("\n")
        total_lines = len(lines)

        # If specific range requested, apply it
        if tail_lines is not None:
            start = max(0, total_lines - tail_lines)
            selected = lines[start:]
            range_info = f"(last {tail_lines} lines, {start + 1}–{total_lines})"
            content = "\n".join(selected)
            return ToolResult(
                f"[File: {path}] {range_info}\n\n```\n{content}\n```"
            )

        if line_start is not None and line_end is not None:
            selected = lines[line_start - 1 : line_end]
            range_info = f"(lines {line_start}–{line_end})"
            content = "\n".join(selected)
            return ToolResult(
                f"[File: {path}] {range_info}\n\n```\n{content}\n```"
            )

        # Check size limits
        if size_bytes > MAX_SIZE_BYTES or total_lines > MAX_LINES:
            return ToolResult(
                f"[File: {path}] is large ({size_bytes // 1024}KB, {total_lines} lines). "
                f"Please specify a range:\n"
                f"- tail_lines: <N>  — read last N lines\n"
                f"- line_start + line_end: <start>, <end>  — read specific range\n"
                f"Recommended: tail_lines=100 for log files."
            )

        return ToolResult(f"[File: {path}]\n\n```\n{raw}\n```")
