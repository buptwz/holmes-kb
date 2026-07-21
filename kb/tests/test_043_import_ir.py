"""Tests for spec 043 D7 import IR (T029–T033) + import-side applies_to (T039).

Covers:
- T029: Summarizer steps/actor IR (schema normalization, prompts)
- T030: Generator mechanical behavior tags from steps[].actor/kind
- T031: fidelity step-preservation check (loss ratio + physical steps)
- T032: Classifier full-document outline + multi-topic boundary sanitizing
- T033: read-coverage hard invariant (find_unread_sections / ensure_coverage)
- T039: applies_to extraction (normalize, vocabulary prompt injection,
        mechanical frontmatter injection)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from holmes.kb.agent.fidelity import verify_summary_fidelity_042
from holmes.kb.agent.outline import (
    extract_document_outline,
    find_unread_sections,
    merge_read_ranges,
)
from holmes.kb.agent.phases.classifier import DocumentClassifier
from holmes.kb.agent.phases.generator import GeneratorAgent, _step_behavior_tag
from holmes.kb.agent.phases.summarizer import SummarizerAgent, _normalize_summary
from holmes.kb.agent.pipeline import _inject_applies_to
from holmes.kb.agent.prompts.summarizer_prompts import _build_system_prompt


# ---------------------------------------------------------------------------
# Mock LLM providers
# ---------------------------------------------------------------------------


class MockToolCall:
    def __init__(self, id: str, name: str, input: dict):
        self.id = id
        self.name = name
        self.input = input


class MockProvider:
    """Scripted mock provider: each response is str (assistant text) or
    ("tools", [MockToolCall, ...]) to simulate tool-use turns."""

    def __init__(self, responses: list[Any] | None = None):
        self._responses = list(responses or [])
        self._call_idx = 0
        self.last_system: str = ""
        self.last_messages: list = []

    def _next(self) -> Any:
        if self._call_idx < len(self._responses):
            item = self._responses[self._call_idx]
        else:
            item = "{}"
        self._call_idx += 1
        return item

    def complete(self, messages, system, model, max_tokens, tools=None):
        self.last_system = system
        item = self._next()
        if isinstance(item, tuple) and item[0] == "tools":
            return False, item[1], messages, {}
        updated = list(messages) + [{"role": "assistant", "content": str(item)}]
        return True, [], updated, {}

    def simple_complete(self, messages, system="", max_tokens=512):
        self.last_system = system
        self.last_messages = messages
        item = self._next()
        return item if isinstance(item, str) else "{}"

    def append_tool_results(self, messages, results):
        for tool_id, result in results:
            messages.append({
                "role": "tool",
                "tool_use_id": tool_id,
                "content": result,
            })
        return messages


# ---------------------------------------------------------------------------
# T029 — steps/actor IR normalization
# ---------------------------------------------------------------------------


class TestNormalizeSteps:
    def test_valid_steps_pass_through(self):
        data = _normalize_summary({
            "steps": [
                {"action": "用示波器量测时钟", "actor": "human", "kind": "action"},
                {"action": "查看 SEL 日志", "actor": "agent", "kind": "action",
                 "command": "ipmitool sel list", "expected": "无 ECC 事件"},
                {"action": "若 LED 红色 → 路径 A", "actor": "human", "kind": "decision"},
                {"action": "BMC 固件刷写", "actor": "remote", "kind": "action",
                 "command": "ipmitool hpm upgrade fw.bin", "risk": "danger"},
            ],
        })
        steps = data["steps"]
        assert len(steps) == 4
        assert steps[0]["actor"] == "human"
        assert steps[1]["command"] == "ipmitool sel list"
        assert steps[1]["expected"] == "无 ECC 事件"
        assert steps[2]["kind"] == "decision"
        assert steps[3]["actor"] == "remote"

    def test_missing_steps_defaults_to_empty(self):
        assert _normalize_summary({})["steps"] == []
        assert _normalize_summary({"steps": "not-a-list"})["steps"] == []

    def test_invalid_actor_falls_back_to_agent(self):
        data = _normalize_summary({
            "steps": [{"action": "做某事", "actor": "robot"}],
        })
        assert data["steps"][0]["actor"] == "agent"

    def test_invalid_kind_falls_back_to_action(self):
        data = _normalize_summary({
            "steps": [{"action": "做某事", "actor": "human", "kind": "maybe"}],
        })
        assert data["steps"][0]["kind"] == "action"

    def test_empty_action_dropped_and_string_wrapped(self):
        data = _normalize_summary({
            "steps": [
                {"action": "", "actor": "human"},
                {"actor": "human"},
                "重新插拔 Riser 卡",
                42,
            ],
        })
        assert data["steps"] == [
            {"action": "重新插拔 Riser 卡", "actor": "agent", "kind": "action"},
        ]

    def test_blank_command_and_expected_omitted(self):
        data = _normalize_summary({
            "steps": [{"action": "观察波形", "actor": "human", "kind": "verify",
                       "command": "  ", "expected": ""}],
        })
        step = data["steps"][0]
        assert "command" not in step
        assert "expected" not in step
        assert step["kind"] == "verify"

    def test_summarizer_returns_steps_end_to_end(self):
        response = json.dumps({
            "brief": "PCIe 训练失败排查",
            "key_facts": ["f1"],
            "steps": [
                {"action": "量测 Riser 卡供电", "actor": "human", "kind": "action"},
                {"action": "lspci 确认设备枚举", "actor": "agent", "kind": "action",
                 "command": "lspci -nn", "expected": "能看到 GPU"},
            ],
        }, ensure_ascii=False)
        provider = MockProvider([response])
        summarizer = SummarizerAgent(provider=provider, model="test")
        result = summarizer.run("some doc", {"source_text": "some doc"})
        assert result is not None
        assert len(result["steps"]) == 2
        assert result["steps"][0]["actor"] == "human"


class TestSummarizerStepsPrompt:
    def test_base_prompt_defines_actor_labels(self):
        prompt = _build_system_prompt("pitfall")
        assert '"human"' in prompt and '"agent"' in prompt and '"remote"' in prompt
        assert "## steps" in prompt

    def test_pitfall_guidance_requires_ordered_actor_steps(self):
        prompt = _build_system_prompt("pitfall")
        assert "IN DOCUMENT ORDER" in prompt
        assert "Physical actions" in prompt


# ---------------------------------------------------------------------------
# T039 — applies_to extraction (import side)
# ---------------------------------------------------------------------------


class TestNormalizeAppliesTo:
    def test_valid_applies_to_passes(self):
        data = _normalize_summary({
            "applies_to": {
                "product_line": ["serdes-gen2"],
                "test_stage": ["dvt", "pvt"],
                "firmware": "<=2.3",
            },
        })
        assert data["applies_to"] == {
            "product_line": ["serdes-gen2"],
            "test_stage": ["dvt", "pvt"],
            "firmware": "<=2.3",
        }

    def test_unknown_keys_and_empty_values_dropped(self):
        data = _normalize_summary({
            "applies_to": {"product_line": ["x1", " "], "station": ["s1"], "firmware": "  "},
        })
        assert data["applies_to"] == {"product_line": ["x1"]}

    def test_empty_or_invalid_removed_entirely(self):
        assert "applies_to" not in _normalize_summary({"applies_to": {}})
        assert "applies_to" not in _normalize_summary({"applies_to": "nope"})
        assert "applies_to" not in _normalize_summary({})

    def test_summarizer_returns_applies_to_end_to_end(self):
        response = json.dumps({
            "brief": "b", "key_facts": [],
            "applies_to": {"product_line": ["granite"], "firmware": ">=1.8"},
        }, ensure_ascii=False)
        provider = MockProvider([response])
        summarizer = SummarizerAgent(provider=provider, model="test")
        result = summarizer.run("doc", {"source_text": "doc"})
        assert result is not None
        assert result["applies_to"]["product_line"] == ["granite"]
        assert result["applies_to"]["firmware"] == ">=1.8"


class TestVocabularyPromptInjection:
    def test_vocabulary_values_in_prompt(self):
        prompt = _build_system_prompt(
            "pitfall",
            vocabulary={"product_line": ["serdes-gen2"], "test_stage": ["dvt"]},
        )
        assert "serdes-gen2" in prompt
        assert "dvt" in prompt
        assert "PREFER reusing" in prompt

    def test_empty_vocabulary_free_extraction_note(self):
        prompt = _build_system_prompt("pitfall", vocabulary={})
        assert "no existing vocabulary" in prompt

    def test_summarizer_loads_vocabulary_from_kb_config(self, tmp_path: Path):
        (tmp_path / "kb-config.yml").write_text(
            "vocabulary:\n  product_line: [serdes-gen2]\n", encoding="utf-8",
        )
        provider = MockProvider(['{"brief": "b", "key_facts": []}'])
        summarizer = SummarizerAgent(provider=provider, model="test")
        result = summarizer.run("doc", {"source_text": "doc", "kb_root": tmp_path})
        assert result is not None
        assert "serdes-gen2" in provider.last_system

    def test_summarizer_without_kb_root_still_works(self):
        provider = MockProvider(['{"brief": "b", "key_facts": []}'])
        summarizer = SummarizerAgent(provider=provider, model="test")
        result = summarizer.run("doc", {"source_text": "doc"})
        assert result is not None
        assert "no existing vocabulary" in provider.last_system


class TestInjectAppliesTo:
    _DRAFT = (
        "---\nid: x\ntype: pitfall\ncategory: pcie\ntitle: T\n"
        "tags: [a]\nlanguage: zh\n---\n\n## Symptoms\n- s\n"
    )

    def test_injects_into_frontmatter(self):
        out = _inject_applies_to(self._DRAFT, {"product_line": ["serdes-gen2"]})
        assert "applies_to:" in out
        assert "serdes-gen2" in out
        # body preserved
        assert "## Symptoms" in out

    def test_unparseable_draft_unchanged(self):
        assert _inject_applies_to("no frontmatter here", {"a": ["b"]}) == \
            "no frontmatter here"


# ---------------------------------------------------------------------------
# T030 — mechanical behavior tags
# ---------------------------------------------------------------------------


class TestStepBehaviorTag:
    def test_actor_mapping(self):
        assert _step_behavior_tag({"actor": "human"}, {}) == "[physical]"
        assert _step_behavior_tag({"actor": "remote"}, {}) == "[remote]"

    def test_agent_uses_command_risk(self):
        risks = {"ipmitool sel clear": "danger", "reboot": "write"}
        assert _step_behavior_tag(
            {"actor": "agent", "command": "ipmitool sel clear"}, risks,
        ) == "[api:danger]"
        assert _step_behavior_tag(
            {"actor": "agent", "command": "reboot"}, risks,
        ) == "[api:write]"

    def test_agent_unknown_command_defaults_read(self):
        assert _step_behavior_tag({"actor": "agent", "command": "x"}, {}) == "[api:read]"
        assert _step_behavior_tag({"actor": "agent"}, {}) == "[api:read]"

    def test_kind_overrides_actor(self):
        assert _step_behavior_tag(
            {"actor": "human", "kind": "decision"}, {},
        ) == "[decide]"
        assert _step_behavior_tag(
            {"actor": "remote", "kind": "verify"}, {},
        ) == "[verify]"

    def test_invalid_risk_defaults_read(self):
        risks = {"cmd": "explode"}
        assert _step_behavior_tag(
            {"actor": "agent", "command": "cmd"}, risks,
        ) == "[api:read]"


class TestGeneratorStepsBlock:
    def _summary(self) -> dict[str, Any]:
        return {
            "brief": "b",
            "key_facts": ["f1"],
            "commands": [
                {"cmd": "lspci -nn", "expected": "列出 PCI 设备", "risk": "read"},
                {"cmd": "ipmitool hpm upgrade fw.bin", "expected": "刷写完成",
                 "risk": "danger"},
            ],
            "steps": [
                {"action": "量测 Riser 卡供电", "actor": "human", "kind": "action"},
                {"action": "确认设备枚举", "actor": "agent", "kind": "action",
                 "command": "lspci -nn"},
                {"action": "BMC 固件刷写", "actor": "remote", "kind": "action",
                 "command": "ipmitool hpm upgrade fw.bin"},
                {"action": "若 LED 红色 → 更换 Riser", "actor": "human",
                 "kind": "decision"},
                {"action": "确认 link 恢复 Gen4", "actor": "agent", "kind": "verify"},
            ],
            "applies_to": {"product_line": ["serdes-gen2"]},
        }

    def test_steps_block_with_mechanical_tags(self):
        block = GeneratorAgent._build_summary_input(self._summary(), "pitfall", "zh")
        assert "Steps (5 items" in block
        assert "[physical] 量测 Riser 卡供电" in block
        assert "[api:read] 确认设备枚举" in block
        assert "[remote] BMC 固件刷写" in block  # NOT [api:danger] — actor wins
        assert "[decide] 若 LED 红色 → 更换 Riser" in block
        assert "[verify] 确认 link 恢复 Gen4" in block
        assert "Command: lspci -nn" in block

    def test_applies_to_line_rendered(self):
        block = GeneratorAgent._build_summary_input(self._summary(), "pitfall", "zh")
        assert "AppliesTo" in block
        assert "serdes-gen2" in block

    def test_no_steps_no_block(self):
        summary = {"brief": "b", "key_facts": [], "commands": []}
        block = GeneratorAgent._build_summary_input(summary, "pitfall", "en")
        assert "Steps (" not in block
        assert "AppliesTo" not in block


# ---------------------------------------------------------------------------
# T031 — fidelity step preservation
# ---------------------------------------------------------------------------


class TestFidelitySteps:
    def _summary(self, steps: list[dict]) -> dict[str, Any]:
        return {"brief": "b", "key_facts": [], "commands": [], "steps": steps}

    def test_all_steps_present_no_issues(self):
        summary = self._summary([
            {"action": "量测 Riser 卡供电", "actor": "human", "kind": "action"},
            {"action": "确认枚举", "actor": "agent", "kind": "action",
             "command": "lspci -nn"},
        ])
        draft = "1. [physical] 量测 Riser 卡供电\n2. [api:read] `lspci -nn`\n"
        errors, warnings = verify_summary_fidelity_042(summary, draft)
        assert errors == []
        assert warnings == []

    def test_step_loss_over_30pct_is_error(self):
        summary = self._summary([
            {"action": f"步骤{i} 执行操作", "actor": "agent", "kind": "action",
             "command": f"cmd-{i}"}
            for i in range(4)
        ])
        draft = "cmd-0\ncmd-1"  # 2/4 missing = 50%
        errors, _ = verify_summary_fidelity_042(summary, draft)
        assert any("步骤丢失" in e and "2/4" in e for e in errors)

    def test_step_loss_under_30pct_is_warning(self):
        summary = self._summary([
            {"action": f"步骤{i} 执行操作", "actor": "agent", "kind": "action",
             "command": f"cmd-{i}"}
            for i in range(4)
        ])
        draft = "cmd-0\ncmd-1\ncmd-2"  # 1/4 missing = 25%
        errors, warnings = verify_summary_fidelity_042(summary, draft)
        assert not any("步骤丢失" in e for e in errors)
        assert any("步骤丢失" in w for w in warnings)

    def test_missing_physical_step_is_error_even_below_ratio(self):
        summary = self._summary([
            {"action": "用示波器量测时钟信号波形", "actor": "human", "kind": "action"},
            *[
                {"action": f"步骤{i} 执行操作", "actor": "agent", "kind": "action",
                 "command": f"cmd-{i}"}
                for i in range(5)
            ],
        ])
        # only the human step missing → 1/6 ≈ 17% but still an error
        draft = "\n".join(f"cmd-{i}" for i in range(5))
        errors, _ = verify_summary_fidelity_042(summary, draft)
        assert any("物理步骤丢失" in e for e in errors)

    def test_no_steps_no_check(self):
        errors, warnings = verify_summary_fidelity_042(
            {"brief": "b", "key_facts": [], "commands": []}, "draft",
        )
        assert errors == []
        assert warnings == []


# ---------------------------------------------------------------------------
# T032 — Classifier full-document outline + boundary sanitizing
# ---------------------------------------------------------------------------


class TestClassifierOutline:
    def test_long_doc_prompt_includes_full_outline(self):
        # Doc > 8000 chars with a heading beyond the snippet cutoff
        head = "# 标题\n\n" + "正文内容。" * 100  # ~500 chars
        tail = "\n\n## 第二主题 电源时序\n\n" + "更多内容。" * 2000  # pushes past 8K
        doc = head + tail
        assert len(doc) > 8000

        provider = MockProvider(['{"doc_type": "incident", "reason": "x"}'])
        classifier = DocumentClassifier(provider=provider, model="test")
        classifier.classify(doc)

        user_msg = provider.last_messages[0]["content"]
        assert "第二主题 电源时序" in user_msg  # heading beyond 8K visible via outline
        assert "Document outline" in user_msg
        assert "first 8000 chars" in user_msg

    def test_short_doc_prompt_unchanged(self):
        provider = MockProvider(['{"doc_type": "incident", "reason": "x"}'])
        classifier = DocumentClassifier(provider=provider, model="test")
        classifier.classify("short doc")
        user_msg = provider.last_messages[0]["content"]
        assert "Document:\n\nshort doc" in user_msg
        assert "Document outline" not in user_msg


class TestSanitizeTopicBoundaries:
    def _pipeline(self, tmp_path: Path):
        from holmes.config import HolmesConfig
        from holmes.kb.agent.pipeline import ImportPipeline

        cfg = HolmesConfig()
        return ImportPipeline(kb_root=tmp_path, cfg=cfg, _provider=MockProvider())

    def test_out_of_range_dropped_with_warning(self, tmp_path: Path):
        from holmes.kb.agent.report import ImportReport

        pipeline = self._pipeline(tmp_path)
        report = ImportReport()
        doc = "a" * 1000
        result = pipeline._sanitize_topic_boundaries([500, 99999, -3], doc, report)
        assert result == [500]
        assert any("99999" in w for w in report.warnings)

    def test_boundary_snapped_to_heading(self, tmp_path: Path):
        from holmes.kb.agent.report import ImportReport

        pipeline = self._pipeline(tmp_path)
        report = ImportReport()
        doc = "前言\n" * 100 + "\n## 第二主题\n" + "内容\n" * 200
        offset = doc.index("## 第二主题")
        result = pipeline._sanitize_topic_boundaries(
            [offset + 120], doc, report,
        )
        assert result == [offset]

    def test_far_boundary_not_snapped(self, tmp_path: Path):
        from holmes.kb.agent.report import ImportReport

        pipeline = self._pipeline(tmp_path)
        report = ImportReport()
        doc = "前言\n" * 100 + "\n## 主题\n" + "内容\n" * 500
        result = pipeline._sanitize_topic_boundaries([1500], doc, report)
        assert result == [1500]


# ---------------------------------------------------------------------------
# T033 — read-coverage hard invariant
# ---------------------------------------------------------------------------


class TestFindUnreadSections:
    def _doc(self) -> str:
        return (
            "# 标题\n\n介绍。\n\n"
            "## 症状\n\n" + "症状内容。" * 50 + "\n\n"
            "## 根因\n\n" + "根因内容。" * 50 + "\n\n"
            "## 解决\n\n" + "解决内容。" * 50 + "\n"
        )

    def test_fully_read_no_unread(self):
        doc = self._doc()
        outline = extract_document_outline(doc)
        assert find_unread_sections(outline, [(0, len(doc))]) == []

    def test_unread_tail_detected(self):
        doc = self._doc()
        outline = extract_document_outline(doc)
        resolution = next(h for h in outline if h["text"] == "解决")
        unread = find_unread_sections(outline, [(0, resolution["offset"])])
        assert unread == ["解决"]

    def test_gap_tolerance_merges_ranges(self):
        assert merge_read_ranges([(0, 100), (130, 200)]) == [(0, 200)]
        assert merge_read_ranges([(0, 100), (200, 300)]) == [(0, 100), (200, 300)]

    def test_empty_outline_no_unread(self):
        assert find_unread_sections([], []) == []


class TestSummarizerCoverage:
    def _long_doc(self) -> str:
        part1 = "## 第一部分 症状\n\n" + "症状描述。" * 800 + "\n\n"  # >8K with part2
        part2 = "## 第二部分 解决\n\n" + "解决步骤。" * 800 + "\n"
        return part1 + part2

    def test_direct_mode_marks_fully_read(self):
        provider = MockProvider(['{"brief": "b", "key_facts": []}'])
        summarizer = SummarizerAgent(provider=provider, model="test")
        doc = "short doc"
        result = summarizer.run(doc, {"source_text": doc})
        assert result is not None
        assert summarizer.last_read_ranges == [(0, len(doc))]
        assert summarizer.ensure_coverage(result, doc, {"source_text": doc}) == []

    def test_tool_loop_records_ranges_and_supplements(self):
        doc = self._long_doc()
        total = len(doc)
        half = total // 2
        summary_json = json.dumps({
            "brief": "b", "key_facts": ["f1"],
            "outline": [
                {"section": "Symptoms", "description": "s"},
                {"section": "Resolution", "description": "r"},
            ],
        }, ensure_ascii=False)
        supplement_json = json.dumps(
            {"brief": "", "key_facts": ["f2"], "steps": []}, ensure_ascii=False,
        )
        provider = MockProvider([
            # Main loop: read only the first half, then emit JSON
            ("tools", [MockToolCall("t1", "read_document_range",
                                    {"start_char": 0, "end_char": half})]),
            summary_json,
            # Supplement pass (triggered by ensure_coverage): read the rest
            ("tools", [MockToolCall("t2", "read_document_range",
                                    {"start_char": half, "end_char": total})]),
            supplement_json,
        ])
        summarizer = SummarizerAgent(provider=provider, model="test")
        ctx = {"source_text": doc}
        result = summarizer.run(doc, ctx)
        assert result is not None
        assert (0, half) in summarizer.last_read_ranges

        still_unread = summarizer.ensure_coverage(result, doc, ctx)
        assert still_unread == []
        assert (half, total) in summarizer.last_read_ranges
        # supplement merged new facts
        assert "f2" in result["key_facts"]

    def test_still_unread_returned_when_supplement_fails(self):
        doc = self._long_doc()
        half = len(doc) // 2
        summary_json = json.dumps({
            "brief": "b", "key_facts": ["f1"],
            "outline": [
                {"section": "Symptoms", "description": "s"},
                {"section": "Resolution", "description": "r"},
            ],
        }, ensure_ascii=False)
        provider = MockProvider([
            ("tools", [MockToolCall("t1", "read_document_range",
                                    {"start_char": 0, "end_char": half})]),
            summary_json,
            # Supplement: LLM emits JSON without reading → still unread
            json.dumps({"brief": "", "key_facts": []}),
        ])
        summarizer = SummarizerAgent(provider=provider, model="test")
        ctx = {"source_text": doc}
        result = summarizer.run(doc, ctx)
        still_unread = summarizer.ensure_coverage(result, doc, ctx)
        assert "第二部分 解决" in still_unread

    def test_exhaustion_flag_set_on_iteration_cap(self):
        doc = self._long_doc()
        # LLM keeps reading forever, never emits JSON
        responses = [
            ("tools", [MockToolCall(f"t{i}", "read_document_range",
                                    {"start_char": 0, "end_char": 100})])
            for i in range(20)
        ]
        provider = MockProvider(responses)
        summarizer = SummarizerAgent(provider=provider, model="test")
        result = summarizer.run(doc, {"source_text": doc})
        # No valid JSON after cap → run returns None; exhaustion flagged
        assert result is None
        assert summarizer.last_exhausted is True


# ---------------------------------------------------------------------------
# Pipeline-level integration (T033 report, T039 frontmatter)
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    def _make_pipeline(self, tmp_path: Path, provider: MockProvider):
        from holmes.config import HolmesConfig
        from holmes.kb.agent.pipeline import ImportPipeline

        (tmp_path / "_pending").mkdir(parents=True, exist_ok=True)
        return ImportPipeline(
            kb_root=tmp_path,
            cfg=HolmesConfig(model="test"),
            no_interactive=True,
            _provider=provider,
        )

    _CLASSIFIER_RESP = (
        '{"doc_type": "incident", "suggested_type": "pitfall", '
        '"language": "zh", "reason": "test"}'
    )
    _DRAFT = (
        "---\nid: t-001\ntype: pitfall\ncategory: pcie\ntitle: T\n"
        "brief: b\ntags: [pcie]\nlanguage: zh\n---\n\n"
        "## Contents\n\n| Section | Description |\n|---|---|\n"
        "| Symptoms | s |\n| Root Cause | r |\n| Resolution | x |\n\n"
        "## Symptoms\n- s\n\n## Root Cause\nr\n\n## Resolution\nx\n"
    )

    def test_uncovered_sections_recorded_in_report(self, tmp_path: Path):
        """T033: supplement 补读仍失败的 section 必须写入 report，不静默。"""
        part1 = "## 第一部分 症状\n\n" + "症状描述。" * 900 + "\n\n"
        part2 = "## 第二部分 解决\n\n" + "解决步骤。" * 900 + "\n"
        doc = part1 + part2
        half = len(doc) // 2
        summary_json = json.dumps({
            "brief": "b", "key_facts": ["f1"], "commands": [],
            "outline": [
                {"section": "Symptoms", "description": "s"},
                {"section": "Root Cause", "description": "r"},
                {"section": "Resolution", "description": "x"},
            ],
        }, ensure_ascii=False)
        provider = MockProvider([
            self._CLASSIFIER_RESP,
            # Summarizer tool loop: reads only first half, then emits JSON
            ("tools", [MockToolCall("t1", "read_document_range",
                                    {"start_char": 0, "end_char": half})]),
            summary_json,
            # Forced supplement: emits JSON WITHOUT reading the second half
            json.dumps({"brief": "", "key_facts": []}),
            # Generator
            self._DRAFT,
        ])
        pipeline = self._make_pipeline(tmp_path, provider)
        report = pipeline.run(doc)
        assert any(
            "未覆盖" in w and "第二部分 解决" in w for w in report.warnings
        ), report.warnings

    def test_applies_to_lands_in_pending_frontmatter(self, tmp_path: Path):
        """T039: summary 的 applies_to 机械注入产出条目的 frontmatter。"""
        doc = "# 电源时序异常\n\nDVT 阶段 serdes-gen2 上电时序违规。\n"
        summary_json = json.dumps({
            "brief": "b", "key_facts": ["f1"], "commands": [],
            "applies_to": {"product_line": ["serdes-gen2"], "test_stage": ["dvt"]},
            "outline": [
                {"section": "Symptoms", "description": "s"},
                {"section": "Root Cause", "description": "r"},
                {"section": "Resolution", "description": "x"},
            ],
        }, ensure_ascii=False)
        provider = MockProvider([
            self._CLASSIFIER_RESP,
            summary_json,
            self._DRAFT,  # note: draft itself has NO applies_to
        ])
        pipeline = self._make_pipeline(tmp_path, provider)
        report = pipeline.run(doc)
        written = [
            p for p in tmp_path.rglob("*.md")
            if p.name not in ("log.md", "_index.md") and "pending" in str(p)
        ]
        assert written, f"no entry written; errors={report.errors}"
        content = written[0].read_text(encoding="utf-8")
        assert "applies_to:" in content
        assert "serdes-gen2" in content
        assert "dvt" in content
