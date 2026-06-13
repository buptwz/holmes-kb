"""Bash diagnostic command execution tool.

Requires user confirmation (requires_confirmation=True).
Timeout: 30 seconds. Output truncated at 10,000 characters.
"""

from __future__ import annotations

import asyncio
import shlex
from typing import Any

from holmes.agent.tools.base import BaseTool, ToolResult
from holmes.logging_config import get_logger


logger = get_logger("tools.bash")

TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 10_000
TRUNCATION_NOTE = "\n\n[Output truncated — exceeded 10,000 characters]"


class BashTool(BaseTool):
    """Execute a shell command for diagnostic purposes.

    Requires user confirmation before each execution.
    stdout and stderr are combined in the output.
    Commands are killed after 30 seconds.
    """

    name = "bash_execute"
    description = (
        "Execute a shell command for diagnostic purposes. "
        "Use this to check system state, inspect logs, run diagnostic utilities. "
        "Commands run with the user's environment. "
        "Requires user confirmation. Timeout: 30 seconds. "
        "Examples: 'ps aux | grep nginx', 'tail -n 50 /var/log/syslog', 'df -h'"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute.",
            },
            "working_dir": {
                "type": "string",
                "description": "Working directory for the command. Defaults to current directory.",
            },
        },
        "required": ["command"],
    }
    requires_confirmation = True

    async def execute(self, command: str, working_dir: str = ".", **kwargs: Any) -> ToolResult:  # noqa: ARG002
        """Execute a shell command.

        Args:
            command: The command to run.
            working_dir: Optional working directory.

        Returns:
            ToolResult with combined stdout/stderr.
        """
        logger.info("Executing command: %s", command)
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=working_dir,
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return ToolResult(
                    f"Command timed out after {TIMEOUT_SECONDS} seconds: {command}",
                    is_error=True,
                )

            output = stdout.decode("utf-8", errors="replace")
            exit_code = proc.returncode or 0

            # Truncate if too long
            truncated = False
            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS]
                truncated = True

            header = f"$ {command}\n[exit code: {exit_code}]\n\n"
            full_output = header + output + (TRUNCATION_NOTE if truncated else "")

            is_error = exit_code != 0
            return ToolResult(full_output, is_error=is_error)

        except Exception as e:
            logger.exception("Command execution failed: %s", command)
            return ToolResult(f"Execution error: {e}", is_error=True)
