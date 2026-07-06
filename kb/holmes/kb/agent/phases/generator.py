"""GeneratorAgent — Phase 3: format confirmed KP summaries into KB entries.

Runs after Review. Takes KnowledgePoints with confirmed structured summaries
(key_facts, commands) and formats them into KB entry Markdown with YAML frontmatter.

Key design difference from the old ExtractorAgent:
  - Extractor: read source + understand + format → one-shot, lossy
  - Generator: summary (confirmed input) + source (reference) → format only

The Generator does NOT decide what to include — that was decided by Summarizer
and confirmed by the user. The Generator only decides HOW to present it.
All key_facts must appear in the output. All commands must appear verbatim.
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

MAX_GENERATOR_ITERATIONS = 15  # tool-call iterations per generation (safety cap)

GENERATOR_SYSTEM_PROMPT = """\
## Role

You are the Generator phase of a knowledge base import pipeline. Your job is to
format a pre-extracted knowledge summary into a complete KB entry in Markdown
with YAML frontmatter.

## Input

You receive a structured summary containing:
- **description**: what this knowledge point is about
- **type**: the KB entry type (pitfall/model/guideline/process/decision)
- **key_facts**: all important facts — EVERY fact MUST appear in your output
- **commands**: all commands/code — EVERY command MUST appear verbatim in your output
- **source section**: you can read the original source for additional context

## Task

1. Optionally call read_document_range to check the original source for context.
2. Format ALL key_facts and commands into the correct KB entry structure.
3. Output the completed entry Markdown. Output NOTHING else.

## Mandatory Inclusion Rules

- EVERY item in key_facts MUST be reflected in the output body sections.
- EVERY item in commands MUST appear character-for-character in a code block or
  inline code in the output. DO NOT paraphrase, abbreviate, or omit any command.
- If a command is executable, put it in a ```bash block.
- If a command is a config snippet, use the appropriate language block.

## TYPE-SECTION TABLE (follow exactly)

| type      | required sections (in order)                        |
|-----------|-----------------------------------------------------|
| pitfall   | ## Symptoms · ## Root Cause · ## Resolution         |
| model     | ## Overview · ## Key Concepts · ## Usage            |
| guideline | ## Context · ## Guideline · ## Rationale            |
| process   | ## Purpose · ## Steps · ## Outcome                  |
| decision  | ## Context · ## Decision · ## Rationale             |

## Constraints

- DO NOT add sections not listed in the TYPE-SECTION TABLE for your chosen type.
- DO write all content in the same language as the source (check the language field).
- DO use complete, independent noun phrases for tags.
- DO NOT invent information not present in key_facts, commands, or the source section.

## Output Format

```
---
id: <unique slug>
type: <type>
category: <category>
title: <concise title>
tags: [<tag1>, <tag2>]
language: <lang>
---

<sections for the chosen type>
```
"""


class GeneratorAgent:
    """Phase 3: format confirmed KP summaries into KB entries.

    Each call to ``run_one()`` starts with a fresh message context containing
    the full KP summary as structured input. The LLM's job is formatting only.

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

    def run_one(
        self,
        kp: KnowledgePoint,
        knowledge_map: KnowledgeMap,
        ctx: dict[str, Any],
    ) -> str:
        """Generate a KB entry Markdown draft from a confirmed KP summary.

        Args:
            kp: KnowledgePoint with summarized=True (key_facts, commands populated).
            knowledge_map: Full KnowledgeMap (for sibling context).
            ctx: Shared pipeline context with "source_text".

        Returns:
            Draft KB entry as Markdown string. Empty string on failure.
        """
        # Build the structured summary input for the LLM.
        summary_block = self._build_summary_input(kp)

        messages: list[Any] = [
            {
                "role": "user",
                "content": (
                    f"Generate a KB entry from this confirmed summary:\n\n"
                    f"{summary_block}\n\n"
                    f"Source section: characters {kp.section_start} to {kp.section_end}. "
                    f"You may call read_document_range(start_char={kp.section_start}, "
                    f"end_char={kp.section_end}) to check the original source for context, "
                    f"but ALL key_facts and commands above are mandatory — do not omit any."
                ),
            }
        ]

        _kp_label = str(kp.id)[:30]
        for _turn in range(MAX_GENERATOR_ITERATIONS):
            stop, tool_calls, messages, _ = self.provider.complete(
                messages=messages,
                system=GENERATOR_SYSTEM_PROMPT,
                model=self.model,
                max_tokens=4096,
                tools=DOC_ACCESS_TOOL_DEFINITIONS,
            )

            if stop or not tool_calls:
                break

            _tools_str = ",".join(tc.name for tc in tool_calls)
            self.reporter.info(f"Generator({_kp_label}) turn {_turn + 1} [{_tools_str}]")

            results: list[tuple[str, str]] = []
            for tc in tool_calls:
                handler = DOC_ACCESS_TOOL_HANDLERS.get(tc.name)
                if handler is None:
                    result: dict[str, Any] = {"error": f"unknown tool: {tc.name}"}
                else:
                    result = handler(ctx, tc.input)
                results.append((tc.id, json.dumps(result)))

            messages = self.provider.append_tool_results(messages, results)

        return self._extract_draft(messages)

    def run_one_with_feedback(
        self,
        kp: KnowledgePoint,
        knowledge_map: KnowledgeMap,
        ctx: dict[str, Any],
        previous_draft: str,
        feedback: str,
    ) -> str:
        """Re-generate a KB entry with specific fidelity feedback.

        Takes the previous draft and a description of what's missing,
        asks the LLM to fix it.

        Args:
            kp: The KnowledgePoint.
            knowledge_map: Full KnowledgeMap.
            ctx: Shared pipeline context.
            previous_draft: The draft that failed fidelity check.
            feedback: Human-readable description of what's missing.

        Returns:
            Corrected draft, or empty string on failure.
        """
        summary_block = self._build_summary_input(kp)

        messages: list[Any] = [
            {
                "role": "user",
                "content": (
                    f"Your previous draft for {kp.id} had fidelity issues:\n"
                    f"  {feedback}\n\n"
                    f"Here is the original summary (ALL items are mandatory):\n\n"
                    f"{summary_block}\n\n"
                    f"Here is your previous draft:\n\n"
                    f"{previous_draft}\n\n"
                    f"Fix the issues above. You may call read_document_range("
                    f"start_char={kp.section_start}, end_char={kp.section_end}) "
                    f"to re-check the source. Output ONLY the corrected entry Markdown."
                ),
            }
        ]

        _kp_label = str(kp.id)[:30]
        for _turn in range(MAX_GENERATOR_ITERATIONS):
            stop, tool_calls, messages, _ = self.provider.complete(
                messages=messages,
                system=GENERATOR_SYSTEM_PROMPT,
                model=self.model,
                max_tokens=4096,
                tools=DOC_ACCESS_TOOL_DEFINITIONS,
            )

            if stop or not tool_calls:
                break

            _tools_str = ",".join(tc.name for tc in tool_calls)
            self.reporter.info(f"Generator({_kp_label}) retry turn {_turn + 1} [{_tools_str}]")

            results: list[tuple[str, str]] = []
            for tc in tool_calls:
                handler = DOC_ACCESS_TOOL_HANDLERS.get(tc.name)
                if handler is None:
                    result: dict[str, Any] = {"error": f"unknown tool: {tc.name}"}
                else:
                    result = handler(ctx, tc.input)
                results.append((tc.id, json.dumps(result)))

            messages = self.provider.append_tool_results(messages, results)

        return self._extract_draft(messages)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary_input(kp: KnowledgePoint) -> str:
        """Build the structured summary block that the LLM receives."""
        lines = [
            f"ID: {kp.id}",
            f"Type: {kp.type_hint}",
            f"Category: {kp.category_hint or '(detect from content)'}",
            f"Language: {kp.language}",
            f"Description: {kp.description}",
            "",
            f"Key Facts ({len(kp.key_facts)} items — ALL must appear in output):",
        ]
        for i, fact in enumerate(kp.key_facts, 1):
            lines.append(f"  {i}. {fact}")

        lines.append("")
        lines.append(f"Commands/Code ({len(kp.commands)} items — ALL must appear verbatim):")
        if kp.commands:
            for i, cmd in enumerate(kp.commands, 1):
                lines.append(f"  {i}. {cmd}")
        else:
            lines.append("  (none)")

        if kp.related_kps:
            lines.append("")
            lines.append("Related KPs:")
            for rel in kp.related_kps:
                lines.append(f"  - {rel}")

        return "\n".join(lines)

    @staticmethod
    def _extract_draft(messages: list[Any]) -> str:
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
