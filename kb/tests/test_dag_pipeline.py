"""Tests for pipeline.py _run_dag_pipeline() integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from holmes.kb.agent.dag.formatter import dag_to_markdown
from holmes.kb.agent.dag.schema import (
    Complexity,
    DAGEdge,
    DAGGraph,
    DAGNode,
    NodeType,
)
from holmes.kb.agent.provider.base import LLMProvider, ToolCall


class MockProvider(LLMProvider):
    def __init__(self, turns):
        self._turns = list(turns)
        self._idx = 0

    def complete(self, messages, system, model, max_tokens, tools):
        if self._idx >= len(self._turns):
            return True, [], messages, {}
        calls = self._turns[self._idx]
        self._idx += 1
        updated = list(messages) + [{"role": "assistant"}]
        if not calls:
            return True, [], updated, {}
        return False, calls, updated, {}

    def simple_complete(self, messages, system="", max_tokens=512):
        return ""

    def append_tool_results(self, messages, results):
        return list(messages) + [{"role": "user", "results": results}]


def _make_valid_dag_md() -> str:
    n1 = DAGNode("N1", "root", NodeType.decision, Complexity.simple,
                  children=[DAGEdge("yes", "N2")])
    n2 = DAGNode("N2", "proc", NodeType.remote_action, Complexity.process,
                  section_heading="### Steps",
                  children=[DAGEdge("done", "END")])
    g = DAGGraph(nodes=[n1, n2], title="T", source_file="src.md", generated="2026-06-24")
    return dag_to_markdown(g)


def test_run_dag_pipeline_no_longer_raises(tmp_path):
    """_run_dag_pipeline() must not raise NotImplementedError."""
    from holmes.kb.agent.pipeline import ThreePhaseImportPipeline

    valid_md = _make_valid_dag_md()
    turns = [
        [ToolCall(id="t1", name="write_dag", input={"content": valid_md})],
        [ToolCall(id="t2", name="output_dag", input={})],
    ]
    provider = MockProvider(turns)

    cfg = MagicMock()
    cfg.model = "test-model"

    pipeline = ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        no_interactive=True,
        dry_run=True,
        _provider=provider,
    )

    (tmp_path / "_import-state").mkdir()

    # Should not raise NotImplementedError
    report = pipeline._run_dag_pipeline(
        source_text="This is a pitfall document about hardware failure.",
        file_path=None,
    )
    assert report is not None
    assert not any("NotImplementedError" in e for e in report.errors)


def test_run_dag_pipeline_returns_import_report(tmp_path):
    """_run_dag_pipeline() returns an ImportReport instance."""
    from holmes.kb.agent.pipeline import ThreePhaseImportPipeline
    from holmes.kb.agent.report import ImportReport

    provider = MockProvider([[]])  # stop immediately
    cfg = MagicMock()
    cfg.model = "test-model"

    pipeline = ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        no_interactive=True,
        dry_run=True,
        _provider=provider,
    )
    (tmp_path / "_import-state").mkdir()

    report = pipeline._run_dag_pipeline("source text")
    assert isinstance(report, ImportReport)
