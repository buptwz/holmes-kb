"""Tests for post-eval root-cause fixes (spec 043):

1. Generator empty-draft robustness (both providers' message shapes):
   - _extract_draft skips empty assistant turns instead of returning ""
   - generation loop nudges on empty final response instead of giving up
2. Type-override gating: a confident Classifier result is never flipped by
   brittle outline keyword heuristics (oscilloscope guideline → decision bug).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from holmes.config import HolmesConfig
from holmes.kb.agent.phases.generator import GeneratorAgent
from holmes.kb.agent.pipeline import ImportPipeline


class _ScriptedProvider:
    """Minimal provider stub returning scripted assistant texts (OpenAI shape)."""

    def __init__(self, texts: list[Any]):
        self._texts = list(texts)
        self.calls = 0

    def complete(self, messages, system, model, max_tokens, tools=None):  # noqa: ANN001
        item = self._texts[min(self.calls, len(self._texts) - 1)]
        self.calls += 1
        content = item if not isinstance(item, list) else item
        updated = list(messages) + [{"role": "assistant", "content": content}]
        return True, [], updated, {}

    def simple_complete(self, messages, system="", max_tokens=512):  # noqa: ANN001
        return "{}"

    def append_tool_results(self, messages, results):  # noqa: ANN001
        return messages


_SUMMARY = {
    "brief": "测试摘要",
    "key_facts": ["fact one", "fact two"],
    "commands": [],
    "symptoms": [],
    "resolution_branches": [],
    "outline": [{"section": "Guideline", "description": "rules"}],
    "steps": [],
}


class TestExtractDraftSkipsEmpty:
    def test_openai_empty_final_turn(self) -> None:
        messages = [
            {"role": "assistant", "content": "## Guideline\n- 真实 draft 内容"},
            {"role": "user", "content": "nudge"},
            {"role": "assistant", "content": ""},  # gateway returned null content
        ]
        assert GeneratorAgent._extract_draft(messages) == "## Guideline\n- 真实 draft 内容"

    def test_anthropic_empty_blocks(self) -> None:
        messages = [
            {"role": "assistant", "content": [{"type": "text", "text": "旧 draft"}]},
            {"role": "assistant", "content": []},  # Anthropic turn with no text blocks
        ]
        assert GeneratorAgent._extract_draft(messages) == "旧 draft"

    def test_all_empty_returns_empty(self) -> None:
        assert GeneratorAgent._extract_draft([{"role": "assistant", "content": ""}]) == ""


class TestGeneratorEmptyNudge:
    def test_nudge_recovers_draft(self) -> None:
        provider = _ScriptedProvider(["", "## Guideline\n- 追问后产出"])
        gen = GeneratorAgent(provider=provider, model="test")  # type: ignore[arg-type]
        draft = gen.run(_SUMMARY, {"source_text": "x" * 100})
        assert draft == "## Guideline\n- 追问后产出"
        assert provider.calls == 2  # initial + 1 nudge

    def test_nudge_recovers_draft_anthropic_shape(self) -> None:
        # Anthropic shape: empty content block list, then a text block.
        provider = _ScriptedProvider([[], [{"type": "text", "text": "## Guideline\n- 块内容"}]])
        gen = GeneratorAgent(provider=provider, model="test")  # type: ignore[arg-type]
        draft = gen.run(_SUMMARY, {"source_text": "x" * 100})
        assert draft == "## Guideline\n- 块内容"
        assert provider.calls == 2

    def test_nudge_exhaustion_returns_empty(self) -> None:
        provider = _ScriptedProvider(["", "", "", ""])
        gen = GeneratorAgent(provider=provider, model="test")  # type: ignore[arg-type]
        draft = gen.run(_SUMMARY, {"source_text": "x" * 100})
        assert draft == ""
        assert provider.calls == 3  # initial + 2 nudges max


# ---------------------------------------------------------------------------
# Type-override gating
# ---------------------------------------------------------------------------


class _PipelineMockProvider(_ScriptedProvider):
    """Scripted for the 3 pipeline LLM calls (classifier/summarizer/generator)."""

    def complete(self, messages, system, model, max_tokens, tools=None):  # noqa: ANN001
        item = self._texts[min(self.calls, len(self._texts) - 1)]
        self.calls += 1
        updated = list(messages) + [{"role": "assistant", "content": str(item)}]
        return True, [], updated, {}

    def simple_complete(self, messages, system="", max_tokens=512):  # noqa: ANN001
        item = self._texts[min(self.calls, len(self._texts) - 1)]
        self.calls += 1
        return str(item)


def _run_pipeline(tmp_path: Path, responses: list[str]) -> str:
    """Run the real pipeline with scripted LLM; return the pending entry's type."""
    import frontmatter

    provider = _PipelineMockProvider(responses)
    pipeline = ImportPipeline(
        kb_root=tmp_path,
        cfg=HolmesConfig(model="test"),
        no_interactive=True,
        _provider=provider,
    )
    doc = "# 高速信号示波器量测规范\n\n" + ("1. 必须使用有源差分探头，禁止使用无源探头。\n" * 8)
    report = pipeline.run(doc, file_path=None)
    assert not report.errors, f"pipeline errors: {report.errors}"
    pending = list((tmp_path / "contributions" / "pending").glob("*.md"))
    assert pending, "no pending entry produced"
    return str(frontmatter.load(str(pending[0])).metadata.get("type", ""))


_CLASSIFIER_GUIDELINE = (
    '{"doc_type":"guideline","suggested_type":"guideline","language":"zh",'
    '"is_multi_topic":false,"topic_boundaries":[],"branch_count":0,"reason":"rules doc"}'
)
_SUMMARY_WITH_DECISION_OUTLINE = (
    '{"brief":"示波器量测规范","key_facts":["f1","f2"],"commands":[],'
    '"symptoms":[],"resolution_branches":[],'
    '"outline":[{"section":"Purpose","description":"p"},'
    '{"section":"Decision","description":"判读标准"},'
    '{"section":"Guideline","description":"规则"}],'
    '"steps":[],"decision_tree":""}'
)
_GUIDELINE_DRAFT = (
    "---\ntype: guideline\ntitle: 示波器量测规范\ncategory: general\n"
    "tags: [oscilloscope, measurement]\n---\n\n## Guideline\n- 必须使用有源差分探头\n"
)


class TestTypeOverrideGating:
    def test_confident_classifier_not_flipped_by_outline_keyword(self, tmp_path: Path) -> None:
        """Regression: guideline doc with a 'Decision' outline section must stay
        guideline (previously flipped to decision by keyword heuristic)."""
        entry_type = _run_pipeline(
            tmp_path, [_CLASSIFIER_GUIDELINE, _SUMMARY_WITH_DECISION_OUTLINE, _GUIDELINE_DRAFT],
        )
        assert entry_type == "guideline"

    def test_classifier_failure_still_allows_inference(self, tmp_path: Path) -> None:
        """When the Classifier falls back (max retries), content inference may
        still override — the heuristic's intended use."""
        import frontmatter

        provider = _PipelineMockProvider([
            "garbage not json",  # classifier attempt 1 — parse failure
            "still garbage",     # classifier attempt 2 — parse failure → fallback pitfall
            '{"brief":"流程文档","key_facts":["f1"],"commands":[],"symptoms":[],'
            '"resolution_branches":[],'
            '"outline":[{"section":"Steps","description":"s"}],'
            '"steps":[],"decision_tree":""}',
            "---\ntype: process\ntitle: 刷写流程\ncategory: general\ntags: [a,b,c]\n---\n\n## Steps\n1. 第一步\n",
        ])
        pipeline = ImportPipeline(
            kb_root=tmp_path, cfg=HolmesConfig(model="test"),
            no_interactive=True, _provider=provider,
        )
        doc = "# 流程\n\n" + ("1. 按顺序执行。\n" * 10)
        report = pipeline.run(doc, file_path=None)
        assert not report.errors, f"pipeline errors: {report.errors}"
        pending = list((tmp_path / "contributions" / "pending").glob("*.md"))
        assert pending
        entry_type = str(frontmatter.load(str(pending[0])).metadata.get("type", ""))
        # classifier fell back to pitfall; outline has "Steps" → inference to process
        assert entry_type == "process"
