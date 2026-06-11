"""Unit tests for MCPManager connection lifetime and graceful degradation.

Covers US3:
- Connection stays open after initialize() (AsyncExitStack)
- close() properly exits the context
- Graceful degradation when MCP server is unreachable
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from holmes.agent.mcp_manager import MCPManager, MCPProxyTool
from holmes.config import HolmesConfig, MCPServerConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(servers: list[dict] | None = None) -> HolmesConfig:
    cfg = HolmesConfig(
        api_key="test-key",
        api_base_url="http://localhost",
        model="gpt-test",
    )
    if servers:
        cfg.mcp_servers = [MCPServerConfig(**s) for s in servers]
    return cfg


def _make_mock_tool():
    tool = MagicMock()
    tool.name = "mock_tool"
    tool.description = "A mock MCP tool"
    tool.inputSchema = {"type": "object", "properties": {}}
    return tool


# ---------------------------------------------------------------------------
# US3: Connection lifetime — AsyncExitStack
# ---------------------------------------------------------------------------

class TestMCPConnectionLifetime:
    """Verify connections stay open until close() is called."""

    def test_connection_stays_open_after_initialize(self):
        """stdio_client context must NOT exit when initialize() returns."""
        enter_count = 0
        exit_count = 0

        class FakeExitStack:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def enter_async_context(self, cm):
                nonlocal enter_count
                enter_count += 1
                return await cm.__aenter__()

            async def aclose(self):
                nonlocal exit_count
                exit_count += 1

        config = _make_config([
            {"name": "test-server", "command": "echo", "args": [], "env": {}}
        ])
        mgr = MCPManager(config)

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

        @asynccontextmanager
        async def mock_stdio_client(params):
            yield (AsyncMock(), AsyncMock())

        @asynccontextmanager
        async def mock_client_session(read, write):
            yield mock_session

        async def run():
            mgr._exit_stack = FakeExitStack()
            import holmes.agent.mcp_manager as mcp_mod
            with patch.object(mcp_mod, "stdio_client", mock_stdio_client), \
                 patch.object(mcp_mod, "ClientSession", mock_client_session):
                await mgr._connect_server(config.mcp_servers[0])

        asyncio.run(run())

        # enter_async_context was called (connections opened), exit_count == 0 (not closed)
        assert enter_count > 0
        assert exit_count == 0, "Connections must NOT be closed after initialize()"

    def test_close_exits_all_contexts(self):
        """close() must call aclose() on the exit stack."""
        aclose_called = False

        class TrackingExitStack:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def enter_async_context(self, cm):
                return await cm.__aenter__()

            async def aclose(self):
                nonlocal aclose_called
                aclose_called = True

        config = _make_config()
        mgr = MCPManager(config)

        async def run():
            mgr._exit_stack = TrackingExitStack()
            await mgr.close()

        asyncio.run(run())
        assert aclose_called, "close() must call _exit_stack.aclose()"

    def test_initialize_no_servers_does_not_crash(self):
        """initialize() with empty mcp_servers must complete without error."""
        config = _make_config()  # no servers
        mgr = MCPManager(config)

        async def run():
            await mgr.initialize()
            await mgr.close()

        asyncio.run(run())  # must not raise

    def test_tools_empty_when_no_servers(self):
        """tools property must be empty list when no servers configured."""
        config = _make_config()
        mgr = MCPManager(config)

        async def run():
            await mgr.initialize()

        asyncio.run(run())
        assert mgr.tools == []


# ---------------------------------------------------------------------------
# US3: Graceful degradation
# ---------------------------------------------------------------------------

class TestMCPGracefulDegradation:
    """Verify MCPManager starts with warning when server is unreachable."""

    def test_connect_failure_does_not_raise(self):
        """If a server is unreachable, initialize() must complete without raising."""
        config = _make_config([
            {"name": "bad-server", "command": "nonexistent", "args": [], "env": {}}
        ])
        mgr = MCPManager(config)

        async def run():
            import holmes.agent.mcp_manager as mcp_mod
            with patch.object(mcp_mod, "stdio_client", side_effect=FileNotFoundError("not found")):
                try:
                    await mgr.initialize()
                except Exception:
                    pass  # shouldn't reach here but let test assert below
            await mgr.close()

        asyncio.run(run())
        assert mgr.tools == [], "No tools on connect failure"
        assert len(mgr.server_status) == 1
        assert mgr.server_status[0]["connected"] is False

    def test_partial_failure_other_servers_still_loaded(self):
        """If one of two servers fails, the other's tools are still registered."""
        config = _make_config([
            {"name": "bad-server", "command": "bad", "args": [], "env": {}},
            {"name": "good-server", "command": "good", "args": [], "env": {}},
        ])
        mgr = MCPManager(config)

        mock_tool = _make_mock_tool()
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[mock_tool]))

        call_count = 0

        @asynccontextmanager
        async def selective_stdio_client(params):
            nonlocal call_count
            call_count += 1
            if params.command == "bad":
                raise ConnectionError("bad server")
            yield (AsyncMock(), AsyncMock())

        @asynccontextmanager
        async def mock_client_session(read, write):
            yield mock_session

        async def run():
            import holmes.agent.mcp_manager as mcp_mod
            with patch.object(mcp_mod, "stdio_client", selective_stdio_client), \
                 patch.object(mcp_mod, "ClientSession", mock_client_session):
                await mgr.initialize()
            await mgr.close()

        asyncio.run(run())

        statuses = {s["name"]: s for s in mgr.server_status}
        assert statuses["bad-server"]["connected"] is False
        assert statuses["good-server"]["connected"] is True
        assert len(mgr.tools) == 1


# ---------------------------------------------------------------------------
# US3: MCPProxyTool execution
# ---------------------------------------------------------------------------

class TestMCPProxyTool:
    """Verify proxy tool forwards calls to the MCP session."""

    def test_execute_returns_text_content(self):
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(
            return_value=[{"text": "hello from mcp"}]
        )
        tool = MCPProxyTool(
            tool_name="greet",
            tool_description="Greet",
            tool_schema={"type": "object", "properties": {}},
            mcp_client=mock_client,
            server_name="test",
        )

        async def run():
            return await tool.execute(name="world")

        result = asyncio.run(run())
        assert result.content == "hello from mcp"
        assert not result.is_error

    def test_execute_handles_error(self):
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(side_effect=ConnectionError("closed"))
        tool = MCPProxyTool(
            tool_name="broken",
            tool_description="Broken",
            tool_schema={"type": "object", "properties": {}},
            mcp_client=mock_client,
            server_name="test",
        )

        async def run():
            return await tool.execute()

        result = asyncio.run(run())
        assert result.is_error
        assert "closed" in result.content
