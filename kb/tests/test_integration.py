"""Integration tests — full KB lifecycle chain (mock LLM).

Tests the end-to-end flow:
  holmes setup → holmes kb search → holmes import → holmes kb confirm
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from holmes.cli import cli
from holmes.config import HolmesConfig, save_config


_MOCK_LLM_CONTENT = """\
---
id: ""
type: pitfall
title: Redis Connection Pool Exhausted
maturity: draft
category: database
tags: [redis, connection-pool]
created_at: ""
updated_at: ""
---

## Symptoms
Connection timeouts under peak load.

## Root Cause
Connection pool is too small for the workload.

## Resolution
Increase `maxclients` in redis.conf and restart.
"""


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    (kb / "pitfall" / "database").mkdir(parents=True)
    (kb / "contributions" / "pending").mkdir(parents=True)
    (kb / "model").mkdir()
    (kb / "guideline").mkdir()
    (kb / "process").mkdir()
    (kb / "decision").mkdir()
    return kb


@pytest.fixture
def holmes_home(tmp_path: Path, kb_root: Path) -> Path:
    home = tmp_path / "holmes_home"
    home.mkdir()
    cfg = HolmesConfig(
        kb_path=str(kb_root),
        model="mock-model",
        api_key="test-key",
        api_base_url="http://localhost",
    )
    save_config(cfg, holmes_home=home)
    return home


def _mock_openai() -> MagicMock:
    mock = MagicMock()
    choice = MagicMock()
    choice.message.content = _MOCK_LLM_CONTENT
    response = MagicMock()
    response.choices = [choice]
    mock.chat.completions.create = AsyncMock(return_value=response)
    return mock


def test_setup_command(tmp_path: Path, kb_root: Path):
    """holmes setup writes config.json and settings.json."""
    holmes_home = tmp_path / "holmes_cfg"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "setup",
        "--kb-path", str(kb_root),
        "--model", "gpt-4o",
        "--api-key", "test-key",
        "--api-base-url", "http://localhost",
    ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)
    assert result.exit_code == 0
    assert (holmes_home / "config.json").exists()
    assert (holmes_home / "settings.json").exists()
    settings = json.loads((holmes_home / "settings.json").read_text())
    assert settings["env"]["HOLMES_KB_PATH"] == str(kb_root)


def test_kb_search_empty_kb(kb_root: Path, holmes_home: Path):
    """holmes kb search returns no results on empty KB."""
    runner = CliRunner()
    result = runner.invoke(cli, [
        "kb", "--kb-path", str(kb_root), "search", "Redis", "--json",
    ], catch_exceptions=False)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data == []


def test_import_and_confirm_flow(tmp_path: Path, kb_root: Path, holmes_home: Path):
    """Full flow: import document → pending → confirm → official KB."""
    doc = tmp_path / "incident.md"
    doc.write_text(
        "Redis connection timeouts observed during peak hours. "
        "Root cause was connection pool exhaustion. "
        "Resolved by increasing maxclients in redis.conf.",
        encoding="utf-8",
    )

    runner = CliRunner()

    # Import document (mock LLM).
    mock_client = _mock_openai()
    with patch("holmes.kb.importer.openai.AsyncOpenAI", return_value=mock_client):
        result = runner.invoke(cli, [
            "--kb-path", str(kb_root),
            "import", str(doc),
        ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)
    assert result.exit_code == 0
    assert "Saved" in result.output
    pending_id = [
        line.split()[-1]
        for line in result.output.splitlines()
        if "Saved" in line
    ][0]

    # Verify pending entry exists.
    pending_dir = kb_root / "contributions" / "pending"
    pending_files = list(pending_dir.glob("*.md"))
    assert len(pending_files) == 1

    # Confirm the pending entry (simulate all gates passing with y\n response).
    result = runner.invoke(cli, [
        "kb", "--kb-path", str(kb_root), "confirm", pending_id,
    ], input="y\ny\n", catch_exceptions=False)
    assert result.exit_code == 0
    assert "confirmed" in result.output.lower()

    # Verify entry is now in official KB.
    from holmes.kb.store import list_entries
    entries = list_entries(kb_root)
    assert len(entries) == 1
    assert entries[0].type == "pitfall"
    assert entries[0].category == "database"

    # Search should now find it.
    result = runner.invoke(cli, [
        "kb", "--kb-path", str(kb_root), "search", "Redis", "--json",
    ], catch_exceptions=False)
    data = json.loads(result.output)
    assert len(data) >= 1
    assert any("Redis" in r.get("title", "") for r in data)
