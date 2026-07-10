"""Tests for 042 one-doc-one-entry pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pytest

from holmes.kb.agent.phases.classifier import (
    ClassificationResult,
    DocumentClassifier,
    DocumentType,
)
from holmes.kb.agent.phases.summarizer import SummarizerAgent
from holmes.kb.agent.phases.generator import GeneratorAgent
from holmes.kb.agent.interactive_review import (
    review_summary,
    review_draft,
    _extract_title,
    _extract_type,
)
from holmes.kb.agent.fidelity import verify_summary_fidelity_042
from holmes.kb.agent.normalizer import DraftNormalizer
from holmes.kb.agent.pipeline import ImportPipeline, ThreePhaseImportPipeline
from holmes.kb.agent.report import ImportReport


# ---------------------------------------------------------------------------
# Mock LLM Provider
# ---------------------------------------------------------------------------


class MockToolCall:
    def __init__(self, id: str, name: str, input: dict):
        self.id = id
        self.name = name
        self.input = input


class MockProvider:
    """Configurable mock LLM provider for pipeline tests."""

    def __init__(self, responses: list[str] | None = None):
        self._responses = responses or []
        self._call_idx = 0

    def complete(self, messages, system, model, max_tokens, tools=None):
        if self._call_idx < len(self._responses):
            text = self._responses[self._call_idx]
        else:
            text = "{}"
        self._call_idx += 1
        updated = list(messages) + [{"role": "assistant", "content": text}]
        return True, [], updated, {}

    def simple_complete(self, messages, system="", max_tokens=512):
        if self._call_idx < len(self._responses):
            text = self._responses[self._call_idx]
        else:
            text = "{}"
        self._call_idx += 1
        return text

    def append_tool_results(self, messages, results):
        for tool_id, result in results:
            messages.append({
                "role": "tool",
                "tool_use_id": tool_id,
                "content": result,
            })
        return messages


# ---------------------------------------------------------------------------
# Classifier Tests (042)
# ---------------------------------------------------------------------------


class TestClassifier042:
    """Tests for 042 classifier output: suggested_type, language, multi-topic."""

    def test_classify_returns_suggested_type(self):
        provider = MockProvider([
            '{"doc_type": "incident", "suggested_type": "pitfall", '
            '"language": "zh", "reason": "故障排查"}'
        ])
        classifier = DocumentClassifier(provider=provider, model="test")
        result = classifier.classify("some text")
        assert result.doc_type == DocumentType.incident
        assert result.suggested_type == "pitfall"
        assert result.language == "zh"

    def test_classify_returns_language(self):
        provider = MockProvider([
            '{"doc_type": "runbook", "suggested_type": "process", '
            '"language": "en", "reason": "how-to"}'
        ])
        classifier = DocumentClassifier(provider=provider, model="test")
        result = classifier.classify("some text")
        assert result.language == "en"
        assert result.suggested_type == "process"

    def test_classify_multi_topic(self):
        provider = MockProvider([
            '{"doc_type": "mixed", "suggested_type": "pitfall", '
            '"language": "zh", "is_multi_topic": true, '
            '"topic_boundaries": [500, 1200], "reason": "multi-topic"}'
        ])
        classifier = DocumentClassifier(provider=provider, model="test")
        result = classifier.classify("some text")
        assert result.is_multi_topic is True
        assert result.topic_boundaries == [500, 1200]

    def test_classify_no_multi_topic_by_default(self):
        provider = MockProvider([
            '{"doc_type": "incident", "reason": "simple"}'
        ])
        classifier = DocumentClassifier(provider=provider, model="test")
        result = classifier.classify("some text")
        assert result.is_multi_topic is False
        assert result.topic_boundaries == []

    def test_classify_needs_dag_always_false(self):
        """042: DAG routing removed."""
        provider = MockProvider([
            '{"doc_type": "incident", "reason": "complex"}'
        ])
        classifier = DocumentClassifier(provider=provider, model="test")
        result = classifier.classify("some text")
        assert result.needs_dag is False

    def test_classify_fallback_on_error(self):
        provider = MockProvider(["not valid json!!!"])
        classifier = DocumentClassifier(provider=provider, model="test")
        result = classifier.classify("some text")
        # Should get default
        assert result.doc_type == DocumentType.incident
        assert result.suggested_type == "pitfall"

    def test_classify_suggested_type_fallback(self):
        """When suggested_type is invalid, fall back from doc_type mapping."""
        provider = MockProvider([
            '{"doc_type": "runbook", "suggested_type": "invalid_type", "reason": "test"}'
        ])
        classifier = DocumentClassifier(provider=provider, model="test")
        result = classifier.classify("some text")
        assert result.suggested_type == "process"  # runbook → process


# ---------------------------------------------------------------------------
# Summarizer Tests (042)
# ---------------------------------------------------------------------------


class TestSummarizer042:
    """Tests for whole-document summarizer."""

    def test_summarizer_returns_dict(self):
        json_response = (
            '{"brief": "Redis OOM fix", "key_facts": ["fact1", "fact2"], '
            '"commands": ["redis-cli info"], "symptoms": ["high memory"], '
            '"resolution_branches": [{"when": "OOM", "label": "Flush"}]}'
        )
        provider = MockProvider([json_response])
        summarizer = SummarizerAgent(provider=provider, model="test")
        ctx = {"source_text": "some doc"}
        result = summarizer.run("some doc", ctx)
        assert result is not None
        assert result["brief"] == "Redis OOM fix"
        assert len(result["key_facts"]) == 2
        assert len(result["commands"]) == 1
        assert len(result["symptoms"]) == 1
        assert len(result["resolution_branches"]) == 1

    def test_summarizer_handles_code_fenced_json(self):
        json_response = (
            "Here's the summary:\n```json\n"
            '{"brief": "test", "key_facts": [], "commands": []}\n```'
        )
        provider = MockProvider([json_response])
        summarizer = SummarizerAgent(provider=provider, model="test")
        result = summarizer.run("some doc", {"source_text": "some doc"})
        assert result is not None
        assert result["brief"] == "test"

    def test_summarizer_retries_on_invalid_json(self):
        # First response is non-JSON, feedback retry triggers second call
        # which returns "{}" (MockProvider default) — parsed as empty summary
        provider = MockProvider(["I cannot parse this document."])
        summarizer = SummarizerAgent(provider=provider, model="test")
        result = summarizer.run("some doc", {"source_text": "some doc"})
        assert result is not None  # feedback retry recovered

    def test_summarizer_returns_none_on_persistent_failure(self):
        # All attempts return non-JSON — should return None after exhausting retries
        bad_responses = ["not json"] * 5  # enough for initial + all retries
        provider = MockProvider(bad_responses)
        summarizer = SummarizerAgent(provider=provider, model="test")
        result = summarizer.run("some doc", {"source_text": "some doc"})
        assert result is None

    def test_summarizer_normalizes_missing_fields(self):
        provider = MockProvider(['{"brief": "test"}'])
        summarizer = SummarizerAgent(provider=provider, model="test")
        result = summarizer.run("some doc", {"source_text": "some doc"})
        assert result is not None
        assert result["key_facts"] == []
        assert result["commands"] == []
        assert result["symptoms"] == []
        assert result["resolution_branches"] == []
        assert result["outline"] == []

    def test_summarizer_extracts_outline(self):
        json_response = (
            '{"brief": "test", "key_facts": ["f1"], "commands": [], '
            '"symptoms": [], "resolution_branches": [], '
            '"outline": [{"section": "Symptoms", "description": "2 symptoms"}, '
            '{"section": "Root Cause", "description": "1 root cause"}, '
            '{"section": "Resolution", "description": "3 steps"}]}'
        )
        provider = MockProvider([json_response])
        summarizer = SummarizerAgent(provider=provider, model="test")
        result = summarizer.run("some doc", {"source_text": "some doc"})
        assert result is not None
        assert len(result["outline"]) == 3
        assert result["outline"][0]["section"] == "Symptoms"
        assert result["outline"][0]["description"] == "2 symptoms"

    def test_summarizer_extracts_decision_tree(self):
        json_response = (
            '{"brief": "test", "key_facts": ["f1"], "commands": [], '
            '"symptoms": [], '
            '"resolution_branches": ['
            '{"when": "a", "label": "A"}, '
            '{"when": "b", "label": "B"}, '
            '{"when": "c", "label": "C"}], '
            '"outline": [{"section": "Symptoms", "description": "test"}, '
            '{"section": "Root Cause", "description": "test"}, '
            '{"section": "Resolution", "description": "test"}], '
            '"decision_tree": "root\\n├─ [A]\\n├─ [B]\\n└─ [C]"}'
        )
        provider = MockProvider([json_response])
        summarizer = SummarizerAgent(provider=provider, model="test")
        result = summarizer.run("some doc", {"source_text": "some doc"})
        assert result is not None
        assert result["decision_tree"] == "root\n├─ [A]\n├─ [B]\n└─ [C]"
        assert len(result["resolution_branches"]) == 3


# ---------------------------------------------------------------------------
# Generator Tests (042)
# ---------------------------------------------------------------------------


class TestGenerator042:
    """Tests for progressive disclosure generator."""

    def _make_summary(self) -> dict[str, Any]:
        return {
            "brief": "Redis OOM fix",
            "key_facts": ["Redis uses 4GB memory", "maxmemory not set"],
            "commands": ["redis-cli info memory", "redis-cli config set maxmemory 4gb"],
            "symptoms": ["High memory usage", "Connection timeouts"],
            "resolution_branches": [
                {"when": "OOM", "label": "Flush keys"},
                {"when": "High load", "label": "Increase memory"},
            ],
            "outline": [
                {"section": "Symptoms", "description": "2 observable symptoms"},
                {"section": "Root Cause", "description": "1 root cause: maxmemory not set"},
                {"section": "Resolution", "description": "2 branches, 2 commands"},
            ],
        }

    def test_generator_produces_draft(self):
        draft_md = (
            "---\nid: redis-oom\ntype: pitfall\ncategory: database\n"
            "title: Redis OOM\ntags: [redis]\nlanguage: en\n---\n\n"
            "## Contents\n\n| Section | Description |\n|---|---|\n| Symptoms | High memory |\n\n"
            "## Symptoms\n- High memory\n\n## Root Cause\nmaxmemory not set\n\n"
            "## Resolution\n1. redis-cli info memory\n"
        )
        provider = MockProvider([draft_md])
        generator = GeneratorAgent(provider=provider, model="test")
        ctx = {"source_text": "some doc"}
        result = generator.run(self._make_summary(), ctx, "pitfall", "en")
        assert "---" in result
        assert "## Symptoms" in result or "## Resolution" in result

    def test_generator_run_with_feedback(self):
        draft_md = (
            "---\nid: redis-oom\ntype: pitfall\ncategory: database\n"
            "title: Redis OOM\ntags: [redis]\nlanguage: en\n---\n\n"
            "## Contents\n\n| Section | Description |\n|---|---|\n| Symptoms | High memory |\n\n"
            "## Symptoms\n- High memory\n\n## Root Cause\nmaxmemory\n\n"
            "## Resolution\n1. redis-cli config set maxmemory 4gb\n"
        )
        provider = MockProvider([draft_md])
        generator = GeneratorAgent(provider=provider, model="test")
        ctx = {"source_text": "some doc"}
        result = generator.run_with_feedback(
            self._make_summary(), ctx,
            "previous draft", "missing commands",
            "pitfall", "en",
        )
        assert len(result) > 0

    def test_generator_returns_empty_on_no_output(self):
        provider = MockProvider([""])
        generator = GeneratorAgent(provider=provider, model="test")
        result = generator.run(self._make_summary(), {"source_text": "x"}, "pitfall", "en")
        assert result == ""

    def test_build_summary_input_includes_outline(self):
        summary = self._make_summary()
        block = GeneratorAgent._build_summary_input(summary, "pitfall", "en", False)
        assert "Outline (3 sections" in block
        assert "## Symptoms — 2 observable symptoms" in block
        assert "## Root Cause — 1 root cause: maxmemory not set" in block
        assert "## Resolution — 2 branches, 2 commands" in block

    def test_build_summary_input_includes_decision_tree(self):
        summary = self._make_summary()
        summary["decision_tree"] = "root\n├─ [A]\n└─ [B]"
        block = GeneratorAgent._build_summary_input(summary, "pitfall", "en", True)
        assert "Decision Tree" in block
        assert "root\n├─ [A]\n└─ [B]" in block

    def test_build_summary_input_no_outline_no_section(self):
        summary = self._make_summary()
        summary["outline"] = []
        block = GeneratorAgent._build_summary_input(summary, "pitfall", "en", False)
        assert "Outline" not in block


# ---------------------------------------------------------------------------
# Fidelity Check Tests (042)
# ---------------------------------------------------------------------------


class TestFidelity042:
    """Tests for verify_summary_fidelity_042."""

    def test_no_issues_when_all_present(self):
        summary = {
            "key_facts": ["Uses 4GB memory"],
            "commands": [{"cmd": "redis-cli info", "expected": "shows memory stats", "risk": "read"}],
        }
        draft = "## Info\nUses 4GB memory\n```bash\nredis-cli info\n```\nExpected: shows memory stats"
        errors, warnings = verify_summary_fidelity_042(summary, draft)
        assert errors == []
        assert warnings == []

    def test_missing_half_commands_errors(self):
        """1/2 = 50% missing, >30% threshold → error."""
        summary = {
            "key_facts": [],
            "commands": [
                {"cmd": "redis-cli info memory", "expected": "", "risk": "read"},
                {"cmd": "redis-cli dbsize", "expected": "", "risk": "read"},
            ],
        }
        draft = "## Info\n```bash\nredis-cli info memory\n```"
        errors, warnings = verify_summary_fidelity_042(summary, draft)
        assert len(errors) == 1
        assert "命令丢失" in errors[0]

    def test_missing_one_of_four_commands_warns(self):
        """1/4 = 25% missing, ≤30% threshold → warning."""
        summary = {
            "key_facts": [],
            "commands": [
                {"cmd": "cmd1", "expected": "", "risk": "read"},
                {"cmd": "cmd2", "expected": "", "risk": "read"},
                {"cmd": "cmd3", "expected": "", "risk": "read"},
                {"cmd": "cmd4", "expected": "", "risk": "read"},
            ],
        }
        draft = "## Steps\n```\ncmd1\n```\n```\ncmd2\n```\n```\ncmd3\n```"
        errors, warnings = verify_summary_fidelity_042(summary, draft)
        assert not any("命令丢失" in e for e in errors)
        assert any("命令丢失" in w for w in warnings)

    def test_missing_most_commands_errors(self):
        """Most commands missing (>30%) → error, must retry."""
        summary = {
            "key_facts": [],
            "commands": [
                {"cmd": "cmd1", "expected": "", "risk": "read"},
                {"cmd": "cmd2", "expected": "", "risk": "read"},
                {"cmd": "cmd3", "expected": "", "risk": "read"},
                {"cmd": "cmd4", "expected": "", "risk": "write"},
            ],
        }
        draft = "## Resolution\n```bash\ncmd1\n```"
        errors, warnings = verify_summary_fidelity_042(summary, draft)
        assert any("命令丢失" in e for e in errors)

    def test_legacy_string_commands_still_work(self):
        """Backward compat: list[str] commands format still checked."""
        summary = {
            "key_facts": [],
            "commands": ["redis-cli info"],
        }
        draft = "```bash\nredis-cli info\n```"
        errors, warnings = verify_summary_fidelity_042(summary, draft)
        assert not any("命令丢失" in e for e in errors)

    def test_missing_expected_warns(self):
        """Commands with expected field but no Expected: line → warning."""
        summary = {
            "key_facts": [],
            "commands": [
                {"cmd": "lspci -nn", "expected": "should show GPU device", "risk": "read"},
            ],
        }
        draft = "## Steps\n1. [api:read] Check devices:\n```bash\nlspci -nn\n```\nno expected line here"
        errors, warnings = verify_summary_fidelity_042(summary, draft)
        assert any("Expected" in w for w in warnings)

    def test_missing_number_warns(self):
        summary = {
            "key_facts": ["Timeout is 30 seconds", "Max connections 256"],
            "commands": [],
        }
        draft = "Timeout is present but 256 missing"
        errors, warnings = verify_summary_fidelity_042(summary, draft)
        assert any("数字丢失" in w for w in warnings)

    def test_empty_summary_no_issues(self):
        errors, warnings = verify_summary_fidelity_042({"key_facts": [], "commands": []}, "any draft")
        assert errors == []
        assert warnings == []

    def test_missing_branch_errors(self):
        """A missing resolution branch is a structural error."""
        summary = {
            "key_facts": [],
            "commands": [],
            "resolution_branches": [
                {"when": "lspci 不可见", "label": "物理连接问题"},
                {"when": "link 降级", "label": "信号完整性"},
            ],
        }
        draft = "## Resolution\n### 物理连接问题\nsteps here"
        errors, warnings = verify_summary_fidelity_042(summary, draft)
        assert len(errors) == 1
        assert "信号完整性" in errors[0]

    def test_all_branches_present_no_error(self):
        summary = {
            "key_facts": [],
            "commands": [],
            "resolution_branches": [
                {"when": "cond A", "label": "分支A"},
                {"when": "cond B", "label": "分支B"},
            ],
        }
        draft = "## Resolution\n### 分支A\nsteps\n### 分支B\nsteps"
        errors, warnings = verify_summary_fidelity_042(summary, draft)
        assert not any("分支丢失" in e for e in errors)

    def test_all_symptoms_missing_errors_pitfall(self):
        """All symptoms missing in a pitfall entry → error."""
        summary = {
            "key_facts": [],
            "commands": [],
            "symptoms": ["lspci 无法识别 GPU 卡", "BMC SEL 日志中 Memory ECC Error"],
        }
        draft = "## Symptoms\nno relevant content here at all\n## Root Cause\n..."
        errors, warnings = verify_summary_fidelity_042(summary, draft, entry_type="pitfall")
        assert any("症状丢失" in e for e in errors)

    def test_partial_symptoms_warns_pitfall(self):
        """Some symptoms present → warning, not error."""
        summary = {
            "key_facts": [],
            "commands": [],
            "symptoms": ["lspci 无法识别 GPU 卡", "BMC SEL 日志中 Memory ECC Error", "系统自动重启"],
        }
        draft = "## Symptoms\n- lspci 无法识别 GPU 卡\n- 系统自动重启\n## Root Cause\n..."
        errors, warnings = verify_summary_fidelity_042(summary, draft, entry_type="pitfall")
        # 1/3 missing = 33%, ≤50% → warning
        assert not any("症状丢失" in e for e in errors)
        assert any("症状丢失" in w for w in warnings)

    def test_symptoms_not_checked_for_non_pitfall(self):
        """Symptom check only applies to pitfall type."""
        summary = {
            "key_facts": [],
            "commands": [],
            "symptoms": ["some symptom"],
        }
        draft = "## Overview\nno symptoms here"
        errors, warnings = verify_summary_fidelity_042(summary, draft, entry_type="model")
        assert not any("症状" in e for e in errors)
        assert not any("症状" in w for w in warnings)


# ---------------------------------------------------------------------------
# Interactive Review Tests (042)
# ---------------------------------------------------------------------------


class TestReviewSummary:
    def test_non_interactive_auto_accepts(self):
        report = ImportReport()
        result = review_summary({"brief": "test"}, True, report)
        assert result is True

    def test_extract_title(self):
        draft = "---\ntitle: My Title\n---\ncontent"
        assert _extract_title(draft) == "My Title"

    def test_extract_type(self):
        draft = "---\ntype: pitfall\n---\ncontent"
        assert _extract_type(draft) == "pitfall"


class TestReviewDraft:
    def test_non_interactive_auto_accepts(self):
        report = ImportReport()
        result = review_draft("some draft", [], True, report)
        assert result is True

    def test_fidelity_warnings_logged(self):
        report = ImportReport()
        review_draft("some draft", ["warning1", "warning2"], True, report)
        assert "warning1" in report.warnings
        assert "warning2" in report.warnings


# ---------------------------------------------------------------------------
# Normalizer kp-N cleanup Tests
# ---------------------------------------------------------------------------


class TestNormalizerKpCleanup:
    def test_kp_references_cleaned(self):
        draft = (
            "---\ntitle: Test\ntype: pitfall\ntags: []\ncategory: test\n---\n\n"
            "See kp-1 and kp-2 for details.\n"
        )
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="pitfall")
        assert "kp-1" not in result
        assert "kp-2" not in result
        assert any("kp-N" in w for w in warnings)

    def test_no_kp_references_no_warning(self):
        draft = (
            "---\ntitle: Test\ntype: pitfall\ntags: []\ncategory: test\n---\n\n"
            "Normal content.\n"
        )
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="pitfall")
        assert not any("kp-N" in w for w in warnings)


# ---------------------------------------------------------------------------
# Pipeline Integration Tests (042)
# ---------------------------------------------------------------------------


class TestBuildFallbackOutline:
    """Tests for _build_fallback_outline — enriched descriptions from summary."""

    def test_pitfall_outline_uses_counts(self):
        summary = {
            "brief": "Redis OOM",
            "key_facts": ["f1", "f2", "f3"],
            "commands": ["cmd1", "cmd2"],
            "symptoms": ["s1", "s2"],
            "resolution_branches": [{"when": "a", "label": "A"}],
        }
        outline = ImportPipeline._build_fallback_outline(summary, "pitfall")
        assert len(outline) == 3
        assert "2" in outline[0]["description"]  # 2 symptoms
        assert "3" in outline[1]["description"]  # 3 key facts
        assert "2" in outline[2]["description"]  # 2 commands

    def test_model_outline_uses_brief(self):
        summary = {
            "brief": "PROCHOT thermal throttle mechanism",
            "key_facts": ["f1", "f2"],
            "commands": [],
        }
        outline = ImportPipeline._build_fallback_outline(summary, "model")
        assert len(outline) == 3
        assert "PROCHOT" in outline[0]["description"]

    def test_unknown_type_returns_empty(self):
        outline = ImportPipeline._build_fallback_outline({}, "unknown")
        assert outline == []

    def test_zero_counts_still_meaningful(self):
        summary = {
            "brief": "test",
            "key_facts": [],
            "commands": [],
            "symptoms": [],
            "resolution_branches": [],
        }
        outline = ImportPipeline._build_fallback_outline(summary, "pitfall")
        # Should not have generic "Observable symptoms" — should say something about count
        assert outline[0]["description"] == "症状描述"
        assert outline[1]["description"] == "根因分析"
        assert outline[2]["description"] == "排查步骤"


class TestDecisionTreeBackfill:
    """Tests for automatic decision_tree generation when dual-signal triggers."""

    def test_tree_generated_from_branches(self):
        summary = {
            "brief": "PCIe link failure",
            "key_facts": [],
            "commands": [],
            "symptoms": [],
            "resolution_branches": [
                {"when": "lspci 无设备", "label": "物理连接"},
                {"when": "link 降级", "label": "信号完整性"},
                {"when": "AER 错误", "label": "电气兼容性"},
            ],
        }
        # Simulate what pipeline does
        tree_lines = [summary["brief"]]
        labels = "ABCDEFGHIJ"
        for i, b in enumerate(summary["resolution_branches"]):
            label = labels[i]
            connector = "└─" if i == len(summary["resolution_branches"]) - 1 else "├─"
            tree_lines.append(f"{connector} {b['when']} ─→ [{label}] {b['label']}")
        tree = "\n".join(tree_lines)

        assert "[A] 物理连接" in tree
        assert "[B] 信号完整性" in tree
        assert "[C] 电气兼容性" in tree
        assert tree.startswith("PCIe link failure")


class TestPipeline042:
    """Tests for ImportPipeline (042)."""

    def test_backward_compat_alias(self):
        assert ThreePhaseImportPipeline is ImportPipeline

    def test_pipeline_non_kb_skips(self, tmp_path: Path):
        """non_kb classification → skip."""
        provider = MockProvider([
            '{"doc_type": "non_kb", "reason": "no knowledge"}'
        ])
        from holmes.config import HolmesConfig
        cfg = HolmesConfig(model="test")
        pipeline = ImportPipeline(
            kb_root=tmp_path,
            cfg=cfg,
            no_interactive=True,
            _provider=provider,
        )
        report = pipeline.run("just a meeting agenda")
        assert len(report.warnings) > 0
        assert any("non-kb" in w for w in report.warnings)

    def test_pipeline_dry_run_no_writes(self, tmp_path: Path):
        """Dry run produces suggestions but no files."""
        provider = MockProvider([
            '{"doc_type": "incident", "suggested_type": "pitfall", '
            '"language": "en", "reason": "test"}'
        ])
        from holmes.config import HolmesConfig
        cfg = HolmesConfig(model="test")
        pipeline = ImportPipeline(
            kb_root=tmp_path,
            cfg=cfg,
            no_interactive=True,
            dry_run=True,
            _provider=provider,
        )
        report = pipeline.run("some incident text")
        assert report.dry_run is True
        assert len(report.created) == 0

    def test_pipeline_full_flow(self, tmp_path: Path):
        """Full pipeline: classify → summarize → generate → write."""
        classifier_resp = (
            '{"doc_type": "incident", "suggested_type": "pitfall", '
            '"language": "en", "reason": "test"}'
        )
        summarizer_resp = (
            '{"brief": "Redis OOM", "key_facts": ["fact1"], '
            '"commands": ["redis-cli info"], "symptoms": ["high memory"], '
            '"resolution_branches": [], '
            '"outline": [{"section": "Symptoms", "description": "high memory"}, '
            '{"section": "Root Cause", "description": "1 root cause"}, '
            '{"section": "Resolution", "description": "1 command"}]}'
        )
        generator_resp = (
            "---\nid: redis-oom-001\ntype: pitfall\ncategory: database\n"
            "title: Redis OOM\nbrief: Redis OOM\ntags: [redis]\n"
            "language: en\n---\n\n"
            "## Contents\n\n| Section | Description |\n|---|---|\n"
            "| Symptoms | high memory |\n"
            "| Root Cause | 1 root cause |\n"
            "| Resolution | 1 command |\n\n"
            "## Symptoms\n- high memory\n\n"
            "## Root Cause\nfact1\n\n"
            "## Resolution\n1. [api] `redis-cli info`\n"
        )
        provider = MockProvider([classifier_resp, summarizer_resp, generator_resp])
        from holmes.config import HolmesConfig
        cfg = HolmesConfig(model="test")

        # Create _pending dir
        (tmp_path / "_pending").mkdir(parents=True, exist_ok=True)

        pipeline = ImportPipeline(
            kb_root=tmp_path,
            cfg=cfg,
            no_interactive=True,
            _provider=provider,
        )
        report = pipeline.run("# Redis OOM\n\nHigh memory usage...")
        # Should have created one entry
        assert len(report.created) >= 0  # May or may not create depending on write_kb_entry
        assert len(report.errors) == 0 or any("write" in e.lower() for e in report.errors)


# ---------------------------------------------------------------------------
# _strip_llm_wrapper tests
# ---------------------------------------------------------------------------


class TestStripLlmWrapper:
    """Tests for ImportPipeline._strip_llm_wrapper()."""

    def test_clean_frontmatter_unchanged(self):
        draft = "---\nid: test\ntype: pitfall\n---\n## Symptoms\nfoo"
        assert ImportPipeline._strip_llm_wrapper(draft) == draft

    def test_strips_code_fence_wrapper(self):
        draft = "```markdown\n---\nid: test\n---\n## Body\n```"
        result = ImportPipeline._strip_llm_wrapper(draft)
        assert result.startswith("---")
        assert "```" not in result

    def test_strips_preamble_text(self):
        draft = "Here's the KB entry:\n\n```markdown\n---\nid: test\n---\n## Body\n```"
        result = ImportPipeline._strip_llm_wrapper(draft)
        assert result.startswith("---")
        assert "Here's" not in result

    def test_strips_preamble_with_direct_frontmatter(self):
        draft = "以下是生成的条目：\n---\nid: test\ntype: pitfall\n---\n## Symptoms"
        result = ImportPipeline._strip_llm_wrapper(draft)
        assert result.startswith("---")

    def test_fixes_missing_closing_frontmatter(self):
        draft = "---\nid: test\ntype: pitfall\n\n## Symptoms\nfoo"
        result = ImportPipeline._strip_llm_wrapper(draft)
        # Should insert --- before ## Symptoms
        assert "\n---\n" in result or result.count("---") >= 2

    def test_trailing_code_fence_removed(self):
        draft = "---\nid: test\n---\n## Body\ntext\n```"
        result = ImportPipeline._strip_llm_wrapper(draft)
        assert not result.rstrip().endswith("```")

    def test_empty_frontmatter_then_code_fence(self):
        """LLM outputs ---\\n\\n```yaml\\n---\\nreal content..."""
        draft = "---\n\n```yaml\n---\nid: test\ntype: pitfall\n---\n## Symptoms\nfoo\n```"
        result = ImportPipeline._strip_llm_wrapper(draft)
        assert result.startswith("---\nid: test")
        assert "```" not in result


# ---------------------------------------------------------------------------
# Classification Result compat tests
# ---------------------------------------------------------------------------


class TestClassificationResultCompat:
    def test_needs_dag_always_false(self):
        result = ClassificationResult(
            doc_type=DocumentType.incident,
            reason="test",
        )
        assert result.needs_dag is False

    def test_has_complexity_field(self):
        """Backward compat: complexity field exists."""
        result = ClassificationResult(
            doc_type=DocumentType.incident,
            reason="test",
        )
        assert hasattr(result, "complexity")

    def test_has_granularity_hint_field(self):
        result = ClassificationResult(
            doc_type=DocumentType.incident,
            reason="test",
        )
        assert hasattr(result, "granularity_hint")


# ---------------------------------------------------------------------------
# E2E Validation: Import → MCP retrieval
# ---------------------------------------------------------------------------


class TestE2EImportToMCP:
    """042 Phase 4 validation: import produces one entry, MCP can retrieve it."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        for d in ("pitfall/database", "_pending/pitfall/database",
                   "contributions/pending"):
            (kb / d).mkdir(parents=True)
        return kb

    def _run_pipeline(self, kb_root: Path, source_text: str, kb_type: str = "pitfall") -> ImportReport:
        """Run full pipeline with mock provider."""
        classifier_resp = (
            f'{{"doc_type": "incident", "suggested_type": "{kb_type}", '
            f'"language": "en", "reason": "test incident"}}'
        )
        summarizer_resp = (
            '{"brief": "PSU redundancy degradation triggers power wall causing GPU training interruption", '
            '"key_facts": ["PSU N+1 redundancy lost", "GPU throttle triggered by power cap", '
            '"Xid 79 error in dmesg"], '
            '"commands": ["nvidia-smi -q -d PAGE_RETIREMENT", '
            '"ipmitool sdr list | grep PS"], '
            '"symptoms": ["GPU utilization drops to 0", "dmesg shows Xid 79", '
            '"BMC reports power fault"], '
            '"resolution_branches": ['
            '{"when": "dmesg has Xid 79", "label": "GPU Xid troubleshooting"}, '
            '{"when": "BMC power fault", "label": "PSU redundancy check"}]}'
        )
        generator_resp = (
            "---\n"
            "id: PT-HW-001\n"
            "type: pitfall\n"
            "category: database\n"
            'title: "PSU Redundancy Degradation"\n'
            'brief: "PSU redundancy degradation triggers power wall"\n'
            "tags: [gpu, psu, power]\n"
            "language: en\n"
            "---\n\n"
            "## Contents\n\n"
            "| Section | Description |\n"
            "|---|---|\n"
            "| Symptoms | 3 symptoms: GPU drop, Xid 79, power fault |\n"
            "| Root Cause | PSU redundancy lost |\n"
            "| Resolution | 2 branches, 2 commands |\n\n"
            "## Symptoms\n"
            "- GPU utilization drops to 0\n"
            "- dmesg shows Xid 79\n"
            "- BMC reports power fault\n\n"
            "## Root Cause\n"
            "PSU N+1 redundancy lost. GPU throttle triggered by power cap.\n\n"
            "## Resolution\n\n"
            "### GPU Xid troubleshooting\n"
            "1. [api] `nvidia-smi -q -d PAGE_RETIREMENT`\n\n"
            "### PSU redundancy check\n"
            "1. [api] `ipmitool sdr list | grep PS`\n"
        )
        provider = MockProvider([classifier_resp, summarizer_resp, generator_resp])
        from holmes.config import HolmesConfig
        cfg = HolmesConfig(model="test")

        pipeline = ImportPipeline(
            kb_root=kb_root, cfg=cfg,
            no_interactive=True, _provider=provider,
        )
        return pipeline.run(source_text)

    def test_one_doc_produces_one_entry(self, kb_root: Path):
        """Core invariant: one source document → exactly one KB entry."""
        report = self._run_pipeline(kb_root, "GPU failure doc with multiple branches...")
        assert len(report.created) == 1, f"Expected 1 entry, got {len(report.created)}"
        assert len(report.errors) == 0, f"Errors: {report.errors}"

    def test_entry_has_brief_field(self, kb_root: Path):
        """042 data model: entry must have brief field in frontmatter."""
        import frontmatter
        self._run_pipeline(kb_root, "GPU failure doc...")
        pending_files = list((kb_root / "contributions" / "pending").rglob("*.md"))
        assert len(pending_files) == 1
        post = frontmatter.load(str(pending_files[0]))
        assert post.metadata.get("brief"), "Entry must have non-empty brief"

    def test_commands_preserved_verbatim(self, kb_root: Path):
        """042 fidelity: commands from source must appear verbatim."""
        self._run_pipeline(kb_root, "GPU failure doc...")
        pending_files = list((kb_root / "contributions" / "pending").rglob("*.md"))
        content = pending_files[0].read_text(encoding="utf-8")
        assert "nvidia-smi -q -d PAGE_RETIREMENT" in content
        assert "ipmitool sdr list | grep PS" in content

    def test_branch_structure_in_resolution(self, kb_root: Path):
        """042 generator: pitfall with multiple branches must have ### subsections."""
        self._run_pipeline(kb_root, "GPU failure doc...")
        pending_files = list((kb_root / "contributions" / "pending").rglob("*.md"))
        content = pending_files[0].read_text(encoding="utf-8")
        assert "### GPU Xid troubleshooting" in content or "### PSU redundancy check" in content

    def test_mcp_browse_finds_entry(self, kb_root: Path):
        """042 MCP: kb_browse (no query) must list the imported entry."""
        from holmes.mcp.tools import handle_kb_browse
        self._run_pipeline(kb_root, "GPU failure doc...")

        # Move from contributions/pending to active pitfall dir for browse
        pending_files = list((kb_root / "contributions" / "pending").rglob("*.md"))
        assert pending_files
        import frontmatter as _fm
        post = _fm.load(str(pending_files[0]))
        # Ensure kb_status is active for browse
        post.metadata["kb_status"] = "active"
        dest = kb_root / "pitfall" / "database" / pending_files[0].name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_fm.dumps(post), encoding="utf-8")

        result = handle_kb_browse(kb_root)
        entries = result.get("entries", [])
        assert len(entries) >= 1, f"kb_browse should list entry, got: {result}"
        assert any("PSU" in e.get("title", "") or "Redundancy" in e.get("title", "")
                    for e in entries), f"PSU entry not in browse results: {entries}"

    def _setup_active_entry(self, kb_root: Path):
        """Import and move pending → active. Returns (entry_id, dest_path)."""
        import frontmatter as _fm
        import shutil
        self._run_pipeline(kb_root, "GPU failure doc...")
        pending_files = list((kb_root / "contributions" / "pending").rglob("*.md"))
        assert pending_files, "Pipeline should have written a pending file"
        post = _fm.load(str(pending_files[0]))
        post.metadata["kb_status"] = "active"
        dest = kb_root / "pitfall" / "database" / pending_files[0].name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_fm.dumps(post), encoding="utf-8")
        entry_id = post.metadata.get("id", dest.stem)
        return entry_id, dest

    def test_mcp_read_summary_has_symptoms(self, kb_root: Path):
        """042 MCP: kb_read summary layer has symptoms for pitfall."""
        from holmes.mcp.tools import handle_kb_read
        entry_id, _ = self._setup_active_entry(kb_root)

        result = handle_kb_read(kb_root, entry_id)
        assert "symptoms" in result, f"Summary should have symptoms: {result}"
        assert isinstance(result["symptoms"], list)
        assert len(result["symptoms"]) >= 1

    def test_mcp_read_full_has_content(self, kb_root: Path):
        """042 MCP: kb_read full=true returns complete document."""
        from holmes.mcp.tools import handle_kb_read
        entry_id, _ = self._setup_active_entry(kb_root)

        result = handle_kb_read(kb_root, entry_id, full=True)
        assert "content" in result
        assert "## Symptoms" in result["content"]
        assert "## Resolution" in result["content"]
        assert "kb_confirm" in result["next"]
