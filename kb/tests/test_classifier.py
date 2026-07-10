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
    analyze_document_structure,
)


# ---------------------------------------------------------------------------
# Mock LLM provider
# ---------------------------------------------------------------------------


def _make_provider(response_json: dict | None = None, raise_exc: Exception | None = None):
    """Build a mock LLMProvider that returns a fixed JSON response."""
    provider = MagicMock()

    if raise_exc is not None:
        provider.simple_complete.side_effect = raise_exc
    else:
        default = {"doc_type": "incident", "reason": "test"}
        raw = json.dumps(response_json or default)
        provider.simple_complete.return_value = raw

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
        provider.simple_complete.return_value = "not json at all!!!"
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
        provider.simple_complete.return_value = '```json\n{"doc_type": "runbook", "reason": "fenced"}\n```'
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


class TestAnalyzeDocumentStructure:
    """Tests for the zero-LLM structural analysis function."""

    def test_counts_ordered_steps(self):
        doc = "1. First step\n2. Second step\n3. Third step\nSome other text."
        result = analyze_document_structure(doc)
        assert result["ordered_steps"] == 3

    def test_counts_h3_steps(self):
        doc = "### Step 1: Prepare\nDo stuff\n### Step 2: Execute\nMore stuff"
        result = analyze_document_structure(doc)
        assert result["ordered_steps"] >= 2

    def test_counts_symptom_keywords(self):
        doc = "症状：系统 error 无法启动，crash 后 fail to boot"
        result = analyze_document_structure(doc)
        assert result["symptom_mentions"] >= 3

    def test_counts_decision_keywords(self):
        doc = "Option A: use Gen5\nOption B: use Gen4\nWe chose Option A due to trade-off"
        result = analyze_document_structure(doc)
        assert result["decision_mentions"] >= 2

    def test_counts_rule_keywords(self):
        doc = "必须佩戴防静电腕带。不允许裸手接触 PCB。Best practice: ground yourself."
        result = analyze_document_structure(doc)
        assert result["rule_mentions"] >= 3

    def test_step_ratio_high_for_process(self):
        lines = [f"{i}. Step {i}: do something" for i in range(1, 11)]
        lines.append("Some context line.")
        doc = "\n".join(lines)
        result = analyze_document_structure(doc)
        assert result["step_ratio"] > 0.15
        assert result["ordered_steps"] >= 10

    def test_step_ratio_low_for_incident(self):
        doc = "症状：GPU error\n根因：金手指氧化\n解决：重新插拔\nSome analysis text."
        result = analyze_document_structure(doc)
        assert result["step_ratio"] < 0.1
        assert result["ordered_steps"] == 0

    def test_empty_document(self):
        result = analyze_document_structure("")
        assert result["ordered_steps"] == 0
        assert result["symptom_mentions"] == 0
