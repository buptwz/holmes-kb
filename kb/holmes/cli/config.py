"""Holmes CLI — config group and subcommands."""

from __future__ import annotations

import json
import sys

import click

from holmes.cli import cli
from holmes.config import _holmes_home, load_config, save_config


@cli.group("config")
def config_group() -> None:
    """View and update Holmes configuration."""


@config_group.command("show")
def config_show() -> None:
    """Display current configuration."""
    cfg = load_config()
    home = _holmes_home()
    click.echo(json.dumps({
        "kb_path": cfg.kb_path,
        "model": cfg.model,
        "api_base_url": cfg.api_base_url,
        "username": cfg.username,
        "config_file": str(home / "config.json"),
        "settings_file": str(home / "settings.json"),
    }, indent=2, ensure_ascii=False))


@config_group.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a configuration value."""
    from holmes.config import save_config

    cfg = load_config()
    allowed_keys = {
        "kb_path", "model", "api_key", "api_base_url", "username",
        "langfuse_enabled", "langfuse_public_key", "langfuse_secret_key", "langfuse_host",
    }
    if key not in allowed_keys:
        click.echo(f"Unknown config key: {key!r}. Allowed: {sorted(allowed_keys)}", err=True)
        sys.exit(1)
    # Bool fields: accept true/false strings
    bool_keys = {"langfuse_enabled"}
    if key in bool_keys:
        value = value.lower() in ("true", "1", "yes")  # type: ignore[assignment]
    setattr(cfg, key, value)
    save_config(cfg)
    click.echo(f"\u2713 {key} = {value}")
