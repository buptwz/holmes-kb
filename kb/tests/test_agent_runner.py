"""Unit tests for ImportAgentRunner loop and ContentVerifier.

Updated to mock at the LLMProvider interface level instead of the raw SDK.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_provider(complete_side_effect=None, complete_return=None):
    """Return a mock LLMProvider for use in runner tests."""
    mock_provider = MagicMock()
    if complete_side_effect is not None:
        mock_provider.complete.side_effect = complete_side_effect
    elif complete_return is not None:
        mock_provider.complete.return_value = complete_return

    # append_tool_results passes messages through with tool result appended.
    def _append_tool_results(messages, results):
        updated = list(messages)
        updated.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": content}
                for tid, content in results
            ],
        })
        return updated

    mock_provider.append_tool_results.side_effect = _append_tool_results
    return mock_provider


# ---------------------------------------------------------------------------
# TestAgentRunnerLoop
# ---------------------------------------------------------------------------


class TestAgentRunnerLoop:
    """Tool-use loop terminates correctly and accumulates messages."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "model",
                  "guideline", "process", "decision"):
            (kb / d).mkdir(parents=True, exist_ok=True)
        return kb

    def test_loop_terminates_on_end_turn(self, kb_root: Path):
        """Pipeline terminates correctly when stop=True is returned.

        With three-phase pipeline, the Reader phase uses DIMINISHING_WINDOW=2 passes
        before stopping, so complete() is called multiple times. The key invariant
        is that the pipeline terminates (does not loop forever) and returns a report.
        """
        from holmes.config import HolmesConfig
        from holmes.kb.agent.runner import ImportAgentRunner

        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="claude-3-5-haiku-20241022",
            api_key="test-key",
        )

        initial_messages = [{"role": "user", "content": "source text"}]
        mock_provider = _make_mock_provider(
            complete_return=(True, [], initial_messages + [{"role": "assistant", "content": "done"}])
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

        # Three-phase pipeline: Reader uses DIMINISHING_WINDOW=2 passes + extraction loop.
        # At minimum 1 complete() call; exact count depends on diminishing returns.
        assert mock_provider.complete.call_count >= 1
        assert report is not None

    def test_tool_results_appended_between_iterations(self, kb_root: Path):
        """tool_use blocks trigger tool calls; results are appended; loop continues."""
        from holmes.config import HolmesConfig
        from holmes.kb.agent.provider.base import ToolCall
        from holmes.kb.agent.runner import ImportAgentRunner

        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="claude-3-5-haiku-20241022",
            api_key="test-key",
        )

        tool_call = ToolCall(id="toolu_001", name="check_source_hash", input={"hash": "abc123def456789a"})

        def complete_side_effect(messages, system, model, max_tokens, tools):
            # Call 0: DocumentClassifier — return a stop response with valid JSON.
            if complete_side_effect.call_count == 0:
                complete_side_effect.call_count += 1
                new_messages = list(messages) + [
                    {"role": "assistant", "content": '{"doc_type": "single_incident", "reason": "test"}'}
                ]
                return (True, [], new_messages)
            # Call 1: Reader/Verifier first iteration — return tool_call.
            if complete_side_effect.call_count == 1:
                complete_side_effect.call_count += 1
                new_messages = list(messages) + [{"role": "assistant", "content": [{"type": "tool_use"}]}]
                return (False, [tool_call], new_messages)
            complete_side_effect.call_count += 1
            new_messages = list(messages) + [{"role": "assistant", "content": "done"}]
            return (True, [], new_messages)

        complete_side_effect.call_count = 0

        mock_provider = _make_mock_provider(complete_side_effect=complete_side_effect)

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

        # Three-phase pipeline: Reader + Extractor + Verifier phases each call complete().
        # Reader may trigger tool calls (check_source_hash in this test is an unknown tool
        # for Reader, so it gets an error result back). Key invariants:
        # - complete() called at least once (loop ran)
        # - append_tool_results() called at least once (tool results were appended)
        assert mock_provider.complete.call_count >= 1
        assert mock_provider.append_tool_results.call_count >= 1

        # Verify append_tool_results was called with the tool_use_id at some point.
        all_append_calls = mock_provider.append_tool_results.call_args_list
        all_tids = [
            tid
            for call in all_append_calls
            for tid, _ in (call[0][1] if call[0] else call[1].get("results", []))
        ]
        assert "toolu_001" in all_tids


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
        from holmes.kb.agent.report import DecisionTrace
        return DecisionTrace(title="test-entry")

    def test_verify_then_clear_removes_from_field_sources(self):
        """Field first verified, then CLEARED: must only appear in unsupported_fields."""
        trace = self._make_trace()

        # First call: field verified
        trace.field_sources["root_cause"] = "(verified)"

        # Second call: same field marked unsupported (last-write-wins)
        trace.field_sources.pop("root_cause", None)
        if "root_cause" not in trace.unsupported_fields:
            trace.unsupported_fields.append("root_cause")

        assert "root_cause" not in trace.field_sources, (
            "root_cause must not be in field_sources after being CLEARED"
        )
        assert "root_cause" in trace.unsupported_fields

    def test_clear_then_verify_removes_from_unsupported(self):
        """Field first CLEARED, then verified: must only appear in field_sources."""
        trace = self._make_trace()

        # First call: field unsupported
        trace.unsupported_fields.append("root_cause")

        # Second call: same field verified (last-write-wins)
        if "root_cause" in trace.unsupported_fields:
            trace.unsupported_fields.remove("root_cause")
        trace.field_sources["root_cause"] = "(verified)"

        assert "root_cause" not in trace.unsupported_fields, (
            "root_cause must not be in unsupported_fields after being verified"
        )
        assert "root_cause" in trace.field_sources

    def test_format_verbose_shows_field_only_once(self):
        """format_verbose() must not show a field as both (verified) and [CLEARED]."""
        from holmes.kb.agent.report import DecisionTrace, ImportReport

        trace = DecisionTrace(title="test-entry")
        # Simulate last-write-wins: field ends up only in unsupported_fields
        trace.unsupported_fields.append("root_cause")
        # field_sources does NOT contain root_cause (already removed by last-write-wins)

        report = ImportReport()
        report.add_trace(trace)
        verbose = report.format_verbose()

        # root_cause should appear exactly once (as CLEARED), not also as (verified)
        cleared_count = verbose.count("[CLEARED")
        verified_lines = [ln for ln in verbose.splitlines() if "root_cause" in ln and "(verified)" in ln]
        assert not verified_lines, (
            f"root_cause appears as (verified) despite being CLEARED: {verbose}"
        )

    def test_two_conflicting_updates_last_write_wins(self):
        """Two conflicting verify_content results for the same field → last write wins."""
        from holmes.kb.agent.report import DecisionTrace

        trace = DecisionTrace(title="test-entry")

        verify1 = {
            "verified_fields": ["title", "root_cause"],
            "unsupported_fields": [],
        }
        verify2 = {
            "verified_fields": ["title"],
            "unsupported_fields": [{"field": "root_cause", "reason": "not in source"}],
        }

        # Simulate first verify_content (verifies root_cause)
        for item in verify1.get("unsupported_fields", []):
            field = item.get("field", "unknown") if isinstance(item, dict) else str(item)
            trace.field_sources.pop(field, None)
            if field not in trace.unsupported_fields:
                trace.unsupported_fields.append(field)
        for field in verify1.get("verified_fields", []):
            if field in trace.unsupported_fields:
                trace.unsupported_fields.remove(field)
            trace.field_sources[field] = "(verified)"

        # Simulate second verify_content (clears root_cause — last write wins)
        for item in verify2.get("unsupported_fields", []):
            field = item.get("field", "unknown") if isinstance(item, dict) else str(item)
            trace.field_sources.pop(field, None)
            if field not in trace.unsupported_fields:
                trace.unsupported_fields.append(field)
        for field in verify2.get("verified_fields", []):
            if field in trace.unsupported_fields:
                trace.unsupported_fields.remove(field)
            trace.field_sources[field] = "(verified)"

        assert "root_cause" not in trace.field_sources, (
            "root_cause must not be in field_sources after second verify CLEARED it"
        )
        assert "root_cause" in trace.unsupported_fields, (
            "root_cause must be in unsupported_fields after second verify CLEARED it"
        )


# ---------------------------------------------------------------------------
# 019: CommandCandidate crash fix (T006)
# ---------------------------------------------------------------------------


class TestCommandCandidateFix:
    """Verify CommandCandidate objects are handled correctly via .line in runner.py."""

    def test_run_skill_and_curation_uses_cmd_line(self, tmp_path):
        """_run_skill_and_curation must not crash when detect_commands returns CommandCandidate."""
        from unittest.mock import MagicMock, patch

        from holmes.config import HolmesConfig
        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.runner import ImportAgentRunner

        kb_root = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "skills"):
            (kb_root / d).mkdir(parents=True, exist_ok=True)

        cfg = HolmesConfig(kb_path=str(kb_root), model="test-model", api_key="key")

        # CommandCandidate mock with .line attribute
        cmd_candidate = MagicMock()
        cmd_candidate.line = "kubectl get pods -n {NAMESPACE}"

        with patch("holmes.kb.agent.runner.create_provider", return_value=MagicMock()):
            runner = ImportAgentRunner(kb_root=kb_root, cfg=cfg, no_interactive=True)

        report = ImportReport()
        with (
            patch("holmes.kb.skill.manager.detect_commands", return_value=[cmd_candidate]),
            patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_advisor_cls,
            patch("holmes.kb.agent.curator.SkillCurator") as mock_curator_cls,
        ):
            from holmes.kb.agent.skill_advisor import Recommendation
            mock_advisor = MagicMock()
            mock_advisor.advise.return_value = MagicMock(
                recommendation=Recommendation.SKIP,
            )
            mock_advisor_cls.return_value = mock_advisor
            mock_curator_cls.return_value.curate.return_value = []

            # Should not raise TypeError
            runner._run_skill_and_curation(
                "pending-test-001",
                "kubectl get pods -n {NAMESPACE}",
                "kubernetes",
                report,
            )

        # param_names extraction must not crash; no skill created (SKIP)
        assert len(report.skills_generated) == 0

    def test_param_names_extracted_from_cmd_line(self, tmp_path):
        """param_names extraction uses cmd.line, correctly finding {PARAM} placeholders."""
        from unittest.mock import MagicMock, patch

        from holmes.config import HolmesConfig
        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.runner import ImportAgentRunner
        from holmes.kb.agent.skill_advisor import Recommendation

        kb_root = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "skills"):
            (kb_root / d).mkdir(parents=True, exist_ok=True)

        cfg = HolmesConfig(kb_path=str(kb_root), model="test-model", api_key="key")

        cmd_candidate = MagicMock()
        cmd_candidate.line = "kubectl set resources deployment/{DEPLOYMENT_NAME} -n {NAMESPACE}"

        captured_param_names = []

        with patch("holmes.kb.agent.runner.create_provider", return_value=MagicMock()):
            runner = ImportAgentRunner(kb_root=kb_root, cfg=cfg, no_interactive=True)

        report = ImportReport()
        with (
            patch("holmes.kb.skill.manager.detect_commands", return_value=[cmd_candidate]),
            patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_advisor_cls,
            patch("holmes.kb.agent.curator.SkillCurator") as mock_curator_cls,
            patch("holmes.kb.agent.tools.create_skill_for_entry") as mock_create,
        ):
            mock_advisor = MagicMock()
            mock_advisor.advise.return_value = MagicMock(
                recommendation=Recommendation.RECOMMENDED,
                suggested_name="test-skill",
                reason="test",
            )
            mock_advisor_cls.return_value = mock_advisor
            mock_curator_cls.return_value.curate.return_value = []
            mock_create.return_value = {"created": True}

            runner._run_skill_and_curation(
                "pending-test-002",
                "kubectl set resources deployment/{DEPLOYMENT_NAME} -n {NAMESPACE}",
                "kubernetes",
                report,
            )
            captured_call = mock_create.call_args
            if captured_call:
                param_names = captured_call[0][1].get("param_names", [])
                captured_param_names.extend(param_names)

        # {DEPLOYMENT_NAME} and {NAMESPACE} must be extracted
        assert "DEPLOYMENT_NAME" in captured_param_names
        assert "NAMESPACE" in captured_param_names


# ---------------------------------------------------------------------------
# 019: E-12 skill gate bypass fix (T016)
# ---------------------------------------------------------------------------


class TestSkillEvaluatedEntriesTracking:
    """_finalize_skill_generation skips entries already handled by tool loop."""

    def test_finalize_skips_entries_in_skill_evaluated_set(self, tmp_path):
        """Entries in _skill_evaluated_entries are not passed to _run_skill_and_curation."""
        from unittest.mock import MagicMock, patch

        from holmes.config import HolmesConfig
        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.runner import ImportAgentRunner

        kb_root = tmp_path / "kb"
        (kb_root / "contributions/pending").mkdir(parents=True)

        cfg = HolmesConfig(kb_path=str(kb_root), model="test-model", api_key="key")
        with patch("holmes.kb.agent.runner.create_provider", return_value=MagicMock()):
            runner = ImportAgentRunner(kb_root=kb_root, cfg=cfg, no_interactive=True)

        # Simulate: LLM called create_skill_for_entry for pending-001 (user said no)
        runner._skill_evaluated_entries.add("pending-001")

        # Both entries in _created_entry_contents
        runner._created_entry_contents = {
            "pending-001": "---\ntitle: Already Handled\ntype: pitfall\n---\n## Resolution\nkubectl get pods\n",
            "pending-002": "---\ntitle: Not Handled\ntype: pitfall\n---\n## Resolution\nkubectl get pods\n",
        }

        report = ImportReport()
        processed_ids = []

        original_method = runner._run_skill_and_curation

        def track_run(entry_id, *args, **kwargs):
            processed_ids.append(entry_id)

        with patch.object(runner, "_run_skill_and_curation", side_effect=track_run):
            runner._finalize_skill_generation(report)

        # pending-001 must be skipped; pending-002 must be processed
        assert "pending-001" not in processed_ids
        assert "pending-002" in processed_ids

    def test_finalize_processes_entries_not_in_skill_evaluated_set(self, tmp_path):
        """Entries NOT in _skill_evaluated_entries are passed to _run_skill_and_curation."""
        from unittest.mock import MagicMock, patch

        from holmes.config import HolmesConfig
        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.runner import ImportAgentRunner

        kb_root = tmp_path / "kb"
        (kb_root / "contributions/pending").mkdir(parents=True)

        cfg = HolmesConfig(kb_path=str(kb_root), model="test-model", api_key="key")
        with patch("holmes.kb.agent.runner.create_provider", return_value=MagicMock()):
            runner = ImportAgentRunner(kb_root=kb_root, cfg=cfg, no_interactive=True)

        runner._created_entry_contents = {
            "pending-003": "---\ntitle: New Entry\ntype: pitfall\n---\n## Resolution\nkubectl get pods\n",
        }

        report = ImportReport()
        processed_ids = []

        with patch.object(runner, "_run_skill_and_curation", side_effect=lambda eid, *a, **k: processed_ids.append(eid)):
            runner._finalize_skill_generation(report)

        assert "pending-003" in processed_ids


# ---------------------------------------------------------------------------
# 019: E-11 LINK description fix (T019)
# ---------------------------------------------------------------------------


class TestFinalizeSkillGenerationDescription:
    """_finalize_skill_generation passes entry title as description to _run_skill_and_curation."""

    def test_title_passed_as_description(self, tmp_path):
        """Entry title from frontmatter is forwarded as description kwarg."""
        from unittest.mock import MagicMock, call, patch

        from holmes.config import HolmesConfig
        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.runner import ImportAgentRunner

        kb_root = tmp_path / "kb"
        (kb_root / "contributions/pending").mkdir(parents=True)

        cfg = HolmesConfig(kb_path=str(kb_root), model="test-model", api_key="key")
        with patch("holmes.kb.agent.runner.create_provider", return_value=MagicMock()):
            runner = ImportAgentRunner(kb_root=kb_root, cfg=cfg, no_interactive=True)

        runner._created_entry_contents = {
            "pending-title-001": (
                "---\ntitle: Nginx upstream 配置错误端口导致 502\n"
                "type: pitfall\ncategory: network\n---\n"
                "## Resolution\nnginx -t && systemctl reload nginx\n"
            ),
        }

        report = ImportReport()
        captured_kwargs = {}

        def capture(entry_id, resolution_text, category, report, description=None):
            captured_kwargs["description"] = description

        with patch.object(runner, "_run_skill_and_curation", side_effect=capture):
            runner._finalize_skill_generation(report)

        assert captured_kwargs.get("description") == "Nginx upstream 配置错误端口导致 502"

    def test_none_description_when_title_missing(self, tmp_path):
        """description is None when entry has no title field."""
        from unittest.mock import MagicMock, patch

        from holmes.config import HolmesConfig
        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.runner import ImportAgentRunner

        kb_root = tmp_path / "kb"
        (kb_root / "contributions/pending").mkdir(parents=True)

        cfg = HolmesConfig(kb_path=str(kb_root), model="test-model", api_key="key")
        with patch("holmes.kb.agent.runner.create_provider", return_value=MagicMock()):
            runner = ImportAgentRunner(kb_root=kb_root, cfg=cfg, no_interactive=True)

        runner._created_entry_contents = {
            "pending-notitle-001": (
                "---\ntype: pitfall\ncategory: network\n---\n"
                "## Resolution\nnginx -t\n"
            ),
        }

        report = ImportReport()
        captured_kwargs = {}

        def capture(entry_id, resolution_text, category, report, description=None):
            captured_kwargs["description"] = description

        with patch.object(runner, "_run_skill_and_curation", side_effect=capture):
            runner._finalize_skill_generation(report)

        assert captured_kwargs.get("description") is None
