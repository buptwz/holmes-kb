"""Anthropic SDK implementation of LLMProvider."""

from __future__ import annotations

import json
from typing import Any

import anthropic

from holmes.config import HolmesConfig
from holmes.kb.agent.provider.base import LLMProvider, ToolCall


class AnthropicProvider(LLMProvider):
    """LLMProvider backed by the Anthropic SDK.

    Passes tool definitions as-is (Anthropic input_schema format).
    Tool results are appended as a user message with tool_result blocks.
    """

    def __init__(self, cfg: HolmesConfig) -> None:
        self._client = anthropic.Anthropic(
            api_key=cfg.api_key or None,
            base_url=cfg.api_base_url or None,
        )
        self._model = cfg.model

    def complete(
        self,
        messages: list[Any],
        system: str,
        model: str,
        max_tokens: int,
        tools: list[dict],
    ) -> tuple[bool, list[ToolCall], list[Any]]:
        """Run one step of the Anthropic tool-use loop."""
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )

        updated = list(messages)
        updated.append({"role": "assistant", "content": response.content})

        tool_calls = [
            ToolCall(id=block.id, name=block.name, input=block.input)
            for block in response.content
            if block.type == "tool_use"
        ]

        stop = response.stop_reason == "end_turn" or not tool_calls
        return stop, tool_calls, updated

    def simple_complete(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 512,
    ) -> str:
        """Single-turn Anthropic completion without tools."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        response = self._client.messages.create(**kwargs)
        return response.content[0].text if response.content else ""

    def append_tool_results(
        self,
        messages: list[Any],
        results: list[tuple[str, str]],
    ) -> list[Any]:
        """Append tool results as an Anthropic user message."""
        updated = list(messages)
        updated.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                }
                for tool_use_id, content in results
            ],
        })
        return updated
