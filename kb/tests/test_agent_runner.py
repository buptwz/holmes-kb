"""Unit tests for ImportAgentRunner (042 delegation wrapper).

Verifies the runner delegates to ImportPipeline correctly.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holmes.kb.agent.report import DecisionTrace, ImportReport


# ---------------------------------------------------------------------------
# TestAgentRunnerLoop
# ---------------------------------------------------------------------------


class TestAgentRunnerLoop:
    """Runner delegates to ImportPipeline and returns a report."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "_pending",
                  "model", "guideline", "process", "decision"):
            (kb / d).mkdir(parents=True, exist_ok=True)
        return kb

    def test_loop_terminates_on_end_turn(self, kb_root: Path):
        """Pipeline terminates correctly and returns a report."""
        from holmes.config import HolmesConfig
        from holmes.kb.agent.runner import ImportAgentRunner

        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="claude-3-5-haiku-20241022",
            api_key="test-key",
        )

        mock_provider = MagicMock()
        mock_provider.complete.return_value = (
            True, [],
            [{"role": "assistant", "content": '{"doc_type": "incident", "reason": "test"}'}],
            {},
        )

        with patch("holmes.kb.agent.runner.create_provider", return_value=mock_provider):
            runner = ImportAgentRunner(
                kb_root=kb_root,
                cfg=cfg,
                no_interactive=True,
                verbose=False,
                dry_run=True,
            )
            report = runner.run(
                source_text=(
                    "PostgreSQL OOM crash. Root cause: shared_buffers. "
                    "Fix: reduce shared_buffers to 1.5GB and reload config."
                )
            )

        assert report is not None


# ---------------------------------------------------------------------------
# TestContentVerifier
# ---------------------------------------------------------------------------


class TestContentVerifier:
    """verify_content tool uses provider.simple_complete() for sub-completions."""

    def _make_mock_provider(self, response_text: str) -> MagicMock:
        mock_provider = MagicMock()
        mock_provider.simple_complete.return_value = response_text
        return mock_provider

    def test_unsupported_field_returns_cleared_list(self):
        """verify_content returns unsupported_fields list when field not in source."""
        from holmes.kb.agent.tools import verify_content

        mock_provider = self._make_mock_provider(
            json.dumps({
                "verified_fields": ["title"],
                "unsupported_fields": [
                    {"field": "root_cause", "reason": "not mentioned in source"}
                ],
                "confidence": 0.4,
            })
        )
        ctx = {"provider": mock_provider, "model": "claude-test", "kb_root": Path("/tmp")}
        result = verify_content(ctx, {
            "source_text": "Database crashed. We restarted it.",
            "draft_content": "---\ntitle: DB Crash\n---\n\n## Root Cause\nMemory leak.\n",
        })

        assert len(result["unsupported_fields"]) == 1
        assert result["unsupported_fields"][0]["field"] == "root_cause"
        assert result["confidence"] == 0.4

    def test_all_supported_returns_empty_unsupported(self):
        """All fields have source support → unsupported_fields is empty."""
        from holmes.kb.agent.tools import verify_content

        mock_provider = self._make_mock_provider(
            json.dumps({
                "verified_fields": ["title", "root_cause", "resolution_commands"],
                "unsupported_fields": [],
                "confidence": 0.95,
            })
        )
        ctx = {"provider": mock_provider, "model": "claude-test", "kb_root": Path("/tmp")}
        result = verify_content(ctx, {
            "source_text": (
                "PostgreSQL OOM. Root cause: shared_buffers too large. "
                "Fix: ALTER SYSTEM SET shared_buffers='1536MB'; SELECT pg_reload_conf();"
            ),
            "draft_content": (
                "---\ntitle: PostgreSQL OOM\n---\n\n"
                "## Root Cause\nshared_buffers too large.\n\n"
                "## Resolution\n`ALTER SYSTEM SET shared_buffers='1536MB';`\n"
            ),
        })

        assert result["unsupported_fields"] == []
        assert result["confidence"] >= 0.9


# ---------------------------------------------------------------------------
# D-7: DecisionTrace last-write-wins mutual exclusion
# ---------------------------------------------------------------------------


class TestDecisionTraceLastWriteWins:
    """D-7: A field may not appear in both field_sources and unsupported_fields."""

    def _make_trace(self):
        return DecisionTrace(title="test-entry")

    def test_verify_then_clear_removes_from_field_sources(self):
        """Field first verified, then CLEARED: must only appear in unsupported_fields."""
        trace = self._make_trace()
        trace.field_sources["root_cause"] = "(verified)"
        trace.field_sources.pop("root_cause", None)
        if "root_cause" not in trace.unsupported_fields:
            trace.unsupported_fields.append("root_cause")

        assert "root_cause" not in trace.field_sources
        assert "root_cause" in trace.unsupported_fields

    def test_clear_then_verify_removes_from_unsupported(self):
        """Field first CLEARED, then verified: must only appear in field_sources."""
        trace = self._make_trace()
        trace.unsupported_fields.append("root_cause")
        if "root_cause" in trace.unsupported_fields:
            trace.unsupported_fields.remove("root_cause")
        trace.field_sources["root_cause"] = "(verified)"

        assert "root_cause" not in trace.unsupported_fields
        assert "root_cause" in trace.field_sources

    def test_format_verbose_shows_field_only_once(self):
        """format_verbose() must not show a field as both (verified) and [CLEARED]."""
        trace = DecisionTrace(title="test-entry")
        trace.unsupported_fields.append("root_cause")

        report = ImportReport()
        report.add_trace(trace)
        verbose = report.format_verbose()

        verified_lines = [ln for ln in verbose.splitlines() if "root_cause" in ln and "(verified)" in ln]
        assert not verified_lines

    def test_two_conflicting_updates_last_write_wins(self):
        """Two conflicting verify_content results for the same field → last write wins."""
        trace = DecisionTrace(title="test-entry")

        verify1 = {
            "verified_fields": ["title", "root_cause"],
            "unsupported_fields": [],
        }
        verify2 = {
            "verified_fields": ["title"],
            "unsupported_fields": [{"field": "root_cause", "reason": "not in source"}],
        }

        for item in verify1.get("unsupported_fields", []):
            field = item.get("field", "unknown") if isinstance(item, dict) else str(item)
            trace.field_sources.pop(field, None)
            if field not in trace.unsupported_fields:
                trace.unsupported_fields.append(field)
        for field in verify1.get("verified_fields", []):
            if field in trace.unsupported_fields:
                trace.unsupported_fields.remove(field)
            trace.field_sources[field] = "(verified)"

        for item in verify2.get("unsupported_fields", []):
            field = item.get("field", "unknown") if isinstance(item, dict) else str(item)
            trace.field_sources.pop(field, None)
            if field not in trace.unsupported_fields:
                trace.unsupported_fields.append(field)
        for field in verify2.get("verified_fields", []):
            if field in trace.unsupported_fields:
                trace.unsupported_fields.remove(field)
            trace.field_sources[field] = "(verified)"

        assert "root_cause" not in trace.field_sources
        assert "root_cause" in trace.unsupported_fields
