"""Tests for holmes.kb.agent.compact — tool-use loop context compaction."""

import json
import pytest

from holmes.kb.agent.compact import (
    CompactAdapter,
    GeneratorCompactAdapter,
    SummarizerCompactAdapter,
    ToolLoopCompact,
    extract_read_ranges,
    format_read_progress,
    get_context_window,
    snip_old_tool_results,
    _covered_chars,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_tool_result_msg(tool_call_id: str, start: int, end: int, total: int, text: str = "...") -> dict:
    """Build an OpenAI-format tool result message."""
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps({
            "text": text,
            "start_char": start,
            "end_char": end,
            "total_chars": total,
        }),
    }


def _make_assistant_msg_with_tool_call(
    tool_call_id: str, start: int, end: int,
) -> dict:
    """Build an OpenAI-format assistant message with a read_document_range call."""
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": "read_document_range",
                    "arguments": json.dumps({
                        "start_char": start,
                        "end_char": end,
                    }),
                },
            }
        ],
    }


def _make_outline() -> list[dict]:
    """Sample 3-section outline."""
    return [
        {"level": 2, "text": "Symptoms", "offset": 0, "length": 5000},
        {"level": 2, "text": "Root Cause", "offset": 5000, "length": 8000},
        {"level": 2, "text": "Resolution", "offset": 13000, "length": 17000},
        {"level": 3, "text": "路径 A", "offset": 13000, "length": 6000},
        {"level": 3, "text": "路径 B", "offset": 19000, "length": 5000},
        {"level": 3, "text": "路径 C", "offset": 24000, "length": 6000},
    ]


def _build_tool_loop_messages(num_reads: int, total_chars: int = 30000) -> list:
    """Build a realistic tool-use message history with N read_document_range calls."""
    chunk_size = total_chars // max(num_reads, 1)
    messages = [{"role": "user", "content": "Extract summary from this doc..."}]
    for i in range(num_reads):
        start = i * chunk_size
        end = min(start + chunk_size, total_chars)
        tc_id = f"tc_{i}"
        messages.append(_make_assistant_msg_with_tool_call(tc_id, start, end))
        messages.append(_make_tool_result_msg(tc_id, start, end, total_chars, text="x" * 3000))
    return messages


class MockProvider:
    """Minimal mock for LLMProvider."""

    def __init__(self, simple_complete_response: str = "{}"):
        self._simple_response = simple_complete_response
        self.simple_complete_calls: list = []

    def simple_complete(self, messages, system="", max_tokens=512):
        self.simple_complete_calls.append({
            "messages": messages,
            "system": system,
            "max_tokens": max_tokens,
        })
        return self._simple_response

    def complete(self, messages, system, model, max_tokens, tools):
        # Return stop=True to end loop
        return True, [], list(messages), {"input_tokens": 0, "output_tokens": 0}

    def append_tool_results(self, messages, results):
        updated = list(messages)
        for tool_call_id, content in results:
            updated.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})
        return updated


# ===========================================================================
# Tests: get_context_window
# ===========================================================================

class TestGetContextWindow:
    def test_known_model(self):
        assert get_context_window("deepseek-v4-pro") == 128_000

    def test_prefix_match(self):
        assert get_context_window("deepseek-v4-flash-latest") == 64_000

    def test_unknown_model(self):
        assert get_context_window("gpt-4o-mini") == 64_000


# ===========================================================================
# Tests: extract_read_ranges
# ===========================================================================

class TestExtractReadRanges:
    def test_extracts_ranges_from_openai_format(self):
        messages = [
            _make_assistant_msg_with_tool_call("tc_0", 0, 8000),
            _make_tool_result_msg("tc_0", 0, 8000, 30000),
            _make_assistant_msg_with_tool_call("tc_1", 8000, 16000),
            _make_tool_result_msg("tc_1", 8000, 16000, 30000),
        ]
        ranges = extract_read_ranges(messages)
        assert ranges == [(0, 8000), (8000, 16000)]

    def test_empty_messages(self):
        assert extract_read_ranges([]) == []

    def test_ignores_non_read_tool_calls(self):
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "tc_x",
                    "type": "function",
                    "function": {
                        "name": "search_in_document",
                        "arguments": json.dumps({"query": "hello"}),
                    },
                }],
            },
        ]
        assert extract_read_ranges(messages) == []

    def test_sorted_output(self):
        messages = [
            _make_assistant_msg_with_tool_call("tc_1", 8000, 16000),
            _make_tool_result_msg("tc_1", 8000, 16000, 30000),
            _make_assistant_msg_with_tool_call("tc_0", 0, 8000),
            _make_tool_result_msg("tc_0", 0, 8000, 30000),
        ]
        ranges = extract_read_ranges(messages)
        assert ranges == [(0, 8000), (8000, 16000)]


# ===========================================================================
# Tests: _covered_chars
# ===========================================================================

class TestCoveredChars:
    def test_full_overlap(self):
        assert _covered_chars([(0, 100)], 0, 100) == 100

    def test_partial_overlap(self):
        assert _covered_chars([(0, 50)], 25, 75) == 25

    def test_no_overlap(self):
        assert _covered_chars([(0, 50)], 60, 100) == 0

    def test_multiple_ranges(self):
        ranges = [(0, 30), (50, 80)]
        # Section [20, 90): covered by [0,30)→10 chars + [50,80)→30 chars = 40
        assert _covered_chars(ranges, 20, 90) == 40


# ===========================================================================
# Tests: format_read_progress
# ===========================================================================

class TestFormatReadProgress:
    def test_fully_read_section(self):
        outline = [{"level": 2, "text": "Section A", "offset": 0, "length": 5000}]
        result = format_read_progress(outline, [(0, 5000)], 5000)
        assert "✓ 已读" in result

    def test_unread_section(self):
        outline = [{"level": 2, "text": "Section A", "offset": 0, "length": 5000}]
        result = format_read_progress(outline, [], 5000)
        assert "← 未读" in result

    def test_partially_read_section(self):
        outline = [{"level": 2, "text": "Section A", "offset": 0, "length": 10000}]
        result = format_read_progress(outline, [(0, 4000)], 10000)
        assert "△ 部分已读" in result

    def test_no_outline_shows_raw_coverage(self):
        result = format_read_progress([], [(0, 5000)], 10000)
        assert "5000/10000" in result

    def test_mixed_coverage(self):
        outline = _make_outline()
        # Read Symptoms (0-5000) and 路径 A (13000-19000) fully
        read_ranges = [(0, 5000), (13000, 19000)]
        result = format_read_progress(outline, read_ranges, 30000)
        assert "Symptoms" in result
        assert "✓ 已读" in result
        assert "← 未读" in result


# ===========================================================================
# Tests: snip_old_tool_results
# ===========================================================================

class TestSnipOldToolResults:
    def test_keeps_recent_results(self):
        messages = _build_tool_loop_messages(3)
        snipped = snip_old_tool_results(messages, keep_recent=2)
        # 3 tool results: snip the oldest 1, keep recent 2
        tool_msgs = [m for m in snipped if m.get("role") == "tool"]
        assert len(tool_msgs) == 3
        # First tool result should be snipped
        first_content = json.loads(tool_msgs[0]["content"])
        assert "已处理" in first_content["text"]
        # Last two should still have real content
        last_content = json.loads(tool_msgs[-1]["content"])
        assert "已处理" not in last_content["text"]

    def test_nothing_to_snip(self):
        messages = _build_tool_loop_messages(2)
        snipped = snip_old_tool_results(messages, keep_recent=2)
        assert snipped is messages  # Same object, nothing changed

    def test_preserves_range_metadata(self):
        messages = _build_tool_loop_messages(4)
        snipped = snip_old_tool_results(messages, keep_recent=1)
        # First 3 tool results snipped — check metadata preserved
        tool_msgs = [m for m in snipped if m.get("role") == "tool"]
        for tm in tool_msgs[:3]:
            data = json.loads(tm["content"])
            assert "start_char" in data
            assert "end_char" in data
            assert "total_chars" in data

    def test_snip_count(self):
        messages = _build_tool_loop_messages(6)
        snipped = snip_old_tool_results(messages, keep_recent=2)
        snipped_count = sum(
            1 for orig, new in zip(messages, snipped) if orig is not new
        )
        assert snipped_count == 4  # 6 total - 2 kept = 4 snipped


# ===========================================================================
# Tests: SummarizerCompactAdapter
# ===========================================================================

class TestSummarizerCompactAdapter:
    def test_force_emit_state_parses_json(self):
        adapter = SummarizerCompactAdapter()
        provider = MockProvider(
            simple_complete_response=json.dumps({
                "brief": "test brief",
                "key_facts": ["fact 1", "fact 2"],
                "commands": ["cmd 1"],
                "symptoms": [],
                "resolution_branches": [],
            })
        )
        state = adapter.force_emit_state([], provider, "system", "model")
        assert state["brief"] == "test brief"
        assert len(state["key_facts"]) == 2

    def test_force_emit_state_handles_failure(self):
        adapter = SummarizerCompactAdapter()

        class FailProvider:
            def simple_complete(self, *a, **kw):
                raise RuntimeError("API error")

        state = adapter.force_emit_state([], FailProvider(), "system", "model")
        assert state == {}

    def test_force_emit_state_handles_garbage(self):
        adapter = SummarizerCompactAdapter()
        provider = MockProvider(simple_complete_response="not json at all")
        state = adapter.force_emit_state([], provider, "system", "model")
        assert state == {}

    def test_build_checkpoint_with_state(self):
        adapter = SummarizerCompactAdapter()
        state = {
            "brief": "test brief",
            "key_facts": ["fact 1"],
            "commands": ["cmd 1"],
            "symptoms": [],
            "resolution_branches": [],
        }
        outline = _make_outline()
        checkpoint = adapter.build_checkpoint_message(
            state=state,
            outline=outline,
            read_ranges=[(0, 5000)],
            total_chars=30000,
            extra_context={
                "suggested_type": "pitfall",
                "read_progress_text": "Symptoms ✓\nRoot Cause ← 未读",
            },
        )
        assert "已提取数据" in checkpoint
        assert "fact 1" in checkpoint
        assert "pitfall" in checkpoint
        assert "继续阅读" in checkpoint

    def test_build_checkpoint_without_state(self):
        adapter = SummarizerCompactAdapter()
        checkpoint = adapter.build_checkpoint_message(
            state={},
            outline=[],
            read_ranges=[],
            total_chars=10000,
            extra_context={"suggested_type": "model"},
        )
        assert "提取进度丢失" in checkpoint
        assert "重新" in checkpoint


# ===========================================================================
# Tests: GeneratorCompactAdapter
# ===========================================================================

class TestGeneratorCompactAdapter:
    def test_force_emit_state_captures_draft(self):
        adapter = GeneratorCompactAdapter()
        provider = MockProvider(simple_complete_response="---\ntitle: Test\n---\n## Symptoms\n- foo")
        state = adapter.force_emit_state([], provider, "system", "model")
        assert "title: Test" in state["partial_draft"]

    def test_force_emit_state_handles_failure(self):
        adapter = GeneratorCompactAdapter()

        class FailProvider:
            def simple_complete(self, *a, **kw):
                raise RuntimeError("boom")

        state = adapter.force_emit_state([], FailProvider(), "system", "model")
        assert state == {}

    def test_build_checkpoint_with_draft(self):
        adapter = GeneratorCompactAdapter()
        checkpoint = adapter.build_checkpoint_message(
            state={"partial_draft": "---\ntitle: Test\n---\n## Symptoms"},
            outline=_make_outline(),
            read_ranges=[(0, 13000)],
            total_chars=30000,
            extra_context={
                "summary_block": "Type: pitfall\nBrief: test",
                "read_progress_text": "Symptoms ✓",
            },
        )
        assert "已生成的部分 draft" in checkpoint
        assert "title: Test" in checkpoint
        assert "输入摘要" in checkpoint
        assert "继续生成" in checkpoint

    def test_build_checkpoint_without_draft(self):
        adapter = GeneratorCompactAdapter()
        checkpoint = adapter.build_checkpoint_message(
            state={"partial_draft": ""},
            outline=[],
            read_ranges=[],
            total_chars=10000,
            extra_context={"summary_block": "Type: pitfall"},
        )
        assert "生成进度丢失" in checkpoint


# ===========================================================================
# Tests: ToolLoopCompact
# ===========================================================================

class TestToolLoopCompact:
    def test_should_compact_under_threshold(self):
        mgr = ToolLoopCompact(
            adapter=SummarizerCompactAdapter(),
            model="deepseek-v4-flash",
            provider=MockProvider(),
            outline=[],
            total_chars=10000,
            context_window_override=64000,
        )
        assert not mgr.should_compact({"input_tokens": 40000})

    def test_should_compact_over_threshold(self):
        mgr = ToolLoopCompact(
            adapter=SummarizerCompactAdapter(),
            model="deepseek-v4-flash",
            provider=MockProvider(),
            outline=[],
            total_chars=10000,
            context_window_override=64000,
        )
        # 80% of 64000 = 51200
        assert mgr.should_compact({"input_tokens": 52000})

    def test_compact_snip_only(self):
        """When enough tool results exist, snip alone suffices."""
        messages = _build_tool_loop_messages(6)
        mgr = ToolLoopCompact(
            adapter=SummarizerCompactAdapter(),
            model="deepseek-v4-flash",
            provider=MockProvider(),
            outline=_make_outline(),
            total_chars=30000,
        )
        result = mgr.compact(messages, "system prompt")
        # Should still be a list of messages (not reset to single checkpoint)
        assert len(result) > 1
        # Old tool results should be snipped
        tool_msgs = [m for m in result if isinstance(m, dict) and m.get("role") == "tool"]
        snipped_count = sum(
            1 for m in tool_msgs if "已处理" in m.get("content", "")
        )
        assert snipped_count >= 3

    def test_compact_escalates_to_checkpoint(self):
        """When too few tool results to snip, escalate to full checkpoint."""
        messages = _build_tool_loop_messages(2)  # Only 2 reads — snip won't help
        provider = MockProvider(
            simple_complete_response=json.dumps({
                "brief": "test",
                "key_facts": ["f1"],
                "commands": [],
                "symptoms": [],
                "resolution_branches": [],
            })
        )
        mgr = ToolLoopCompact(
            adapter=SummarizerCompactAdapter(),
            model="deepseek-v4-flash",
            provider=provider,
            outline=_make_outline(),
            total_chars=30000,
            extra_context={"suggested_type": "pitfall"},
        )
        result = mgr.compact(messages, "system prompt")
        # Should be a single checkpoint message
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert "已提取数据" in result[0]["content"]
        assert "f1" in result[0]["content"]

    def test_compact_count_increments(self):
        messages = _build_tool_loop_messages(6)
        mgr = ToolLoopCompact(
            adapter=SummarizerCompactAdapter(),
            model="deepseek-v4-flash",
            provider=MockProvider(),
            outline=[],
            total_chars=30000,
        )
        assert mgr.compact_count == 0
        mgr.compact(messages, "sys")
        assert mgr.compact_count == 1
        mgr.compact(messages, "sys")
        assert mgr.compact_count == 2

    def test_compact_with_custom_context_window(self):
        mgr = ToolLoopCompact(
            adapter=SummarizerCompactAdapter(),
            model="unknown-model",
            provider=MockProvider(),
            outline=[],
            total_chars=10000,
            context_window_override=32000,
        )
        # 80% of 32000 = 25600
        assert not mgr.should_compact({"input_tokens": 25000})
        assert mgr.should_compact({"input_tokens": 26000})


# ===========================================================================
# Tests: Anthropic message shapes (T035)
# ===========================================================================

def _make_anthropic_assistant_msg(
    tool_use_id: str, start: int, end: int, as_dict: bool = True,
) -> dict:
    """Build an Anthropic-format assistant message with a tool_use block.

    The real AnthropicProvider appends ``response.content`` (SDK block
    objects); ``as_dict=False`` simulates that with SimpleNamespace blocks.
    """
    if as_dict:
        tool_block = {
            "type": "tool_use",
            "id": tool_use_id,
            "name": "read_document_range",
            "input": {"start_char": start, "end_char": end},
        }
    else:
        from types import SimpleNamespace
        tool_block = SimpleNamespace(
            type="tool_use",
            id=tool_use_id,
            name="read_document_range",
            input={"start_char": start, "end_char": end},
        )
    return {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Let me read the next section."},
            tool_block,
        ],
    }


def _make_anthropic_tool_result_msg(
    tool_use_id: str, start: int, end: int, total: int, text: str = "...",
) -> dict:
    """Build an Anthropic-format tool result (user message, tool_result block)."""
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps({
                    "text": text,
                    "start_char": start,
                    "end_char": end,
                    "total_chars": total,
                }),
            }
        ],
    }


def _build_anthropic_tool_loop_messages(
    num_reads: int, total_chars: int = 30000,
) -> list:
    """Build an Anthropic-shape tool-use history with N read calls."""
    chunk_size = total_chars // max(num_reads, 1)
    messages = [{"role": "user", "content": "Extract summary from this doc..."}]
    for i in range(num_reads):
        start = i * chunk_size
        end = min(start + chunk_size, total_chars)
        tu_id = f"toolu_{i}"
        messages.append(_make_anthropic_assistant_msg(tu_id, start, end))
        messages.append(
            _make_anthropic_tool_result_msg(tu_id, start, end, total_chars, text="x" * 3000)
        )
    return messages


class TestExtractReadRangesAnthropic:
    def test_extracts_ranges_from_anthropic_format(self):
        messages = [
            _make_anthropic_assistant_msg("toolu_0", 0, 8000),
            _make_anthropic_tool_result_msg("toolu_0", 0, 8000, 30000),
            _make_anthropic_assistant_msg("toolu_1", 8000, 16000),
            _make_anthropic_tool_result_msg("toolu_1", 8000, 16000, 30000),
        ]
        ranges = extract_read_ranges(messages)
        assert ranges == [(0, 8000), (8000, 16000)]

    def test_extracts_ranges_from_sdk_object_blocks(self):
        """Anthropic SDK content blocks are objects, not dicts."""
        messages = [
            _make_anthropic_assistant_msg("toolu_0", 0, 8000, as_dict=False),
        ]
        assert extract_read_ranges(messages) == [(0, 8000)]

    def test_ignores_non_read_anthropic_tool_use(self):
        messages = [{
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": "toolu_x",
                "name": "search_in_document",
                "input": {"query": "hello"},
            }],
        }]
        assert extract_read_ranges(messages) == []

    def test_mixed_openai_and_anthropic_formats(self):
        messages = [
            _make_assistant_msg_with_tool_call("tc_0", 0, 8000),
            _make_tool_result_msg("tc_0", 0, 8000, 30000),
            _make_anthropic_assistant_msg("toolu_1", 8000, 16000),
            _make_anthropic_tool_result_msg("toolu_1", 8000, 16000, 30000),
        ]
        ranges = extract_read_ranges(messages)
        assert ranges == [(0, 8000), (8000, 16000)]


class TestSnipOldToolResultsAnthropic:
    def test_snips_anthropic_tool_results(self):
        messages = _build_anthropic_tool_loop_messages(4)
        snipped = snip_old_tool_results(messages, keep_recent=2)

        result_msgs = [
            m for m in snipped
            if isinstance(m, dict) and m.get("role") == "user"
            and isinstance(m.get("content"), list)
        ]
        assert len(result_msgs) == 4
        # First two snipped, last two intact
        for m in result_msgs[:2]:
            block = m["content"][0]
            assert block["type"] == "tool_result"
            assert block["tool_use_id"] is not None  # API validity preserved
            data = json.loads(block["content"])
            assert "已处理" in data["text"]
            assert "start_char" in data  # range metadata preserved
        for m in result_msgs[2:]:
            data = json.loads(m["content"][0]["content"])
            assert "已处理" not in data["text"]

    def test_snip_count_anthropic(self):
        messages = _build_anthropic_tool_loop_messages(5)
        snipped = snip_old_tool_results(messages, keep_recent=2)
        snipped_count = sum(
            1 for orig, new in zip(messages, snipped) if orig is not new
        )
        assert snipped_count == 3  # 5 total - 2 kept

    def test_nothing_to_snip_anthropic(self):
        messages = _build_anthropic_tool_loop_messages(2)
        snipped = snip_old_tool_results(messages, keep_recent=2)
        assert snipped is messages

    def test_plain_user_messages_untouched(self):
        """Regular user text messages must not count as tool results."""
        messages = [
            {"role": "user", "content": "please continue"},
            *_build_anthropic_tool_loop_messages(3),
            {"role": "user", "content": "and hurry up"},
        ]
        snipped = snip_old_tool_results(messages, keep_recent=2)
        assert snipped[0] is messages[0]
        assert snipped[-1] is messages[-1]
        snipped_count = sum(
            1 for orig, new in zip(messages, snipped) if orig is not new
        )
        assert snipped_count == 1  # only the oldest tool result

    def test_compact_snip_only_anthropic(self):
        """Anthropic history: snip frees enough → no checkpoint escalation."""
        messages = _build_anthropic_tool_loop_messages(6)
        provider = MockProvider()
        mgr = ToolLoopCompact(
            adapter=SummarizerCompactAdapter(),
            model="deepseek-v4-flash",
            provider=provider,
            outline=_make_outline(),
            total_chars=30000,
        )
        result = mgr.compact(messages, "system prompt")
        # Snip-only path: history preserved (not collapsed to one checkpoint)
        assert len(result) > 1
        # force_emit_state must NOT have been called
        assert provider.simple_complete_calls == []
        snipped_count = sum(
            1 for orig, new in zip(messages, result) if orig is not new
        )
        assert snipped_count >= 3

class TestCompactIntegration:
    def test_checkpoint_preserves_read_ranges(self):
        """After checkpoint compact, the checkpoint message shows which sections were read."""
        messages = _build_tool_loop_messages(3, total_chars=30000)
        outline = _make_outline()
        provider = MockProvider(
            simple_complete_response=json.dumps({
                "brief": "test",
                "key_facts": ["fact A"],
                "commands": [],
                "symptoms": [],
                "resolution_branches": [],
            })
        )
        mgr = ToolLoopCompact(
            adapter=SummarizerCompactAdapter(),
            model="test",
            provider=provider,
            outline=outline,
            total_chars=30000,
            extra_context={"suggested_type": "pitfall"},
            context_window_override=10000,  # Low window to force checkpoint
        )
        result = mgr.compact(messages, "system")
        checkpoint = result[0]["content"]
        # Should contain reading progress
        assert "已读" in checkpoint or "未读" in checkpoint

    def test_checkpoint_for_generator_preserves_summary_block(self):
        """Generator checkpoint must include the full summary input."""
        messages = _build_tool_loop_messages(2)
        summary_block = "Type: pitfall\nBrief: PCIe link training failure"
        provider = MockProvider(
            simple_complete_response="---\ntitle: PCIe\n---\n## Symptoms\n- no device"
        )
        mgr = ToolLoopCompact(
            adapter=GeneratorCompactAdapter(),
            model="test",
            provider=provider,
            outline=_make_outline(),
            total_chars=30000,
            extra_context={"summary_block": summary_block},
            context_window_override=10000,
        )
        result = mgr.compact(messages, "system")
        checkpoint = result[0]["content"]
        assert "PCIe link training failure" in checkpoint
        assert "输入摘要" in checkpoint

    def test_multiple_compacts_accumulate(self):
        """Multiple compacts should work — each captures all state so far."""
        provider = MockProvider()
        mgr = ToolLoopCompact(
            adapter=SummarizerCompactAdapter(),
            model="test",
            provider=provider,
            outline=[],
            total_chars=100000,
            extra_context={"suggested_type": "pitfall"},
            context_window_override=10000,
        )

        # First compact — state is empty (provider returns "{}")
        messages_v1 = _build_tool_loop_messages(2, total_chars=100000)
        result_v1 = mgr.compact(messages_v1, "system")
        assert mgr.compact_count == 1

        # Simulate continuing: add more reads after checkpoint
        messages_v2 = list(result_v1)
        messages_v2.append(_make_assistant_msg_with_tool_call("tc_new", 50000, 60000))
        messages_v2.append(_make_tool_result_msg("tc_new", 50000, 60000, 100000))

        # Second compact — provider returns richer state
        provider._simple_response = json.dumps({
            "brief": "accumulated",
            "key_facts": ["fact from round 1", "fact from round 2"],
            "commands": [],
            "symptoms": [],
            "resolution_branches": [],
        })
        result_v2 = mgr.compact(messages_v2, "system")
        assert mgr.compact_count == 2
        checkpoint = result_v2[0]["content"]
        assert "fact from round 1" in checkpoint
        assert "fact from round 2" in checkpoint
