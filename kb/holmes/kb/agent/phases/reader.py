"""ReaderAgent — Phase 1 of the three-phase import pipeline.

The ReaderAgent reads the source document via doc_access tools and produces
a KnowledgeMap that indexes all knowledge points and their character offsets.
It runs in a fresh, isolated LLM message context (forked agent pattern).

Key design decisions (R-001 through R-008, 022):
- DocumentCursor tracks coverage; all doc reading goes through tools.
- Diminishing returns detection: stop when DIMINISHING_WINDOW consecutive
  reading passes each produce 0 new KnowledgePoints.
- Coverage threshold: aim for >= COVERAGE_THRESHOLD % before stopping.
- Semantic compaction (022 US1): when accumulated message history exceeds
  COMPACT_HISTORY_THRESHOLD characters between passes, _compact_history()
  issues a single LLM call that summarizes all found KPs, per-section
  semantics, and cross-references, then replaces the full history with
  that structured summary. The original document always remains accessible
  via read_document_range — only the message history is compacted.
- Forced coverage (022 US2): after each pass, uncovered gaps > MIN_UNCOVERED_CHARS
  trigger a forced-read prompt injected in the SAME conversation context so
  the LLM retains semantic continuity for cross-reference resolution.
- Per-pass observability (022 US3): a log_fn callback receives structured
  progress after every pass; ImportReport.coverage_pct records final coverage.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Callable, Optional


from holmes.kb.agent.doc_access import DOC_ACCESS_TOOL_DEFINITIONS, DOC_ACCESS_TOOL_HANDLERS
from holmes.kb.agent.knowledge_map import KnowledgeMap, KnowledgePoint
from holmes.kb.agent.provider.base import LLMProvider

# ---------------------------------------------------------------------------
# Constants (C-001 contract: all thresholds as named constants)
# ---------------------------------------------------------------------------

COVERAGE_THRESHOLD = 95.0
DIMINISHING_WINDOW = 2
MAX_READER_ITERATIONS = 30   # tool-call iterations per reading pass (safety cap)
COMPACT_HISTORY_THRESHOLD = 50_000   # 022 US1: compact history when total chars exceed this
MIN_UNCOVERED_CHARS = 500            # 022 US2: min gap size to trigger forced coverage


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _extract_last_assistant_text(messages: list[Any]) -> str:
    """Extract text content from the last assistant message (handles both wire formats)."""
    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
    return ""


# ---------------------------------------------------------------------------
# ReaderConfig (022 FR-008: thresholds configurable, not hard-coded)
# ---------------------------------------------------------------------------


@dataclass
class ReaderConfig:
    """Configurable thresholds for the ReaderAgent (022 FR-008).

    Attributes:
        coverage_threshold: Target coverage percentage (default 95.0).
        compact_history_threshold: Compact message history when total accumulated
            characters exceed this value (default 50_000). Set to 0 to disable.
        min_uncovered_chars: Minimum gap size in chars to trigger forced
            coverage injection (default 500).
    """

    coverage_threshold: float = COVERAGE_THRESHOLD
    compact_history_threshold: int = COMPACT_HISTORY_THRESHOLD
    min_uncovered_chars: int = MIN_UNCOVERED_CHARS


READER_SYSTEM_PROMPT = """\
You are the Reader phase of a multi-phase KB import pipeline.

Your task: read the source document and identify every discrete knowledge point
(pitfall, model, guideline, process, or decision) it contains.

For each knowledge point you find:
1. Use read_document_range to read the relevant section of the document.
2. Use record_knowledge_point to register it with its character offsets,
   a one-sentence description, and your best-guess type and category.
3. Continue reading other sections — do not stop after the first knowledge point.

Use search_in_document to locate sections by keyword if helpful.
Use get_read_coverage to track how much of the document you have read.

IMPORTANT RULES:
- Register EVERY distinct knowledge point — do not merge unrelated topics.
- Use the character offsets from read_document_range to set section_start/end.
- Detect the language of the document (zh for Chinese, en for English) and
  record it per knowledge point.
- When you have read the entire document (coverage ≥ 95%) or cannot find
  more knowledge points, stop calling tools and output a brief summary.

KNOWLEDGE POINT SCOPING:
- One incident = ONE knowledge point. Do NOT create separate KPs for the
  symptoms, root cause, and resolution of the SAME incident or problem.
- A knowledge point represents a complete problem-solution pair, not a section.
- Only split into multiple KPs when topics are clearly independent (different
  systems, different time periods, or explicitly labeled as separate incidents).
"""

# Tool definition for recording a knowledge point into the KnowledgeMap.
_RECORD_KP_TOOL_DEF = {
    "name": "record_knowledge_point",
    "description": (
        "Register a knowledge point found in the source document. "
        "Call this once for each distinct knowledge point you identify."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "One-sentence summary of this knowledge point.",
            },
            "section_start": {
                "type": "integer",
                "description": "Start character offset of the relevant section (inclusive).",
            },
            "section_end": {
                "type": "integer",
                "description": "End character offset of the relevant section (exclusive).",
            },
            "type_hint": {
                "type": "string",
                "enum": ["pitfall", "model", "guideline", "process", "decision"],
                "description": "Best-guess KB type.",
            },
            "category_hint": {
                "type": "string",
                "description": "Best-guess category (e.g. database, network, system, application, kubernetes, messaging, cache, monitoring).",
            },
            "language": {
                "type": "string",
                "description": "ISO 639-1 language code (e.g. zh, en).",
            },
        },
        "required": ["description", "section_start", "section_end"],
    },
}


def _make_record_kp_handler(km: KnowledgeMap) -> Any:
    """Return a tool handler that records KnowledgePoints into km."""

    def _handler(ctx: dict[str, Any], tool_input: dict[str, Any]) -> dict[str, Any]:
        source_text = ctx.get("source_text", "")
        total_chars = len(source_text)

        start = int(tool_input.get("section_start", 0))
        end = int(tool_input.get("section_end", total_chars))

        # Clamp to document bounds.
        start = max(0, min(start, total_chars))
        end = max(start + 1, min(end, total_chars))

        if end <= start:
            return {"ok": False, "error": "section_end must be > section_start after clamping"}

        kp_id = f"kp-{len(km.knowledge_points) + 1}"
        try:
            kp = KnowledgePoint(
                id=kp_id,
                description=str(tool_input.get("description", "")),
                section_start=start,
                section_end=end,
                type_hint=str(tool_input.get("type_hint", "pitfall")),
                category_hint=str(tool_input.get("category_hint", "")),
                language=str(tool_input.get("language", "en")),
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        km.knowledge_points.append(kp)
        return {"ok": True, "kp_id": kp_id, "total_kps": len(km.knowledge_points)}

    return _handler


# ---------------------------------------------------------------------------
# 022 US1: Semantic history compaction prompt
# ---------------------------------------------------------------------------

READER_COMPACT_PROMPT = """\
你正在读取一篇文档，提取其中所有知识点。上下文即将被压缩，请生成一份高密度进度摘要，\
确保后续读取可以无缝继续，不因上下文重置而损失任何已理解的语义信息。

压缩原则：
- 知识形态不限：概念定义、操作流程、因果关系、配置规则、设计决策、对比分析、\
注意事项、架构模型、数据结构、接口规范……均为有效知识，不要偏向"问题/解决方案"格式
- 宁保留勿丢弃：语义价值不确定时，保留而不是略去
- 已记录的知识点信息严禁修改、截断或合并
- 核心目标：为"还没读到的部分"提供足够的前文语义背景，使后续读取中遇到的\
指示代词、前置引用、跨节依赖都能被正确理解

━━━ 第一节：已记录知识点（完整，一条不漏） ━━━

逐条列出所有通过 record_knowledge_point 记录的知识点：
  [id]  type=<type>  category=<category>  lang=<lang>  chars <start>–<end>
  描述：<完整描述，不截断>

如尚无知识点，写"（暂无）"。

━━━ 第二节：文档框架 ━━━

帮助后续理解整个文档的全局上下文：
- 文档类型：（如：事故报告 / 技术手册 / 概念指南 / 架构设计 / API文档 / 教程 / 研究文档 / 其他）
- 核心领域与主题：（1-2句说明这份文档在讲什么）
- 已识别的章节/段落结构：（一行一个，注明各段主题及字符范围）

━━━ 第三节：已读内容语义地图 ━━━

这是压缩中最关键的部分。对每个已读区间记录：
  chars <X>–<Y>  主题：<这段核心讲什么>
  关键内容：<名称 / 数值 / 步骤 / 条件 / 规则 / 关系中最重要的几点，不超过5条>
  前后依赖：<这段依赖哪些前文知识？为哪些后续内容提供前置背景？>

目标：读完此节后，即使不看原文，也能理解文档前半部分的语义，从而正确解读后续\
出现的"上述方法"、"如前所述"、"将X替换为Y"等引用。

━━━ 第四节：文档内术语与定义 ━━━

记录文档中已出现的专有术语、缩写、自定义概念，供解读后续内容时使用：
  <术语/缩写>：<含义或定义>

如无特殊术语，写"（无）"。

━━━ 第五节：跨节引用关系 ━━━

显式记录已发现的跨节依赖（前置条件、指示代词、概念继承、步骤依赖等）：
  示例："第3节的操作步骤以第1节中定义的连接池参数为前提"
  示例："第5节的'此方案'指第2节中描述的分片策略"

如无跨节引用，写"（无）"。

━━━ 第六节：未覆盖区间 ━━━

列出尚未读取的字符区间。如已全覆盖，写"（无）"。

━━━ 完成上述所有节后立即停止，不添加总结性语句 ━━━\
"""


# ---------------------------------------------------------------------------
# ReaderAgent
# ---------------------------------------------------------------------------


class ReaderAgent:
    """Phase 1 agent: reads the source document and produces a KnowledgeMap.

    Runs in a fresh, isolated LLM message context with doc_access tools and
    the record_knowledge_point tool. Terminates when coverage reaches
    config.coverage_threshold or diminishing returns are detected.

    022 additions:
    - Semantic compaction (US1): when accumulated message history exceeds
      config.compact_history_threshold characters between passes, the full
      history is sent to the LLM for semantic summarization. The structured
      summary — preserving all found KPs, per-section semantics, and
      cross-references — replaces the full history. The original document
      always remains accessible via read_document_range.
    - Forced coverage (US2): after each pass, uncovered gaps > config.min_uncovered_chars
      trigger a targeted prompt in the SAME context (preserving semantic continuity).
    - Per-pass observability (US3): log_fn receives a structured progress
      string after every pass and compaction event.

    Args:
        provider: LLMProvider instance (Anthropic or OpenAI-compatible).
        model: Model identifier string.
        config: Optional ReaderConfig; defaults to module-level constants.
    """

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        config: Optional[ReaderConfig] = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.config = config or ReaderConfig()

    def run(
        self,
        source_text: str,
        ctx: dict[str, Any],
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> KnowledgeMap:
        """Read the source document and return a KnowledgeMap.

        Args:
            source_text: Full, untruncated source document text.
            ctx: Shared pipeline context dict. Will have "source_text" and
                 "doc_cursor" set after this call.
            log_fn: Optional callback for per-pass progress strings (US3).
                    Receives a single str; defaults to writing to stderr.

        Returns:
            KnowledgeMap with all identified knowledge points.
        """
        if log_fn is None:
            log_fn = lambda msg: print(msg, file=sys.stderr, flush=True)  # noqa: E731

        km = KnowledgeMap()
        ctx["source_text"] = source_text

        cfg = self.config

        # Build tool list: doc_access tools + record_knowledge_point.
        tools = DOC_ACCESS_TOOL_DEFINITIONS + [_RECORD_KP_TOOL_DEF]
        handlers: dict[str, Any] = {
            **DOC_ACCESS_TOOL_HANDLERS,
            "record_knowledge_point": _make_record_kp_handler(km),
        }

        # 018 Root D: prepend granularity hint from DocumentClassifier if available.
        granularity_hint = ctx.get("granularity_hint", "")
        hint_prefix = (
            f"Document granularity guidance: {granularity_hint}\n\n"
            if granularity_hint else ""
        )

        # Fresh isolated message context (forked agent pattern).
        messages: list[Any] = [
            {
                "role": "user",
                "content": (
                    f"{hint_prefix}"
                    f"Please read the following document and identify all knowledge points.\n\n"
                    f"Document length: {len(source_text)} characters.\n"
                    f"Use read_document_range to read sections and record_knowledge_point "
                    f"for each knowledge point you find.\n\n"
                    f"Start by reading from char 0."
                ),
            }
        ]

        consecutive_zero_passes = 0

        while True:
            kps_before = len(km.knowledge_points)
            forced_coverage_triggered = False

            # --- Inner pass: run until LLM stops or iteration cap ---
            messages, forced_coverage_triggered = self._run_pass(
                messages, tools, handlers, ctx, cfg, forced_coverage_triggered
            )

            km.reading_passes += 1
            kps_after = len(km.knowledge_points)

            # Update coverage stats from DocumentCursor.
            cursor = ctx.get("doc_cursor")
            if cursor is not None:
                km.total_chars = cursor.total_chars
                km.chars_read = cursor.chars_read()
            else:
                km.total_chars = len(source_text)

            new_kps_this_pass = kps_after - kps_before

            # US3: per-pass observability log.
            log_fn(
                f"  [Reader pass {km.reading_passes}] "
                f"coverage: {km.coverage_pct:.1f}% "
                f"({km.chars_read}/{km.total_chars} chars), "
                f"new KPs: {new_kps_this_pass}"
                + (" [forced coverage]" if forced_coverage_triggered else "")
            )

            # Diminishing returns detection (T011).
            if new_kps_this_pass == 0:
                consecutive_zero_passes += 1
            else:
                consecutive_zero_passes = 0

            if consecutive_zero_passes >= DIMINISHING_WINDOW:
                km.diminishing_returns = True
                break

            # Coverage goal reached — stop.
            if km.coverage_pct >= cfg.coverage_threshold:
                break

            # US1: semantic compaction — replace bloated history with structured
            # summary before asking the LLM to continue. Threshold 0 disables.
            if cfg.compact_history_threshold > 0 and self._should_compact(
                messages, cfg.compact_history_threshold
            ):
                messages = self._compact_history(messages, km, ctx, cfg, log_fn)

            # Ask the LLM to continue reading any unread portions.
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Coverage so far: {km.coverage_pct:.1f}%. "
                        f"Continue reading unread sections of the document and "
                        f"record any additional knowledge points you find."
                    ),
                }
            )

        return km

    # ------------------------------------------------------------------
    # 022 US1: Semantic history compaction helpers
    # ------------------------------------------------------------------

    def _should_compact(self, messages: list[Any], threshold: int) -> bool:
        """Return True when total message content exceeds threshold characters."""
        total = sum(len(str(msg.get("content", ""))) for msg in messages)
        return total > threshold

    def _compact_history(
        self,
        messages: list[Any],
        km: KnowledgeMap,
        ctx: dict[str, Any],
        cfg: ReaderConfig,
        log_fn: Callable[[str], None],
    ) -> list[Any]:
        """Replace accumulated history with a semantic summary (022 US1).

        Sends the full conversation history plus a compaction request to the
        LLM. The LLM produces a structured summary that preserves all found
        KPs, per-section semantics, and cross-references. The full history is
        then replaced with: [original first message] + [summary] + [cue to
        continue with remaining uncovered ranges].

        The original document always remains accessible via read_document_range.
        Falls back to the original messages if the LLM produces no summary.
        """
        compact_request: dict[str, Any] = {
            "role": "user",
            "content": READER_COMPACT_PROMPT,
        }

        # Single LLM call — no tools allowed during compaction.
        _stop, _tool_calls, summary_messages = self.provider.complete(
            messages=messages + [compact_request],
            system=READER_SYSTEM_PROMPT,
            model=self.model,
            max_tokens=2048,
            tools=[],
        )

        # Extract the last assistant message text (handles both wire formats).
        summary_text = _extract_last_assistant_text(summary_messages)
        if not summary_text:
            log_fn("  [compact] Warning: compaction produced no summary, skipping")
            return messages

        # Build continuation cue pointing at uncovered ranges.
        cursor = ctx.get("doc_cursor")
        if cursor is not None:
            gaps = [
                (s, e)
                for s, e in cursor.get_uncovered_ranges()
                if (e - s) > cfg.min_uncovered_chars
            ]
            if gaps:
                gap_desc = ", ".join(f"chars {s}–{e}" for s, e in gaps[:5])
                continuation = (
                    f"摘要已记录。请继续读取尚未覆盖的区间：{gap_desc}。"
                    f"记录所有发现的知识点。"
                )
            else:
                continuation = "摘要已记录。文档已基本覆盖，如有遗漏请继续读取。"
        else:
            continuation = "摘要已记录。请继续读取文档剩余部分，记录所有知识点。"

        # Replace full history: original prompt + summary + continuation cue.
        new_messages = [
            messages[0],
            {"role": "assistant", "content": summary_text},
            {"role": "user", "content": continuation},
        ]

        log_fn(
            f"  [compact] History compacted: {len(messages)} → 3 messages "
            f"({km.reading_passes} pass(es), {len(km.knowledge_points)} KPs preserved)"
        )
        return new_messages

    def _run_pass(
        self,
        messages: list[Any],
        tools: list[Any],
        handlers: dict[str, Any],
        ctx: dict[str, Any],
        cfg: ReaderConfig,
        forced_coverage_triggered: bool,
    ) -> tuple[list[Any], bool]:
        """Execute one reading pass, then inject forced-coverage if gaps remain.

        US2: after the LLM stops, detects uncovered gaps > cfg.min_uncovered_chars
             and injects a targeted forced-read prompt in the SAME context,
             then runs one more sub-pass so the LLM can fill the gaps.

        Returns:
            (updated messages, forced_coverage_triggered)
        """
        for _ in range(MAX_READER_ITERATIONS):
            stop, tool_calls, messages = self.provider.complete(
                messages=messages,
                system=READER_SYSTEM_PROMPT,
                model=self.model,
                max_tokens=4096,
                tools=tools,
            )

            if stop or not tool_calls:
                break

            results: list[tuple[str, str]] = []
            for tc in tool_calls:
                handler = handlers.get(tc.name)
                if handler is None:
                    result: dict[str, Any] = {"error": f"unknown tool: {tc.name}"}
                else:
                    result = handler(ctx, tc.input)
                results.append((tc.id, json.dumps(result)))

            messages = self.provider.append_tool_results(messages, results)

        # US2: forced-coverage injection in the SAME context.
        cursor = ctx.get("doc_cursor")
        if cursor is not None:
            gaps = [
                (s, e)
                for s, e in cursor.get_uncovered_ranges()
                if (e - s) > cfg.min_uncovered_chars
            ]
            if gaps:
                forced_coverage_triggered = True
                gap_desc = ", ".join(
                    f"chars {s}–{e}" for s, e in gaps[:5]
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"[COVERAGE GAP] The following sections have not been read yet: "
                            f"{gap_desc}. "
                            f"Please read each of these sections now using read_document_range "
                            f"and record any knowledge points you find."
                        ),
                    }
                )
                # One sub-pass in the same context to fill the gaps.
                for _ in range(MAX_READER_ITERATIONS):
                    stop, tool_calls, messages = self.provider.complete(
                        messages=messages,
                        system=READER_SYSTEM_PROMPT,
                        model=self.model,
                        max_tokens=4096,
                        tools=tools,
                    )
                    if stop or not tool_calls:
                        break
                    results = []
                    for tc in tool_calls:
                        handler = handlers.get(tc.name)
                        if handler is None:
                            result = {"error": f"unknown tool: {tc.name}"}
                        else:
                            result = handler(ctx, tc.input)
                        results.append((tc.id, json.dumps(result)))
                    messages = self.provider.append_tool_results(messages, results)

        return messages, forced_coverage_triggered
