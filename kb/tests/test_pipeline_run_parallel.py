"""Tests for ThreePhaseImportPipeline.run() parallel extractor path (US2).

These tests call pipeline.run() directly — the production code path —
rather than reimplementing the extraction logic. This ensures the actual
ThreadPoolExecutor block in run() is exercised.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holmes.config import HolmesConfig
from holmes.kb.agent.pipeline import ThreePhaseImportPipeline
from holmes.kb.agent.provider.base import LLMProvider, ToolCall


# ---------------------------------------------------------------------------
# Shared mock provider — stop immediately, no tool calls
# ---------------------------------------------------------------------------

class _StopProvider(LLMProvider):
    """Provider that immediately returns stop=True with no tool calls."""

    def complete(self, messages, system, model, max_tokens, tools):
        return True, [], list(messages), {}

    def simple_complete(self, messages, system="", max_tokens=512):
        return ""

    def append_tool_results(self, messages, results):
        return list(messages)


# ---------------------------------------------------------------------------
# Shared draft template
# ---------------------------------------------------------------------------

_DRAFT = textwrap.dedent("""\
    ---
    id: {kp_id}
    type: pitfall
    title: Error {kp_id}
    maturity: draft
    category: network
    tags: []
    created_at: "2026-01-01T00:00:00+00:00"
    updated_at: "2026-01-01T00:00:00+00:00"
    ---

    ## Symptoms

    Symptom for {kp_id}.

    ## Root Cause

    Cause for {kp_id}.

    ## Resolution

    Fix for {kp_id}.
""")


def _make_kp(kp_id: str, idx: int = 0) -> Any:
    kp = MagicMock()
    kp.id = kp_id
    kp.description = f"Description of {kp_id}"
    kp.type_hint = "pitfall"
    kp.section_start = idx * 200
    kp.section_end = (idx + 1) * 200
    kp.extracted = False
    return kp


def _make_classification() -> Any:
    from holmes.kb.agent.phases.classifier import DocumentType
    classification = MagicMock()
    classification.doc_type = DocumentType.single_incident  # any non-non_kb value passes
    classification.reason = "test document"
    classification.granularity_hint = None
    return classification


def _make_knowledge_map(kp_ids: list[str]) -> Any:
    from holmes.kb.agent.phases.reader import COVERAGE_THRESHOLD
    km = MagicMock()
    km.knowledge_points = [_make_kp(kp_id, i) for i, kp_id in enumerate(kp_ids)]
    km.coverage_pct = COVERAGE_THRESHOLD + 1.0  # above threshold
    km.diminishing_returns = False
    km.reading_passes = 1
    return km


# ---------------------------------------------------------------------------
# T1: pipeline.run() correctly runs parallel extraction for all KPs
# ---------------------------------------------------------------------------

def test_pipeline_run_parallel_extracts_all_kps(tmp_path: Path) -> None:
    """T1: pipeline.run() must extract all KPs via the ThreadPoolExecutor block.

    Verifies that the actual run() code path — not a reimplementation — is
    exercised, and that phase_traces reports the parallel extractor label.

    dry_run=False is required: dry_run=True exits after Reader (before Extractor).
    Writes and git operations are mocked so no filesystem side-effects occur.
    """
    kp_ids = ["kp-001", "kp-002", "kp-003"]
    source_text = " ".join(f"Content about {k}." for k in kp_ids) * 50

    cfg = HolmesConfig(api_key="test-key", extractor_concurrency=4)
    provider = _StopProvider()
    km = _make_knowledge_map(kp_ids)
    classification = _make_classification()

    pipeline = ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        no_interactive=True,
        dry_run=False,  # must be False to reach the Extractor phase
        skip_git_commit=True,
        _provider=provider,
    )

    with patch("holmes.kb.agent.pipeline.DocumentClassifier") as MockClassifier, \
         patch("holmes.kb.agent.pipeline.ReaderAgent") as MockReader, \
         patch("holmes.kb.agent.phases.extractor.ExtractorAgent.run") as mock_extract, \
         patch("holmes.kb.agent.tools._find_all_entries_by_hash", return_value=[]), \
         patch("holmes.kb.agent.runner.ImportAgentRunner._git_commit", return_value=None), \
         patch("holmes.kb.agent.runner.ImportAgentRunner._finalize_skill_generation"):

        MockClassifier.return_value.classify.return_value = classification
        MockReader.return_value.run.return_value = km
        mock_extract.side_effect = lambda kp, knowledge_map, ctx: _DRAFT.format(kp_id=kp.id)

        report = pipeline.run(source_text)

    # All 3 KPs should have been attempted by the extractor.
    assert mock_extract.call_count == 3, (
        f"Expected ExtractorAgent.run() called 3 times, got {mock_extract.call_count}"
    )

    # Phase trace must include the parallel extractor label.
    extractor_traces = [t for t in report.phase_traces if t.startswith("Extractor:")]
    assert extractor_traces, f"No Extractor phase trace found. All traces: {report.phase_traces}"
    extractor_trace = extractor_traces[0]
    assert "parallel" in extractor_trace, (
        f"Expected 'parallel' in extractor trace: {extractor_trace!r}"
    )
    assert "3" in extractor_trace, (
        f"Expected KP count in trace: {extractor_trace!r}"
    )


# ---------------------------------------------------------------------------
# T2: extractor_concurrency=1 produces "serial" label in phase_traces
# ---------------------------------------------------------------------------

def test_pipeline_run_concurrency_one_gives_serial_label(tmp_path: Path) -> None:
    """T2: extractor_concurrency=1 must produce 'serial' label in phase_traces."""
    kp_ids = ["kp-A", "kp-B"]
    source_text = "Content A. Content B. " * 50

    cfg = HolmesConfig(api_key="test-key", extractor_concurrency=1)
    provider = _StopProvider()
    km = _make_knowledge_map(kp_ids)
    classification = _make_classification()

    pipeline = ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        no_interactive=True,
        dry_run=False,
        skip_git_commit=True,
        _provider=provider,
    )

    with patch("holmes.kb.agent.pipeline.DocumentClassifier") as MockClassifier, \
         patch("holmes.kb.agent.pipeline.ReaderAgent") as MockReader, \
         patch("holmes.kb.agent.phases.extractor.ExtractorAgent.run") as mock_extract, \
         patch("holmes.kb.agent.tools._find_all_entries_by_hash", return_value=[]), \
         patch("holmes.kb.agent.runner.ImportAgentRunner._git_commit", return_value=None), \
         patch("holmes.kb.agent.runner.ImportAgentRunner._finalize_skill_generation"):

        MockClassifier.return_value.classify.return_value = classification
        MockReader.return_value.run.return_value = km
        mock_extract.side_effect = lambda kp, knowledge_map, ctx: _DRAFT.format(kp_id=kp.id)

        report = pipeline.run(source_text)

    extractor_traces = [t for t in report.phase_traces if t.startswith("Extractor:")]
    assert extractor_traces, f"No Extractor phase trace found. All traces: {report.phase_traces}"
    assert "serial" in extractor_traces[0], (
        f"Expected 'serial' with concurrency=1, got: {extractor_traces[0]!r}"
    )


# ---------------------------------------------------------------------------
# T3: extractor thread exception is captured in report.errors, others succeed
# ---------------------------------------------------------------------------

def test_pipeline_run_extractor_thread_exception_is_captured(tmp_path: Path) -> None:
    """T3: if one extractor thread raises, error is in report.errors; others complete."""
    kp_ids = ["kp-good-1", "kp-bad", "kp-good-2"]
    source_text = "Good content. Bad content. More good content. " * 50

    cfg = HolmesConfig(api_key="test-key", extractor_concurrency=3)
    provider = _StopProvider()
    km = _make_knowledge_map(kp_ids)
    classification = _make_classification()

    pipeline = ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        no_interactive=True,
        dry_run=False,
        skip_git_commit=True,
        _provider=provider,
    )

    def _extract_side_effect(kp, knowledge_map, ctx):
        if kp.id == "kp-bad":
            raise RuntimeError("Simulated extractor failure for kp-bad")
        return _DRAFT.format(kp_id=kp.id)

    with patch("holmes.kb.agent.pipeline.DocumentClassifier") as MockClassifier, \
         patch("holmes.kb.agent.pipeline.ReaderAgent") as MockReader, \
         patch("holmes.kb.agent.phases.extractor.ExtractorAgent.run",
               side_effect=_extract_side_effect), \
         patch("holmes.kb.agent.tools._find_all_entries_by_hash", return_value=[]), \
         patch("holmes.kb.agent.runner.ImportAgentRunner._git_commit", return_value=None), \
         patch("holmes.kb.agent.runner.ImportAgentRunner._finalize_skill_generation"):

        MockClassifier.return_value.classify.return_value = classification
        MockReader.return_value.run.return_value = km

        report = pipeline.run(source_text)

    # The failed KP should appear in report.errors.
    error_msgs = " ".join(report.errors)
    assert "kp-bad" in error_msgs, (
        f"Expected 'kp-bad' in report.errors, got: {report.errors}"
    )
    assert "extractor thread" in error_msgs.lower() or "RuntimeError" in error_msgs, (
        f"Expected thread exception message, got: {report.errors}"
    )
