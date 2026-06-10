"""ReaderAgent — Phase 1 of the three-phase import pipeline.

The ReaderAgent reads the source document via doc_access tools and produces
a KnowledgeMap that indexes all knowledge points and their character offsets.
It runs in a fresh, isolated LLM message context (forked agent pattern).

Key design decisions (R-001 through R-008):
- DocumentCursor tracks coverage; all doc reading goes through tools.
- Diminishing returns detection: stop when DIMINISHING_WINDOW consecutive
  reading passes each produce 0 new KnowledgePoints.
- Coverage threshold: aim for >= COVERAGE_THRESHOLD % before stopping.
"""

from __future__ import annotations

import json
from typing import Any

from holmes.kb.agent.doc_access import DOC_ACCESS_TOOL_DEFINITIONS, DOC_ACCESS_TOOL_HANDLERS
from holmes.kb.agent.knowledge_map import KnowledgeMap, KnowledgePoint
from holmes.kb.agent.provider.base import LLMProvider

# ---------------------------------------------------------------------------
# Constants (C-001 contract: all thresholds as named constants)
# ---------------------------------------------------------------------------

COVERAGE_THRESHOLD = 95.0
DIMINISHING_WINDOW = 2
MAX_READER_ITERATIONS = 30  # tool-call iterations per reading pass (safety cap)

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
# ReaderAgent
# ---------------------------------------------------------------------------


class ReaderAgent:
    """Phase 1 agent: reads the source document and produces a KnowledgeMap.

    Runs in a fresh, isolated LLM message context with doc_access tools and
    the record_knowledge_point tool. Terminates when coverage reaches
    COVERAGE_THRESHOLD or diminishing returns are detected.

    Args:
        provider: LLMProvider instance (Anthropic or OpenAI-compatible).
        model: Model identifier string.
    """

    def __init__(self, provider: LLMProvider, model: str) -> None:
        self.provider = provider
        self.model = model

    def run(self, source_text: str, ctx: dict[str, Any]) -> KnowledgeMap:
        """Read the source document and return a KnowledgeMap.

        Args:
            source_text: Full, untruncated source document text.
            ctx: Shared pipeline context dict. Will have "source_text" and
                 "doc_cursor" set after this call.

        Returns:
            KnowledgeMap with all identified knowledge points.
        """
        km = KnowledgeMap()
        ctx["source_text"] = source_text

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

            # Run one reading pass (LLM loop until it stops calling tools).
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

            km.reading_passes += 1
            kps_after = len(km.knowledge_points)

            # Update coverage stats from DocumentCursor.
            cursor = ctx.get("doc_cursor")
            if cursor is not None:
                km.total_chars = cursor.total_chars
                km.chars_read = cursor.chars_read()
            else:
                km.total_chars = len(source_text)

            # Diminishing returns detection (T011).
            new_kps_this_pass = kps_after - kps_before
            if new_kps_this_pass == 0:
                consecutive_zero_passes += 1
            else:
                consecutive_zero_passes = 0

            if consecutive_zero_passes >= DIMINISHING_WINDOW:
                km.diminishing_returns = True
                break

            # Coverage goal reached — stop.
            if km.coverage_pct >= COVERAGE_THRESHOLD:
                break

            # Ask the LLM to continue reading any unread portions.
            coverage = km.coverage_pct
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Coverage so far: {coverage:.1f}%. "
                        f"Continue reading unread sections of the document and "
                        f"record any additional knowledge points you find."
                    ),
                }
            )

        return km
