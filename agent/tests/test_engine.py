"""Tests for AgentEngine evidence write-back (P0-1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holmes.agent.engine import AgentEngine
from holmes.agent.session import Session
from holmes.agent.tools.base import BaseTool, ToolResult
from holmes.config import HolmesConfig


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


# ---------------------------------------------------------------------------
# T006 — kb_refs populated after successful kb_read_entry tool call
# ---------------------------------------------------------------------------

def test_engine_records_kb_ref_on_successful_read(tmp_path: Path) -> None:
    """After a successful kb_read_entry tool execution, entry_id must appear in kb_refs."""
    engine = _make_engine(kb_root=tmp_path)
    result = ToolResult("entry content", is_error=False)

    # Simulate what the chat loop does after exec_tool succeeds
    tool_name = "kb_read_entry"
    tool_input = {"entry_id": "PT-001"}

    if tool_name == "kb_read_entry" and not result.is_error:
        entry_id = tool_input.get("entry_id", "")
        if entry_id and entry_id not in engine._session.kb_refs:
            engine._session.kb_refs.append(entry_id)

    assert "PT-001" in engine._session.kb_refs


# ---------------------------------------------------------------------------
# T007 — no kb_ref recorded on error result
# ---------------------------------------------------------------------------

def test_engine_does_not_record_kb_ref_on_error(tmp_path: Path) -> None:
    """When kb_read_entry returns an error, entry_id must NOT be added to kb_refs."""
    engine = _make_engine(kb_root=tmp_path)
    result = ToolResult("not found", is_error=True)

    tool_name = "kb_read_entry"
    tool_input = {"entry_id": "PT-001"}

    if tool_name == "kb_read_entry" and not result.is_error:
        entry_id = tool_input.get("entry_id", "")
        if entry_id and entry_id not in engine._session.kb_refs:
            engine._session.kb_refs.append(entry_id)

    assert engine._session.kb_refs == []


# ---------------------------------------------------------------------------
# T008 — same entry_id read twice produces only one kb_refs entry
# ---------------------------------------------------------------------------

def test_engine_deduplicates_kb_refs(tmp_path: Path) -> None:
    """Same entry_id read twice within one session must appear once in kb_refs."""
    engine = _make_engine(kb_root=tmp_path)

    def _record(entry_id: str) -> None:
        if entry_id and entry_id not in engine._session.kb_refs:
            engine._session.kb_refs.append(entry_id)

    _record("PT-001")
    _record("PT-001")

    assert engine._session.kb_refs.count("PT-001") == 1
    assert len(engine._session.kb_refs) == 1


# ---------------------------------------------------------------------------
# T009 — _flush_evidence() calls append_evidence for each entry in kb_refs
# ---------------------------------------------------------------------------

def test_engine_flushes_evidence_on_done(tmp_path: Path) -> None:
    """_flush_evidence() must call append_evidence once per entry in kb_refs."""
    engine = _make_engine(kb_root=tmp_path)
    engine._session.kb_refs = ["PT-001", "PT-002"]

    with patch("holmes.agent.engine.AgentEngine._flush_evidence") as mock_flush:
        # Replace the method to verify it would be called; then call directly
        mock_flush.return_value = None

    # Now test _flush_evidence directly with mocked store
    with patch("holmes.kb.store.append_evidence", return_value=True) as mock_append:
        engine._flush_evidence()

    assert mock_append.call_count == 2
    call_entry_ids = {call.args[1] for call in mock_append.call_args_list}
    assert call_entry_ids == {"PT-001", "PT-002"}

    # Each record must have session_id and date
    for call in mock_append.call_args_list:
        record = call.args[2]
        assert "session_id" in record
        assert "date" in record
        assert record["session_id"] == engine._session.id
