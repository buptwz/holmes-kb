"""Unit tests for SkillAdvisor (Anthropic Agent Skills standard).

Tests the three recommendation outcomes:
  - RECOMMENDED: entry has non-empty Resolution content
  - LINK: entry already has skill_refs (existing skill covers it)
  - SKIP: Resolution content is empty or whitespace-only
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestSkillAdvisor:
    """SkillAdvisor returns correct recommendation based on resolution content."""

    def test_resolution_content_returns_recommended(self, tmp_path: Path):
        """Any non-empty resolution text → RECOMMENDED."""
        from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor

        kb_root = tmp_path / "kb"
        kb_root.mkdir(parents=True, exist_ok=True)
        advisor = SkillAdvisor()

        result = advisor.advise(
            entry_id="PT-DB-001",
            resolution_text="Restart the database service to recover.",
            kb_root=kb_root,
        )
        assert result.recommendation == Recommendation.RECOMMENDED

    def test_multiline_resolution_returns_recommended(self, tmp_path: Path):
        """Multi-step resolution → RECOMMENDED."""
        from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor

        kb_root = tmp_path / "kb"
        kb_root.mkdir(parents=True, exist_ok=True)
        advisor = SkillAdvisor()

        resolution = (
            "1. Check connections:\n"
            "```bash\n"
            "psql -h localhost -c 'SELECT count(*) FROM pg_stat_activity'\n"
            "```\n"
            "2. Reload PgBouncer:\n"
            "```bash\n"
            "pgbouncer --reload\n"
            "```\n"
        )
        result = advisor.advise(
            entry_id="PT-DB-002",
            resolution_text=resolution,
            kb_root=kb_root,
        )
        assert result.recommendation == Recommendation.RECOMMENDED

    def test_empty_resolution_returns_skip(self, tmp_path: Path):
        """Empty resolution text → SKIP."""
        from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor

        kb_root = tmp_path / "kb"
        kb_root.mkdir(parents=True, exist_ok=True)
        advisor = SkillAdvisor()

        result = advisor.advise(
            entry_id="PT-DB-003",
            resolution_text="",
            kb_root=kb_root,
        )
        assert result.recommendation == Recommendation.SKIP

    def test_whitespace_only_resolution_returns_skip(self, tmp_path: Path):
        """Whitespace-only resolution text → SKIP."""
        from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor

        kb_root = tmp_path / "kb"
        kb_root.mkdir(parents=True, exist_ok=True)
        advisor = SkillAdvisor()

        result = advisor.advise(
            entry_id="PT-DB-004",
            resolution_text="   \n\t  ",
            kb_root=kb_root,
        )
        assert result.recommendation == Recommendation.SKIP

    def test_existing_skill_returns_link(self, tmp_path: Path):
        """Entry already has skill_refs → LINK with skill name."""
        from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor

        kb_root = tmp_path / "kb"
        (kb_root / "pitfall" / "database").mkdir(parents=True, exist_ok=True)
        entry_content = """\
---
id: PT-DB-005
type: pitfall
title: PG Connection Pool
maturity: draft
category: database
tags: []
created_at: "2026-01-01"
updated_at: "2026-01-01"
skill_refs:
  - pg-connection-recovery
---

## Resolution
Use existing skill.
"""
        (kb_root / "pitfall" / "database" / "PT-DB-005.md").write_text(entry_content)
        advisor = SkillAdvisor()
        result = advisor.advise(
            entry_id="PT-DB-005",
            resolution_text="Use existing skill.",
            kb_root=kb_root,
        )
        assert result.recommendation == Recommendation.LINK
        assert result.existing_skill == "pg-connection-recovery"

    def test_recommended_has_suggested_name(self, tmp_path: Path):
        """RECOMMENDED result includes a non-empty suggested_name slug."""
        from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor

        kb_root = tmp_path / "kb"
        kb_root.mkdir(parents=True, exist_ok=True)
        advisor = SkillAdvisor()
        result = advisor.advise("PT-DB-010", "Fix the issue by restarting.", kb_root)
        assert result.recommendation == Recommendation.RECOMMENDED
        assert result.suggested_name  # non-empty


# ---------------------------------------------------------------------------
# OPTIONAL enum must not exist
# ---------------------------------------------------------------------------


def test_optional_recommendation_removed():
    """OPTIONAL is no longer a valid Recommendation value."""
    from holmes.kb.agent.skill_advisor import Recommendation
    assert not hasattr(Recommendation, "OPTIONAL"), (
        "Recommendation.OPTIONAL should have been removed in Feature 030"
    )


# ---------------------------------------------------------------------------
# _run_skill_and_curation: RECOMMENDED → create skill; SKIP → nothing
# ---------------------------------------------------------------------------


class TestRunSkillAndCuration:
    """_run_skill_and_curation behavior under new Anthropic Agent Skills standard."""

    def _make_runner(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from holmes.config import HolmesConfig
        from holmes.kb.agent.runner import ImportAgentRunner

        kb_root = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "skills"):
            (kb_root / d).mkdir(parents=True, exist_ok=True)

        cfg = HolmesConfig(kb_path=str(kb_root), model="test-model", api_key="key")
        with patch("holmes.kb.agent.runner.create_provider", return_value=MagicMock()):
            runner = ImportAgentRunner(kb_root=kb_root, cfg=cfg, no_interactive=True)
        return runner

    def test_skip_recommendation_no_skill_created(self, tmp_path):
        """SKIP → no skill created, no suggestion."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.skill_advisor import Recommendation

        runner = self._make_runner(tmp_path)
        report = ImportReport()

        mock_advice = MagicMock()
        mock_advice.recommendation = Recommendation.SKIP
        mock_advice.suggested_name = "some-skill"
        mock_advice.reason = "no resolution"

        with patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_cls:
            mock_cls.return_value.advise.return_value = mock_advice
            runner._run_skill_and_curation("PT-TEST-001", "", "database", report)

        assert report.skills_generated == []
        assert report.skills_linked == []

    def test_recommended_with_gate_declined_adds_suggestion(self, tmp_path):
        """RECOMMENDED + gate=False (dry_run) → suggestion added."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.skill_advisor import Recommendation

        runner = self._make_runner(tmp_path)
        runner.dry_run = True
        report = ImportReport()

        mock_advice = MagicMock()
        mock_advice.recommendation = Recommendation.RECOMMENDED
        mock_advice.suggested_name = "fix-redis"
        mock_advice.reason = "Entry has Resolution content"

        with (
            patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_cls,
            patch.object(runner, "_gate_skill_create", return_value=True),
        ):
            mock_cls.return_value.advise.return_value = mock_advice
            runner._run_skill_and_curation(
                "PT-TEST-002", "Restart Redis.", "database", report
            )

        assert any("fix-redis" in s for s in report.suggestions)


# ---------------------------------------------------------------------------
# _finalize_skill_generation: updated entries evaluated, already-evaluated skipped
# ---------------------------------------------------------------------------


class TestFinalizeSkillGeneration:
    """_finalize_skill_generation evaluates skill for updated entries."""

    def _make_runner(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from holmes.config import HolmesConfig
        from holmes.kb.agent.runner import ImportAgentRunner

        kb_root = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "skills"):
            (kb_root / d).mkdir(parents=True, exist_ok=True)

        cfg = HolmesConfig(kb_path=str(kb_root), model="test-model", api_key="key")
        with patch("holmes.kb.agent.runner.create_provider", return_value=MagicMock()):
            runner = ImportAgentRunner(kb_root=kb_root, cfg=cfg, no_interactive=True)
        return runner

    def test_already_evaluated_entry_skipped(self, tmp_path):
        """Entry in _skill_evaluated_entries is not re-evaluated by finalize."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.report import ImportReport

        runner = self._make_runner(tmp_path)
        report = ImportReport()
        runner._updated_entry_ids.add("UPD-004")
        runner._skill_evaluated_entries.add("UPD-004")

        with patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_cls:
            runner._finalize_skill_generation(report)
            mock_cls.return_value.advise.assert_not_called()

        assert report.suggestions == []

    def test_updated_entry_with_resolution_evaluated(self, tmp_path):
        """Updated entry with Resolution content → SkillAdvisor.advise is called."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.skill_advisor import Recommendation

        runner = self._make_runner(tmp_path)
        report = ImportReport()
        runner._updated_entry_ids.add("UPD-005")

        mock_advice = MagicMock()
        mock_advice.recommendation = Recommendation.SKIP

        with (
            patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_cls,
            patch.object(runner, "_read_entry_content", return_value=(
                "---\ntitle: Test\ncategory: database\n---\n\n"
                "## Resolution\n\nRestart the service.\n"
            )),
        ):
            mock_cls.return_value.advise.return_value = mock_advice
            runner._finalize_skill_generation(report)
            mock_cls.return_value.advise.assert_called_once()
