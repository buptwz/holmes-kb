"""Tests for AgentEngine and KbConfirmEntryTool evidence write-back (US5)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from holmes.agent.engine import AgentEngine
from holmes.agent.session import Session
from holmes.agent.tools.base import ToolResult
from holmes.agent.tools.kb_confirm import KbConfirmEntryTool
from holmes.config import HolmesConfig


_SAMPLE_ENTRY = """\
---
id: PT-001
type: pitfall
title: Test Entry
maturity: draft
category: database
tags: []
created_at: "2026-01-01"
updated_at: "2026-01-01"
---

## Symptoms
Test.
"""


def _make_engine(kb_root: Path | None = None) -> AgentEngine:
    """Create a minimal AgentEngine for unit testing."""
    config = HolmesConfig(
        api_key="test-key",
        api_base_url="http://localhost",
        model="gpt-test",
        kb_path=str(kb_root) if kb_root else None,
    )
    session = Session()
    return AgentEngine(config=config, session=session, tools=[])


def _seed_entry(kb_root: Path) -> None:
    entry_dir = kb_root / "pitfall" / "database"
    entry_dir.mkdir(parents=True, exist_ok=True)
    (entry_dir / "PT-001.md").write_text(_SAMPLE_ENTRY, encoding="utf-8")


# ---------------------------------------------------------------------------
# Session.kb_refs — engine tracks kb_read_entry calls
# ---------------------------------------------------------------------------

def test_session_has_kb_refs_field() -> None:
    """Session must have kb_refs; it starts empty and deduplicates entries."""
    session = Session()
    assert hasattr(session, "kb_refs")
    assert session.kb_refs == []
    session.add_kb_ref("PT-001")
    session.add_kb_ref("PT-001")  # duplicate — must not be added twice
    session.add_kb_ref("PT-002")
    assert session.kb_refs == ["PT-001", "PT-002"]


# ---------------------------------------------------------------------------
# US5: KbConfirmEntryTool writes evidence immediately on call
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_kb_confirm_entry_writes_evidence(tmp_path: Path) -> None:
    """KbConfirmEntryTool.execute() writes evidence sidecar and returns success."""
    _seed_entry(tmp_path)
    tool = KbConfirmEntryTool(kb_root=tmp_path, session_id="test-session-001")
    result = await tool.execute(entry_id="PT-001")
    assert not result.is_error
    sidecar = tmp_path / "contributions" / "evidence" / "PT-001" / "test-session-001.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["session_id"] == "test-session-001"
    assert "date" in data


@pytest.mark.anyio
async def test_kb_confirm_entry_duplicate_returns_message(tmp_path: Path) -> None:
    """Calling KbConfirmEntryTool twice with the same session_id returns a duplicate message."""
    _seed_entry(tmp_path)
    tool = KbConfirmEntryTool(kb_root=tmp_path, session_id="dup-session")
    await tool.execute(entry_id="PT-001")
    result2 = await tool.execute(entry_id="PT-001")
    assert not result2.is_error
    assert "Duplicate" in result2.content or "duplicate" in result2.content
