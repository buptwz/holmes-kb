"""Agent server entry point.

Starts the IPC server and runs it until interrupted.
Used by: holmes tui (via subprocess) or directly: holmes agent start
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional

from holmes.agent.ipc_server import IPCServer
from holmes.agent.mcp_manager import MCPManager
from holmes.agent.tools.base import BaseTool
from holmes.agent.tools.bash import BashTool
from holmes.agent.tools.file_read import FileReadTool
from holmes.agent.tools.kb_confirm import KbConfirmEntryTool
from holmes.agent.tools.kb_read import create_kb_read_tools
from holmes.agent.tools.kb_write import KbWriteEntryTool
from holmes.config import HolmesConfig, load_config
from holmes.logging_config import configure_logging, get_logger


logger = get_logger("agent_server")


def build_tools(config: HolmesConfig, session_id: str = "") -> list[BaseTool]:
    """Build the complete tool list for a session.

    Args:
        config: Holmes configuration.
        session_id: Session ID for tools that write evidence.

    Returns:
        List of tool instances.
    """
    tools: list[BaseTool] = []

    # KB read tools (no confirmation required)
    if config.kb_path:
        kb_root = Path(config.kb_path)
        tools.extend(create_kb_read_tools(kb_root))
        tools.append(KbWriteEntryTool(kb_root))
        tools.append(KbConfirmEntryTool(kb_root, session_id))

    # Diagnostic and file tools
    tools.append(BashTool())
    tools.append(FileReadTool())

    return tools


async def run_server(socket_path: Optional[str] = None) -> None:
    """Start and run the IPC server until interrupted.

    Args:
        socket_path: Unix socket path. Defaults to /tmp/holmes-{pid}.sock.
    """
    configure_logging()
    config = load_config()

    server = IPCServer(
        config=config,
        tools_factory=build_tools,
        socket_path=socket_path,
    )

    # Initialize MCP servers if configured
    if config.mcp_servers:
        mcp_mgr = MCPManager(config)
        await mcp_mgr.initialize()
        # MCP tools will be included by re-running build_tools after init
        # For now, log status
        for status in mcp_mgr.server_status:
            logger.info(
                "MCP server %s: %s (%d tools)",
                status["name"],
                "connected" if status["connected"] else "failed",
                status.get("tool_count", 0),
            )

    await server.start()

    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _shutdown(*_):
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown)

    logger.info("Holmes agent server started. Socket: %s", server.socket_path)
    await stop_event.wait()
    await server.stop()
    logger.info("Agent server stopped")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=None, help="Unix socket path")
    args = parser.parse_args()
    asyncio.run(run_server(args.socket))
