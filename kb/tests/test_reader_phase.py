"""Unit tests for ReaderAgent — Phase 1 of the three-phase pipeline (T015)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holmes.kb.agent.knowledge_map import KnowledgeMap
from holmes.kb.agent.phases.reader import (
    COMPACT_HISTORY_THRESHOLD,
    COVERAGE_THRESHOLD,
    DIMINISHING_WINDOW,
    READER_COMPACT_PROMPT,
    READER_SYSTEM_PROMPT,
    ReaderAgent,
    ReaderConfig,
    _extract_last_assistant_text,
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
            return True, [], messages, {}
        stop, tcs = responses[idx]
        call_idx[0] += 1
        # Append a stub assistant message so messages list grows.
        updated = messages + [{"role": "assistant", "content": f"step {idx}"}]
        return stop, tcs, updated, {}

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


# ---------------------------------------------------------------------------
# 022: Context compression (US1), forced coverage (US2), observability (US3)
# ---------------------------------------------------------------------------


class TestExtractLastAssistantText:
    """Tests for _extract_last_assistant_text helper."""

    def test_extracts_string_content(self):
        messages = [{"role": "assistant", "content": "hello world"}]
        assert _extract_last_assistant_text(messages) == "hello world"

    def test_extracts_list_content_text_blocks(self):
        messages = [{"role": "assistant", "content": [
            {"type": "text", "text": "part1"},
            {"type": "text", "text": " part2"},
        ]}]
        assert _extract_last_assistant_text(messages) == "part1 part2"

    def test_returns_last_assistant_message(self):
        messages = [
            {"role": "assistant", "content": "first"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "second"},
        ]
        assert _extract_last_assistant_text(messages) == "second"

    def test_returns_empty_when_no_assistant(self):
        messages = [{"role": "user", "content": "hello"}]
        assert _extract_last_assistant_text(messages) == ""


class TestReaderCompactHistory:
    """Tests for 022 US1: semantic history compaction."""

    SOURCE = "G" * 1000

    def _make_compacting_provider(self, compact_summary: str) -> LLMProvider:
        """Provider that returns compact_summary on the compaction call (tools=[])."""
        provider = MagicMock(spec=LLMProvider)
        call_idx = [0]

        def _complete(messages, system, model, max_tokens, tools):
            idx = call_idx[0]
            call_idx[0] += 1
            if not tools:
                # Compaction call — return summary text
                summary_msg = {"role": "assistant", "content": compact_summary}
                return True, [], messages + [summary_msg], {}
            return True, [], messages + [{"role": "assistant", "content": f"step {idx}"}], {}

        def _append(messages, results):
            return messages + [{"role": "tool", "content": str(results)}]

        provider.complete.side_effect = _complete
        provider.append_tool_results.side_effect = _append
        return provider

    def test_should_compact_returns_true_when_over_threshold(self):
        """_should_compact returns True when total chars exceed threshold."""
        provider = MagicMock(spec=LLMProvider)
        agent = ReaderAgent(provider=provider, model="m")
        messages = [{"role": "user", "content": "x" * 1000}]
        assert agent._should_compact(messages, threshold=500) is True

    def test_should_compact_returns_false_when_under_threshold(self):
        """_should_compact returns False when total chars are within threshold."""
        provider = MagicMock(spec=LLMProvider)
        agent = ReaderAgent(provider=provider, model="m")
        messages = [{"role": "user", "content": "short"}]
        assert agent._should_compact(messages, threshold=500) is False

    def test_compact_history_replaces_messages_with_3(self):
        """_compact_history reduces history to [original, summary, cue]."""
        summary = "KP list: kp-1 | Redis issue\nSection 0-1000: Redis config"
        provider = self._make_compacting_provider(summary)
        agent = ReaderAgent(provider=provider, model="m")
        km = KnowledgeMap()
        ctx: dict[str, Any] = {}
        original_prompt = {"role": "user", "content": "Please read..."}
        many_messages = [original_prompt] + [
            {"role": "assistant", "content": f"step {i}"} for i in range(20)
        ]
        result = agent._compact_history(many_messages, km, ctx, ReaderConfig(), logs := [].append or (lambda m: None))
        assert len(result) == 3
        assert result[0] is original_prompt
        assert result[1]["role"] == "assistant"
        assert result[1]["content"] == summary

    def test_compact_history_falls_back_on_empty_summary(self):
        """_compact_history returns original messages when LLM produces no summary."""
        provider = self._make_compacting_provider("")  # empty summary
        agent = ReaderAgent(provider=provider, model="m")
        km = KnowledgeMap()
        ctx: dict[str, Any] = {}
        original = [{"role": "user", "content": "x" * 100}]
        logs: list[str] = []
        result = agent._compact_history(original, km, ctx, ReaderConfig(), logs.append)
        assert result is original
        assert any("Warning" in log or "skipping" in log for log in logs)

    def test_compact_history_disabled_when_threshold_zero(self):
        """Setting compact_history_threshold=0 disables compaction entirely."""
        source = "H" * 200
        responses = [(True, []), (True, [])]
        provider = _make_provider(responses)
        cfg = ReaderConfig(compact_history_threshold=0)
        agent = ReaderAgent(provider=provider, model="m", config=cfg)
        km = agent.run(source, {})
        # Should complete without error (no compaction attempted)
        assert km is not None

    def test_compact_prompt_covers_all_knowledge_types(self):
        """READER_COMPACT_PROMPT is not biased toward problem/solution framing."""
        # Explicitly says knowledge is not limited to problems
        assert "不限" in READER_COMPACT_PROMPT or "不要偏向" in READER_COMPACT_PROMPT
        # Mentions concept/process/model type knowledge
        assert "概念" in READER_COMPACT_PROMPT
        assert "流程" in READER_COMPACT_PROMPT

    def test_compact_prompt_preserves_kp_integrity(self):
        """READER_COMPACT_PROMPT instructs that KP info must not be modified."""
        assert "严禁" in READER_COMPACT_PROMPT or "不截断" in READER_COMPACT_PROMPT

    def test_compact_prompt_requires_terminology_section(self):
        """READER_COMPACT_PROMPT has a dedicated section for terminology/definitions."""
        assert "术语" in READER_COMPACT_PROMPT

    def test_compact_prompt_requires_cross_reference_section(self):
        """READER_COMPACT_PROMPT has a section for cross-section references."""
        assert "跨节" in READER_COMPACT_PROMPT

    def test_compact_prompt_instructs_for_future_reading_context(self):
        """READER_COMPACT_PROMPT frames compression as providing context for unread sections."""
        assert "还没读到" in READER_COMPACT_PROMPT or "未覆盖" in READER_COMPACT_PROMPT


class TestReaderAgent022Observability:
    """Tests for 022 US3: per-pass log_fn callback."""

    SOURCE = "D" * 600

    def test_log_fn_called_each_pass(self):
        """log_fn receives a string after every reading pass."""
        logs: list[str] = []
        responses = [
            (False, [_record_kp_call("KP1", 0, 300)]),
            (True, []),
            (True, []),
            (True, []),
        ]
        provider = _make_provider(responses)
        agent = ReaderAgent(provider=provider, model="test-model")
        agent.run(self.SOURCE, {}, log_fn=logs.append)
        assert len(logs) >= 1

    def test_log_fn_message_contains_coverage_and_kp_count(self):
        """log_fn message includes coverage percentage and new KP count."""
        logs: list[str] = []
        responses = [
            (False, [_record_kp_call("KP1", 0, 300), _read_range_call(0, 300)]),
            (True, []),
            (True, []),
            (True, []),
        ]
        provider = _make_provider(responses)
        agent = ReaderAgent(provider=provider, model="test-model")
        agent.run(self.SOURCE, {}, log_fn=logs.append)
        first_log = logs[0]
        assert "coverage" in first_log
        assert "KP" in first_log or "kp" in first_log.lower() or "new" in first_log

    def test_default_log_fn_does_not_raise(self):
        """Without log_fn, the default stderr logging does not raise."""
        responses = [(True, []), (True, [])]
        provider = _make_provider(responses)
        agent = ReaderAgent(provider=provider, model="test-model")
        # Should not raise even without log_fn argument
        km = agent.run(self.SOURCE, {})
        assert km is not None


class TestReaderAgent022ForcedCoverage:
    """Tests for 022 US2: forced coverage injection when gaps > min_uncovered_chars."""

    def test_forced_coverage_injected_when_gap_large(self):
        """When uncovered gap > min_uncovered_chars, a forced-read prompt is injected."""
        # 1000-char document; LLM only reads 0–100, leaving 900-char gap > 500 threshold
        source = "E" * 1000
        logs: list[str] = []

        # Pass 1 inner loop: LLM reads only first 100 chars then stops
        # Then forced coverage sub-pass: LLM stops again (no further KPs)
        # Run will continue passes until diminishing returns
        responses = [
            (False, [_read_range_call(0, 100)]),   # reads first 100, then…
            (True, []),                             # LLM stops → triggers forced coverage check
            (True, []),                             # forced coverage sub-pass: LLM stops
            (True, []),                             # pass 2: 0 new KPs (consecutive=1)
            (True, []),                             # forced coverage sub-pass
            (True, []),                             # pass 3: 0 new KPs (consecutive=2 → stop)
            (True, []),
        ]
        provider = _make_provider(responses)
        cfg = ReaderConfig(min_uncovered_chars=500)
        agent = ReaderAgent(provider=provider, model="test-model", config=cfg)
        agent.run(source, {}, log_fn=logs.append)

        # At least one log should mention forced coverage
        assert any("forced" in log.lower() or "coverage" in log.lower() for log in logs)

    def test_forced_coverage_not_injected_for_small_gaps(self):
        """Gaps <= min_uncovered_chars do not trigger forced coverage injection."""
        source = "F" * 600
        logs: list[str] = []

        # LLM reads 0–400, leaving only 200-char gap (< 500 threshold)
        responses = [
            (False, [_read_range_call(0, 400)]),
            (True, []),
            (True, []),
            (True, []),
        ]
        provider = _make_provider(responses)
        cfg = ReaderConfig(min_uncovered_chars=500)
        agent = ReaderAgent(provider=provider, model="test-model", config=cfg)
        agent.run(source, {}, log_fn=logs.append)

        # No log should contain "[forced coverage]"
        assert not any("[forced coverage]" in log for log in logs)


class TestReaderConfig:
    """Tests for 022 FR-008: configurable thresholds via ReaderConfig."""

    def test_custom_coverage_threshold(self):
        """ReaderConfig.coverage_threshold is used as the stop condition."""
        cfg = ReaderConfig(coverage_threshold=50.0)
        assert cfg.coverage_threshold == 50.0

    def test_custom_compact_threshold(self):
        """ReaderConfig.compact_history_threshold controls compaction trigger."""
        cfg = ReaderConfig(compact_history_threshold=20_000)
        assert cfg.compact_history_threshold == 20_000

    def test_custom_min_uncovered_chars(self):
        """ReaderConfig.min_uncovered_chars controls forced coverage trigger."""
        cfg = ReaderConfig(min_uncovered_chars=100)
        assert cfg.min_uncovered_chars == 100

    def test_default_config_matches_module_constants(self):
        """Default ReaderConfig values match the module-level constants."""
        from holmes.kb.agent.phases.reader import MIN_UNCOVERED_CHARS
        cfg = ReaderConfig()
        assert cfg.coverage_threshold == COVERAGE_THRESHOLD
        assert cfg.compact_history_threshold == COMPACT_HISTORY_THRESHOLD
        assert cfg.min_uncovered_chars == MIN_UNCOVERED_CHARS

