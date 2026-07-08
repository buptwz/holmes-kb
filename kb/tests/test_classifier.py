"""Unit tests for DocumentClassifier (042)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from holmes.kb.agent.phases.classifier import (
    ClassificationResult,
    DiagnosticComplexity,
    DocumentClassifier,
    DocumentType,
    GRANULARITY_HINTS,
)


# ---------------------------------------------------------------------------
# Mock LLM provider
# ---------------------------------------------------------------------------


def _make_provider(response_json: dict | None = None, raise_exc: Exception | None = None):
    """Build a mock LLMProvider that returns a fixed JSON response."""
    provider = MagicMock()

    if raise_exc is not None:
        provider.complete.side_effect = raise_exc
    else:
        default = {"doc_type": "incident", "reason": "test"}
        raw = json.dumps(response_json or default)
        updated = [{"role": "assistant", "content": raw}]
        provider.complete.return_value = (True, [], updated, {})

    return provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDocumentClassifier:
    def test_runbook_classification(self):
        provider = _make_provider({"doc_type": "runbook", "reason": "sequential steps"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("some runbook text")
        assert result.doc_type == DocumentType.runbook
        assert result.suggested_type == "process"

    def test_non_kb_classification(self):
        provider = _make_provider({"doc_type": "non_kb", "reason": "meeting notes"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("Q2 meeting notes...")
        assert result.doc_type == DocumentType.non_kb
        assert "meeting" in result.reason

    def test_exception_falls_back_to_incident(self):
        provider = _make_provider(raise_exc=RuntimeError("API down"))
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("some text")
        assert result.doc_type == DocumentType.incident
        assert "exception" in result.reason or "failed" in result.reason

    def test_malformed_json_falls_back(self):
        provider = MagicMock()
        updated = [{"role": "assistant", "content": "not json at all!!!"}]
        provider.complete.return_value = (True, [], updated, {})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("some text")
        assert result.doc_type == DocumentType.incident
        assert "parse failed" in result.reason or "failed" in result.reason

    def test_legacy_multi_incident_maps_to_incident(self):
        provider = _make_provider({"doc_type": "multi_incident", "reason": "multiple events"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("incident 1... incident 2...")
        assert result.doc_type == DocumentType.incident

    def test_needs_dag_always_false(self):
        """042: DAG routing removed — needs_dag always False."""
        provider = _make_provider({"doc_type": "incident", "reason": "test"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("complex diagnostic doc")
        assert result.needs_dag is False

    def test_mixed_type(self):
        provider = _make_provider({"doc_type": "mixed", "reason": "multi-type doc"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("incident + guidelines doc")
        assert result.doc_type == DocumentType.mixed

    def test_guideline_classification(self):
        provider = _make_provider({"doc_type": "guideline", "reason": "best practices"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("best practices document")
        assert result.doc_type == DocumentType.guideline
        assert result.suggested_type == "guideline"

    def test_unknown_doc_type_falls_back(self):
        provider = _make_provider({"doc_type": "banana", "reason": "unknown type"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("some document")
        assert result.doc_type == DocumentType.incident

    def test_reason_truncated_to_100(self):
        long_reason = "x" * 200
        provider = _make_provider({"doc_type": "runbook", "reason": long_reason})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("text")
        assert len(result.reason) <= 100

    def test_markdown_fenced_json_handled(self):
        provider = MagicMock()
        raw = '```json\n{"doc_type": "runbook", "reason": "fenced"}\n```'
        updated = [{"role": "assistant", "content": raw}]
        provider.complete.return_value = (True, [], updated, {})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("text")
        assert result.doc_type == DocumentType.runbook
        assert result.reason == "fenced"


class TestBackwardCompat:
    """042 backward compat: stub classes and fields still importable."""

    def test_diagnostic_complexity_importable(self):
        assert DiagnosticComplexity.simple == "simple"

    def test_granularity_hints_is_dict(self):
        assert isinstance(GRANULARITY_HINTS, dict)

    def test_classification_result_has_compat_fields(self):
        result = ClassificationResult(doc_type=DocumentType.incident, reason="test")
        assert hasattr(result, "complexity")
        assert hasattr(result, "granularity_hint")


class TestClassifierKnowledgeValueCriterion:
    """021 T008: _CLASSIFIER_SYSTEM_PROMPT uses knowledge-value criterion for non_kb."""

    def test_prompt_explains_knowledge_value_criterion(self):
        from holmes.kb.agent.phases.classifier import _CLASSIFIER_SYSTEM_PROMPT
        lower = _CLASSIFIER_SYSTEM_PROMPT.lower()
        assert "knowledge" in lower
        assert "non_kb" in lower or "non-kb" in lower

    def test_prompt_has_examples_showing_meeting_with_incident_is_not_non_kb(self):
        from holmes.kb.agent.phases.classifier import _CLASSIFIER_SYSTEM_PROMPT
        assert "meeting" in _CLASSIFIER_SYSTEM_PROMPT.lower()

    def test_mock_llm_incident_meeting_note_not_non_kb(self):
        provider = _make_provider({"doc_type": "incident", "reason": "contains incident analysis"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("Meeting note: Redis OOM incident discussion and fix")
        assert result.doc_type == DocumentType.incident

    def test_mock_llm_pure_admin_meeting_is_non_kb(self):
        provider = _make_provider({"doc_type": "non_kb", "reason": "only scheduling and logistics"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("Meeting: Q2 review schedule, OKR updates, coffee budget")
        assert result.doc_type == DocumentType.non_kb
