"""ExtractorAgent — Phase 2 of the three-phase import pipeline.

One ExtractorAgent instance runs per KnowledgePoint, starting from a fresh,
isolated LLM message context (forked agent pattern). It reads only the section
of the source document corresponding to its assigned KnowledgePoint and produces
a draft KB entry in Markdown with YAML frontmatter.

Context isolation guarantee (C-003):
- `messages` starts as [] for every ExtractorAgent invocation.
- Tool results from one KP extraction never appear in another KP's messages.
"""

from __future__ import annotations

import json
from typing import Any

from holmes.kb.agent.doc_access import DOC_ACCESS_TOOL_DEFINITIONS, DOC_ACCESS_TOOL_HANDLERS
from holmes.kb.agent.knowledge_map import KnowledgeMap, KnowledgePoint
from holmes.kb.agent.provider.base import LLMProvider

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXTRACTOR_SYSTEM_PROMPT = """\
You are the Extractor phase of a multi-phase KB import pipeline.

You are given one specific knowledge point to extract from the source document.
Your task: produce a complete, standalone KB entry in Markdown with YAML frontmatter.

IMPORTANT RULES:
- Use read_document_range to read ONLY the section assigned to this knowledge point
  (the section_start and section_end character offsets are provided in the user message).
- Do NOT read sections outside your assigned range — other knowledge points will be
  processed separately.
- Write ALL field content in the same language as the source text.
- Only include content that has direct support in the source section.
- All commands in the ## Resolution section MUST be copied verbatim character-for-character
  from the source text. Do NOT paraphrase, reorder, summarize, or reconstruct commands.
  If you cannot find the exact commands in your assigned section, write only the commands
  that appear word-for-word in the source, and omit the rest.
- The entry MUST follow this structure:

```
---
id: <generate a unique slug>
type: <pitfall|model|guideline|process|decision>
category: <database|network|application|system|kubernetes|messaging|cache|monitoring>
title: <concise title>
tags: [<tag1>, <tag2>]  # complete noun phrases only; no sentence fragments
language: <zh|en>
---

## Symptoms

<symptoms or problem description>

## Root Cause

<root cause analysis>

## Resolution

<step-by-step resolution. Include all actionable steps: prose instructions, shell
commands in code blocks, verification steps, and any manual intervention points.
This section becomes the agent instruction body for the associated skill.>
```

- For pitfall entries: Symptoms, Root Cause, and Resolution sections are mandatory.
- When finished, output ONLY the completed entry Markdown — no extra commentary.

CRITICAL FOR ## Resolution:
- Reproduce resolution steps faithfully from the source. This content will be read
  by an AI agent as instructions — preserve the full actionable detail.
- If the source contains shell commands, copy them VERBATIM including all flags,
  arguments, and syntax. Do NOT paraphrase or summarize commands.
- Multi-line commands using backslash continuation (lines ending with \\) MUST be
  copied as a complete unit including every continuation line.
- Code blocks (```bash ... ```) should contain executable commands. Non-command
  explanatory text belongs outside code blocks as prose.
- Preserve markdown blockquote formatting (> ...) in Resolution content. Manual
  intervention points, warnings, and human decision checkpoints marked with > in
  the source MUST retain their > prefix in the output. Do NOT strip blockquote markers.

CRITICAL FOR tags:
- Each tag MUST be a complete, independent word or noun phrase (e.g. "连接池耗尽",
  "raft-log-lag", "minAvailable配置错误").
- Do NOT use sentence fragments, verb phrases, or mid-sentence excerpts as tags
  (e.g. "等于副本数导致" is WRONG — it is a fragment, not a noun phrase).
- Chinese tags must be noun phrases. English tags must be kebab-case terms or acronyms.
"""

MAX_EXTRACTOR_ITERATIONS = 20  # tool-call iterations per extraction (safety cap)


class ExtractorAgent:
    """Phase 2 agent: extracts one KB entry draft from a single KnowledgePoint.

    Each call to `run()` starts with an empty messages list — this ensures that
    tool results, context, and content from one KP never contaminate another.

    Args:
        provider: LLMProvider instance.
        model: Model identifier string.
    """

    def __init__(self, provider: LLMProvider, model: str) -> None:
        self.provider = provider
        self.model = model

    def run(
        self,
        kp: KnowledgePoint,
        knowledge_map: KnowledgeMap,
        ctx: dict[str, Any],
    ) -> str:
        """Extract a single KB entry draft for the given KnowledgePoint.

        Args:
            kp: The KnowledgePoint to extract (character offsets, type hint, etc.).
            knowledge_map: The full KnowledgeMap (used for context about other KPs,
                           but the LLM is instructed not to read outside kp's range).
            ctx: Shared pipeline context with "source_text" set to the full document.

        Returns:
            Draft KB entry as a Markdown string with YAML frontmatter.
            Returns empty string if extraction fails.
        """
        # Fresh isolated message context — CRITICAL for context isolation (C-003).
        messages: list[Any] = [
            {
                "role": "user",
                "content": (
                    f"Extract the KB entry for this knowledge point:\n\n"
                    f"ID: {kp.id}\n"
                    f"Description: {kp.description}\n"
                    f"Type hint: {kp.type_hint}\n"
                    f"Category hint: {kp.category_hint or '(detect from content)'}\n"
                    f"Language: {kp.language}\n"
                    f"Section: characters {kp.section_start} to {kp.section_end}\n\n"
                    f"Use read_document_range(start_char={kp.section_start}, "
                    f"end_char={kp.section_end}) to read your assigned section, "
                    f"then produce the KB entry."
                ),
            }
        ]

        # Each Extractor gets its own fresh tool-use loop.
        for _ in range(MAX_EXTRACTOR_ITERATIONS):
            stop, tool_calls, messages = self.provider.complete(
                messages=messages,
                system=EXTRACTOR_SYSTEM_PROMPT,
                model=self.model,
                max_tokens=4096,
                tools=DOC_ACCESS_TOOL_DEFINITIONS,
            )

            if stop or not tool_calls:
                break

            results: list[tuple[str, str]] = []
            for tc in tool_calls:
                handler = DOC_ACCESS_TOOL_HANDLERS.get(tc.name)
                if handler is None:
                    result: dict[str, Any] = {"error": f"unknown tool: {tc.name}"}
                else:
                    result = handler(ctx, tc.input)
                results.append((tc.id, json.dumps(result)))

            messages = self.provider.append_tool_results(messages, results)

        # Extract the final text from the last assistant message.
        return self._extract_draft(messages)

    @staticmethod
    def _extract_draft(messages: list[Any]) -> str:
        """Return the content of the last assistant message in the conversation."""
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content.strip()
                # Handle list content (Anthropic format: list of content blocks)
                if isinstance(content, list):
                    texts = [
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    ]
                    return "\n".join(t for t in texts if t).strip()
        return ""

    @staticmethod
    def _validate_and_repair_draft(draft: str) -> tuple[str, str | None]:
        """Validate and attempt to repair a draft's YAML frontmatter.

        Handles three common LLM output defects:
        1. Prose preamble before the opening '---' (e.g. "Here is the entry:\n---")
        2. Missing closing '---' after the YAML block
        3. Unparseable YAML content

        Returns:
            (repaired_draft, None)     — draft is valid (possibly repaired with warning=None)
            (repaired_draft, warning)  — draft was repaired; warning describes what was fixed
            ("", error_message)        — draft is unrecoverable; caller should skip this KP
        """
        import frontmatter as _fm

        if not draft:
            return "", "empty draft"

        # Step 1: Strip prose preamble before the first '---'.
        first_delim = draft.find("---")
        if first_delim == -1:
            return "", "no YAML frontmatter delimiter '---' found in draft"
        if first_delim > 0:
            warning = f"stripped {first_delim} chars of prose preamble before frontmatter"
            draft = draft[first_delim:]
        else:
            warning = None

        # Step 2: Ensure there is a closing '---' after the opening delimiter.
        # The structure must be: ---\n<yaml>\n---\n<body>
        # Find the second occurrence of '---' (after the opening one).
        after_open = draft[3:]  # skip opening '---'
        second_delim = after_open.find("---")
        if second_delim == -1:
            # No closing delimiter — insert it at the YAML/body boundary.
            # The boundary is the first blank line (\n\n) or the first Markdown heading (\n#).
            import re as _re
            boundary = _re.search(r'\n\n|\n#', after_open)
            if boundary:
                insert_at = boundary.start()
                after_open = after_open[:insert_at] + "\n---" + after_open[insert_at:]
            else:
                after_open = after_open.rstrip() + "\n---\n"
            draft = "---" + after_open
            repair_note = "inserted missing closing '---'"
            warning = f"{warning}; {repair_note}" if warning else repair_note

        # Step 3: Validate that frontmatter.loads() can parse it.
        try:
            _fm.loads(draft)
        except Exception as exc:  # noqa: BLE001
            return "", f"YAML parse error after repair attempt: {exc}"

        return draft, warning
