"""Unit tests for M3 — Classifier routing in ThreePhaseImportPipeline.

Covers:
  US1: --type pitfall bypasses Classifier entirely → _run_dag_pipeline()
  US2: Classifier returning single_incident/multi_incident → _run_dag_pipeline()
       Classifier returning runbook/guideline/non_kb → existing pipeline
  US3: _run_dag_pipeline() raises NotImplementedError (M4 stub);
       dry_run / no_interactive accessible via self
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holmes.kb.agent.pipeline import ThreePhaseImportPipeline
from holmes.kb.agent.phases.classifier import ClassificationResult, DocumentType
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.agent.report import ImportReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PITFALL_SOURCE = (
    "# Redis OOM\n\n"
    "## Root Cause\nMemory limit exceeded.\n\n"
    "## Resolution\nRestart Redis with increased memory.\n"
)

_RUNBOOK_SOURCE = (
    "# Deploy Checklist\n\n"
    "1. Build image\n2. Push to registry\n3. Update deployment\n"
)


def _make_cfg():
    cfg = MagicMock()
    cfg.model = "test-model"
    cfg.provider = "openai"
    cfg.api_key = "test-key"
    cfg.api_base_url = "http://localhost"
    return cfg


def _noop_provider() -> LLMProvider:
    """Provider that immediately stops the tool loop."""
    provider = MagicMock(spec=LLMProvider)
    provider.complete.return_value = (True, [], [{"role": "assistant", "content": "done"}], {})
    provider.append_tool_results.side_effect = lambda msgs, results: msgs
    return provider


def _make_pipeline(
    tmp_path: Path,
    force_type: str | None = None,
    dry_run: bool = True,
    no_interactive: bool = True,
) -> ThreePhaseImportPipeline:
    cfg = _make_cfg()
    return ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        dry_run=dry_run,
        no_interactive=no_interactive,
        force_type=force_type,
        _provider=_noop_provider(),
    )


def _classification(doc_type: DocumentType) -> ClassificationResult:
    return ClassificationResult(
        doc_type=doc_type,
        reason="test",
        granularity_hint="",
    )


# ---------------------------------------------------------------------------
# US1: --type pitfall bypasses Classifier entirely
# ---------------------------------------------------------------------------


class TestForcePitfallBypassesClassifier:
    """US1: --type pitfall skips Classifier and calls _run_dag_pipeline()."""

    def test_classifier_not_called_when_force_type_pitfall(self, tmp_path):
        pipeline = _make_pipeline(tmp_path, force_type="pitfall")
        with patch.object(pipeline, "_run_dag_pipeline", side_effect=RuntimeError("dag_called")) as mock_dag, \
             patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls:
            with pytest.raises(RuntimeError, match="dag_called"):
                pipeline.run(_PITFALL_SOURCE)
            mock_dag.assert_called_once()
            mock_cls.assert_not_called()

    def test_dag_receives_source_text(self, tmp_path):
        pipeline = _make_pipeline(tmp_path, force_type="pitfall")
        captured = {}

        def _capture(source_text, file_path=None):
            captured["source_text"] = source_text
            return ImportReport(dry_run=True)

        with patch.object(pipeline, "_run_dag_pipeline", side_effect=_capture):
            pipeline.run(_PITFALL_SOURCE)

        assert captured["source_text"] == _PITFALL_SOURCE

    def test_dag_receives_file_path(self, tmp_path):
        pipeline = _make_pipeline(tmp_path, force_type="pitfall")
        captured = {}
        fp = tmp_path / "doc.md"

        def _capture(source_text, file_path=None):
            captured["file_path"] = file_path
            return ImportReport(dry_run=True)

        with patch.object(pipeline, "_run_dag_pipeline", side_effect=_capture):
            pipeline.run(_PITFALL_SOURCE, file_path=fp)

        assert captured["file_path"] == fp


# ---------------------------------------------------------------------------
# US2: Classifier auto-routing — single_incident
# ---------------------------------------------------------------------------


class TestSingleIncidentRouting:
    """US2: Classifier result single_incident routes to _run_dag_pipeline()."""

    def test_single_incident_calls_dag_pipeline(self, tmp_path):
        pipeline = _make_pipeline(tmp_path)
        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls_class, \
             patch.object(pipeline, "_run_dag_pipeline", return_value=ImportReport(dry_run=True)) as mock_dag:
            mock_cls_class.return_value.classify.return_value = _classification(DocumentType.single_incident)
            pipeline.run(_PITFALL_SOURCE)
        mock_dag.assert_called_once()

    def test_single_incident_no_warning_printed(self, tmp_path, capsys):
        pipeline = _make_pipeline(tmp_path)
        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls_class, \
             patch.object(pipeline, "_run_dag_pipeline", return_value=ImportReport(dry_run=True)):
            mock_cls_class.return_value.classify.return_value = _classification(DocumentType.single_incident)
            pipeline.run(_PITFALL_SOURCE)
        assert "警告" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# US2: Classifier auto-routing — multi_incident + warning
# ---------------------------------------------------------------------------


class TestMultiIncidentRouting:
    """US2: Classifier result multi_incident routes to _run_dag_pipeline() and prints warning."""

    def test_multi_incident_calls_dag_pipeline(self, tmp_path):
        pipeline = _make_pipeline(tmp_path)
        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls_class, \
             patch.object(pipeline, "_run_dag_pipeline", return_value=ImportReport(dry_run=True)) as mock_dag:
            mock_cls_class.return_value.classify.return_value = _classification(DocumentType.multi_incident)
            pipeline.run(_PITFALL_SOURCE)
        mock_dag.assert_called_once()

    def test_multi_incident_prints_warning(self, tmp_path, capsys):
        pipeline = _make_pipeline(tmp_path)
        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls_class, \
             patch.object(pipeline, "_run_dag_pipeline", return_value=ImportReport(dry_run=True)):
            mock_cls_class.return_value.classify.return_value = _classification(DocumentType.multi_incident)
            pipeline.run(_PITFALL_SOURCE)
        out = capsys.readouterr().out
        assert "警告" in out
        assert "建议拆分" in out


# ---------------------------------------------------------------------------
# US2: Non-pitfall types use existing pipeline (no DAG)
# ---------------------------------------------------------------------------


class TestNonPitfallRoutesToExistingPipeline:
    """US2: runbook / guideline / non_kb go through existing pipeline, not DAG."""

    @pytest.mark.parametrize("doc_type", [
        DocumentType.runbook,
        DocumentType.guideline,
    ])
    def test_non_pitfall_does_not_call_dag(self, doc_type, tmp_path):
        pipeline = _make_pipeline(tmp_path)
        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls_class, \
             patch.object(pipeline, "_run_dag_pipeline") as mock_dag, \
             patch.object(pipeline, "_run_extraction_loop"):
            mock_cls_class.return_value.classify.return_value = _classification(doc_type)
            pipeline.run(_RUNBOOK_SOURCE)
        mock_dag.assert_not_called()

    def test_non_kb_does_not_call_dag(self, tmp_path):
        pipeline = _make_pipeline(tmp_path)
        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls_class, \
             patch.object(pipeline, "_run_dag_pipeline") as mock_dag:
            mock_cls_class.return_value.classify.return_value = _classification(DocumentType.non_kb)
            report = pipeline.run(_RUNBOOK_SOURCE)
        mock_dag.assert_not_called()
        assert any("non-kb" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# US3: _run_dag_pipeline stub raises NotImplementedError
# ---------------------------------------------------------------------------


class TestDagPipelineStub:
    """US3: _run_dag_pipeline() is implemented in M4 (no longer raises NotImplementedError)."""

    def test_no_longer_raises_not_implemented(self, tmp_path):
        from holmes.kb.agent.report import ImportReport
        pipeline = _make_pipeline(tmp_path)
        (tmp_path / "_import-state").mkdir(exist_ok=True)
        report = pipeline._run_dag_pipeline("source text")
        assert isinstance(report, ImportReport)

    def test_accepts_file_path_kwarg(self, tmp_path):
        from holmes.kb.agent.report import ImportReport
        pipeline = _make_pipeline(tmp_path)
        (tmp_path / "_import-state").mkdir(exist_ok=True)
        fp = tmp_path / "doc.md"
        report = pipeline._run_dag_pipeline("source text", file_path=fp)
        assert isinstance(report, ImportReport)


# ---------------------------------------------------------------------------
# US3: dry_run / no_interactive propagation via self
# ---------------------------------------------------------------------------


class TestDagPipelineParameterPropagation:
    """US3: dry_run and no_interactive are stored on self, accessible to _run_dag_pipeline."""

    def test_dry_run_propagated(self, tmp_path):
        pipeline = _make_pipeline(tmp_path, force_type="pitfall", dry_run=True)
        assert pipeline.dry_run is True

    def test_no_interactive_propagated(self, tmp_path):
        pipeline = _make_pipeline(tmp_path, force_type="pitfall", no_interactive=True)
        assert pipeline.no_interactive is True

    def test_dag_called_with_dry_run_accessible(self, tmp_path):
        """_run_dag_pipeline can read self.dry_run when invoked."""
        pipeline = _make_pipeline(tmp_path, force_type="pitfall", dry_run=True)
        seen = {}

        def _check(source_text, file_path=None):
            seen["dry_run"] = pipeline.dry_run
            return ImportReport(dry_run=True)

        with patch.object(pipeline, "_run_dag_pipeline", side_effect=_check):
            pipeline.run(_PITFALL_SOURCE)

        assert seen["dry_run"] is True
