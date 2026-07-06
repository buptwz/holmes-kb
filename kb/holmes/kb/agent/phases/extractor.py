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
from holmes.kb.progress import NullReporter, ProgressReporter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXTRACTOR_SYSTEM_PROMPT = """\
## Role

You are the Extractor phase of a multi-phase KB import pipeline. Your sole job is to
produce one complete, standalone KB entry in Markdown with YAML frontmatter from the
source section assigned to you.

## Task

1. Call read_document_range(start_char=<section_start>, end_char=<section_end>) to read
   your assigned section.
2. Choose the correct KB type from: pitfall | model | guideline | process | decision.
3. Use the TYPE-SECTION TABLE below to determine which sections to write — use ONLY
   those sections, no others.
4. Output the completed entry Markdown. Output NOTHING else — no preamble, no commentary.

## TYPE-SECTION TABLE (authoritative — follow exactly)

| type      | required sections (in order)                        |
|-----------|-----------------------------------------------------|
| pitfall   | ## Symptoms · ## Root Cause · ## Resolution         |
| model     | ## Overview · ## Key Concepts · ## Usage            |
| guideline | ## Context · ## Guideline · ## Rationale            |
| process   | ## Purpose · ## Steps · ## Outcome                  |
| decision  | ## Context · ## Decision · ## Rationale             |

## Constraints

**Source fidelity**
- DO include only content that has direct support in your assigned source section.
- DO NOT invent, infer, or extrapolate any field value not present in the source.
- DO write all field content (title, tags, body sections) in the same language as
  the source text. DO NOT translate.

**Section discipline**
- DO NOT mix sections across types (e.g. a `decision` entry MUST NOT contain
  ## Symptoms, ## Root Cause, or ## Resolution).
- DO NOT add sections not listed in the TYPE-SECTION TABLE for your chosen type.
- DO NOT read outside your assigned character range.

**Verbatim fidelity (applies to ALL sections, ALL types)**
- The following content MUST be copied character-for-character from the source. DO NOT
  paraphrase, translate, abbreviate, or omit any of these:
  - Shell commands (including all flags, arguments, pipes, backslash continuations)
  - API endpoint paths (e.g. `/v1/health/summary`, `POST /api/diagnostic`)
  - URLs, IP addresses, port numbers
  - Configuration parameter names and values (e.g. `max_connections=100`)
  - Error codes, status codes (e.g. `E01`, `HTTP 503`)
  - File paths (e.g. `/etc/config.yaml`)
- DO put executable commands inside ```bash … ``` blocks. Non-command prose goes outside.
- DO preserve blockquote markers (> …) for warnings and manual-intervention checkpoints.
- DO NOT omit any actionable step present in the source.

**Tags**
- DO use complete, independent noun phrases (e.g. "连接池耗尽", "raft-log-lag").
- DO NOT use sentence fragments, verb phrases, or mid-sentence excerpts.
- Chinese tags must be noun phrases; English tags must be kebab-case terms or acronyms.

## Output Format

Output ONLY the entry Markdown. Structure:

```
---
id: <unique slug>
type: <pitfall|model|guideline|process|decision>
category: <infer from document content, e.g. hardware/gpu, network/switch, database — use / for hierarchy>
title: <concise title>
tags: [<tag1>, <tag2>]
language: <zh|en>
---

<sections for the chosen type — see TYPE-SECTION TABLE>
```

### Examples (one per type — follow this exact structure)

pitfall: `---\nid: X\ntype: pitfall\ncategory: database\ntitle: T\ntags: [t]\nlanguage: en\n---\n## Symptoms\n…\n## Root Cause\n…\n## Resolution\n…`

model: `---\nid: X\ntype: model\ncategory: network\ntitle: T\ntags: [t]\nlanguage: en\n---\n## Overview\n…\n## Key Concepts\n…\n## Usage\n…`

guideline: `---\nid: X\ntype: guideline\ncategory: application\ntitle: T\ntags: [t]\nlanguage: en\n---\n## Context\n…\n## Guideline\n…\n## Rationale\n…`

process: `---\nid: X\ntype: process\ncategory: system\ntitle: T\ntags: [t]\nlanguage: en\n---\n## Purpose\n…\n## Steps\n…\n## Outcome\n…`

decision: `---\nid: X\ntype: decision\ncategory: database\ntitle: T\ntags: [t]\nlanguage: en\n---\n## Context\n…\n## Decision\n…\n## Rationale\n…`
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

    def __init__(self, provider: LLMProvider, model: str, reporter: ProgressReporter | None = None) -> None:
        self.provider = provider
        self.model = model
        self.reporter: ProgressReporter = reporter or NullReporter()

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
        # 039: Sibling brief injection — give Extractor awareness of other KPs
        # for terminology consistency, without leaking content.
        sibling_note = ""
        if len(knowledge_map.knowledge_points) > 1:
            siblings = "\n".join(
                f"  - {skp.id}: [{skp.type_hint}] {skp.description}"
                for skp in knowledge_map.knowledge_points
                if skp.id != kp.id
            )
            sibling_note = (
                f"\n\nOther knowledge points in this document "
                f"(for terminology consistency only — do NOT include their content):\n"
                f"{siblings}"
            )

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
                    f"{sibling_note}"
                ),
            }
        ]

        # Each Extractor gets its own fresh tool-use loop.
        _kp_label = str(kp.id)[:30]
        for _turn in range(MAX_EXTRACTOR_ITERATIONS):
            stop, tool_calls, messages, _ = self.provider.complete(
                messages=messages,
                system=EXTRACTOR_SYSTEM_PROMPT,
                model=self.model,
                max_tokens=4096,
                tools=DOC_ACCESS_TOOL_DEFINITIONS,
            )

            if stop or not tool_calls:
                break

            _tools_str = ",".join(tc.name for tc in tool_calls)
            self.reporter.info(f"Extractor({_kp_label}) turn {_turn + 1} [{_tools_str}]")

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
