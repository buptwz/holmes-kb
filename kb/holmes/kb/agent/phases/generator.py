"""GeneratorAgent — format confirmed summary into a single KB entry (042).

Takes the confirmed summary dict (from Summarizer + user review) and generates
a complete KB entry with YAML frontmatter + Markdown body following progressive
disclosure structure.

Key design: Generator does NOT decide what to include — that was decided by
Summarizer and confirmed by user. Generator only decides HOW to present it.
All key_facts must appear. All commands must appear verbatim.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from holmes.kb.agent.compact import (
    GeneratorCompactAdapter,
    ToolLoopCompact,
)
from holmes.kb.agent.doc_access import DOC_ACCESS_TOOL_DEFINITIONS, DOC_ACCESS_TOOL_HANDLERS
from holmes.kb.agent.phases.summarizer import extract_document_outline
from holmes.kb.agent.observability import observe
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.progress import NullReporter, ProgressReporter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_GENERATOR_ITERATIONS = 15  # tool-call iterations (safety cap)

GENERATOR_SYSTEM_PROMPT = """\
You are the Generator in a knowledge base pipeline for NPI hardware engineers. \
You receive a pre-extracted summary and format it into a complete KB entry. You \
decide HOW to present the information — what to include was already decided.

# Golden rules

1. **Every key_fact must appear** in the body sections. Do not drop any.
2. **Every command must appear verbatim** in a code block — character for character. \
   Do not paraphrase, abbreviate, or reformat commands.
3. **Write in the document's language** (check the `Language` field). If the source \
   is Chinese, ALL prose must be Chinese. English technical terms are OK inline.
4. **Output ONLY the Markdown entry** — no preamble like "Here is the entry", \
   no wrapping in ``` fences.

# YAML frontmatter

```yaml
---
id: <kebab-case-slug-from-title>    # e.g., dimm-ecc-error-server-reboot
type: <type>                         # exactly as given in Type field
category: <one-or-two-level-slug>    # e.g., memory, pcie/link-training
title: <concise title ≤60 chars>     # specific, not generic
brief: "<one sentence from Brief>"   # quoted, ≤150 chars
tags: [<tag1>, <tag2>, ...]          # 4-8 lowercase tags, technical terms
language: <lang>                     # exactly as given in Language field
decision_map:                        # ONLY for complex entries (≥3 branches)
  - symptom: "<observable condition>"
    branch: "<branch label>"
  - symptom: "..."
    branch: "..."
---
```

Rules for `decision_map`:
- Include ONLY when HasComplexBranching is true (≥3 resolution branches).
- Each entry maps an observable symptom/condition to a branch label.
- Branch labels must match the ### headings in the Resolution section.
- Omit decision_map entirely for simple entries (≤2 branches).

Rules for frontmatter fields:
- `title`: Specific enough to distinguish from similar entries. Include the component \
  and the failure/topic. Bad: "内存问题". Good: "Samsung DDR5 DIMM ECC 错误累积导致重启".
- `category`: Use lowercase kebab-case. One level ("memory") or two ("pcie/link-training").
- `tags`: Technical terms an engineer would search for. Include component names, \
  protocols, error types. Do NOT include generic words like "troubleshooting" or "issue".
- `brief`: Copy from the summary Brief field. If it exceeds 150 chars, shorten it \
  while preserving the key technical detail.

# ## Contents — rendered from Outline (do NOT invent)

Every KB entry MUST start with a `## Contents` section immediately after the YAML \
frontmatter. **The Contents is derived from the Outline provided in the summary input — \
you MUST NOT add, remove, or rename sections beyond what the Outline specifies.**

### Contents for complex branching pitfall (HasComplexBranching=true)

Copy the Decision Tree from the summary input as the Contents, wrapped in a code block.

Example output:

    ## Contents

    ```
    PCIe link training 失败
    ├─ lspci 完全看不到设备? ─→ [A] 物理连接问题
    └─ 设备可见但 link 降级? ─→ [B] 信号完整性问题
    ```

Copy the decision_tree string from the summary verbatim between the ``` fences.

### Contents for all other types

Render the Outline as a Markdown table:

```markdown
## Contents

| Section | Description |
|---|---|
| <outline[0].section> | <outline[0].description> |
| <outline[1].section> | <outline[1].description> |
| ... | ... |
```

Rules:
- One row per Outline entry, in the same order.
- Use the section name and description EXACTLY as given in the Outline.
- Do NOT add rows for sections not in the Outline.

### Sections in body MUST match Outline

After `## Contents`, generate one `## <section>` heading per Outline entry, \
in the SAME order. The heading text must match `outline[].section` exactly. \
Do NOT add extra ## sections. Do NOT omit any.

# Entry structure by type

## pitfall — problem → root cause → fix

Progressive disclosure layers:
1. Title + brief → engineer judges relevance in 2 seconds
2. Contents → agent sees structure and navigates
3. Symptoms → engineer confirms "this matches what I see"
4. Root Cause → engineer understands WHY this happens
5. Resolution → engineer follows steps to FIX it

Required sections (in order): `## Contents` · `## Symptoms` · `## Root Cause` · \
`## Resolution`

### ## Symptoms
List each observable symptom as a bullet. Include error messages in backticks, \
log patterns, LED states, metric thresholds. Be specific — "服务器重启" is too vague; \
"burn-in 48h 后自动重启，无 kernel panic" is good.

### ## Root Cause
Explain WHY the problem occurs. Include relevant environment details (platform, \
component versions) as context. State the cause-effect chain clearly.

### ## Resolution
If there are multiple resolution_branches, start with a navigation table:

```markdown
| 你看到的现象 | 对应分支 |
|---|---|
| <condition from branch.when> | <branch.label> |
| ... | ... |

### <branch.label>
1. [tag] Step description
   ```bash
   command here
   ```
2. [decide] If condition → action; otherwise → next step
...
```

If only one branch, skip the table and write sequential steps directly.

**Behavior tags** — prefix EVERY step with exactly one tag:
- `[api:read]` — run a READ-ONLY command (lspci, cat, grep, sensor read). Agent can auto-execute.
- `[api:write]` — run a command that MODIFIES state but is recoverable (config change, service restart).
- `[api:danger]` — run a command that is IRREVERSIBLE or can damage hardware (firmware flash, \
  sel clear, disk format). Agent MUST warn and get confirmation before executing.
- `[physical]` — physical action (inspect, reseat, measure with instrument)
- `[decide]` — ask the user which condition they observe, then branch to the next step. \
  Use ONLY when the user needs to report an observation. Example: "查看 LED 状态：绿色 → step 3, 红色 → step 5"
- `[verify]` — check the result of a previous step against expected outcome. \
  Use for conclusions and confirmations. Example: "ECC 错误为 0 → 问题解决; 仍有错误 → 返回第一步"
- `[remote]` — action on a remote system (BMC, switch, management plane)

**Expected output** — for EVERY `[api:*]` step, add an `Expected:` line after the code block \
explaining what the output means. The summary's `commands[].expected` field provides this — \
copy it verbatim. This is critical: the agent uses Expected to interpret command output \
and decide the next action without asking the engineer.

Example:
```
1. [api:read] 查看 SEL 日志中的内存错误：
   ```bash
   ipmitool sel list | grep -i "memory"
   ```
   Expected: 若输出含 Memory ECC Error 且集中在同一 slot → 确认该位置故障；无 memory 相关事件 → 排除内存问题
```

## model — concept explanation for reference

Required sections (in order): `## Contents` · `## Overview` · `## Key Concepts` · \
`## Usage`

- **Overview**: One paragraph explaining what this concept/mechanism is and why it matters.
- **Key Concepts**: Break into ### subsections for each concept. Explain mechanisms, \
  include diagrams/tables where the source has them, include relevant commands.
- **Usage**: How NPI engineers use this knowledge — validation procedures, what to check.

## guideline — rules and best practices

Required sections (in order): `## Contents` · `## Context` · `## Guideline` · \
`## Rationale`

- **Context**: Why this guideline exists, what problem it prevents.
- **Guideline**: The actual rules, organized as numbered items or ### subsections. \
  Each rule should be actionable ("必须...", "不允许...", "should...").
- **Rationale**: Why these specific rules matter, consequences of violation.

## process — step-by-step procedure

Required sections (in order): `## Contents` · `## Purpose` · `## Steps` · \
`## Outcome`

- **Purpose**: What this procedure accomplishes, when to use it, prerequisites.
- **Steps**: Numbered steps with ### subsections for major phases. Each step should \
  include the exact commands to run. Use behavior tags on each step.
- **Outcome**: What the successful result looks like, how to verify, what to do if \
  the procedure fails.

## decision — choice rationale (ADR)

Required sections (in order): `## Contents` · `## Context` · `## Decision` · \
`## Rationale`

- **Context**: The problem or need that required a decision, constraints involved.
- **Decision**: What was chosen, with implementation details and commands.
- **Rationale**: Why this option was chosen over alternatives. Include the alternatives \
  that were considered and why they were rejected.

# Constraints

- Use ONLY the sections listed above for the given type. No extra sections.
- Do NOT invent information not present in key_facts, commands, or the source document.
- Do NOT add a "References" or "See Also" section.
- Place commands in ```bash blocks. Config snippets use the appropriate language tag.
"""


class GeneratorAgent:
    """Format confirmed summary into a single KB entry.

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

    @observe(name="generator")
    def run(
        self,
        summary: dict[str, Any],
        ctx: dict[str, Any],
        suggested_type: str = "pitfall",
        language: str = "en",
        has_complex_branching: bool = False,
    ) -> str:
        """Generate a KB entry from a confirmed summary.

        Args:
            summary: Dict with brief, key_facts, commands, symptoms,
                     resolution_branches.
            ctx: Pipeline context with "source_text".
            suggested_type: KB entry type.
            language: Document language.
            has_complex_branching: If True, generate Contents tree + decision_map.

        Returns:
            Draft KB entry as Markdown string. Empty string on failure.
        """
        summary_block = self._build_summary_input(
            summary, suggested_type, language, has_complex_branching,
        )

        messages: list[Any] = [
            {
                "role": "user",
                "content": (
                    f"Generate a KB entry from this confirmed summary:\n\n"
                    f"{summary_block}\n\n"
                    f"You may call read_document_range to check the original source "
                    f"for additional context, but ALL key_facts and commands above "
                    f"are mandatory — do not omit any."
                ),
            }
        ]

        # Compact manager
        source_text = ctx.get("source_text", "")
        total_chars = len(source_text)
        outline = extract_document_outline(source_text)
        compact_mgr = ToolLoopCompact(
            adapter=GeneratorCompactAdapter(),
            model=self.model,
            provider=self.provider,
            outline=outline,
            total_chars=total_chars,
            extra_context={"summary_block": summary_block},
            reporter=self.reporter,
        )

        for _turn in range(MAX_GENERATOR_ITERATIONS):
            stop, tool_calls, messages, usage = self.provider.complete(
                messages=messages,
                system=GENERATOR_SYSTEM_PROMPT,
                model=self.model,
                max_tokens=8192,
                tools=DOC_ACCESS_TOOL_DEFINITIONS,
            )

            if stop or not tool_calls:
                break

            _tools_str = ",".join(tc.name for tc in tool_calls)
            self.reporter.info(f"Generator turn {_turn + 1} [{_tools_str}]")

            results: list[tuple[str, str]] = []
            for tc in tool_calls:
                handler = DOC_ACCESS_TOOL_HANDLERS.get(tc.name)
                if handler is None:
                    result: dict[str, Any] = {"error": f"unknown tool: {tc.name}"}
                else:
                    result = handler(ctx, tc.input)
                results.append((tc.id, json.dumps(result)))

            messages = self.provider.append_tool_results(messages, results)

            if compact_mgr.should_compact(usage):
                messages = compact_mgr.compact(messages, GENERATOR_SYSTEM_PROMPT)

        return self._extract_draft(messages)

    def run_with_feedback(
        self,
        summary: dict[str, Any],
        ctx: dict[str, Any],
        previous_draft: str,
        feedback: str,
        suggested_type: str = "pitfall",
        language: str = "en",
        has_complex_branching: bool = False,
    ) -> str:
        """Re-generate a KB entry with specific fidelity feedback.

        Args:
            summary: Confirmed summary dict.
            ctx: Pipeline context.
            previous_draft: Draft that failed fidelity check.
            feedback: Description of what's missing.
            suggested_type: KB entry type.
            language: Document language.
            has_complex_branching: If True, generate Contents tree + decision_map.

        Returns:
            Corrected draft, or empty string on failure.
        """
        summary_block = self._build_summary_input(
            summary, suggested_type, language, has_complex_branching,
        )

        messages: list[Any] = [
            {
                "role": "user",
                "content": (
                    f"Your previous draft had fidelity issues:\n"
                    f"  {feedback}\n\n"
                    f"Here is the confirmed summary (ALL items are mandatory):\n\n"
                    f"{summary_block}\n\n"
                    f"Here is your previous draft:\n\n"
                    f"{previous_draft}\n\n"
                    f"Fix the issues above. Output ONLY the corrected entry Markdown."
                ),
            }
        ]

        # Compact manager for retry loop
        source_text = ctx.get("source_text", "")
        total_chars = len(source_text)
        outline = extract_document_outline(source_text)
        compact_mgr = ToolLoopCompact(
            adapter=GeneratorCompactAdapter(),
            model=self.model,
            provider=self.provider,
            outline=outline,
            total_chars=total_chars,
            extra_context={"summary_block": summary_block},
            reporter=self.reporter,
        )

        for _turn in range(MAX_GENERATOR_ITERATIONS):
            stop, tool_calls, messages, usage = self.provider.complete(
                messages=messages,
                system=GENERATOR_SYSTEM_PROMPT,
                model=self.model,
                max_tokens=8192,
                tools=DOC_ACCESS_TOOL_DEFINITIONS,
            )

            if stop or not tool_calls:
                break

            _tools_str = ",".join(tc.name for tc in tool_calls)
            self.reporter.info(f"Generator retry turn {_turn + 1} [{_tools_str}]")

            results: list[tuple[str, str]] = []
            for tc in tool_calls:
                handler = DOC_ACCESS_TOOL_HANDLERS.get(tc.name)
                if handler is None:
                    result: dict[str, Any] = {"error": f"unknown tool: {tc.name}"}
                else:
                    result = handler(ctx, tc.input)
                results.append((tc.id, json.dumps(result)))

            messages = self.provider.append_tool_results(messages, results)

            if compact_mgr.should_compact(usage):
                messages = compact_mgr.compact(messages, GENERATOR_SYSTEM_PROMPT)

        return self._extract_draft(messages)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary_input(
        summary: dict[str, Any],
        suggested_type: str,
        language: str,
        has_complex_branching: bool = False,
    ) -> str:
        """Build the structured summary block that the LLM receives."""
        key_facts = summary.get("key_facts", [])
        commands = summary.get("commands", [])
        symptoms = summary.get("symptoms", [])
        branches = summary.get("resolution_branches", [])

        lines = [
            f"Type: {suggested_type}",
            f"Language: {language}",
            f"Brief: {summary.get('brief', '')}",
            f"HasComplexBranching: {has_complex_branching}",
            "",
            f"Key Facts ({len(key_facts)} items — ALL must appear in output):",
        ]
        for i, fact in enumerate(key_facts, 1):
            lines.append(f"  {i}. {fact}")

        lines.append("")
        lines.append(f"Commands/Code ({len(commands)} items — ALL must appear verbatim):")
        if commands:
            for i, cmd in enumerate(commands, 1):
                if isinstance(cmd, dict):
                    risk = cmd.get("risk", "read")
                    lines.append(f"  {i}. [api:{risk}] {cmd.get('cmd', '')}")
                    expected = cmd.get("expected", "")
                    if expected:
                        lines.append(f"     Expected: {expected}")
                else:
                    lines.append(f"  {i}. {cmd}")
        else:
            lines.append("  (none)")

        if symptoms:
            lines.append("")
            lines.append(f"Symptoms ({len(symptoms)} items):")
            for i, sym in enumerate(symptoms, 1):
                lines.append(f"  {i}. {sym}")

        if branches:
            lines.append("")
            lines.append(f"Resolution Branches ({len(branches)}):")
            for i, b in enumerate(branches, 1):
                lines.append(f"  {i}. [{b.get('when', '')}] → {b.get('label', '')}")

        # Outline — defines the section structure for the KB entry
        outline = summary.get("outline", [])
        if outline:
            lines.append("")
            lines.append(
                f"Outline ({len(outline)} sections — "
                f"generate EXACTLY these sections in this order):"
            )
            for item in outline:
                lines.append(f"  ## {item.get('section', '')} — {item.get('description', '')}")

        # Decision tree — Contents format for complex branching
        decision_tree = summary.get("decision_tree", "")
        if decision_tree and has_complex_branching:
            lines.append("")
            lines.append("Decision Tree (use as-is for ## Contents):")
            lines.append(decision_tree)

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
