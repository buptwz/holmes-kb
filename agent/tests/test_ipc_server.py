"""Unit tests for IPCServer concurrent dispatch and protocol compliance.

Covers:
- US1: asyncio.create_task concurrent dispatch (deadlock fix)
- US2: chat.send JSON-RPC ack before streaming
- US3: build_tools extra_tools injection
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from holmes.agent.ipc_server import IPCServer, _ok_response, _error_response, _notification
from holmes.config import HolmesConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config() -> HolmesConfig:
    return HolmesConfig(
        api_key="test-key",
        api_base_url="http://localhost",
        model="gpt-test",
    )


def _make_writer() -> MagicMock:
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    return writer


def _make_server() -> IPCServer:
    config = _make_config()
    return IPCServer(config=config, tools_factory=lambda cfg, sid="": [])


def _encode(data: dict) -> bytes:
    return (json.dumps(data) + "\n").encode()


# ---------------------------------------------------------------------------
# US1: Concurrent dispatch — asyncio.create_task
# ---------------------------------------------------------------------------

class TestConcurrentDispatch:
    """Verify the read-loop dispatches requests as tasks (non-blocking)."""

    def test_dispatch_isolated_catches_exception_and_sends_error(self):
        """_dispatch_isolated must not propagate exceptions to caller."""
        server = _make_server()
        writer = _make_writer()

        async def run():
            # Patch _dispatch to raise
            async def bad_dispatch(req, w):
                raise RuntimeError("boom")

            server._dispatch = bad_dispatch
            request = {"jsonrpc": "2.0", "id": 1, "method": "session.list", "params": {}}
            await server._dispatch_isolated(request, writer)

        asyncio.run(run())
        # writer.write should have been called with an error response
        written = b"".join(call.args[0] for call in writer.write.call_args_list)
        data = json.loads(written.decode().strip())
        assert data["id"] == 1
        assert "error" in data

    def test_dispatch_isolated_no_id_swallows_exception_silently(self):
        """_dispatch_isolated with no req_id must not send error response."""
        server = _make_server()
        writer = _make_writer()

        async def run():
            async def bad_dispatch(req, w):
                raise RuntimeError("boom")

            server._dispatch = bad_dispatch
            request = {"jsonrpc": "2.0", "method": "session.list", "params": {}}
            await server._dispatch_isolated(request, writer)

        asyncio.run(run())
        # No write calls — no id means no error response
        assert writer.write.call_count == 0

    def test_handle_client_creates_tasks_not_awaited_inline(self):
        """_handle_client must use create_task, not await _dispatch directly."""
        server = _make_server()

        # Inspect ipc_server source for the create_task call
        import inspect
        import holmes.agent.ipc_server as ipc_module
        source = inspect.getsource(ipc_module.IPCServer._handle_client)
        assert "create_task" in source, (
            "_handle_client must use asyncio.create_task for concurrent dispatch"
        )


# ---------------------------------------------------------------------------
# US1: Deadlock scenario — tool.approve unblocks session.resolve
# ---------------------------------------------------------------------------

class TestSessionResolveDeadlock:
    """Verify session.resolve and tool.approve can interleave on same connection."""

    def test_no_deadlock_approve_unblocks_resolve(self):
        """Simulate the deadlock scenario: resolve waits for approve on same connection."""
        server = _make_server()
        writer = _make_writer()

        approve_received = asyncio.Event()
        resolve_completed = asyncio.Event()

        async def mock_resolve(params, w):
            # Simulate waiting for a future (like the real handler does)
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            tool_call_id = "tc-test-001"
            server._pending_confirmations[tool_call_id] = future
            await asyncio.wait_for(future, timeout=2.0)
            resolve_completed.set()
            return {"kb_entry_id": "", "summary_preview": ""}

        async def mock_approve(params, w):
            approve_received.set()
            tool_call_id = params["tool_call_id"]
            fut = server._pending_confirmations.pop(tool_call_id, None)
            if fut and not fut.done():
                fut.set_result((True, None))
            return {"ok": True}

        server._handle_session_resolve = mock_resolve
        server._handle_tool_approve = mock_approve

        async def run():
            # Dispatch resolve as task (non-blocking)
            resolve_req = {
                "jsonrpc": "2.0", "id": 1,
                "method": "session.resolve",
                "params": {"session_id": "s1"},
            }
            asyncio.create_task(server._dispatch_isolated(resolve_req, writer))

            # Yield so the resolve task starts and waits on its future
            await asyncio.sleep(0)

            # Now dispatch approve — must be processed while resolve is waiting
            approve_req = {
                "jsonrpc": "2.0", "id": 2,
                "method": "tool.approve",
                "params": {"tool_call_id": "tc-test-001"},
            }
            await server._dispatch_isolated(approve_req, writer)

            # Wait for resolve to complete
            await asyncio.wait_for(resolve_completed.wait(), timeout=2.0)

        asyncio.run(run())
        assert resolve_completed.is_set()


# ---------------------------------------------------------------------------
# US2: chat.send protocol compliance — ack before stream
# ---------------------------------------------------------------------------

class TestChatSendAck:
    """Verify chat.send sends JSON-RPC ack when request has an id."""

    def test_chat_send_with_id_sends_ack_first(self):
        """chat.send with id=42 must send {"ok": true} before any notifications."""
        server = _make_server()
        writer = _make_writer()

        sent_messages: list[dict] = []

        async def capture_send(w, data):
            sent_messages.append(data)

        server._send = capture_send

        # Mock engine that yields no events (chat returns an async generator directly)
        mock_engine = MagicMock()
        mock_engine.chat = MagicMock(return_value=_empty_async_gen())
        server._engines["session-1"] = mock_engine

        async def run():
            params = {"session_id": "session-1", "message": "hello"}
            await server._handle_chat_send(params, writer, req_id=42)

        asyncio.run(run())

        assert len(sent_messages) >= 1
        first = sent_messages[0]
        assert first.get("id") == 42
        assert first.get("result") == {"ok": True}

    def test_chat_send_without_id_no_ack(self):
        """chat.send without id must not send a JSON-RPC response."""
        server = _make_server()
        writer = _make_writer()

        sent_messages: list[dict] = []

        async def capture_send(w, data):
            sent_messages.append(data)

        server._send = capture_send

        mock_engine = MagicMock()
        mock_engine.chat = MagicMock(return_value=_empty_async_gen())
        server._engines["session-1"] = mock_engine

        async def run():
            params = {"session_id": "session-1", "message": "hello"}
            await server._handle_chat_send(params, writer, req_id=None)

        asyncio.run(run())

        # No response-style messages (those with "id" key)
        response_msgs = [m for m in sent_messages if "id" in m]
        assert response_msgs == []

    def test_dispatch_passes_req_id_to_chat_send(self):
        """_dispatch must pass req_id to _handle_chat_send."""
        import inspect
        import holmes.agent.ipc_server as ipc_module

        source = inspect.getsource(ipc_module.IPCServer._dispatch)
        # The dispatch code must reference req_id when calling chat.send or skill.invoke
        assert "req_id" in source


# ---------------------------------------------------------------------------
# US3: build_tools extra_tools injection
# ---------------------------------------------------------------------------

class TestBuildToolsExtraTools:
    """Verify build_tools accepts and injects extra_tools."""

    def test_extra_tools_injected(self):
        from holmes.agent_server import build_tools
        from holmes.agent.tools.base import BaseTool, ToolResult

        class MockTool(BaseTool):
            name = "mock_mcp_tool"
            description = "mock"
            input_schema = {"type": "object", "properties": {}}
            requires_confirmation = False

            async def execute(self, **kwargs):
                return ToolResult("ok")

        config = _make_config()
        mock_tool = MockTool()
        tools = build_tools(config, extra_tools=[mock_tool])
        tool_names = [t.name for t in tools]
        assert "mock_mcp_tool" in tool_names

    def test_no_extra_tools_unchanged(self):
        from holmes.agent_server import build_tools
        config = _make_config()
        tools_without = build_tools(config)
        tools_with_none = build_tools(config, extra_tools=None)
        assert len(tools_without) == len(tools_with_none)

    def test_extra_tools_empty_list_unchanged(self):
        from holmes.agent_server import build_tools
        config = _make_config()
        tools_without = build_tools(config)
        tools_with_empty = build_tools(config, extra_tools=[])
        assert len(tools_without) == len(tools_with_empty)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _empty_async_gen():
    """Async generator that yields nothing."""
    return
    yield  # make it a generator
