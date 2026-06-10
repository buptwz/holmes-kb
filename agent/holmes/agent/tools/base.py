"""Tool abstraction base class for Holmes Agent.

All tools implement this interface. Tools with requires_confirmation=True
will pause agent execution and wait for user approval via IPC before running.
"""

from __future__ import annotations

import abc
from typing import Any


class ToolResult:
    """Result from a tool execution."""

    def __init__(self, content: str, is_error: bool = False) -> None:
        """Initialize ToolResult.

        Args:
            content: The string output of the tool.
            is_error: Whether this result represents an error.
        """
        self.content = content
        self.is_error = is_error

    def __repr__(self) -> str:
        status = "error" if self.is_error else "ok"
        preview = self.content[:80] + "..." if len(self.content) > 80 else self.content
        return f"ToolResult({status}, {preview!r})"


class BaseTool(abc.ABC):
    """Abstract base class for all Holmes agent tools.

    Subclasses must implement `execute`. The `requires_confirmation` flag
    controls whether the agent pauses before execution.
    """

    #: Human-readable tool name passed to the Anthropic API.
    name: str

    #: Description shown to the LLM when choosing tools.
    description: str

    #: JSON Schema for the tool's input parameters.
    input_schema: dict[str, Any]

    #: If True, agent pauses and waits for user approval before executing.
    requires_confirmation: bool = False

    @abc.abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given keyword arguments.

        Args:
            **kwargs: Tool-specific parameters matching input_schema.

        Returns:
            ToolResult with the tool's output or error.
        """

    def to_api_schema(self) -> dict[str, Any]:
        """Convert this tool to the Anthropic API tool definition format.

        Returns:
            Dict with name, description, and input_schema.
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
