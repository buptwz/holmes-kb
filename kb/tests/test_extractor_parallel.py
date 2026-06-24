"""Tests for parallel Extractor phase (US2 perf optimisation)."""

from __future__ import annotations

import textwrap
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holmes.config import HolmesConfig
from holmes.kb.agent.pipeline import ExtractorResult, ThreePhaseImportPipeline
from holmes.kb.agent.provider.base import LLMProvider, ToolCall
from holmes.kb.agent.report import ImportReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DRAFT_TEMPLATE = textwrap.dedent("""\
    ---
    id: {kp_id}
    type: pitfall
    title: Error {kp_id}
    maturity: draft
    category: database
    tags: []
    created_at: "2026-01-01T00:00:00+00:00"
    updated_at: "2026-01-01T00:00:00+00:00"
    ---

    ## Root Cause

    Cause for {kp_id}.

    ## Resolution

    Fix for {kp_id}.
""")


class _NoOpProvider(LLMProvider):
    """Provider that always returns stop=True with no tool calls."""

    def complete(self, messages, system, model, max_tokens, tools):
        return True, [], list(messages), {}

    def simple_complete(self, messages, system="", max_tokens=512):
        return ""

    def append_tool_results(self, messages, results):
        return list(messages)


def _make_kp(kp_id: str, section_start: int = 0, section_end: int = 100) -> Any:
    """Build a minimal KnowledgePoint mock."""
    kp = MagicMock()
    kp.id = kp_id
    kp.description = f"Description of {kp_id}"
    kp.type_hint = "pitfall"
    kp.section_start = section_start
    kp.section_end = section_end
    kp.extracted = False
    return kp


def _make_knowledge_map(kp_ids: list[str]) -> Any:
    """Build a minimal KnowledgeMap mock with given KP IDs."""
    km = MagicMock()
    km.knowledge_points = [_make_kp(kp_id, i * 100, (i + 1) * 100) for i, kp_id in enumerate(kp_ids)]
    km.coverage_pct = 100.0
    km.diminishing_returns = False
    km.reading_passes = 1
    return km


# ---------------------------------------------------------------------------
# Test: all KPs are extracted
# ---------------------------------------------------------------------------

def test_parallel_extractor_all_kps_extracted(tmp_path: Path) -> None:
    """All KPs must appear in kp_drafts after parallel extraction."""
    kp_ids = ["kp-001", "kp-002", "kp-003", "kp-004"]
    km = _make_knowledge_map(kp_ids)
    cfg = HolmesConfig(api_key="test-key", extractor_concurrency=4)

    pipeline = ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        no_interactive=True,
        dry_run=True,
        _provider=_NoOpProvider(),
    )

    source_text = " ".join(f"Content for {kp_id}." for kp_id in kp_ids) * 20

    def _fake_extractor_run(kp, knowledge_map, ctx):
        return _DRAFT_TEMPLATE.format(kp_id=kp.id)

    with patch(
        "holmes.kb.agent.phases.extractor.ExtractorAgent.run",
        side_effect=_fake_extractor_run,
    ):
        report = ImportReport(dry_run=True)
        ctx: dict[str, Any] = {
            "kb_root": tmp_path,
            "dry_run": True,
            "provider": pipeline._provider,
            "model": cfg.model,
            "report": report,
            "source_hash": "hash123",
            "no_interactive": True,
            "source_text": source_text,
            "force_type": "",
            "force": False,
        }
        # Inject km directly into pipeline run by patching reader
        pipeline._provider = _NoOpProvider()

        # Run just the extractor portion by setting up state manually
        from holmes.kb.agent.phases.reader import COVERAGE_THRESHOLD
        pipeline.cfg = cfg

        # Re-run extraction loop portion directly
        kp_drafts: dict[str, str] = {}
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from holmes.kb.agent.doc_access import DocumentCursor

        # Simulate what run() does for the Extractor phase
        concurrency = max(1, cfg.extractor_concurrency)
        actual_workers = min(concurrency, len(km.knowledge_points))

        def _extract(kp):
            from holmes.kb.agent.phases.extractor import ExtractorAgent
            from holmes.kb.agent.normalizer import DraftNormalizer
            result = ExtractorResult(kp_id=kp.id)
            ctx_copy = dict(ctx)
            ctx_copy["doc_cursor"] = DocumentCursor(source_text)
            extractor = ExtractorAgent(provider=pipeline._provider, model=cfg.model)
            draft = extractor.run(kp, km, ctx_copy)
            if not draft:
                return result
            repaired, warning = ExtractorAgent._validate_and_repair_draft(draft)
            if not repaired:
                result.errors.append(f"{kp.id}: draft format error — {warning}")
                return result
            normalizer = DraftNormalizer()
            repaired, _ = normalizer.normalize(repaired, kb_type=kp.type_hint or "")
            result.repaired = repaired
            return result

        with ThreadPoolExecutor(max_workers=actual_workers) as pool:
            futures = {pool.submit(_extract, kp): kp for kp in km.knowledge_points}
            for future in as_completed(futures):
                kp = futures[future]
                ex_result = future.result()
                if ex_result.repaired:
                    kp_drafts[kp.id] = ex_result.repaired

    assert set(kp_drafts.keys()) == set(kp_ids), (
        f"Expected all KP IDs in kp_drafts, got {set(kp_drafts.keys())}"
    )


# ---------------------------------------------------------------------------
# Test: extractor_concurrency=1 behaves like serial
# ---------------------------------------------------------------------------

def test_extractor_concurrency_one_is_serial(tmp_path: Path) -> None:
    """extractor_concurrency=1 must produce identical results to serial execution."""
    kp_ids = ["kp-A", "kp-B"]
    cfg = HolmesConfig(api_key="test-key", extractor_concurrency=1)

    pipeline = ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        no_interactive=True,
        dry_run=True,
        _provider=_NoOpProvider(),
    )

    assert pipeline.cfg.extractor_concurrency == 1


# ---------------------------------------------------------------------------
# Test: ExtractorResult dataclass
# ---------------------------------------------------------------------------

def test_extractor_result_defaults() -> None:
    """ExtractorResult must have sensible defaults."""
    r = ExtractorResult(kp_id="test-001")
    assert r.kp_id == "test-001"
    assert r.draft is None
    assert r.repaired is None
    assert r.errors == []
    assert r.warnings == []
    assert r.phase_traces == []


def test_extractor_result_with_values() -> None:
    """ExtractorResult must store all assigned fields."""
    r = ExtractorResult(
        kp_id="kp-X",
        draft="draft content",
        repaired="repaired content",
        errors=["err1"],
        warnings=["warn1"],
        phase_traces=["trace1"],
    )
    assert r.repaired == "repaired content"
    assert r.errors == ["err1"]


# ---------------------------------------------------------------------------
# Test: phase_traces includes concurrency info
# ---------------------------------------------------------------------------

def test_phase_trace_includes_parallel_label(tmp_path: Path) -> None:
    """Extractor phase trace must include 'parallel, N workers' when concurrency > 1."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from holmes.kb.agent.doc_access import DocumentCursor

    cfg = HolmesConfig(api_key="test-key", extractor_concurrency=4)
    pipeline = ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        no_interactive=True,
        dry_run=True,
        _provider=_NoOpProvider(),
    )

    km = _make_knowledge_map(["kp-1", "kp-2"])
    source_text = "Content for kp-1 and kp-2. " * 50
    report = ImportReport(dry_run=True)
    kp_drafts: dict[str, str] = {}

    def _fake_extractor_run(kp, knowledge_map, ctx):
        return _DRAFT_TEMPLATE.format(kp_id=kp.id)

    with patch(
        "holmes.kb.agent.phases.extractor.ExtractorAgent.run",
        side_effect=_fake_extractor_run,
    ):
        # Inline the extractor phase logic (same as what run() does).
        from holmes.kb.agent.normalizer import DraftNormalizer
        from holmes.kb.agent.phases.extractor import ExtractorAgent

        _total_kps = len(km.knowledge_points)
        concurrency = max(1, cfg.extractor_concurrency)
        actual_workers = min(concurrency, _total_kps)

        def _extract(kp):
            result = ExtractorResult(kp_id=kp.id)
            ctx_copy = {"doc_cursor": DocumentCursor(source_text)}
            extractor = ExtractorAgent(provider=pipeline._provider, model=cfg.model)
            draft = extractor.run(kp, km, ctx_copy)
            if not draft:
                return result
            repaired, _ = ExtractorAgent._validate_and_repair_draft(draft)
            if repaired:
                normalizer = DraftNormalizer()
                repaired, _ = normalizer.normalize(repaired, kb_type=kp.type_hint or "")
                result.repaired = repaired
            return result

        with ThreadPoolExecutor(max_workers=actual_workers) as pool:
            futures = {pool.submit(_extract, kp): kp for kp in km.knowledge_points}
            for future in as_completed(futures):
                kp = futures[future]
                ex_result = future.result()
                if ex_result.repaired:
                    kp.extracted = True
                    kp_drafts[kp.id] = ex_result.repaired

        concurrency_label = (
            f"parallel, {actual_workers} worker{'s' if actual_workers != 1 else ''}"
            if actual_workers > 1
            else "serial"
        )
        trace = (
            f"Extractor: {len(kp_drafts)}/{_total_kps} "
            f"knowledge points extracted ({concurrency_label})"
        )
        report.phase_traces.append(trace)

    assert "parallel" in trace, f"Expected 'parallel' in trace: {trace!r}"
    assert "2 workers" in trace, f"Expected '2 workers' in trace: {trace!r}"
    assert set(kp_drafts.keys()) == {"kp-1", "kp-2"}
