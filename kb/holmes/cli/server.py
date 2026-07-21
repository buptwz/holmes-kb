"""Holmes CLI — start command (MCP server)."""

from __future__ import annotations

import click

from holmes.cli import _require_kb_root, cli


@cli.command("start")
@click.option("--port", default=8765, help="Port for MCP server (default: 8765)")
@click.option(
    "--mode",
    type=click.Choice(["local", "central"]),
    default="local",
    help=(
        "Deployment mode: local (loopback, no auth, git-config identity) or "
        "central (shared server — bearer token auth via config mcp_token, "
        "contributor param enforced). Default: local"
    ),
)
@click.option(
    "--host",
    default=None,
    help="Interface to bind (default: 127.0.0.1 local, 0.0.0.0 central)",
)
@click.pass_context
def start_cmd(ctx: click.Context, port: int, mode: str, host: str | None) -> None:
    """Start the Holmes KB MCP server (streamable-http transport).

    Client config: {"url": "http://localhost:<port>"}
    Central mode requires: holmes config set mcp_token <token>
    """
    kb_root = _require_kb_root(ctx)
    bind_host = host or ("0.0.0.0" if mode == "central" else "127.0.0.1")
    click.echo(f"Holmes KB MCP server ({mode} mode) running at http://{bind_host}:{port}")
    from holmes.mcp.server import run_server
    run_server(kb_root, port=port, host=bind_host, mode=mode)
