"""Holmes Agent core engine.

Implements the agentic loop modeled after claude-code's QueryEngine:
- Anthropic SDK streaming calls
- Tool execution loop with requires_confirmation pause points
- Event emission for IPC notifications (token, tool_start, tool_end, tool_confirm)
- Knowledge extraction on session resolve
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

import openai

from holmes.agent.context_builder import build_system_prompt, normalize_messages_for_api
from holmes.agent.memory import load_memory
from holmes.agent.session import Session, save_session
from holmes.agent.tools.base import BaseTool, ToolResult
from holmes.config import HolmesConfig
from holmes.logging_config import get_logger


logger = get_logger("agent.engine")

MAX_TOOL_ITERATIONS = 20
KNOWLEDGE_EXTRACT_SYSTEM = """You are a knowledge extraction specialist.
Given a troubleshooting session, extract a structured knowledge entry in Markdown with YAML frontmatter.

Required frontmatter fields: id (use placeholder 'PENDING'), type (pitfall/model/guideline/process/decision),
title, maturity (draft), category (for pitfall: network/system/application/database), tags (list),
created_at, updated_at.

For 'pitfall' type (most common), include these sections:
## Symptoms
## Root Cause
## Resolution
## Prevention (optional)

Return ONLY the Markdown with frontmatter, no extra text."""


# Event types emitted by the engine
@dataclass
class TokenEvent:
    session_id: str
    delta: str


@dataclass
class ToolStartEvent:
    session_id: str
    tool_call_id: str
    tool_name: str
    input: dict[str, Any]


@dataclass
class ToolEndEvent:
    session_id: str
    tool_call_id: str
    output: str
    status: str  # "done" | "error"


@dataclass
class ToolConfirmEvent:
    """Emitted when a tool requires user confirmation."""

    session_id: str
    tool_call_id: str
    tool_name: str
    description: str
    input_preview: dict[str, Any]


@dataclass
class DoneEvent:
    session_id: str
    input_tokens: int
    output_tokens: int
    kb_refs: list[str] = field(default_factory=list)


@dataclass
class ErrorEvent:
    session_id: str
    error: str
    code: Optional[str] = None


AgentEvent = TokenEvent | ToolStartEvent | ToolEndEvent | ToolConfirmEvent | DoneEvent | ErrorEvent

# Confirmation decision supplied back to the engine
ConfirmDecision = tuple[bool, Optional[str]]  # (approved, deny_reason)


class AgentEngine:
    """Holmes agentic engine.

    Usage:
        engine = AgentEngine(config, session, tools)
        async for event in engine.chat("Why is my service failing?"):
            handle(event)
    """

    def __init__(
        self,
        config: HolmesConfig,
        session: Session,
        tools: list[BaseTool],
        confirm_callback: Optional[
            Callable[[ToolConfirmEvent], Coroutine[Any, Any, ConfirmDecision]]
        ] = None,
    ) -> None:
        """Initialize the engine.

        Args:
            config: Holmes configuration.
            session: Active session object.
            tools: List of available tools.
            confirm_callback: Async callback invoked for tools requiring confirmation.
                              If None, all confirmations are auto-denied.
        """
        self._config = config
        self._session = session
        self._tools: dict[str, BaseTool] = {t.name: t for t in tools}
        self._confirm_callback = confirm_callback
        self._client = openai.AsyncOpenAI(
            api_key=config.api_key or None,
            base_url=config.api_base_url or None,
        )
        self._kb_root: Optional[Path] = None
        if config.kb_path:
            self._kb_root = Path(config.kb_path)

    async def chat(self, user_message: str) -> AsyncIterator[AgentEvent]:
        """Process a user message and run the agentic tool loop.

        Yields AgentEvent objects for streaming to the IPC layer.

        Args:
            user_message: The user's input text.
        """
        self._session.add_message("user", user_message)
        save_session(self._session)

        memory_text = load_memory(self._kb_root)
        system_prompt = build_system_prompt(memory_text=memory_text)
        api_messages = normalize_messages_for_api(
            [{"role": m.role, "content": m.content} for m in self._session.messages]
        )

        api_tools = [t.to_api_schema() for t in self._tools.values()]
        total_input_tokens = 0
        total_output_tokens = 0
        assistant_text_parts: list[str] = []

        try:
            for _iteration in range(MAX_TOOL_ITERATIONS):
                stream_result = await self._run_one_turn(
                    system_prompt=system_prompt,
                    messages=api_messages,
                    tools=api_tools,
                )
                async for event in stream_result:
                    if isinstance(event, TokenEvent):
                        assistant_text_parts.append(event.delta)
                        yield event
                    elif isinstance(event, _InternalUsageEvent):
                        total_input_tokens += event.input_tokens
                        total_output_tokens += event.output_tokens
                    elif isinstance(event, _InternalToolRequestsEvent):
                        # Execute tools
                        tool_result_messages: list[dict[str, Any]] = []

                        for tool_use in event.tool_uses:
                            tool_call_id = tool_use["id"]
                            tool_name = tool_use["name"]
                            tool_input = tool_use.get("input", {})

                            self._session.start_tool_call(tool_call_id, tool_name, tool_input)
                            save_session(self._session)

                            tool = self._tools.get(tool_name)
                            if tool is None:
                                result = ToolResult(
                                    f"Unknown tool: {tool_name}", is_error=True
                                )
                                self._session.finish_tool_call(
                                    tool_call_id, result.content, "error"
                                )
                            elif tool.requires_confirmation:
                                confirm_event = ToolConfirmEvent(
                                    session_id=self._session.id,
                                    tool_call_id=tool_call_id,
                                    tool_name=tool_name,
                                    description=tool.description[:200],
                                    input_preview=tool_input,
                                )
                                yield confirm_event

                                approved, reason = await self._wait_for_confirmation(
                                    confirm_event
                                )
                                if approved:
                                    yield ToolStartEvent(
                                        session_id=self._session.id,
                                        tool_call_id=tool_call_id,
                                        tool_name=tool_name,
                                        input=tool_input,
                                    )
                                    result = await self._exec_tool(tool, tool_input)
                                    status = "error" if result.is_error else "done"
                                    self._session.finish_tool_call(
                                        tool_call_id, result.content, status  # type: ignore[arg-type]
                                    )
                                    yield ToolEndEvent(
                                        session_id=self._session.id,
                                        tool_call_id=tool_call_id,
                                        output=result.content,
                                        status=status,
                                    )
                                else:
                                    deny_msg = f"User denied tool execution. Reason: {reason or 'no reason given'}"
                                    result = ToolResult(deny_msg, is_error=False)
                                    self._session.finish_tool_call(
                                        tool_call_id, deny_msg, "denied"
                                    )
                                    yield ToolEndEvent(
                                        session_id=self._session.id,
                                        tool_call_id=tool_call_id,
                                        output=deny_msg,
                                        status="denied",
                                    )
                            else:
                                yield ToolStartEvent(
                                    session_id=self._session.id,
                                    tool_call_id=tool_call_id,
                                    tool_name=tool_name,
                                    input=tool_input,
                                )
                                result = await self._exec_tool(tool, tool_input)
                                status = "error" if result.is_error else "done"
                                self._session.finish_tool_call(
                                    tool_call_id, result.content, status  # type: ignore[arg-type]
                                )
                                yield ToolEndEvent(
                                    session_id=self._session.id,
                                    tool_call_id=tool_call_id,
                                    output=result.content,
                                    status=status,
                                )
                            save_session(self._session)

                            tool_result_messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "content": result.content,
                            })

                        # Add assistant message and tool results to context (OpenAI format)
                        if assistant_text_parts or event.tool_uses:
                            assistant_msg: dict[str, Any] = {"role": "assistant"}
                            assistant_msg["content"] = "".join(assistant_text_parts) if assistant_text_parts else None
                            if event.tool_uses:
                                assistant_msg["tool_calls"] = [
                                    {
                                        "id": tu["id"],
                                        "type": "function",
                                        "function": {
                                            "name": tu["name"],
                                            "arguments": json.dumps(tu.get("input", {})),
                                        },
                                    }
                                    for tu in event.tool_uses
                                ]
                            api_messages.append(assistant_msg)
                            api_messages.extend(tool_result_messages)
                        assistant_text_parts = []

                    elif isinstance(event, _InternalStopEvent):
                        # No more tool calls — final assistant turn done
                        if assistant_text_parts:
                            final_text = "".join(assistant_text_parts)
                            self._session.add_message("assistant", final_text)
                            save_session(self._session)
                        yield DoneEvent(
                            session_id=self._session.id,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            kb_refs=list(self._session.kb_refs),
                        )
                        return

        except openai.APIError as e:
            logger.error("OpenAI API error: %s", e)
            yield ErrorEvent(
                session_id=self._session.id,
                error=str(e),
                code="api_error",
            )
        except Exception as e:
            logger.exception("Unexpected engine error")
            yield ErrorEvent(
                session_id=self._session.id,
                error=str(e),
                code="internal_error",
            )

    async def extract_knowledge(self) -> str:
        """Extract a knowledge entry from the current session.

        Uses LLM to summarize the session into a structured KB entry.

        Returns:
            Frontmatter Markdown string for the new KB entry.
        """
        conversation_text = "\n\n".join(
            f"**{m.role.upper()}**: {m.content}" for m in self._session.messages
        )
        prompt = (
            f"Extract a knowledge entry from this troubleshooting session:\n\n"
            f"{conversation_text}"
        )
        response = await self._client.chat.completions.create(
            model=self._config.model,
            max_completion_tokens=2048,
            messages=[
                {"role": "system", "content": KNOWLEDGE_EXTRACT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""

    async def compact_context(self, session: Session) -> str:
        """Compress session history into a summary.

        Args:
            session: Session to compact.

        Returns:
            Summary text to replace old messages.
        """
        conversation_text = "\n\n".join(
            f"{m.role}: {m.content}" for m in session.messages
        )
        response = await self._client.chat.completions.create(
            model=self._config.model,
            max_completion_tokens=1024,
            messages=[{
                "role": "user",
                "content": (
                    f"Summarize this troubleshooting conversation concisely, "
                    f"preserving all important diagnostic steps and findings:\n\n{conversation_text}"
                ),
            }],
        )
        return response.choices[0].message.content or ""

    async def _wait_for_confirmation(
        self, event: ToolConfirmEvent
    ) -> ConfirmDecision:
        """Wait for confirmation via the callback.

        Args:
            event: The confirmation event.

        Returns:
            Tuple of (approved, reason).
        """
        if self._confirm_callback is None:
            return (False, "No confirmation handler configured")
        return await self._confirm_callback(event)

    async def _exec_tool(
        self, tool: BaseTool, tool_input: dict[str, Any]
    ) -> ToolResult:
        """Execute a tool safely, catching exceptions.

        Args:
            tool: Tool instance.
            tool_input: Input parameters.

        Returns:
            ToolResult (never raises).
        """
        try:
            return await tool.execute(**tool_input)
        except Exception as e:
            logger.exception("Tool %s raised exception", tool.name)
            return ToolResult(f"Tool error: {e}", is_error=True)

    def _build_openai_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Anthropic-style tool schemas to OpenAI function calling format."""
        result = []
        for t in tools:
            result.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            })
        return result

    async def _run_one_turn(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[Any]:
        """Run one streaming turn with the Anthropic API.

        Yields internal events: tokens, tool requests, stop.
        """
        return self._stream_turn(system_prompt, messages, tools)

    async def _stream_turn(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[Any]:
        """Async generator for one streaming API turn (OpenAI-compatible format).

        Yields:
            _InternalTokenEvent, _InternalUsageEvent, _InternalToolRequestsEvent,
            or _InternalStopEvent.
        """
        # Build OpenAI messages: system prompt as first system message
        openai_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        openai_tools = self._build_openai_tools(tools) if tools else []

        # Accumulate tool call deltas: index -> {id, name, arguments}
        tool_call_accum: dict[int, dict[str, Any]] = {}
        input_tokens = 0
        output_tokens = 0
        finish_reason: Optional[str] = None

        api_kwargs: dict[str, Any] = {
            "model": self._config.model,
            "max_completion_tokens": self._config.max_tokens,
            "messages": openai_messages,
            "stream": True,
        }
        if openai_tools:
            api_kwargs["tools"] = openai_tools

        stream = await self._client.chat.completions.create(**api_kwargs)
        async for chunk in stream:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                finish_reason = choice.finish_reason or finish_reason
                delta = choice.delta

                # Text token
                if delta.content:
                    yield TokenEvent(session_id=self._session.id, delta=delta.content)

                # Tool call deltas
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_call_accum:
                            tool_call_accum[idx] = {
                                "id": tc_delta.id or "",
                                "name": tc_delta.function.name if tc_delta.function else "",
                                "arguments": "",
                            }
                        else:
                            if tc_delta.id:
                                tool_call_accum[idx]["id"] = tc_delta.id
                            if tc_delta.function and tc_delta.function.name:
                                tool_call_accum[idx]["name"] = tc_delta.function.name
                        if tc_delta.function and tc_delta.function.arguments:
                            tool_call_accum[idx]["arguments"] += tc_delta.function.arguments

        yield _InternalUsageEvent(input_tokens=input_tokens, output_tokens=output_tokens)

        if tool_call_accum:
            tool_uses = []
            for tc in tool_call_accum.values():
                try:
                    input_data = json.loads(tc["arguments"] or "{}")
                except json.JSONDecodeError:
                    input_data = {}
                tool_uses.append({
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": input_data,
                })
            yield _InternalToolRequestsEvent(tool_uses=tool_uses)
        else:
            yield _InternalStopEvent(stop_reason=finish_reason or "stop")


# Internal events used only within _stream_turn → chat pipeline
@dataclass
class _InternalUsageEvent:
    input_tokens: int
    output_tokens: int


@dataclass
class _InternalToolRequestsEvent:
    tool_uses: list[dict[str, Any]]


@dataclass
class _InternalStopEvent:
    stop_reason: str
