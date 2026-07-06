"""SummarizerAgent — Phase 1.5: enrich KnowledgePoints with structured summaries.

Runs after Reader (which identifies KP boundaries) and before Review/Generator.
For each KnowledgePoint, makes one focused LLM call to extract:
  - key_facts: all important factual statements
  - commands: all commands, code snippets, config fragments (verbatim)
  - related_kps: relationships to other KPs in the same document

The prompt is focused solely on "extract everything, miss nothing" — no formatting,
no KB structure, no type-section table. This separation of concerns is the key
architectural difference from the old Extractor which tried to do extraction +
formatting in one shot.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from holmes.kb.agent.doc_access import DOC_ACCESS_TOOL_DEFINITIONS, DOC_ACCESS_TOOL_HANDLERS
from holmes.kb.agent.knowledge_map import KnowledgeMap, KnowledgePoint
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.progress import NullReporter, ProgressReporter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SUMMARIZER_ITERATIONS = 10  # tool-call iterations per KP (safety cap)

SUMMARIZER_SYSTEM_PROMPT = """\
## Role

You are the Summarizer phase of a knowledge extraction pipeline. Your sole job is to
deeply read a source section and extract ALL important information into a structured
JSON summary. You do NOT format anything — you only extract.

## Task

1. Call read_document_range(start_char=<start>, end_char=<end>) to read your assigned section.
2. Extract every piece of important information into the JSON format below.
3. Output ONLY the JSON object — no markdown, no commentary, no preamble.

## Extraction Rules

**key_facts** — every important factual statement in the section:
- Technical facts (versions, requirements, limitations, behaviors)
- Cause-effect relationships ("X happens because Y")
- Conditions and prerequisites ("requires X", "only when Y")
- Quantitative data (thresholds, sizes, counts, timeouts)
- DO NOT summarize or merge facts — one fact per item
- DO NOT omit facts you consider "minor" — extract everything
- Write each fact as a complete, standalone sentence

**commands** — every command, code snippet, config fragment, API call:
- Copy character-for-character from the source. DO NOT paraphrase or abbreviate.
- Include the full command with all flags, arguments, pipes, continuations
- Include config snippets, API endpoints, file paths, URLs
- Include inline code references (variable names, function names, parameter values)
- If the source has no commands/code, return an empty list

**related_kps** — IDs of other knowledge points that are related:
- Only reference KP IDs provided in the sibling list
- Types of relationships: prerequisite, follow-up, alternative, complement
- Format each as: "<kp_id>:<relationship>" (e.g. "kp-3:prerequisite")
- If no clear relationships exist, return an empty list

## Output Format

```json
{
  "key_facts": ["fact 1", "fact 2", ...],
  "commands": ["command 1", "code snippet 2", ...],
  "related_kps": ["kp-N:relationship", ...]
}
```
"""


def _try_json_parse(text: str) -> Optional[dict[str, Any]]:
    """Try to parse text as a JSON dict. Returns None on failure."""
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _normalize_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure key_facts, commands, related_kps are lists of strings."""
    for key in ("key_facts", "commands", "related_kps"):
        val = data.get(key)
        if val is None:
            data[key] = []
        elif not isinstance(val, list):
            data[key] = [str(val)]
        else:
            data[key] = [str(item) for item in val]
    return data


class SummarizerAgent:
    """Phase 1.5: enrich each KnowledgePoint with a structured summary.

    Each call to ``run_one()`` starts with an empty message context — isolated
    per KP, same as the old ExtractorAgent pattern.

    Args:
        provider: LLMProvider instance.
        model: Model identifier string.
        reporter: Progress reporter for user-facing output.
    """

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        reporter: Optional[ProgressReporter] = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.reporter: ProgressReporter = reporter or NullReporter()

    def run(
        self,
        knowledge_map: KnowledgeMap,
        ctx: dict[str, Any],
    ) -> KnowledgeMap:
        """Enrich all unsummarized KPs in the knowledge map.

        Modifies KPs in-place (sets key_facts, commands, related_kps, summarized).

        Args:
            knowledge_map: The KnowledgeMap with KPs identified by Reader.
            ctx: Shared pipeline context with "source_text".

        Returns:
            The same KnowledgeMap, with KPs enriched.
        """
        pending = [kp for kp in knowledge_map.knowledge_points if not kp.summarized]
        total = len(pending)
        if total == 0:
            return knowledge_map

        for idx, kp in enumerate(pending):
            self.reporter.step(idx + 1, total, f"Summarize: {kp.description[:50]}")
            self.run_one(kp, knowledge_map, ctx)

        done_count = sum(1 for kp in pending if kp.summarized)
        self.reporter.done(
            f"Summarizer: {done_count}/{total} 个知识点摘要完成"
        )
        return knowledge_map

    def run_one(
        self,
        kp: KnowledgePoint,
        knowledge_map: KnowledgeMap,
        ctx: dict[str, Any],
    ) -> None:
        """Extract structured summary for a single KnowledgePoint.

        Modifies kp in-place.
        """
        # Build sibling context for relationship detection.
        sibling_lines = ""
        if len(knowledge_map.knowledge_points) > 1:
            siblings = "\n".join(
                f"  - {skp.id}: [{skp.type_hint}] {skp.description}"
                for skp in knowledge_map.knowledge_points
                if skp.id != kp.id
            )
            sibling_lines = f"\n\nOther knowledge points in this document:\n{siblings}"

        # Fresh isolated message context.
        messages: list[Any] = [
            {
                "role": "user",
                "content": (
                    f"Extract a complete summary for this knowledge point:\n\n"
                    f"ID: {kp.id}\n"
                    f"Description: {kp.description}\n"
                    f"Type: {kp.type_hint}\n"
                    f"Section: characters {kp.section_start} to {kp.section_end}\n\n"
                    f"Use read_document_range(start_char={kp.section_start}, "
                    f"end_char={kp.section_end}) to read the section, then output "
                    f"the JSON summary."
                    f"{sibling_lines}"
                ),
            }
        ]

        # Tool-use loop.
        _kp_label = str(kp.id)[:30]
        for _turn in range(MAX_SUMMARIZER_ITERATIONS):
            stop, tool_calls, messages, _ = self.provider.complete(
                messages=messages,
                system=SUMMARIZER_SYSTEM_PROMPT,
                model=self.model,
                max_tokens=4096,
                tools=DOC_ACCESS_TOOL_DEFINITIONS,
            )

            if stop or not tool_calls:
                break

            _tools_str = ",".join(tc.name for tc in tool_calls)
            self.reporter.info(f"Summarizer({_kp_label}) turn {_turn + 1} [{_tools_str}]")

            results: list[tuple[str, str]] = []
            for tc in tool_calls:
                handler = DOC_ACCESS_TOOL_HANDLERS.get(tc.name)
                if handler is None:
                    result: dict[str, Any] = {"error": f"unknown tool: {tc.name}"}
                else:
                    result = handler(ctx, tc.input)
                results.append((tc.id, json.dumps(result)))

            messages = self.provider.append_tool_results(messages, results)

        # If the loop exhausted all turns without text output, nudge the LLM
        # to emit the JSON summary in one final call (no tools).
        raw = self._extract_text(messages)
        if not raw:
            self.reporter.info(f"Summarizer({_kp_label}): 催促输出 JSON...")
            messages.append({
                "role": "user",
                "content": (
                    "You have read enough. Now output the JSON summary immediately. "
                    "Output ONLY the JSON object, nothing else."
                ),
            })
            _, _, messages, _ = self.provider.complete(
                messages=messages,
                system=SUMMARIZER_SYSTEM_PROMPT,
                model=self.model,
                max_tokens=4096,
                tools=[],  # No tools — force text output.
            )
            raw = self._extract_text(messages)
        parsed = self._parse_summary(raw)
        if parsed is not None:
            kp.key_facts = parsed.get("key_facts", [])
            kp.commands = parsed.get("commands", [])
            kp.related_kps = parsed.get("related_kps", [])
            kp.summarized = True
        else:
            # Log first 200 chars of raw output for debugging.
            _preview = raw[:200].replace("\n", "\\n") if raw else "(empty)"
            self.reporter.warn(
                f"Summarizer({_kp_label}): JSON 解析失败，跳过摘要 | raw: {_preview}"
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(messages: list[Any]) -> str:
        """Return the text content of the last assistant message."""
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content.strip()
                if isinstance(content, list):
                    texts = [
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    ]
                    return "\n".join(t for t in texts if t).strip()
        return ""

    @staticmethod
    def _parse_summary(raw: str) -> Optional[dict[str, Any]]:
        """Parse the JSON summary from raw LLM output.

        Handles multiple LLM output formats:
        1. Raw JSON object
        2. JSON wrapped in ```json ... ``` code fences
        3. Prose preamble followed by JSON or code-fenced JSON
        4. JSON embedded anywhere in the text (fallback: find first { to last })

        Returns None on parse failure.
        """
        if not raw:
            return None

        text = raw.strip()

        # Strategy 1: Direct JSON parse.
        data = _try_json_parse(text)
        if data is not None:
            return _normalize_summary(data)

        # Strategy 2: Strip markdown code fences (```json ... ```).
        import re
        fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if fence_match:
            data = _try_json_parse(fence_match.group(1).strip())
            if data is not None:
                return _normalize_summary(data)

        # Strategy 3: Find the first { ... } block (greedy from first { to last }).
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            data = _try_json_parse(text[first_brace:last_brace + 1])
            if data is not None:
                return _normalize_summary(data)

        return None
