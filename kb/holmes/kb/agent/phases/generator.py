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
from holmes.kb.agent.outline import extract_document_outline
from holmes.kb.agent.observability import observe
from holmes.kb.agent.prompts.generator_prompts import GENERATOR_SYSTEM_PROMPT
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.agent.risk import infer_command_risk
from holmes.kb.progress import NullReporter, ProgressReporter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_GENERATOR_ITERATIONS = 15  # tool-call iterations (safety cap)


def _step_behavior_tag(step: dict[str, Any], risk_by_cmd: dict[str, str]) -> str:
    """Mechanically derive the behavior tag for a step (spec 043 D7/T030).

    Mapping rules (deterministic — no LLM discretion):
      kind=decision           → [decide]
      kind=verify             → [verify]
      actor=human             → [physical]
      actor=remote            → [remote]
      actor=agent (+ command) → [api:{risk}] with risk looked up from the
                                summary's commands[]; on miss, deterministic
                                verb-based inference (T045)
    """
    kind = step.get("kind", "action")
    if kind == "decision":
        return "[decide]"
    if kind == "verify":
        return "[verify]"
    actor = step.get("actor", "agent")
    if actor == "human":
        return "[physical]"
    if actor == "remote":
        return "[remote]"
    cmd_text = str(step.get("command", ""))
    # Lookup hit inherits the normalized (already risk-corrected) commands[];
    # on miss, fall back to the deterministic verb-based inference (T045)
    # instead of blindly defaulting to read.
    risk = risk_by_cmd.get(cmd_text) or infer_command_risk(cmd_text)
    if risk not in ("read", "write", "danger"):
        risk = "read"
    return f"[api:{risk}]"


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

        # Steps with mechanically pre-assigned behavior tags (T030).
        steps = summary.get("steps", [])
        if steps:
            risk_by_cmd = {
                str(c.get("cmd", "")): str(c.get("risk", "read"))
                for c in commands
                if isinstance(c, dict)
            }
            lines.append("")
            lines.append(
                f"Steps ({len(steps)} items — ordered; behavior tags are "
                f"PRE-ASSIGNED and must be used EXACTLY as given):"
            )
            for i, step in enumerate(steps, 1):
                if not isinstance(step, dict):
                    lines.append(f"  {i}. {step}")
                    continue
                tag = _step_behavior_tag(step, risk_by_cmd)
                lines.append(f"  {i}. {tag} {step.get('action', '')}")
                command = step.get("command", "")
                if command:
                    lines.append(f"     Command: {command}")
                expected = step.get("expected", "")
                if expected:
                    lines.append(f"     Expected: {expected}")

        # Applicability metadata (T039) — Generator copies it to frontmatter.
        applies_to = summary.get("applies_to")
        if isinstance(applies_to, dict) and applies_to:
            lines.append("")
            lines.append(
                "AppliesTo (copy verbatim into the YAML frontmatter as "
                f"`applies_to`): {json.dumps(applies_to, ensure_ascii=False)}"
            )

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
