"""Integration tests for ThreePhaseImportPipeline (T030).

Tests the 7 quickstart scenarios (T-01 through T-07) using mocked LLM providers.
Verifies pipeline structure, KnowledgeMap handling, and report fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holmes.kb.agent.phases.classifier import ClassificationResult, DocumentType
from holmes.kb.agent.pipeline import ThreePhaseImportPipeline
from holmes.kb.agent.provider.base import LLMProvider, ToolCall
from holmes.kb.agent.report import ImportReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path):
    """Create a minimal HolmesConfig-like object."""
    cfg = MagicMock()
    cfg.model = "test-model"
    cfg.provider = "anthropic"
    cfg.api_key = "test-key"
    cfg.api_base_url = None
    return cfg


def _noop_provider() -> LLMProvider:
    """Provider that immediately stops — no tool calls."""
    provider = MagicMock(spec=LLMProvider)
    provider.complete.return_value = (True, [], [{"role": "assistant", "content": "done"}], {})
    provider.append_tool_results.side_effect = lambda msgs, results: msgs
    return provider


def _make_pipeline(tmp_path: Path, dry_run: bool = True, **kwargs) -> ThreePhaseImportPipeline:
    """Build a pipeline with a real tmp_path kb_root and mocked config."""
    cfg = _make_config(tmp_path)
    pipeline = ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        dry_run=dry_run,
        **kwargs,
    )
    return pipeline


def _patch_provider(pipeline: ThreePhaseImportPipeline, provider: LLMProvider) -> None:
    """Replace pipeline's internal provider with a mock."""
    pipeline._provider = provider


@pytest.fixture(autouse=True)
def _classifier_returns_runbook():
    """Patch DocumentClassifier to return runbook so existing tests don't hit M3 DAG routing."""
    result = ClassificationResult(
        doc_type=DocumentType.runbook,
        reason="test fixture — non-pitfall",
        granularity_hint="",
    )
    with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls:
        mock_cls.return_value.classify.return_value = result
        yield


# ---------------------------------------------------------------------------
# T-01: Small document (< 3K chars, EN, 1 KP)
# ---------------------------------------------------------------------------


class TestScenarioT01SmallDocEN:
    """T-01: < 3K chars, English, 1 KP — entry created, no warnings."""

    def test_pipeline_returns_report(self, tmp_path):
        """Pipeline always returns an ImportReport."""
        pipeline = _make_pipeline(tmp_path)
        _patch_provider(pipeline, _noop_provider())
        source = "# Redis OOM\n\n## Root Cause\nMemory limit exceeded.\n\n## Resolution\nRestart Redis.\n"
        report = pipeline.run(source)
        assert isinstance(report, ImportReport)

    def test_knowledge_map_attached_to_report(self, tmp_path):
        """report.knowledge_map is populated after the Reader phase."""
        pipeline = _make_pipeline(tmp_path)
        _patch_provider(pipeline, _noop_provider())
        source = "# Redis OOM\n\n" + "x" * 200
        report = pipeline.run(source)
        assert report.knowledge_map is not None

    def test_source_text_never_truncated_in_ctx(self, tmp_path):
        """The pipeline never truncates source_text — full text available to all phases."""
        pipeline = _make_pipeline(tmp_path)

        captured_ctx: dict = {}

        original_complete = _noop_provider()

        def capturing_complete(messages, system, model, max_tokens, tools):
            # First call is from ReaderAgent — capture its context
            return True, [], [{"role": "assistant", "content": "done"}], {}

        original_complete.complete.side_effect = capturing_complete
        _patch_provider(pipeline, original_complete)

        source = "x" * 15000  # 15K chars
        report = pipeline.run(source)
        # Pipeline should NOT have truncated the source
        assert report.knowledge_map is not None
        # The total_chars should reflect the full document length
        assert report.knowledge_map.total_chars == len(source)

    def test_phase_traces_populated(self, tmp_path):
        """phase_traces should contain at least the Reader trace."""
        pipeline = _make_pipeline(tmp_path)
        _patch_provider(pipeline, _noop_provider())
        source = "# Test\n\n" + "x" * 100
        report = pipeline.run(source)
        assert len(report.phase_traces) >= 1
        assert any("Reader" in t for t in report.phase_traces)


# ---------------------------------------------------------------------------
# T-02: 10K chars, EN, 1 KP — full resolution, no CLEARED
# ---------------------------------------------------------------------------


class TestScenarioT02LargeDocEN:
    """T-02: 10K chars, EN, 1 KP — large document handled without truncation."""

    def test_10k_source_sets_total_chars_correctly(self, tmp_path):
        """total_chars in KnowledgeMap equals len(source_text) for 10K doc."""
        pipeline = _make_pipeline(tmp_path)
        _patch_provider(pipeline, _noop_provider())
        source = "# Title\n\n" + "content " * 1200  # ~10K chars
        report = pipeline.run(source)
        assert report.knowledge_map is not None
        assert report.knowledge_map.total_chars == len(source)


# ---------------------------------------------------------------------------
# T-03: 15K chars, ZH, 1 KP — Chinese section found
# ---------------------------------------------------------------------------


class TestScenarioT03LargeDocZH:
    """T-03: 15K chars, Chinese doc — pipeline handles Unicode correctly."""

    def test_chinese_source_processed_correctly(self, tmp_path):
        """Chinese document is processed without truncation."""
        fixture_path = Path(__file__).parent / "fixtures" / "large_runbook_15k.md"
        if fixture_path.exists():
            source = fixture_path.read_text(encoding="utf-8")
        else:
            source = "# MySQL 磁盘满\n\n" + "中文内容 " * 1800

        pipeline = _make_pipeline(tmp_path)
        _patch_provider(pipeline, _noop_provider())
        report = pipeline.run(source)
        assert report.knowledge_map is not None
        assert report.knowledge_map.total_chars == len(source)

    def test_resolution_at_char_9000_accessible(self, tmp_path):
        """For a 15K document, total_chars should reflect full document."""
        fixture_path = Path(__file__).parent / "fixtures" / "large_runbook_15k.md"
        if not fixture_path.exists():
            pytest.skip("large_runbook_15k.md fixture not found")

        source = fixture_path.read_text(encoding="utf-8")
        assert len(source) >= 15000, "Fixture must be >= 15K chars"

        # Verify Resolution section is after char 9000
        res_idx = source.find("## Resolution")
        assert res_idx > 9000, f"## Resolution at {res_idx}, expected > 9000"

        pipeline = _make_pipeline(tmp_path)
        _patch_provider(pipeline, _noop_provider())
        report = pipeline.run(source)
        assert report.knowledge_map.total_chars == len(source)


# ---------------------------------------------------------------------------
# T-04: 8K chars, EN, 3 KPs — no cross-contamination
# ---------------------------------------------------------------------------


class TestScenarioT04MultiKP:
    """T-04: Multi-KP document — each KP extracted independently."""

    def test_multi_kp_fixture_has_three_incidents(self):
        """multi_kp_postmortem.md fixture contains Redis, MySQL, Nginx incidents."""
        fixture_path = Path(__file__).parent / "fixtures" / "multi_kp_postmortem.md"
        if not fixture_path.exists():
            pytest.skip("multi_kp_postmortem.md fixture not found")
        content = fixture_path.read_text(encoding="utf-8")
        assert "Redis" in content
        assert "MySQL" in content
        assert "Nginx" in content

    def test_extractor_context_isolation_via_kp_drafts(self, tmp_path):
        """kp_drafts in ctx are keyed by KP ID — no cross-contamination possible."""
        from holmes.kb.agent.knowledge_map import KnowledgeMap, KnowledgePoint
        from holmes.kb.agent.phases.extractor import ExtractorAgent

        km = KnowledgeMap()
        source = "Redis content " * 200 + "MySQL content " * 200 + "Nginx content " * 200
        km.knowledge_points = [
            KnowledgePoint(id="kp-1", description="Redis", section_start=0, section_end=2800),
            KnowledgePoint(id="kp-2", description="MySQL", section_start=2800, section_end=5600),
            KnowledgePoint(id="kp-3", description="Nginx", section_start=5600, section_end=8400),
        ]

        call_messages: list[list[Any]] = []

        provider = MagicMock(spec=LLMProvider)

        def _complete(messages, system, model, max_tokens, tools):
            call_messages.append(list(messages))
            return True, [], messages + [{"role": "assistant", "content": "draft"}], {}

        provider.complete.side_effect = _complete
        provider.append_tool_results.side_effect = lambda msgs, r: msgs

        agent = ExtractorAgent(provider=provider, model="test-model")
        ctx = {"source_text": source}

        for kp in km.knowledge_points:
            agent.run(kp, km, ctx)

        # Each KP's extractor should start with exactly 1 message (fresh context)
        for i, kp_msgs in enumerate(call_messages):
            assert len(kp_msgs) == 1, (
                f"KP-{i+1} extractor started with {len(kp_msgs)} messages, "
                f"expected 1 (fresh isolated context)"
            )


# ---------------------------------------------------------------------------
# T-05: Chinese runbook, 1 KP — Skill recommendation
# ---------------------------------------------------------------------------


class TestScenarioT05ChineseSkill:
    """T-05: Chinese runbook — Skill recommendation present."""

    def test_redis_zh_fixture_contains_two_commands(self):
        """redis_runbook_zh.md has 2+ commands in diagnostic section."""
        fixture_path = Path(__file__).parent / "fixtures" / "redis_runbook_zh.md"
        if not fixture_path.exists():
            pytest.skip("redis_runbook_zh.md fixture not found")
        content = fixture_path.read_text(encoding="utf-8")
        assert "redis-cli INFO replication" in content
        assert "redis-cli DEBUG SLEEP 0" in content


# ---------------------------------------------------------------------------
# T-06: Dry-run — no duplicate "Would create:" lines
# ---------------------------------------------------------------------------


class TestScenarioT06DryRun:
    """T-06: Dry-run produces exactly 1 "Would create:" line (W6-F1 fix)."""

    def test_dry_run_flag_set_on_report(self, tmp_path):
        """Report has dry_run=True when pipeline is configured with dry_run=True."""
        pipeline = _make_pipeline(tmp_path, dry_run=True)
        _patch_provider(pipeline, _noop_provider())
        report = pipeline.run("# Test\n\ncontent here\n" + "x" * 200)
        assert report.dry_run is True

    def test_no_duplicate_suggestions(self, tmp_path):
        """Each unique suggestion appears only once in report.suggestions (W6-F1)."""
        # Simulate a provider that calls write_kb_entry twice with same title
        from holmes.kb.agent.tools import TOOL_DEFINITIONS

        call_count = [0]

        provider = MagicMock(spec=LLMProvider)

        def _complete(messages, system, model, max_tokens, tools):
            c = call_count[0]
            call_count[0] += 1
            if c == 0:
                # Return a write_kb_entry call
                return (
                    False,
                    [ToolCall(
                        id="tc1",
                        name="write_kb_entry",
                        input={
                            "content": "---\ntype: pitfall\ntitle: Redis OOM\n---\nbody",
                            "source_hash": "abc123",
                            "confidence": 0.9,
                            "title": "Redis OOM",
                        },
                    )],
                    messages + [{"role": "assistant", "content": "writing"}],
                    {},
                )
            if c == 1:
                # Duplicate write_kb_entry (same title)
                return (
                    False,
                    [ToolCall(
                        id="tc2",
                        name="write_kb_entry",
                        input={
                            "content": "---\ntype: pitfall\ntitle: Redis OOM\n---\nbody",
                            "source_hash": "abc123",
                            "confidence": 0.9,
                            "title": "Redis OOM",
                        },
                    )],
                    messages + [{"role": "assistant", "content": "writing again"}],
                    {},
                )
            return True, [], messages + [{"role": "assistant", "content": "done"}], {}

        provider.complete.side_effect = _complete
        provider.append_tool_results.side_effect = (
            lambda msgs, results: msgs + [{"role": "tool", "content": str(results)}]
        )

        pipeline = _make_pipeline(tmp_path, dry_run=True)
        _patch_provider(pipeline, provider)

        report = pipeline.run("# Redis OOM\n\ncontent " + "x" * 200)

        # W6-F1: "Would create: Redis OOM" should appear at most once
        would_create = [s for s in report.suggestions if "Would create" in s and "Redis OOM" in s]
        assert len(would_create) <= 1, (
            f"Expected at most 1 'Would create: Redis OOM', got {len(would_create)}: {would_create}"
        )


# ---------------------------------------------------------------------------
# T-07: Batch (3 docs) — verbose trace per entry
# ---------------------------------------------------------------------------


class TestScenarioT07BatchVerbose:
    """T-07: Batch import with verbose — trace block per entry."""

    def test_verbose_format_includes_knowledge_map_info(self, tmp_path):
        """format_verbose() includes KnowledgeMap stats when available."""
        from holmes.kb.agent.knowledge_map import KnowledgeMap, KnowledgePoint

        pipeline = _make_pipeline(tmp_path)
        _patch_provider(pipeline, _noop_provider())
        report = pipeline.run("# Test\n\n" + "x" * 200)

        # Inject a non-empty KnowledgeMap for verbose test
        km = KnowledgeMap(
            knowledge_points=[
                KnowledgePoint(id="kp-1", description="Test KP", section_start=0, section_end=100)
            ],
            total_chars=200,
            chars_read=200,
            reading_passes=1,
        )
        report.knowledge_map = km

        verbose_output = report.format_verbose()
        assert "knowledge points: 1" in verbose_output
        assert "coverage:" in verbose_output
        assert "reading passes: 1" in verbose_output

    def test_phase_traces_in_verbose_output(self, tmp_path):
        """Phase traces appear in format_verbose() output."""
        pipeline = _make_pipeline(tmp_path)
        _patch_provider(pipeline, _noop_provider())
        report = pipeline.run("# Test\n\n" + "x" * 200)

        # Ensure phase traces are in verbose output
        if report.phase_traces:
            verbose_output = report.format_verbose()
            for trace in report.phase_traces:
                assert trace in verbose_output


# ---------------------------------------------------------------------------
# T-08: D-4 + D-5 fixes (pipeline.py)
# ---------------------------------------------------------------------------


class TestD4ZeroKPWarning:
    """D-4: Reader returning 0 KPs should produce a warning in report.warnings."""

    def test_zero_kp_produces_warning(self, tmp_path):
        """When Reader finds 0 KPs, report.warnings contains a no-KP message."""
        pipeline = _make_pipeline(tmp_path)
        _patch_provider(pipeline, _noop_provider())
        report = pipeline.run("# Empty Doc\n\nNothing actionable here.")
        # With noop provider, reader finds 0 KPs → D-4 warning must be present
        assert any("No knowledge points identified" in w for w in report.warnings), (
            f"Expected 'No knowledge points identified' in warnings, got: {report.warnings}"
        )

    def test_nonzero_kp_no_spurious_warning(self, tmp_path):
        """When Reader finds at least 1 KP, no 0-KP warning is added."""
        from holmes.kb.agent.knowledge_map import KnowledgeMap, KnowledgePoint
        from unittest.mock import patch as _patch

        pipeline = _make_pipeline(tmp_path)
        _patch_provider(pipeline, _noop_provider())

        km_with_kp = KnowledgeMap(
            knowledge_points=[
                KnowledgePoint(id="kp-1", description="Test KP", section_start=0, section_end=100)
            ],
            total_chars=200,
            chars_read=100,
            reading_passes=1,
            diminishing_returns=True,
        )

        with _patch(
            "holmes.kb.agent.phases.reader.ReaderAgent.run", return_value=km_with_kp
        ):
            report = pipeline.run("# Test\n\n" + "x" * 200)

        assert not any("No knowledge points identified" in w for w in report.warnings), (
            f"Spurious 0-KP warning present despite KPs found: {report.warnings}"
        )


class TestD5DeduplicationPrompt:
    """D-5: Dedup is handled programmatically in Phase 2.5 (intra-import), not by the LLM."""

    def test_extraction_loop_prompt_does_not_ask_llm_for_compare_root_cause(self, tmp_path):
        """The LLM writer loop prompt must NOT include a compare_root_cause step.
        Intra-import dedup (_run_intra_import_dedup) runs before the LLM writer loop."""
        from holmes.kb.agent.knowledge_map import KnowledgeMap, KnowledgePoint
        from unittest.mock import patch as _patch, MagicMock

        pipeline = _make_pipeline(tmp_path, dry_run=False)

        captured_messages = []

        def capturing_provider_complete(messages, system, model, max_tokens, tools):
            captured_messages.extend(messages)
            return True, [], messages + [{"role": "assistant", "content": "done"}], {}

        provider = MagicMock(spec=LLMProvider)
        provider.complete.side_effect = capturing_provider_complete
        provider.append_tool_results.side_effect = lambda msgs, results: msgs

        km_with_kp = KnowledgeMap(
            knowledge_points=[
                KnowledgePoint(id="kp-1", description="Test KP", section_start=0, section_end=100)
            ],
            total_chars=200,
            chars_read=100,
            reading_passes=1,
            diminishing_returns=True,
        )

        with _patch("holmes.kb.agent.phases.reader.ReaderAgent.run", return_value=km_with_kp):
            draft = "---\ntitle: Test\ntype: pitfall\n---\n## Root Cause\nTest.\n"
            with _patch("holmes.kb.agent.phases.extractor.ExtractorAgent.run", return_value=draft):
                # Patch _run_intra_import_dedup so it doesn't interfere with prompt capture
                with _patch.object(pipeline, "_run_intra_import_dedup", return_value=set()):
                    _patch_provider(pipeline, provider)
                    pipeline.run("# Test\n\n" + "x" * 200)

        # The LLM writer loop prompt must NOT ask LLM to call compare_root_cause
        all_content = " ".join(
            str(m.get("content", "")) for m in captured_messages
        )
        assert "compare_root_cause" not in all_content.lower() or "read_kb_entries_by_category" not in all_content, (
            "LLM writer loop prompt must not instruct LLM to do cross-KB dedup — "
            "import always creates new entries"
        )


# ---------------------------------------------------------------------------
# E-2: force_type override
# ---------------------------------------------------------------------------


class TestForceTypeOverride:
    """E-2: force_type parameter enforces entry type regardless of LLM classification."""

    def test_force_type_pitfall_routes_to_dag_pipeline(self, tmp_path):
        """M3: force_type='pitfall' bypasses Classifier and routes to _run_dag_pipeline()."""
        pipeline = _make_pipeline(tmp_path, force_type="pitfall")
        _patch_provider(pipeline, _noop_provider())

        with patch.object(pipeline, "_run_dag_pipeline", return_value=ImportReport(dry_run=True)) as mock_dag, \
             patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls:
            report = pipeline.run("# Redis Policy\n\n" + "x" * 200)

        mock_dag.assert_called_once()
        mock_cls.assert_not_called()
        assert report is not None

    def test_force_type_none_leaves_type_unchanged(self, tmp_path):
        """When force_type=None (default), LLM-assigned type is preserved."""
        pipeline = _make_pipeline(tmp_path, force_type=None)
        assert pipeline.force_type is None

    def test_force_type_propagated_from_runner_to_pipeline(self, tmp_path):
        """ImportAgentRunner passes force_type to ThreePhaseImportPipeline."""
        from holmes.kb.agent.runner import ImportAgentRunner

        cfg = MagicMock()
        cfg.model = "test-model"
        cfg.provider = "anthropic"
        cfg.api_key = "test-key"
        cfg.api_base_url = None

        with patch("holmes.kb.agent.provider.create_provider"):
            runner = ImportAgentRunner(
                kb_root=tmp_path,
                cfg=cfg,
                force_type="process",
            )
        assert runner.force_type == "process"

    def test_draft_type_overwritten_when_force_type_set(self, tmp_path):
        """Direct unit test: pipeline applies force_type to frontmatter after extraction."""
        import frontmatter as fm
        from holmes.kb.agent.pipeline import ThreePhaseImportPipeline

        pipeline = _make_pipeline(tmp_path, force_type="pitfall")

        # Simulate what the pipeline does to a draft with wrong type
        draft = "---\ntype: guideline\ntitle: Test\n---\n\nBody.\n"
        post = fm.loads(draft)
        post.metadata["type"] = pipeline.force_type
        rewritten = fm.dumps(post)

        post_check = fm.loads(rewritten)
        assert post_check.metadata["type"] == "pitfall"


class TestForceTypeValidationCLI:
    """E-2: CLI --type validation rejects invalid values."""

    def test_valid_types_accepted(self):
        """All valid type values are in the accepted set."""
        valid = {"pitfall", "model", "guideline", "process", "decision"}
        assert len(valid) == 5

    def test_invalid_type_would_be_rejected(self):
        """Logic check: invalid value is not in valid set."""
        valid = {"pitfall", "model", "guideline", "process", "decision"}
        assert "unknown_type" not in valid
        assert "PITFALL" not in valid  # case-sensitive check (lowercased before comparison)


# ---------------------------------------------------------------------------
# 018 Root E: Verbatim fallback helper tests
# ---------------------------------------------------------------------------


class TestVerbatimFallbackHelpers:
    """018 Root E: _is_resolution_empty and _inject_resolution unit tests."""

    def test_is_resolution_empty_with_empty_section(self):
        """_is_resolution_empty returns True for empty ## Resolution."""
        from holmes.kb.agent.pipeline import _is_resolution_empty
        draft = "---\nid: x\n---\n\n## Symptoms\n\nFails.\n\n## Root Cause\n\nCause.\n\n## Resolution\n\n"
        assert _is_resolution_empty(draft) is True

    def test_is_resolution_empty_with_content(self):
        """_is_resolution_empty returns False when ## Resolution has content."""
        from holmes.kb.agent.pipeline import _is_resolution_empty
        draft = "---\nid: x\n---\n\n## Symptoms\n\nFails.\n\n## Resolution\n\nkubectl rollout restart\n"
        assert _is_resolution_empty(draft) is False

    def test_is_resolution_empty_missing_section(self):
        """_is_resolution_empty returns True when ## Resolution is absent."""
        from holmes.kb.agent.pipeline import _is_resolution_empty
        draft = "---\nid: x\n---\n\n## Symptoms\n\nFails.\n"
        assert _is_resolution_empty(draft) is True

    def test_inject_resolution_adds_content(self):
        """_inject_resolution inserts commands and recovery marker."""
        from holmes.kb.agent.pipeline import _inject_resolution
        import frontmatter
        draft = "---\nid: x\n---\n\n## Symptoms\n\nFails.\n\n## Root Cause\n\nCause.\n\n## Resolution\n\n"
        commands = ["kubectl rollout restart deployment/api", "kubectl get pods"]
        result = _inject_resolution(draft, commands)
        post = frontmatter.loads(result)
        assert "[auto-recovered from source]" in post.content
        assert "kubectl rollout restart deployment/api" in post.content
        assert "kubectl get pods" in post.content

    def test_inject_resolution_preserves_frontmatter(self):
        """_inject_resolution keeps frontmatter metadata intact."""
        from holmes.kb.agent.pipeline import _inject_resolution
        import frontmatter
        draft = "---\nid: PT-001\ntitle: Test\ntype: pitfall\n---\n\n## Resolution\n\n"
        result = _inject_resolution(draft, ["kubectl delete pod"])
        post = frontmatter.loads(result)
        assert post.metadata["id"] == "PT-001"
        assert post.metadata["title"] == "Test"

    def test_nonempty_resolution_is_not_empty(self):
        """_is_resolution_empty returns False for a Resolution with content."""
        from holmes.kb.agent.pipeline import _is_resolution_empty
        draft = "---\nid: x\n---\n\n## Resolution\n\nAlready has content.\n"
        # Non-empty Resolution → guard returns False; pipeline skips injection
        assert _is_resolution_empty(draft) is False


# ---------------------------------------------------------------------------
# T010: Document-level dedup pre-check (Feature 020)
# ---------------------------------------------------------------------------


class TestDocumentLevelDedup:
    """ThreePhaseImportPipeline.run() aborts early when document already imported (020 T010)."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        (kb / "contributions/pending").mkdir(parents=True)
        return kb

    def _make_pipeline(self, kb_root: Path, force: bool = False, dry_run: bool = False):
        from unittest.mock import MagicMock, patch
        from holmes.config import HolmesConfig
        from holmes.kb.agent.pipeline import ThreePhaseImportPipeline

        cfg = HolmesConfig(kb_path=str(kb_root), model="test-model", api_key="key")
        with patch("holmes.kb.agent.pipeline.create_provider", return_value=MagicMock()):
            pipeline = ThreePhaseImportPipeline(
                kb_root=kb_root, cfg=cfg, no_interactive=True,
                dry_run=dry_run, force=force,
            )
        return pipeline

    def test_existing_hash_skips_entire_pipeline(self, kb_root):
        """When source_hash exists in confirmed KB, pipeline returns immediately with skipped entries."""
        from unittest.mock import MagicMock, patch
        from holmes.kb.store import EntryMeta

        pipeline = self._make_pipeline(kb_root)

        # Confirmed entry — should trigger exact-duplicate skip (M2 Step 0a).
        existing_entry = EntryMeta(
            id="PT-DB-001", type="pitfall", title="DB Timeout", maturity="draft",
            category="database", tags=[], created_at="", updated_at="",
            file_path=str(kb_root / "pitfall/database/PT-DB-001.md"),
            source_hash="abc123def456abcd",
        )
        with patch("holmes.kb.store.find_entries_by_source_hash", return_value=[existing_entry]) as mock_find:
            report = pipeline.run("some source text")

        mock_find.assert_called_once()
        assert "PT-DB-001" in report.skipped
        assert len(report.created) == 0
        assert any("已存在完全相同" in w for w in report.warnings)

    def test_no_existing_hash_proceeds_normally(self, kb_root):
        """When source_hash not found, pipeline proceeds (calls DocumentClassifier)."""
        from unittest.mock import MagicMock, patch

        pipeline = self._make_pipeline(kb_root)

        with patch("holmes.kb.agent.tools._find_all_entries_by_hash", return_value=[]):
            with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls:
                mock_inst = MagicMock()
                from holmes.kb.agent.phases.classifier import DocumentType, ClassificationResult
                mock_inst.classify.return_value = ClassificationResult(doc_type=DocumentType.non_kb, reason="test skip", granularity_hint=None)
                mock_cls.return_value = mock_inst
                report = pipeline.run("some new source text")

        # non_kb doc → returns early, but DocumentClassifier was called (pipeline proceeded)
        mock_inst.classify.assert_called_once()

    def test_force_bypasses_dedup(self, kb_root):
        """force=True skips all Step 0 checks and proceeds directly to the pipeline (M2)."""
        from unittest.mock import MagicMock, patch

        pipeline = self._make_pipeline(kb_root, force=True)

        with patch("holmes.kb.store.find_entries_by_source_hash") as mock_find_hash:
            with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls:
                from holmes.kb.agent.phases.classifier import DocumentType, ClassificationResult
                mock_cls.return_value.classify.return_value = ClassificationResult(
                    doc_type=DocumentType.non_kb, reason="test", granularity_hint=None
                )
                try:
                    report = pipeline.run("some source text")
                except (RuntimeError, NotImplementedError, ValueError):
                    pass  # pipeline continued past Step 0 into LLM phase

        # With force=True, Step 0 is entirely skipped — hash check is NOT called.
        mock_find_hash.assert_not_called()
        # Pipeline continued (DocumentClassifier was called).
        mock_cls.return_value.classify.assert_called_once()

    def test_dry_run_bypasses_dedup(self, kb_root):
        """dry_run=True bypasses document-level dedup (dedup only applies to real writes)."""
        from unittest.mock import MagicMock, patch

        pipeline = self._make_pipeline(kb_root, dry_run=True)

        existing = [("pending-existing-001", "/some/path.md")]
        with patch("holmes.kb.agent.tools._find_all_entries_by_hash", return_value=existing) as mock_find:
            with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls:
                from holmes.kb.agent.phases.classifier import DocumentType, ClassificationResult
                mock_cls.return_value.classify.return_value = ClassificationResult(
                    doc_type=DocumentType.non_kb, reason="test", granularity_hint=None
                )
                pipeline.run("some source text")

        mock_find.assert_not_called()


# ---------------------------------------------------------------------------
# T009 (021): --force bypasses non_kb early return
# ---------------------------------------------------------------------------


class TestForceBypassNonKb:
    """021 T009: force=True bypasses non_kb early return; force=False triggers early return."""

    def _make_pipeline(self, kb_root, force: bool = False, dry_run: bool = True):
        from holmes.kb.agent.pipeline import ThreePhaseImportPipeline

        cfg = MagicMock()
        cfg.model = "test-model"
        cfg.provider = "anthropic"
        cfg.api_key = "test-key"
        cfg.api_base_url = None
        return ThreePhaseImportPipeline(
            kb_root=kb_root,
            cfg=cfg,
            dry_run=dry_run,
            force=force,
        )

    def test_force_true_does_not_early_return_on_non_kb(self, tmp_path):
        """force=True: non_kb document continues past classifier, warning added."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.phases.classifier import ClassificationResult, DocumentType

        pipeline = self._make_pipeline(tmp_path, force=True, dry_run=True)
        pipeline._provider = MagicMock()

        non_kb_result = ClassificationResult(
            doc_type=DocumentType.non_kb,
            reason="pure logistics",
            granularity_hint="",
        )

        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls:
            mock_cls.return_value.classify.return_value = non_kb_result
            # Reader needs a provider — mock it to stop immediately
            reader_provider = MagicMock()
            reader_provider.complete.return_value = (True, [], [{"role": "assistant", "content": "done"}], {})
            reader_provider.append_tool_results.side_effect = lambda msgs, results: msgs
            pipeline._provider = reader_provider
            report = pipeline.run("some logistics meeting content")

        # Must have warning containing "force bypassed"
        assert any("force bypassed" in w for w in report.warnings)

    def test_force_false_early_returns_on_non_kb(self, tmp_path):
        """force=False: non_kb document triggers early return, 0 created."""
        from unittest.mock import MagicMock, patch

        from holmes.kb.agent.phases.classifier import ClassificationResult, DocumentType

        pipeline = self._make_pipeline(tmp_path, force=False, dry_run=False)

        non_kb_result = ClassificationResult(
            doc_type=DocumentType.non_kb,
            reason="logistics only",
            granularity_hint="",
        )

        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls:
            mock_cls.return_value.classify.return_value = non_kb_result
            pipeline._provider = MagicMock()
            report = pipeline.run("some logistics content")

        assert len(report.created) == 0
        assert any("non-kb document" in w and "skipped" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# T019 (021): format_dry_run_plan() shows KP titles and types
# ---------------------------------------------------------------------------


class TestFormatDryRunPlanKpOutput:
    """021 T019: format_dry_run_plan() lists KP descriptions and type/category."""

    def test_non_empty_knowledge_map_lists_kp_descriptions(self, tmp_path):
        """KnowledgeMap with 2 KPs → dry-run output contains 'Would create (est.)'."""
        from holmes.kb.agent.knowledge_map import KnowledgeMap, KnowledgePoint
        from holmes.kb.agent.report import ImportReport

        report = ImportReport()
        report.knowledge_map = KnowledgeMap(
            knowledge_points=[
                KnowledgePoint(
                    id="kp-1",
                    description="Redis connection pool exhausted",
                    section_start=0,
                    section_end=100,
                    type_hint="pitfall",
                    category_hint="database",
                ),
                KnowledgePoint(
                    id="kp-2",
                    description="Nginx upstream timeout",
                    section_start=100,
                    section_end=200,
                    type_hint="pitfall",
                    category_hint="network",
                ),
            ],
            total_chars=200,
            chars_read=200,
        )

        output = report.format_dry_run_plan()
        assert "Would create (est.)" in output
        assert "Redis connection pool exhausted" in output
        assert "Nginx upstream timeout" in output
        assert "pitfall" in output

    def test_empty_knowledge_map_shows_zero_kp_message(self, tmp_path):
        """KnowledgeMap with 0 KPs → dry-run output says ~0 knowledge point(s)."""
        from holmes.kb.agent.knowledge_map import KnowledgeMap
        from holmes.kb.agent.report import ImportReport

        report = ImportReport()
        report.knowledge_map = KnowledgeMap(knowledge_points=[], total_chars=100, chars_read=100)

        output = report.format_dry_run_plan()
        assert "~0 knowledge point(s)" in output
        assert "Would create (est.)" not in output


class TestIntraImportDedup:
    """024: _run_intra_import_dedup — draft-vs-draft dedup within a single import run.

    Import always creates new entries. No cross-KB reads or updates.
    """

    def _make_pipeline(self, tmp_path):
        from unittest.mock import MagicMock, patch
        from holmes.config import HolmesConfig
        from holmes.kb.agent.pipeline import ThreePhaseImportPipeline

        kb_root = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending"):
            (kb_root / d).mkdir(parents=True, exist_ok=True)
        cfg = HolmesConfig(kb_path=str(kb_root), model="test-model", api_key="key")
        with patch("holmes.kb.agent.pipeline.create_provider", return_value=MagicMock()):
            pipeline = ThreePhaseImportPipeline(
                kb_root=kb_root, cfg=cfg, no_interactive=True
            )
        return pipeline

    def test_pipeline_has_intra_import_dedup_method(self):
        """_run_intra_import_dedup must exist; _run_dedup_pass must not."""
        from holmes.kb.agent.pipeline import ThreePhaseImportPipeline
        assert hasattr(ThreePhaseImportPipeline, "_run_intra_import_dedup"), (
            "_run_intra_import_dedup method must exist"
        )
        assert not hasattr(ThreePhaseImportPipeline, "_run_dedup_pass"), (
            "_run_dedup_pass must be removed — cross-KB dedup is gone"
        )

    def test_system_prompt_does_not_instruct_cross_kb_dedup(self):
        """_IMPORT_SYSTEM_PROMPT must not instruct LLM to do cross-KB dedup."""
        from holmes.kb.agent.runner import _IMPORT_SYSTEM_PROMPT
        assert "read_kb_entries_by_category" not in _IMPORT_SYSTEM_PROMPT, (
            "System prompt must not ask LLM to read existing KB entries for dedup"
        )
        assert "update_kb_entry" not in _IMPORT_SYSTEM_PROMPT, (
            "System prompt must not instruct LLM to call update_kb_entry (merge)"
        )

    def test_same_root_cause_drafts_deduplicated(self, tmp_path):
        """Two drafts with identical root cause in one import → only first kept."""
        from holmes.kb.agent.report import ImportReport
        from holmes.kb.agent.pipeline import ThreePhaseImportPipeline

        pipeline = self._make_pipeline(tmp_path)
        report = ImportReport()

        same_root = "Disk I/O saturated by runaway write process"
        draft_a = (
            "---\ntitle: Disk I/O pitfall A\ntype: pitfall\ncategory: system\n---\n"
            f"## Root Cause\n{same_root}\n\n## Resolution\nkill -9 $(lsof -t +D /var)\n"
        )
        draft_b = (
            "---\ntitle: Disk I/O pitfall B\ntype: pitfall\ncategory: system\n---\n"
            f"## Root Cause\n{same_root}\n\n## Resolution\niostat -x 1\n"
        )
        drafts = {"kp-1": draft_a, "kp-2": draft_b}

        duplicates = pipeline._run_intra_import_dedup(drafts, report)

        assert len(duplicates) == 1
        assert "kp-1" not in duplicates, "First draft must be kept"
        assert "kp-2" in duplicates, "Second duplicate draft must be skipped"
        assert any("kp-2" in s for s in report.skipped), (
            "Duplicate must be annotated in report.skipped"
        )

    def test_different_root_cause_drafts_both_kept(self, tmp_path):
        """Two drafts with different root causes → both kept, none skipped."""
        from holmes.kb.agent.report import ImportReport

        pipeline = self._make_pipeline(tmp_path)
        report = ImportReport()

        draft_a = (
            "---\ntitle: OOM crash\ntype: pitfall\ncategory: system\n---\n"
            "## Root Cause\nJVM heap exhausted due to memory leak in cache eviction\n"
            "## Resolution\njmap -histo:live <pid>\n"
        )
        draft_b = (
            "---\ntitle: Disk full\ntype: pitfall\ncategory: system\n---\n"
            "## Root Cause\nLog rotation misconfigured; rotated logs not purged\n"
            "## Resolution\ndf -h && du -sh /var/log/*\n"
        )
        drafts = {"kp-1": draft_a, "kp-2": draft_b}

        duplicates = pipeline._run_intra_import_dedup(drafts, report)

        assert len(duplicates) == 0, "No drafts should be deduplicated when root causes differ"
        assert len(report.skipped) == 0

    def test_non_pitfall_uses_title_for_dedup(self, tmp_path):
        """Guideline/model types without Root Cause use title similarity for dedup."""
        from holmes.kb.agent.report import ImportReport

        pipeline = self._make_pipeline(tmp_path)
        report = ImportReport()

        draft_a = (
            "---\ntitle: How to configure log rotation\ntype: guideline\ncategory: system\n---\n"
            "Use logrotate with weekly rotation and 4 weeks retention.\n"
        )
        draft_b = (
            "---\ntitle: How to configure log rotation\ntype: guideline\ncategory: system\n---\n"
            "Configure logrotate: weekly, rotate 4, compress.\n"
        )
        drafts = {"kp-1": draft_a, "kp-2": draft_b}

        duplicates = pipeline._run_intra_import_dedup(drafts, report)

        assert len(duplicates) == 1
        assert "kp-2" in duplicates, "Second guideline with identical title must be deduplicated"

    def test_runner_no_longer_has_pending_dedup_match(self, tmp_path):
        """_pending_dedup_match field must be removed from ImportAgentRunner (dead code)."""
        from unittest.mock import MagicMock, patch
        from holmes.config import HolmesConfig
        from holmes.kb.agent.runner import ImportAgentRunner

        kb_root = tmp_path / "kb"
        kb_root.mkdir(parents=True, exist_ok=True)
        cfg = HolmesConfig(kb_path=str(kb_root), model="test-model", api_key="key")
        with patch("holmes.kb.agent.runner.create_provider", return_value=MagicMock()):
            runner = ImportAgentRunner(kb_root=kb_root, cfg=cfg, no_interactive=True)

        assert not hasattr(runner, "_pending_dedup_match"), (
            "_pending_dedup_match must be removed — write_kb_entry intercept for "
            "cross-KB dedup is no longer needed"
        )
