"""Holmes CLI — start command (MCP server)."""

from __future__ import annotations

import click

from holmes.cli import cli, _require_kb_root


@cli.command("start")
@click.option("--port", default=8765, help="Port for MCP server (default: 8765)")
@click.pass_context
def start_cmd(ctx: click.Context, port: int) -> None:
    """Start the Holmes KB MCP server (streamable-http transport).

    Client config: {"url": "http://localhost:<port>"}
    """
    kb_root = _require_kb_root(ctx)
    click.echo(f"Holmes KB MCP server running at http://localhost:{port}")
    from holmes.mcp.server import run_server
    run_server(kb_root, port=port)
