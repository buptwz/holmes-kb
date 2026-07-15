"""Holmes CLI entry point.

Commands::

    holmes setup          -- configure KB path and model settings
    holmes import <file>  -- import a document into KB pending area
    holmes overview       -- show KB overview (README + index)
    holmes search         -- full-text search
    holmes show <id>      -- show a KB entry by ID
    holmes pending        -- list pending entries
    holmes approve <id>   -- approve a pending entry
    holmes delete <id>    -- soft-delete a KB entry
    holmes decay          -- run maturity decay check
    holmes doctor         -- self-diagnostic with optional --fix
    holmes history <id>   -- show version snapshots
    holmes list           -- list all KB entries
    holmes lint           -- health check
    holmes start          -- start MCP server

Legacy ``holmes kb <cmd>`` syntax still works for backward compatibility.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

from holmes.config import HolmesConfig, _holmes_home, load_config, save_config


# ---------------------------------------------------------------------------
# Main group
# ---------------------------------------------------------------------------


def _get_version() -> str:
    try:
        from importlib.metadata import version as _meta_version
        return _meta_version("holmes-kb")
    except Exception:
        return "0.1.0"


@click.group(invoke_without_command=True)
@click.version_option(_get_version(), "--version", "-v", prog_name="holmes")
@click.option("--kb-path", envvar="HOLMES_KB_PATH", default=None,
              help="Path to the knowledge base directory.")
@click.pass_context
def cli(ctx: click.Context, kb_path: Optional[str]) -> None:
    """Holmes -- knowledge-based troubleshooting assistant."""
    ctx.ensure_object(dict)
    if kb_path:
        ctx.obj["kb_path"] = kb_path
    else:
        cfg = load_config()
        ctx.obj["kb_path"] = cfg.kb_path or None


# ---------------------------------------------------------------------------
# Legacy `holmes kb <cmd>` group (hidden, backward compat)
# ---------------------------------------------------------------------------


@cli.group("kb", hidden=True)
@click.option("--kb-path", envvar="HOLMES_KB_PATH", default=None)
@click.pass_context
def kb(ctx: click.Context, kb_path: Optional[str]) -> None:
    """Knowledge base management commands (legacy -- use `holmes <cmd>` directly)."""
    ctx.ensure_object(dict)
    if kb_path:
        ctx.obj["kb_path"] = kb_path


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _require_kb_root(ctx: click.Context) -> Path:
    kb_path = ctx.obj.get("kb_path") or load_config().kb_path
    if not kb_path:
        click.echo("KB path not configured. Run: holmes setup --kb-path <path>", err=True)
        sys.exit(1)
    return Path(kb_path)


# ---------------------------------------------------------------------------
# Register all command modules (lazy imports keep startup fast)
# ---------------------------------------------------------------------------

# Import command modules — each module registers its commands on `cli` or `kb`
# at import time via decorators. Order doesn't matter for Click.
from holmes.cli import (  # noqa: E402, F401
    setup_cmd,
    import_cmd,
    browse,
    pending,
    confirm,
    governance,
    config,
    server,
    log,
)
