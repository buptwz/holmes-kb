"""Shared pytest fixtures for KB Skill tests."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# @pytest.mark.llm — real LLM integration tests
#
# Skip by default. Run with: HOLMES_LLM_TESTS=1 pytest -m llm
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "llm: integration tests that make real LLM API calls (requires HOLMES_LLM_TESTS=1)",
    )
    # Enable pipeline progress logging to stderr for LLM e2e tests.
    if os.environ.get("HOLMES_LLM_TESTS") == "1":
        import logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(message)s",
            datefmt="%H:%M:%S",
        )


def pytest_collection_modifyitems(config, items):
    if os.environ.get("HOLMES_LLM_TESTS") != "1":
        skip_llm = pytest.mark.skip(reason="set HOLMES_LLM_TESTS=1 to run real LLM tests")
        for item in items:
            if item.get_closest_marker("llm"):
                item.add_marker(skip_llm)


# ---------------------------------------------------------------------------
# Real LLM fixtures (only used when HOLMES_LLM_TESTS=1)
# ---------------------------------------------------------------------------


_CONFIG_PATH = Path.home() / ".holmes" / "config.json"
_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


@pytest.fixture(scope="session")
def holmes_config() -> Any:
    """HolmesConfig-like object loaded from ~/.holmes/config.json."""
    raw = _load_config()
    cfg = MagicMock()
    cfg.api_key = raw.get("api_key", "")
    cfg.api_base_url = raw.get("api_base_url", None)
    cfg.model = raw.get("model", "gpt-4o")
    cfg.provider = "openai"
    cfg.username = raw.get("username", "e2e-tester")
    cfg.max_tokens = raw.get("max_tokens", 4096)
    return cfg


@pytest.fixture(scope="session")
def real_provider(holmes_config):
    """Real OpenAI-compatible LLMProvider using config from ~/.holmes/config.json."""
    from holmes.kb.agent.provider.openai_provider import OpenAIProvider
    return OpenAIProvider(holmes_config)


@pytest.fixture
def llm_kb_root(tmp_path: Path) -> Path:
    """Fresh KB root for LLM e2e tests."""
    return tmp_path


# ---------------------------------------------------------------------------
# Core KB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    """Return a fresh temporary KB root directory."""
    return tmp_path


def make_entry(
    kb_root: Path,
    entry_id: str = "PT-DB-001",
    extra_frontmatter: str = "",
) -> Path:
    """Create a minimal valid pitfall KB entry and return its path."""
    entry_dir = kb_root / "pitfall" / "database"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    entry_path.write_text(textwrap.dedent(f"""\
        ---
        id: {entry_id}
        type: pitfall
        title: Test Entry {entry_id}
        maturity: draft
        category: database
        tags: []
        created_at: "2024-01-01T00:00:00+00:00"
        updated_at: "2024-01-01T00:00:00+00:00"
        {extra_frontmatter}
        ---

        ## Symptoms
        Test symptoms.

        ## Root Cause
        Test root cause.

        ## Resolution
        Test resolution.
    """), encoding="utf-8")
    return entry_path
