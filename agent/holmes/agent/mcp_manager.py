"""MCP server manager for Holmes Agent.

Reads mcp_servers from config, connects to each server,
and proxies their tools as BaseTool instances.

Connections are kept alive for the agent process lifetime via AsyncExitStack.
Call close() on shutdown to release all connections.
"""

from __future__ import annotations

import contextlib
from typing import Any, Optional

from holmes.agent.tools.base import BaseTool, ToolResult
from holmes.config import HolmesConfig, MCPServerConfig
from holmes.logging_config import get_logger

# MCP SDK is optional; imported at module level so tests can patch these names.
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:  # pragma: no cover
    ClientSession = None  # type: ignore[assignment,misc]
    StdioServerParameters = None  # type: ignore[assignment]
    stdio_client = None  # type: ignore[assignment]


logger = get_logger("agent.mcp_manager")


class MCPProxyTool(BaseTool):
    """Proxy tool that delegates execution to an MCP server tool.

    Args:
        tool_name: Original tool name from MCP server.
        tool_description: Tool description from MCP server.
        tool_schema: JSON Schema for the tool's input.
        mcp_client: Connected MCP client instance.
    """

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        tool_schema: dict[str, Any],
        mcp_client: Any,
        server_name: str,
    ) -> None:
        self.name = tool_name
        self.description = f"[MCP:{server_name}] {tool_description}"
        self.input_schema = tool_schema
        self.requires_confirmation = False
        self._mcp_client = mcp_client
        self._server_name = server_name

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool via MCP client.

        Args:
            **kwargs: Tool input parameters.

        Returns:
            ToolResult with the tool's output.
        """
        try:
            result = await self._mcp_client.call_tool(self.name, kwargs)
            # MCP result is typically a list of content blocks
            if isinstance(result, list):
                text_parts = [
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in result
                ]
                return ToolResult("\n".join(text_parts))
            return ToolResult(str(result))
        except Exception as e:
            logger.error("MCP tool %s failed: %s", self.name, e)
            return ToolResult(f"MCP tool error: {e}", is_error=True)


class MCPManager:
    """Manages connections to configured MCP servers.

    Reads from config.mcp_servers and registers proxy tools.
    Gracefully degrades if a server is unavailable.

    Connection lifecycle:
        await mgr.initialize()   # connect all servers; connections stay open
        # ... agent runs ...
        await mgr.close()        # release all connections on shutdown
    """

    def __init__(self, config: HolmesConfig) -> None:
        self._config = config
        self._tools: list[BaseTool] = []
        self._server_status: list[dict[str, Any]] = []
        self._exit_stack: contextlib.AsyncExitStack = contextlib.AsyncExitStack()

    async def initialize(self) -> None:
        """Connect to all configured MCP servers and discover tools.

        Connections are held open via AsyncExitStack until close() is called.
        """
        await self._exit_stack.__aenter__()
        if not self._config.mcp_servers:
            return

        for server_cfg in self._config.mcp_servers:
            await self._connect_server(server_cfg)

    async def close(self) -> None:
        """Close all MCP server connections."""
        await self._exit_stack.aclose()
        logger.info("MCPManager closed %d server connection(s)", len(self._server_status))

    async def _connect_server(self, server_cfg: MCPServerConfig) -> None:
        """Connect to a single MCP server and register its tools.

        Uses AsyncExitStack to keep the connection open past this method call.

        Args:
            server_cfg: MCP server configuration.
        """
        try:
            if stdio_client is None or ClientSession is None or StdioServerParameters is None:
                raise ImportError("mcp SDK not installed")

            params = StdioServerParameters(
                command=server_cfg.command,
                args=server_cfg.args,
                env=server_cfg.env or None,
            )

            read, write = await self._exit_stack.enter_async_context(
                stdio_client(params)
            )
            session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            tools_response = await session.list_tools()
            proxy_tools = []
            for tool in tools_response.tools:
                proxy = MCPProxyTool(
                    tool_name=tool.name,
                    tool_description=tool.description or "",
                    tool_schema=tool.inputSchema or {"type": "object", "properties": {}},
                    mcp_client=session,
                    server_name=server_cfg.name,
                )
                proxy_tools.append(proxy)
            self._tools.extend(proxy_tools)
            self._server_status.append({
                "name": server_cfg.name,
                "connected": True,
                "tool_count": len(proxy_tools),
            })
            logger.info(
                "Connected to MCP server %s (%d tools)",
                server_cfg.name,
                len(proxy_tools),
            )
        except Exception as e:
            logger.warning("Failed to connect to MCP server %s: %s", server_cfg.name, e)
            self._server_status.append({
                "name": server_cfg.name,
                "connected": False,
                "tool_count": 0,
                "error": str(e),
            })

    @property
    def tools(self) -> list[BaseTool]:
        """Return all successfully loaded MCP proxy tools."""
        return self._tools

    @property
    def server_status(self) -> list[dict[str, Any]]:
        """Return connection status for all configured servers."""
        return self._server_status
