"""Unit tests for ReaderAgent — Phase 1 of the three-phase pipeline (T015)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holmes.kb.agent.knowledge_map import KnowledgeMap
from holmes.kb.agent.phases.reader import (
    COVERAGE_THRESHOLD,
    DIMINISHING_WINDOW,
    READER_SYSTEM_PROMPT,
    ReaderAgent,
)
from holmes.kb.agent.provider.base import LLMProvider, ToolCall


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_provider(responses: list[tuple[bool, list[ToolCall]]]) -> LLMProvider:
    """Build a mock LLMProvider that returns the given sequence of responses."""
    provider = MagicMock(spec=LLMProvider)

    call_idx = [0]

    def _complete(messages, system, model, max_tokens, tools):
        idx = call_idx[0]
        if idx >= len(responses):
            return True, [], messages
        stop, tcs = responses[idx]
        call_idx[0] += 1
        # Append a stub assistant message so messages list grows.
        updated = messages + [{"role": "assistant", "content": f"step {idx}"}]
        return stop, tcs, updated

    def _append_tool_results(messages, results):
        tool_results = [{"role": "tool", "tool_use_id": tid, "content": c} for tid, c in results]
        return messages + tool_results

    provider.complete.side_effect = _complete
    provider.append_tool_results.side_effect = _append_tool_results
    return provider


def _record_kp_call(description: str, start: int, end: int, lang: str = "en") -> ToolCall:
    return ToolCall(
        id=f"tc-rk-{start}",
        name="record_knowledge_point",
        input={
            "description": description,
            "section_start": start,
            "section_end": end,
            "type_hint": "pitfall",
            "language": lang,
        },
    )


def _read_range_call(start: int, end: int) -> ToolCall:
    return ToolCall(
        id=f"tc-rdr-{start}",
        name="read_document_range",
        input={"start_char": start, "end_char": end},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReaderAgentBasic:
    SOURCE = "# Title\n\nThis is a short document about Redis OOM issues."

    def test_returns_knowledge_map(self):
        """ReaderAgent.run() always returns a KnowledgeMap."""
        provider = _make_provider([(True, [])])  # LLM stops immediately
        agent = ReaderAgent(provider=provider, model="test-model")
        km = agent.run(self.SOURCE, {})
        assert isinstance(km, KnowledgeMap)

    def test_sets_source_text_in_ctx(self):
        """ctx['source_text'] is set to the full source text."""
        provider = _make_provider([(True, [])])
        agent = ReaderAgent(provider=provider, model="test-model")
        ctx: dict[str, Any] = {}
        agent.run(self.SOURCE, ctx)
        assert ctx["source_text"] == self.SOURCE

    def test_source_text_never_truncated(self):
        """ctx['source_text'] equals the original source even for large docs."""
        large_source = "x" * 20_000
        provider = _make_provider([(True, [])])
        agent = ReaderAgent(provider=provider, model="test-model")
        ctx: dict[str, Any] = {}
        agent.run(large_source, ctx)
        assert ctx["source_text"] == large_source

    def test_single_knowledge_point_recorded(self):
        """A record_knowledge_point tool call adds a KP to the map."""
        responses = [
            (False, [_record_kp_call("Redis OOM", 0, len(self.SOURCE))]),
            (True, []),  # LLM stops on next turn
        ]
        provider = _make_provider(responses)
        agent = ReaderAgent(provider=provider, model="test-model")
        km = agent.run(self.SOURCE, {})
        assert len(km.knowledge_points) == 1
        assert km.knowledge_points[0].description == "Redis OOM"

    def test_multiple_knowledge_points_recorded(self):
        """Multiple record_knowledge_point calls create multiple KPs."""
        source = "A" * 600
        responses = [
            (
                False,
                [
                    _record_kp_call("Redis issue", 0, 200),
                    _record_kp_call("MySQL issue", 200, 400),
                    _record_kp_call("Nginx issue", 400, 600),
                ],
            ),
            (True, []),
        ]
        provider = _make_provider(responses)
        agent = ReaderAgent(provider=provider, model="test-model")
        km = agent.run(source, {})
        assert len(km.knowledge_points) == 3

    def test_kp_ids_are_sequential(self):
        """KP IDs are assigned as kp-1, kp-2, ..."""
        source = "B" * 200
        responses = [
            (False, [_record_kp_call("A", 0, 100), _record_kp_call("B", 100, 200)]),
            (True, []),
        ]
        provider = _make_provider(responses)
        agent = ReaderAgent(provider=provider, model="test-model")
        km = agent.run(source, {})
        assert km.knowledge_points[0].id == "kp-1"
        assert km.knowledge_points[1].id == "kp-2"

    def test_reading_passes_counted(self):
        """reading_passes reflects how many LLM passes were made.

        With DIMINISHING_WINDOW=2, a single zero-KP response causes 2 passes
        (agent retries once before declaring diminishing returns).
        """
        provider = _make_provider([(True, [])])  # stop immediately; mock returns (True,[]) for all further calls too
        agent = ReaderAgent(provider=provider, model="test-model")
        km = agent.run(self.SOURCE, {})
        # Must complete DIMINISHING_WINDOW consecutive zero-KP passes before stopping
        assert km.reading_passes == DIMINISHING_WINDOW
        assert km.diminishing_returns is True


class TestReaderAgentDiminishingReturns:
    SOURCE = "C" * 500

    def test_stops_after_diminishing_window_zero_passes(self):
        """Stops and sets diminishing_returns=True after DIMINISHING_WINDOW passes with 0 new KPs."""
        # First pass: 1 KP found. Second and third passes: 0 KPs. Should stop after 2 zero-passes.
        responses = [
            (False, [_record_kp_call("First KP", 0, 250)]),
            (True, []),  # end of pass 1
            # Pass 2: no new KPs
            (True, []),
            # Pass 3: no new KPs → DIMINISHING_WINDOW reached
            (True, []),
        ]
        provider = _make_provider(responses)
        agent = ReaderAgent(provider=provider, model="test-model")
        km = agent.run(self.SOURCE, {})
        assert km.diminishing_returns is True

    def test_diminishing_returns_with_two_zero_passes_from_start(self):
        """If the first 2 passes both yield 0 KPs, stop with diminishing_returns=True."""
        # Both passes stop immediately with no tool calls
        responses = [
            (True, []),  # pass 1: 0 new KPs
            (True, []),  # pass 2: 0 new KPs → DIMINISHING_WINDOW=2 reached
        ]
        provider = _make_provider(responses)
        agent = ReaderAgent(provider=provider, model="test-model")
        km = agent.run(self.SOURCE, {})
        assert km.diminishing_returns is True
        assert len(km.knowledge_points) == 0

    def test_consecutive_count_resets_when_kps_found(self):
        """Consecutive zero-pass count resets when a pass finds new KPs."""
        # Pass 1: 0 KPs, Pass 2: 1 KP (resets counter), Pass 3+4: 0 KPs → stop
        responses = [
            (True, []),  # pass 1: 0 new KPs (consecutive=1)
            # Pass 2: 1 new KP found → consecutive resets to 0
            (False, [_record_kp_call("Late KP", 0, 250)]),
            (True, []),  # end of pass 2
            # Pass 3: 0 new KPs (consecutive=1)
            (True, []),
            # Pass 4: 0 new KPs (consecutive=2 → stop)
            (True, []),
        ]
        provider = _make_provider(responses)
        agent = ReaderAgent(provider=provider, model="test-model")
        km = agent.run(self.SOURCE, {})
        assert km.diminishing_returns is True
        assert len(km.knowledge_points) == 1


class TestReaderAgentDocAccessTools:
    SOURCE = "# Title\n\nContent about Redis. More content. " + "x" * 200

    def test_doc_access_tools_available(self):
        """read_document_range tool calls are handled correctly."""
        responses = [
            (False, [_read_range_call(0, 50)]),
            (True, []),
        ]
        provider = _make_provider(responses)
        agent = ReaderAgent(provider=provider, model="test-model")
        ctx: dict[str, Any] = {}
        km = agent.run(self.SOURCE, ctx)
        # Reading creates a DocumentCursor in ctx
        assert "doc_cursor" in ctx

    def test_coverage_tracked_via_cursor(self):
        """After reading, total_chars and chars_read are updated from DocumentCursor."""
        responses = [
            (False, [_read_range_call(0, len(self.SOURCE))]),
            (True, []),
        ]
        provider = _make_provider(responses)
        agent = ReaderAgent(provider=provider, model="test-model")
        ctx: dict[str, Any] = {}
        km = agent.run(self.SOURCE, ctx)
        assert km.total_chars == len(self.SOURCE)
        assert km.chars_read > 0


class TestReaderKPScoping:
    """Tests for D-3: KP scoping instruction prevents over-splitting."""

    def test_reader_system_prompt_contains_scoping_instruction(self):
        """READER_SYSTEM_PROMPT must contain the one-incident-one-KP scoping instruction."""
        assert "One incident" in READER_SYSTEM_PROMPT
        assert "ONE" in READER_SYSTEM_PROMPT or "one" in READER_SYSTEM_PROMPT.lower()

    def test_reader_system_prompt_forbids_splitting_same_incident(self):
        """READER_SYSTEM_PROMPT must explicitly forbid splitting symptoms/root-cause/resolution."""
        prompt_lower = READER_SYSTEM_PROMPT.lower()
        # Should mention not splitting the same incident
        assert "do not" in prompt_lower or "not create" in prompt_lower or "not split" in prompt_lower

    def test_single_incident_produces_at_most_two_kps(self):
        """A single-incident document should produce ≤ 2 KPs with correct prompting.

        The mock simulates an LLM that records only 1 KP for a single incident
        (symptoms + root cause + resolution in one document), as guided by the
        scoping instruction.
        """
        source = (
            "## Incident: Redis OOM\n\n"
            "### Symptoms\nRedis memory usage 100%.\n\n"
            "### Root Cause\nMaxmemory policy misconfigured.\n\n"
            "### Resolution\nSet maxmemory-policy allkeys-lru.\n"
        )
        # Correctly-guided LLM records 1 KP for the whole incident
        responses = [
            (False, [_record_kp_call("Redis OOM — maxmemory policy misconfigured", 0, len(source))]),
            (True, []),
        ]
        provider = _make_provider(responses)
        agent = ReaderAgent(provider=provider, model="test-model")
        km = agent.run(source, {})
        assert len(km.knowledge_points) <= 2

    def test_single_incident_single_kp_description(self):
        """The single KP description should be the full problem description, not just symptoms."""
        source = "Incident: DB connection pool exhausted. Cause: leak in query. Fix: close connections.\n"
        responses = [
            (False, [_record_kp_call("DB connection pool exhausted due to query leak", 0, len(source))]),
            (True, []),
        ]
        provider = _make_provider(responses)
        agent = ReaderAgent(provider=provider, model="test-model")
        km = agent.run(source, {})
        assert len(km.knowledge_points) == 1
        kp = km.knowledge_points[0]
        # Description should encompass the problem, not just one section
        assert len(kp.description) > 10

