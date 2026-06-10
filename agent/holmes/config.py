"""Holmes configuration management.

Reads and writes ~/.holmes/config.json. Validates kb_path and mcp_servers.
"""

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator


HOLMES_DIR = Path(os.environ.get("HOLMES_HOME", Path.home() / ".holmes"))
CONFIG_PATH = HOLMES_DIR / "config.json"


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server."""

    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}


class HolmesConfig(BaseModel):
    """Holmes agent configuration."""

    kb_path: str = ""
    mcp_servers: list[MCPServerConfig] = []
    log_level: str = "INFO"
    model: str = "gpt-4o"
    max_tokens: int = 8192
    # OpenAI-compatible API settings
    api_base_url: str = ""   # e.g. https://your-proxy.com/v1
    api_key: str = ""        # overrides OPENAI_API_KEY env var if set

    @field_validator("kb_path")
    @classmethod
    def validate_kb_path(cls, v: str) -> str:
        """Validate that kb_path exists if provided."""
        if v and not Path(v).is_dir():
            raise ValueError(f"kb_path does not exist or is not a directory: {v}")
        return v

    def get_kb_path(self) -> Path:
        """Return kb_path as a resolved Path object."""
        if not self.kb_path:
            raise ValueError(
                "kb_path is not configured. Run 'holmes config init' to set it up."
            )
        return Path(self.kb_path).resolve()


def load_config() -> HolmesConfig:
    """Load configuration from ~/.holmes/config.json.

    Returns default config if file does not exist.
    """
    if not CONFIG_PATH.exists():
        return HolmesConfig()
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return HolmesConfig(**data)


def save_config(config: HolmesConfig) -> None:
    """Save configuration to ~/.holmes/config.json."""
    HOLMES_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, indent=2)


def update_config(updates: dict[str, Any]) -> HolmesConfig:
    """Load, update, and save config. Returns updated config."""
    config = load_config()
    data = config.model_dump()
    data.update(updates)
    updated = HolmesConfig(**data)
    save_config(updated)
    return updated
