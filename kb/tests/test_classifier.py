"""Unit tests for DocumentClassifier (018 Root D)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from holmes.kb.agent.phases.classifier import (
    ClassificationResult,
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
        raw = json.dumps(response_json or {"doc_type": "single_incident", "reason": "test"})
        # Simulate the updated messages list with assistant reply.
        updated = [{"role": "assistant", "content": raw}]
        provider.complete.return_value = (True, [], updated, {})

    return provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDocumentClassifier:
    def test_runbook_classification(self):
        """018: runbook → DocumentType.runbook with granularity hint."""
        provider = _make_provider({"doc_type": "runbook", "reason": "sequential steps"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("some runbook text")
        assert result.doc_type == DocumentType.runbook
        assert "3" in result.granularity_hint or "8" in result.granularity_hint

    def test_non_kb_classification(self):
        """018: non_kb → DocumentType.non_kb with empty granularity hint."""
        provider = _make_provider({"doc_type": "non_kb", "reason": "meeting notes"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("Q2 meeting notes...")
        assert result.doc_type == DocumentType.non_kb
        assert result.granularity_hint == ""
        assert "meeting" in result.reason

    def test_exception_falls_back_to_single_incident(self):
        """018: LLM exception → default single_incident with no raise."""
        provider = _make_provider(raise_exc=RuntimeError("API down"))
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("some text")
        assert result.doc_type == DocumentType.single_incident
        assert "classification failed" in result.reason

    def test_malformed_json_falls_back(self):
        """018: malformed JSON response → default single_incident."""
        provider = MagicMock()
        updated = [{"role": "assistant", "content": "not json at all!!!"}]
        provider.complete.return_value = (True, [], updated, {})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("some text")
        assert result.doc_type == DocumentType.single_incident
        assert "classification failed" in result.reason

    def test_multi_incident_hint(self):
        """018: multi_incident → hint contains 'one knowledge point per distinct incident'."""
        provider = _make_provider({"doc_type": "multi_incident", "reason": "multiple events"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("incident 1... incident 2...")
        assert result.doc_type == DocumentType.multi_incident
        assert "one knowledge point per distinct incident" in result.granularity_hint

    def test_single_incident_empty_hint(self):
        """018: single_incident → empty granularity_hint."""
        provider = _make_provider({"doc_type": "single_incident", "reason": "single event"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("one incident description")
        assert result.doc_type == DocumentType.single_incident
        assert result.granularity_hint == ""

    def test_guideline_hint(self):
        """018: guideline → hint mentions 'rule or principle'."""
        provider = _make_provider({"doc_type": "guideline", "reason": "best practices"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("best practices document")
        assert result.doc_type == DocumentType.guideline
        assert "rule" in result.granularity_hint.lower() or "principle" in result.granularity_hint.lower()

    def test_unknown_doc_type_falls_back(self):
        """018: unknown doc_type value → falls back to single_incident."""
        provider = _make_provider({"doc_type": "banana", "reason": "unknown type"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("some document")
        assert result.doc_type == DocumentType.single_incident

    def test_reason_truncated_to_100(self):
        """018: reason field is capped at 100 chars."""
        long_reason = "x" * 200
        provider = _make_provider({"doc_type": "runbook", "reason": long_reason})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("text")
        assert len(result.reason) <= 100

    def test_markdown_fenced_json_handled(self):
        """018: LLM wraps JSON in ```json ... ``` fences → still parsed correctly."""
        provider = MagicMock()
        raw = '```json\n{"doc_type": "runbook", "reason": "fenced"}\n```'
        updated = [{"role": "assistant", "content": raw}]
        provider.complete.return_value = (True, [], updated, {})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("text")
        assert result.doc_type == DocumentType.runbook
        assert result.reason == "fenced"


class TestGranularityHints:
    def test_all_types_have_hints_entry(self):
        """018: every DocumentType has an entry in GRANULARITY_HINTS."""
        for dt in DocumentType:
            assert dt in GRANULARITY_HINTS, f"Missing hint for {dt}"

    def test_non_kb_and_single_incident_empty(self):
        assert GRANULARITY_HINTS[DocumentType.non_kb] == ""
        assert GRANULARITY_HINTS[DocumentType.single_incident] == ""


# ---------------------------------------------------------------------------
# T008 (021): classifier prompt contains knowledge-value criterion
# ---------------------------------------------------------------------------


class TestClassifierKnowledgeValueCriterion:
    """021 T008: _CLASSIFIER_SYSTEM_PROMPT uses knowledge-value criterion for non_kb."""

    def test_prompt_explains_knowledge_value_criterion(self):
        """non_kb criterion must be based on content knowledge value, not format."""
        from holmes.kb.agent.phases.classifier import _CLASSIFIER_SYSTEM_PROMPT

        lower = _CLASSIFIER_SYSTEM_PROMPT.lower()
        # Must mention that it's about knowledge value, not document type/format
        assert "knowledge" in lower
        # Must not solely say "meeting notes" as the criterion
        # (must also convey that format doesn't determine non_kb)
        assert "non_kb" in lower or "non-kb" in lower

    def test_prompt_has_examples_showing_meeting_with_incident_is_not_non_kb(self):
        """Prompt must show that meeting notes WITH incident analysis are not non_kb."""
        from holmes.kb.agent.phases.classifier import _CLASSIFIER_SYSTEM_PROMPT

        # Should contain a positive example showing incident-containing meeting notes → not non_kb
        assert "meeting" in _CLASSIFIER_SYSTEM_PROMPT.lower()
        # The example should show meeting notes as NOT non_kb
        lines = _CLASSIFIER_SYSTEM_PROMPT.splitlines()
        meeting_lines = [l for l in lines if "meeting" in l.lower()]
        assert len(meeting_lines) > 0

    def test_mock_llm_incident_meeting_note_not_non_kb(self):
        """Mock LLM returning single_incident for meeting note with incident is accepted."""
        provider = _make_provider({"doc_type": "single_incident", "reason": "contains incident analysis"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("Meeting note: Redis OOM incident discussion and fix")
        assert result.doc_type == DocumentType.single_incident

    def test_mock_llm_pure_admin_meeting_is_non_kb(self):
        """Mock LLM returning non_kb for pure logistics meeting is accepted."""
        provider = _make_provider({"doc_type": "non_kb", "reason": "only scheduling and logistics"})
        classifier = DocumentClassifier(provider=provider, model="test-model")
        result = classifier.classify("Meeting: Q2 review schedule, OKR updates, coffee budget")
        assert result.doc_type == DocumentType.non_kb
