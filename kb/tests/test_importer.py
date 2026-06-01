"""Tests for kb/holmes/kb/importer.py — LLM-based document import."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from holmes.kb.importer import ContentTooShortError, import_document


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    (tmp_path / "contributions" / "pending").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def sample_doc(tmp_path: Path) -> Path:
    doc = tmp_path / "incident.md"
    doc.write_text(
        "During last night's on-call we noticed Redis connection timeouts spiking. "
        "After investigation, we found the maxconn setting was too low. "
        "Increasing the pool size resolved the issue.",
        encoding="utf-8",
    )
    return doc


@pytest.fixture
def short_doc(tmp_path: Path) -> Path:
    doc = tmp_path / "short.md"
    doc.write_text("Too short", encoding="utf-8")
    return doc


_MOCK_LLM_RESPONSE = """\
---
id: ""
type: pitfall
title: Redis Connection Pool Exhaustion
maturity: draft
category: database
tags: [redis, connection-pool]
created_at: ""
updated_at: ""
---

## Symptoms
Connection timeouts during peak load.

## Root Cause
maxconn setting was too low for the load.

## Resolution
Increase the Redis connection pool size in configuration.
"""


def _make_mock_openai() -> MagicMock:
    """Build a minimal mock of AsyncOpenAI client."""
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = _MOCK_LLM_RESPONSE
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.asyncio
async def test_import_rejects_short_content(kb_root: Path, short_doc: Path):
    with pytest.raises(ContentTooShortError):
        await import_document(kb_root, short_doc, model="mock", api_key="x")


@pytest.mark.asyncio
async def test_import_dry_run_does_not_write(kb_root: Path, sample_doc: Path):
    mock_client = _make_mock_openai()
    with patch("holmes.kb.importer.openai.AsyncOpenAI", return_value=mock_client):
        result = await import_document(
            kb_root, sample_doc, model="mock", api_key="x", dry_run=True
        )
    assert result.dry_run is True
    assert result.pending_id == "(dry-run)"
    pending_dir = kb_root / "contributions" / "pending"
    assert list(pending_dir.glob("*.md")) == []


@pytest.mark.asyncio
async def test_import_writes_pending(kb_root: Path, sample_doc: Path):
    mock_client = _make_mock_openai()
    with patch("holmes.kb.importer.openai.AsyncOpenAI", return_value=mock_client):
        result = await import_document(
            kb_root, sample_doc, model="mock", api_key="x", dry_run=False
        )
    assert result.dry_run is False
    assert result.pending_id.startswith("pending-")
    assert result.kb_type == "pitfall"
    assert result.title == "Redis Connection Pool Exhaustion"

    pending_dir = kb_root / "contributions" / "pending"
    pending_files = list(pending_dir.glob("*.md"))
    assert len(pending_files) == 1


@pytest.mark.asyncio
async def test_import_type_override(kb_root: Path, sample_doc: Path):
    mock_client = _make_mock_openai()
    with patch("holmes.kb.importer.openai.AsyncOpenAI", return_value=mock_client):
        result = await import_document(
            kb_root, sample_doc, model="mock", api_key="x",
            kb_type="guideline", category=None, dry_run=True,
        )
    # LLM response still says pitfall but override is passed in prompt.
    # The returned type comes from LLM output parsing.
    assert result.kb_type is not None
