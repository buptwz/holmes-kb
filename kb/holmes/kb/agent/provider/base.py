"""LLM provider abstraction for the Holmes import agent.

Defines the LLMProvider interface and ToolCall dataclass that decouple
runner.py from any specific SDK (Anthropic, OpenAI, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolCall:
    """A normalised tool call returned by the LLM, provider-agnostic."""

    id: str
    name: str
    input: dict[str, Any]


class LLMProvider(ABC):
    """Abstract base class for LLM provider implementations.

    Concrete implementations (AnthropicProvider, OpenAIProvider) handle
    SDK-specific wire formats while exposing a stable interface to runner.py
    and tools.py.
    """

    @abstractmethod
    def complete(
        self,
        messages: list[Any],
        system: str,
        model: str,
        max_tokens: int,
        tools: list[dict],
    ) -> tuple[bool, list[ToolCall], list[Any], dict[str, int]]:
        """Run one step of the tool-use loop.

        Args:
            messages: Current message history in provider-compatible format.
            system: System prompt string.
            model: Model identifier string.
            max_tokens: Maximum tokens for the response.
            tools: Tool definitions in Anthropic input_schema format.

        Returns:
            Tuple of (stop, tool_calls, updated_messages, usage) where:
                stop: True when no more tool calls are needed (loop should exit).
                tool_calls: List of ToolCall objects to dispatch.
                updated_messages: Message history with assistant turn appended.
                usage: Token counts {"input_tokens": int, "output_tokens": int}.
        """

    @abstractmethod
    def simple_complete(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 512,
    ) -> str:
        """Single-turn text completion without tool calling.

        Used by compare_root_cause, verify_content, and skill generation.

        Args:
            messages: List of chat messages.
            system: Optional system prompt.
            max_tokens: Maximum tokens for the response (default 512).

        Returns:
            Raw text from the LLM response.
        """

    @abstractmethod
    def append_tool_results(
        self,
        messages: list[Any],
        results: list[tuple[str, str]],
    ) -> list[Any]:
        """Append tool results to messages in provider wire format.

        Args:
            messages: Current message history.
            results: List of (tool_use_id, json_content) tuples.

        Returns:
            Updated message history with tool results appended.
        """
