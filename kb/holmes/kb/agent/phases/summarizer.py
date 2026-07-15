"""SummarizerAgent — whole-document structured extraction (042).

Single LLM call per document. Extracts brief, key_facts, commands,
symptoms, and resolution_branches from the entire source document.

Type-aware: uses suggested_type from Classifier to guide extraction
toward the dimensions most useful for each KB type.

Output is a plain dict (no KnowledgeMap dependency):
  {
    "brief": str,
    "key_facts": [str, ...],
    "commands": [{"cmd": str, "expected": str, "risk": str}, ...],
    "symptoms": [str, ...],           # pitfall only
    "resolution_branches": [dict, ...]  # pitfall only
  }
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from holmes.kb.agent.compact import (
    SummarizerCompactAdapter,
    ToolLoopCompact,
)
from holmes.kb.agent.doc_access import DOC_ACCESS_TOOL_DEFINITIONS, DOC_ACCESS_TOOL_HANDLERS
from holmes.kb.agent.observability import observe
from holmes.kb.agent.outline import (
    check_outline_coverage,
    extract_document_outline,
    format_outline_for_prompt,
)
from holmes.kb.agent.prompts.summarizer_prompts import _TYPE_GUIDANCE, _SUMMARIZER_BASE_PROMPT, _build_system_prompt
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.progress import NullReporter, ProgressReporter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SUMMARIZER_ITERATIONS = 15  # tool-call iterations (safety cap)
DIRECT_MODE_CHAR_LIMIT = 8000   # docs under this size skip tool-use loop



def _try_json_parse(text: str) -> Optional[dict[str, Any]]:
    """Try to parse text as a JSON dict. Returns None on failure."""
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _normalize_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure all expected fields exist with correct types."""
    # String fields
    if not isinstance(data.get("brief"), str):
        data["brief"] = str(data.get("brief", ""))

    # List of strings fields
    for key in ("key_facts", "symptoms"):
        val = data.get(key)
        if val is None:
            data[key] = []
        elif not isinstance(val, list):
            data[key] = [str(val)]
        else:
            data[key] = [str(item) for item in val]

    # Commands: list of dicts with cmd/expected/risk (accept legacy list[str] too)
    raw_cmds = data.get("commands")
    if not isinstance(raw_cmds, list):
        data["commands"] = [] if raw_cmds is None else [{"cmd": str(raw_cmds), "expected": "", "risk": "read"}]
    else:
        clean_cmds: list[dict] = []
        for item in raw_cmds:
            if isinstance(item, dict):
                clean_cmds.append({
                    "cmd": str(item.get("cmd", "")),
                    "expected": str(item.get("expected", "")),
                    "risk": str(item.get("risk", "read")) if item.get("risk") in ("read", "write", "danger") else "read",
                })
            elif isinstance(item, str):
                # Legacy format: plain string → wrap in dict
                clean_cmds.append({"cmd": item, "expected": "", "risk": "read"})
        data["commands"] = clean_cmds

    # List of dicts field
    branches = data.get("resolution_branches")
    if not isinstance(branches, list):
        data["resolution_branches"] = []
    else:
        clean = []
        for b in branches:
            if isinstance(b, dict):
                clean.append({
                    "when": str(b.get("when", "")),
                    "label": str(b.get("label", "")),
                })
        data["resolution_branches"] = clean

    # Outline: list of {"section": str, "description": str}
    outline = data.get("outline")
    if not isinstance(outline, list):
        data["outline"] = []
    else:
        clean_outline = []
        for item in outline:
            if isinstance(item, dict):
                clean_outline.append({
                    "section": str(item.get("section", "")),
                    "description": str(item.get("description", "")),
                })
        data["outline"] = clean_outline

    # Decision tree: optional string
    dt = data.get("decision_tree")
    if dt is not None and not isinstance(dt, str):
        data["decision_tree"] = str(dt)

    return data


class SummarizerAgent:
    """Whole-document summarizer — single LLM call per document.

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

    @observe(name="summarizer")
    def run(
        self,
        source_text: str,
        ctx: dict[str, Any],
        suggested_type: str | None = None,
    ) -> Optional[dict[str, Any]]:
        """Extract structured summary from the entire document.

        Args:
            source_text: Full source document text.
            ctx: Pipeline context (must contain "source_text").
            suggested_type: KB type from Classifier (pitfall/model/guideline/
                process/decision). Guides type-specific extraction.

        Returns:
            Summary dict with brief, key_facts, commands, symptoms,
            resolution_branches. None on complete failure.
        """
        type_label = suggested_type or "unknown"
        self.reporter.start(f"Summarizer: 提取文档摘要 (type={type_label})...")

        system_prompt = _build_system_prompt(suggested_type)

        total_chars = len(source_text)

        # Extract document outline for guided reading
        outline = extract_document_outline(source_text)
        outline_block = format_outline_for_prompt(outline, total_chars)

        # Direct mode: for small documents, embed full text and skip tool-use loop
        if total_chars <= DIRECT_MODE_CHAR_LIMIT:
            raw = self._run_direct(
                source_text, system_prompt, type_label, outline_block, total_chars,
            )
        else:
            raw = self._run_tool_loop(
                source_text, ctx, system_prompt, type_label, outline_block,
                outline, total_chars,
            )

        parsed = self._parse_summary(raw)
        if parsed is None:
            _preview = raw[:200].replace("\n", "\\n") if raw else "(empty)"
            self.reporter.warn(f"Summarizer: JSON 解析失败 | raw: {_preview}")
            return None

        # Coverage check: are all outline sections reflected in the summary?
        uncovered = check_outline_coverage(outline, parsed)
        if uncovered:
            self.reporter.info(
                f"Summarizer: {len(uncovered)} section(s) 未覆盖，补充提取: "
                + ", ".join(uncovered[:5])
            )
            parsed = self._supplement_extraction(
                parsed, uncovered, outline, ctx, system_prompt,
            )

        n_facts = len(parsed.get("key_facts", []))
        n_cmds = len(parsed.get("commands", []))
        n_syms = len(parsed.get("symptoms", []))
        n_branches = len(parsed.get("resolution_branches", []))
        n_outline = len(parsed.get("outline", []))
        has_tree = bool(parsed.get("decision_tree"))
        self.reporter.done(
            f"Summarizer: {n_facts} facts, {n_cmds} commands, "
            f"{n_syms} symptoms, {n_branches} branches, "
            f"{n_outline} outline sections"
            + (", decision_tree=yes" if has_tree else "")
        )
        return parsed

    def _run_direct(
        self,
        source_text: str,
        system_prompt: str,
        type_label: str,
        outline_block: str,
        total_chars: int,
    ) -> str:
        """Direct mode: embed full document in prompt, single LLM call."""
        self.reporter.info(
            f"Summarizer: direct mode ({total_chars} chars < {DIRECT_MODE_CHAR_LIMIT})"
        )

        user_content = (
            f"Extract a complete summary from this document "
            f"({total_chars} characters total). "
            f"Document type: {type_label}.\n\n"
        )
        if outline_block:
            user_content += f"{outline_block}\n\n"
        user_content += (
            "Here is the FULL document text:\n\n"
            "---BEGIN DOCUMENT---\n"
            f"{source_text}\n"
            "---END DOCUMENT---\n\n"
            "Output the JSON summary now."
        )

        messages: list[Any] = [{"role": "user", "content": user_content}]

        max_retries = 2
        for attempt in range(max_retries + 1):
            _, _, messages, _ = self.provider.complete(
                messages=messages,
                system=system_prompt,
                model=self.model,
                max_tokens=8192,
                tools=[],
            )
            raw = self._extract_text(messages)
            if raw and self._parse_summary(raw) is not None:
                return raw  # valid JSON
            if attempt >= max_retries:
                return raw  # exhausted retries
            self.reporter.info(f"Summarizer: JSON 反馈重试 ({attempt + 1}/{max_retries})...")
            messages.append({
                "role": "user",
                "content": (
                    "Your JSON output was truncated or malformed and could not be parsed. "
                    "Re-output the COMPLETE JSON summary. Be more concise in key_facts "
                    "descriptions to fit within output limits. "
                    "Output ONLY the JSON object, nothing else."
                ),
            })
        return self._extract_text(messages)

    def _run_tool_loop(
        self,
        source_text: str,
        ctx: dict[str, Any],
        system_prompt: str,
        type_label: str,
        outline_block: str,
        outline: list[dict[str, Any]],
        total_chars: int,
    ) -> str:
        """Unified agent loop: tool-use + validate + feedback retry.

        Modelled after claude-code's agent loop pattern:
        - Single while loop, not separate "tool phase" + "retry phase"
        - Every turn ends with validation; failure injects feedback and continues
        - State transitions: tool_use → nudge → json_retry → terminal
        """
        user_content = (
            f"Extract a complete summary from this document "
            f"({total_chars} characters total). "
            f"Document type: {type_label}.\n\n"
        )
        if outline_block:
            user_content += f"{outline_block}\n\n"
        user_content += (
            f"Use read_document_range(start_char=0, end_char={min(total_chars, 8000)}) "
            f"to start reading. For documents over 8000 chars, make additional calls "
            f"to read the remaining parts.\n\n"
            f"Then output the JSON summary."
        )

        messages: list[Any] = [{"role": "user", "content": user_content}]

        compact_mgr = ToolLoopCompact(
            adapter=SummarizerCompactAdapter(),
            model=self.model,
            provider=self.provider,
            outline=outline,
            total_chars=total_chars,
            extra_context={"suggested_type": type_label},
            reporter=self.reporter,
        )

        json_retries = 0
        max_json_retries = 2

        for _turn in range(MAX_SUMMARIZER_ITERATIONS):
            # --- LLM call ---
            use_tools = json_retries == 0  # disable tools during JSON retries
            stop, tool_calls, messages, usage = self.provider.complete(
                messages=messages,
                system=system_prompt,
                model=self.model,
                max_tokens=8192,
                tools=DOC_ACCESS_TOOL_DEFINITIONS if use_tools else [],
            )

            # --- Tool execution (continue loop) ---
            if tool_calls:
                _tools_str = ",".join(tc.name for tc in tool_calls)
                self.reporter.info(f"Summarizer turn {_turn + 1} [{_tools_str}]")

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
                    messages = compact_mgr.compact(messages, system_prompt)
                continue  # next turn

            # --- Validate: try to parse JSON from assistant output ---
            raw = self._extract_text(messages)

            if raw and self._parse_summary(raw) is not None:
                return raw  # terminal: valid JSON

            # --- Feedback: inject error message and continue ---
            if json_retries >= max_json_retries:
                return raw  # terminal: exhausted retries, return best effort

            json_retries += 1
            if not raw:
                feedback = (
                    "You have read enough. Now output the JSON summary immediately. "
                    "Output ONLY the JSON object, nothing else."
                )
                self.reporter.info(
                    f"Summarizer: 催促输出 JSON ({json_retries}/{max_json_retries})..."
                )
            else:
                feedback = (
                    "Your JSON output was truncated or malformed and could not be parsed. "
                    "Re-output the COMPLETE JSON summary. Be more concise in key_facts "
                    "descriptions to fit within output limits. "
                    "Output ONLY the JSON object, nothing else."
                )
                self.reporter.info(
                    f"Summarizer: JSON 反馈重试 ({json_retries}/{max_json_retries})..."
                )
            messages.append({"role": "user", "content": feedback})
            # continue → next turn calls LLM with tools=[] (json_retries > 0)

        return self._extract_text(messages)

    def _supplement_extraction(
        self,
        existing: dict[str, Any],
        uncovered: list[str],
        outline: list[dict[str, Any]],
        ctx: dict[str, Any],
        system_prompt: str,
    ) -> dict[str, Any]:
        """Supplement extraction for sections missed in the first pass.

        Asks LLM to read and extract only the uncovered sections, then merges
        the results into the existing summary.
        """
        # Build character ranges for uncovered sections
        section_ranges: list[str] = []
        for section_text in uncovered:
            for h in outline:
                if h["text"] == section_text:
                    section_ranges.append(
                        f"- \"{section_text}\" starting at char {h['offset']}"
                    )
                    break

        prompt = (
            "The following sections were NOT covered in your previous extraction:\n\n"
            + "\n".join(section_ranges) + "\n\n"
            "Read these sections using read_document_range and extract additional "
            "key_facts, commands, symptoms, and resolution_branches. "
            "Output ONLY a JSON object with the ADDITIONAL items (same schema). "
            "Do not repeat items already extracted."
        )

        messages: list[Any] = [{"role": "user", "content": prompt}]

        for _turn in range(MAX_SUMMARIZER_ITERATIONS):
            stop, tool_calls, messages, _ = self.provider.complete(
                messages=messages,
                system=system_prompt,
                model=self.model,
                max_tokens=4096,
                tools=DOC_ACCESS_TOOL_DEFINITIONS,
            )
            if stop or not tool_calls:
                break

            self.reporter.info(f"Summarizer supplement turn {_turn + 1}")
            results: list[tuple[str, str]] = []
            for tc in tool_calls:
                handler = DOC_ACCESS_TOOL_HANDLERS.get(tc.name)
                if handler is None:
                    result: dict[str, Any] = {"error": f"unknown tool: {tc.name}"}
                else:
                    result = handler(ctx, tc.input)
                results.append((tc.id, json.dumps(result)))
            messages = self.provider.append_tool_results(messages, results)

        raw = self._extract_text(messages)
        supplement = self._parse_summary(raw)
        if supplement is None:
            self.reporter.warn("Summarizer: 补充提取 JSON 解析失败")
            return existing

        # Merge: append new items to existing lists
        for key in ("key_facts", "commands", "symptoms"):
            new_items = supplement.get(key, [])
            if new_items:
                existing[key] = existing.get(key, []) + new_items

        new_branches = supplement.get("resolution_branches", [])
        if new_branches:
            existing["resolution_branches"] = (
                existing.get("resolution_branches", []) + new_branches
            )

        self.reporter.info(
            f"Summarizer: 补充提取完成 — "
            f"+{len(supplement.get('key_facts', []))} facts, "
            f"+{len(supplement.get('commands', []))} cmds, "
            f"+{len(new_branches)} branches"
        )
        return existing

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

        Handles: raw JSON, code-fenced JSON, embedded JSON.
        Returns None on parse failure.
        """
        if not raw:
            return None

        text = raw.strip()

        # Strategy 1: Direct JSON parse.
        data = _try_json_parse(text)
        if data is not None:
            return _normalize_summary(data)

        # Strategy 2: Strip markdown code fences.
        import re
        fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if fence_match:
            data = _try_json_parse(fence_match.group(1).strip())
            if data is not None:
                return _normalize_summary(data)

        # Strategy 3: Find first { ... } block.
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            data = _try_json_parse(text[first_brace:last_brace + 1])
            if data is not None:
                return _normalize_summary(data)

        return None
