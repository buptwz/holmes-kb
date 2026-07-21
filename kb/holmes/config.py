"""Holmes configuration management.

Reads and writes ~/.holmes/config.json (or $HOLMES_HOME/config.json).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


def _holmes_home() -> Path:
    """Return the Holmes config directory, honouring HOLMES_HOME env var."""
    env = os.environ.get("HOLMES_HOME")
    if env:
        return Path(env)
    return Path.home() / ".holmes"


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server (consumed by holmes.agent)."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class HolmesConfig:
    """Holmes runtime configuration."""

    kb_path: str = ""
    model: str = "gpt-4o"
    api_base_url: str = ""
    api_key: str = ""
    log_level: str = "WARNING"
    max_tokens: int = 4096
    provider: str = "openai"
    # M1: username is written to contributors[].user during import.
    username: str = ""
    # D4: static bearer token for the MCP server in central mode.
    mcp_token: str = ""
    # Import pipeline tunables; 0 means "use the code default"
    # (READ_CHUNK_CHARS / DIRECT_MODE_CHAR_LIMIT in holmes.kb.agent).
    read_chunk_chars: int = 0
    direct_mode_char_limit: int = 0
    # MCP servers consumed by the holmes.agent package (namespace compat).
    mcp_servers: list[MCPServerConfig] = field(default_factory=list)
    # Langfuse observability (optional, disabled by default)
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "HolmesConfig":
        """Create HolmesConfig from a plain dictionary."""
        return cls(
            kb_path=data.get("kb_path", ""),
            model=data.get("model", "gpt-4o"),
            api_base_url=data.get("api_base_url", ""),
            api_key=data.get("api_key", ""),
            log_level=data.get("log_level", "WARNING"),
            max_tokens=int(data.get("max_tokens", 4096)),
            provider=data.get("provider", "openai"),
            username=data.get("username", ""),
            mcp_token=data.get("mcp_token", ""),
            read_chunk_chars=int(data.get("read_chunk_chars", 0)),
            direct_mode_char_limit=int(data.get("direct_mode_char_limit", 0)),
            mcp_servers=[
                MCPServerConfig(**s) for s in data.get("mcp_servers", [])
            ],
            langfuse_enabled=bool(data.get("langfuse_enabled", False)),
            langfuse_public_key=data.get("langfuse_public_key", ""),
            langfuse_secret_key=data.get("langfuse_secret_key", ""),
            langfuse_host=data.get("langfuse_host", ""),
        )

    def to_dict(self) -> dict:
        """Convert config to a plain dictionary."""
        return asdict(self)


def load_config(holmes_home: Optional[Path] = None) -> HolmesConfig:
    """Load HolmesConfig from the config file.

    Args:
        holmes_home: Override for the Holmes home directory.

    Returns:
        Loaded HolmesConfig (defaults if file missing).
    """
    home = holmes_home or _holmes_home()
    config_path = home / "config.json"
    if not config_path.exists():
        return HolmesConfig()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return HolmesConfig.from_dict(data)
    except (json.JSONDecodeError, OSError):
        return HolmesConfig()


def save_config(config: HolmesConfig, holmes_home: Optional[Path] = None) -> None:
    """Persist HolmesConfig to disk.

    Args:
        config: Configuration to save.
        holmes_home: Override for the Holmes home directory.
    """
    home = holmes_home or _holmes_home()
    home.mkdir(parents=True, exist_ok=True)
    config_path = home / "config.json"
    config_path.write_text(
        json.dumps(config.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
