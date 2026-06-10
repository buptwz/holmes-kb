"""Unit tests for SkillAdvisor (T025 [US5]).

Tests the three recommendation outcomes:
  - SKIP: no commands or fewer than 3 steps
  - RECOMMENDED: 3+ steps or parameter placeholders
  - LINK: existing skill already covers entry
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestSkillAdvisor:
    """T025: SkillAdvisor returns correct recommendation based on resolution content."""

    def test_fewer_than_3_steps_returns_skip(self, tmp_path: Path):
        """T025a: resolution with 0 commands → Recommendation.SKIP."""
        from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor

        kb_root = tmp_path / "kb"
        kb_root.mkdir(parents=True, exist_ok=True)
        advisor = SkillAdvisor()

        result = advisor.advise(
            entry_id="PT-DB-001",
            resolution_text="Restart the database service to recover.",
            kb_root=kb_root,
        )
        # No commands detected → SKIP or OPTIONAL
        assert result.recommendation in (Recommendation.SKIP, Recommendation.OPTIONAL)

    def test_3_steps_with_placeholder_returns_recommended(self, tmp_path: Path):
        """T025b: 3+ steps + {param} placeholder → Recommendation.RECOMMENDED."""
        from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor

        kb_root = tmp_path / "kb"
        kb_root.mkdir(parents=True, exist_ok=True)
        advisor = SkillAdvisor()

        resolution = (
            "1. Check connections:\n"
            "```bash\n"
            "psql -h {host} -c 'SELECT count(*) FROM pg_stat_activity'\n"
            "```\n"
            "2. Set pool size:\n"
            "```bash\n"
            "pgbouncer-set-pool --size {pool_size} --db {database}\n"
            "```\n"
            "3. Reload PgBouncer:\n"
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

    def test_existing_skill_returns_link(self, tmp_path: Path):
        """T025c: entry already has skill_refs → Recommendation.LINK with skill name."""
        from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor

        kb_root = tmp_path / "kb"
        (kb_root / "pitfall" / "database").mkdir(parents=True, exist_ok=True)
        # Create a minimal entry with skill_refs.
        entry_content = """\
---
id: PT-DB-003
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
        (kb_root / "pitfall" / "database" / "PT-DB-003.md").write_text(entry_content)
        advisor = SkillAdvisor()
        result = advisor.advise(
            entry_id="PT-DB-003",
            resolution_text="Use existing skill.",
            kb_root=kb_root,
        )
        assert result.recommendation == Recommendation.LINK
        assert result.existing_skill == "pg-connection-recovery"


# ---------------------------------------------------------------------------
# 018 E-8: Threshold tests — RECOMMENDED ≥3, OPTIONAL 1-2
# ---------------------------------------------------------------------------


def test_three_commands_recommended(tmp_path):
    """018 E-8: 3 commands in a code block → RECOMMENDED."""
    from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor
    resolution = (
        "```bash\n"
        "kubectl get pods -n default\n"
        "kubectl delete pod {POD_NAME} -n default\n"
        "kubectl rollout restart deployment/api\n"
        "```\n"
    )
    advisor = SkillAdvisor()
    result = advisor.advise("PT-K8-001", resolution, tmp_path)
    assert result.recommendation == Recommendation.RECOMMENDED


def test_two_commands_optional(tmp_path):
    """018 E-8: 2 commands in a code block → OPTIONAL (not RECOMMENDED)."""
    from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor
    resolution = (
        "```bash\n"
        "kubectl get pods -n default\n"
        "kubectl delete pod my-pod -n default\n"
        "```\n"
    )
    advisor = SkillAdvisor()
    result = advisor.advise("PT-K8-002", resolution, tmp_path)
    assert result.recommendation == Recommendation.OPTIONAL


def test_one_command_optional(tmp_path):
    """018 E-8: 1 command in a code block → OPTIONAL."""
    from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor
    resolution = "```bash\nkubectl rollout restart deployment/api\n```\n"
    advisor = SkillAdvisor()
    result = advisor.advise("PT-K8-003", resolution, tmp_path)
    assert result.recommendation == Recommendation.OPTIONAL


def test_zero_commands_skip(tmp_path):
    """018 E-8: 0 commands → SKIP."""
    from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor
    resolution = "Check the application logs manually."
    advisor = SkillAdvisor()
    result = advisor.advise("PT-APP-001", resolution, tmp_path)
    assert result.recommendation == Recommendation.SKIP


# ---------------------------------------------------------------------------
# T014-T016 (021): _run_skill_and_curation OPTIONAL/RECOMMENDED/0-cmd paths
# ---------------------------------------------------------------------------


class TestRunSkillAndCurationOptionalPath:
    """021 T014-T016: _run_skill_and_curation adds 'skill candidate' for OPTIONAL."""

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

    def test_one_command_triggers_skill_candidate_suggestion(self, tmp_path):
        """021 T014: 1 command → OPTIONAL → report.suggestions contains 'skill candidate'."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.skill_advisor import Recommendation

        runner = self._make_runner(tmp_path)
        report = ImportReport()

        mock_advice = MagicMock()
        mock_advice.recommendation = Recommendation.OPTIONAL
        mock_advice.suggested_name = "restart-redis"
        mock_advice.reason = "1 command detected"

        with patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_cls:
            mock_cls.return_value.advise.return_value = mock_advice
            runner._run_skill_and_curation(
                "PT-TEST-001",
                "systemctl restart redis",
                "database",
                report,
            )

        assert any("skill candidate" in s for s in report.suggestions), (
            f"Expected 'skill candidate' in suggestions: {report.suggestions}"
        )

    def test_two_commands_triggers_skill_candidate_suggestion(self, tmp_path):
        """021 T014: 2 commands → OPTIONAL → report.suggestions contains 'skill candidate'."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.skill_advisor import Recommendation

        runner = self._make_runner(tmp_path)
        report = ImportReport()

        mock_advice = MagicMock()
        mock_advice.recommendation = Recommendation.OPTIONAL
        mock_advice.suggested_name = "restart-redis"
        mock_advice.reason = "2 commands detected"

        with patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_cls:
            mock_cls.return_value.advise.return_value = mock_advice
            runner._run_skill_and_curation(
                "PT-TEST-002",
                "systemctl stop redis\nsystemctl start redis",
                "database",
                report,
            )

        assert any("skill candidate" in s for s in report.suggestions)

    def test_zero_commands_no_skill_candidate_suggestion(self, tmp_path):
        """021 T015: 0 commands → SKIP → no 'skill candidate' in suggestions."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.skill_advisor import Recommendation

        runner = self._make_runner(tmp_path)
        report = ImportReport()

        mock_advice = MagicMock()
        mock_advice.recommendation = Recommendation.SKIP
        mock_advice.suggested_name = "some-skill"
        mock_advice.reason = "no commands"

        with patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_cls:
            mock_cls.return_value.advise.return_value = mock_advice
            runner._run_skill_and_curation(
                "PT-TEST-003",
                "Check the logs manually.",
                "database",
                report,
            )

        assert not any("skill candidate" in s for s in report.suggestions)

    def test_three_plus_commands_recommended_no_skill_candidate(self, tmp_path):
        """021 T016: 3+ commands → RECOMMENDED → no 'skill candidate' (OPTIONAL not triggered)."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.skill_advisor import Recommendation

        runner = self._make_runner(tmp_path)
        report = ImportReport()

        mock_advice = MagicMock()
        mock_advice.recommendation = Recommendation.RECOMMENDED
        mock_advice.suggested_name = "restart-cluster"
        mock_advice.reason = "3 commands detected"

        with (
            patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_cls,
            patch.object(runner, "_gate_skill_create", return_value=False),
        ):
            mock_cls.return_value.advise.return_value = mock_advice
            runner._run_skill_and_curation(
                "PT-TEST-004",
                "cmd1\ncmd2\ncmd3",
                "database",
                report,
            )

        # RECOMMENDED path — no "skill candidate" suggestion
        assert not any("skill candidate" in s for s in report.suggestions)


class TestFinalizeSkillForUpdatedEntries:
    """US3 (023): _finalize_skill_generation must emit OPTIONAL suggestions for updated entries."""

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

    def _make_entry_file(self, kb_root: Path, entry_id: str, resolution_cmds: list) -> Path:
        """Write a minimal KB entry file for the given entry_id."""
        # Put under contributions/ so list_entries can find it
        entry_dir = kb_root / "contributions" / "pending"
        entry_file = entry_dir / f"{entry_id}.md"
        cmds_block = "\n".join(resolution_cmds)
        entry_file.write_text(
            f"---\ntitle: Test Entry\ncategory: database\nid: {entry_id}\n---\n\n"
            f"## Resolution\n\n```bash\n{cmds_block}\n```\n"
        )
        return entry_file

    def test_one_command_update_path_triggers_skill_candidate(self, tmp_path):
        """Entry updated via update_kb_entry + 1 command → OPTIONAL suggestion emitted."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.skill_advisor import Recommendation

        runner = self._make_runner(tmp_path)
        kb_root = runner.kb_root
        self._make_entry_file(kb_root, "UPD-001", ["redis-cli config set maxmemory 4gb"])

        report = ImportReport()
        runner._updated_entry_ids.add("UPD-001")

        mock_advice = MagicMock()
        mock_advice.recommendation = Recommendation.OPTIONAL
        mock_advice.suggested_name = "redis-maxmemory-fix"
        mock_advice.reason = "1 command"

        with (
            patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_cls,
            patch.object(runner, "_read_entry_content", return_value=(
                "---\ntitle: Redis Fix\ncategory: database\n---\n\n"
                "## Resolution\n\n```bash\nredis-cli config set maxmemory 4gb\n```\n"
            )),
        ):
            mock_cls.return_value.advise.return_value = mock_advice
            runner._finalize_skill_generation(report)

        assert any("skill candidate" in s for s in report.suggestions), (
            f"expected 'skill candidate' in suggestions, got: {report.suggestions}"
        )

    def test_two_commands_update_path_triggers_skill_candidate(self, tmp_path):
        """Entry updated via update_kb_entry + 2 commands → OPTIONAL suggestion emitted."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.skill_advisor import Recommendation

        runner = self._make_runner(tmp_path)
        report = ImportReport()
        runner._updated_entry_ids.add("UPD-002")

        mock_advice = MagicMock()
        mock_advice.recommendation = Recommendation.OPTIONAL
        mock_advice.suggested_name = "redis-fix"
        mock_advice.reason = "2 commands"

        with (
            patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_cls,
            patch.object(runner, "_read_entry_content", return_value=(
                "---\ntitle: Redis Fix 2\ncategory: database\n---\n\n"
                "## Resolution\n\n```bash\nredis-cli info memory\nredis-cli config set maxmemory 4gb\n```\n"
            )),
        ):
            mock_cls.return_value.advise.return_value = mock_advice
            runner._finalize_skill_generation(report)

        assert any("skill candidate" in s for s in report.suggestions), (
            f"expected 'skill candidate' in suggestions, got: {report.suggestions}"
        )

    def test_zero_commands_update_path_no_skill_candidate(self, tmp_path):
        """Entry updated with no commands → SKIP → no 'skill candidate' suggestion."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.skill_advisor import Recommendation

        runner = self._make_runner(tmp_path)
        report = ImportReport()
        runner._updated_entry_ids.add("UPD-003")

        mock_advice = MagicMock()
        mock_advice.recommendation = Recommendation.SKIP

        with (
            patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_cls,
            patch.object(runner, "_read_entry_content", return_value=(
                "---\ntitle: Pure Analysis\ncategory: database\n---\n\n"
                "## Resolution\n\nCheck the logs manually.\n"
            )),
        ):
            mock_cls.return_value.advise.return_value = mock_advice
            runner._finalize_skill_generation(report)

        assert not any("skill candidate" in s for s in report.suggestions), (
            f"expected no 'skill candidate', got: {report.suggestions}"
        )

    def test_already_evaluated_entry_skipped(self, tmp_path):
        """Entry in _skill_evaluated_entries is not re-evaluated by finalize."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.report import ImportReport

        runner = self._make_runner(tmp_path)
        report = ImportReport()
        runner._updated_entry_ids.add("UPD-004")
        runner._skill_evaluated_entries.add("UPD-004")  # already evaluated

        with patch("holmes.kb.agent.skill_advisor.SkillAdvisor") as mock_cls:
            runner._finalize_skill_generation(report)
            # SkillAdvisor.advise should never be called
            mock_cls.return_value.advise.assert_not_called()

        assert report.suggestions == []
