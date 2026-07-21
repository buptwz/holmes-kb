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
    "resolution_branches": [dict, ...],  # pitfall only
    "steps": [{                       # ordered procedure/diagnostic steps
      "action": str,
      "actor": "human" | "agent" | "remote",
      "kind": "action" | "decision" | "verify",
      "command": str,                 # optional
      "expected": str,                # optional
    }, ...],
    "applies_to": {                   # optional applicability metadata (D6)
      "product_line": [str, ...],
      "test_stage": [str, ...],
      "firmware": str,
    },
  }
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from holmes.kb.agent.compact import (
    SummarizerCompactAdapter,
    ToolLoopCompact,
)
from holmes.kb.agent.doc_access import DOC_ACCESS_TOOL_DEFINITIONS, DOC_ACCESS_TOOL_HANDLERS, READ_CHUNK_CHARS
from holmes.kb.agent.observability import observe
from holmes.kb.agent.outline import (
    check_outline_coverage,
    extract_document_outline,
    find_unread_sections,
    format_outline_for_prompt,
)
from holmes.kb.agent.prompts.summarizer_prompts import _TYPE_GUIDANCE, _SUMMARIZER_BASE_PROMPT, _build_system_prompt
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.agent.risk import correct_command_risk
from holmes.kb.progress import NullReporter, ProgressReporter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SUMMARIZER_ITERATIONS = 15  # tool-call iterations (safety cap)
DIRECT_MODE_CHAR_LIMIT = 8000   # docs under this size skip tool-use loop

# Placeholder noise values for applies_to (spec 043 T047) — canonical
# definition lives in holmes.kb.schema so doctor can share it.
from holmes.kb.schema import is_placeholder_value as _is_placeholder



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
                cmd_text = str(item.get("cmd", ""))
                llm_risk = str(item.get("risk", "read")) if item.get("risk") in ("read", "write", "danger") else "read"
                clean_cmds.append({
                    "cmd": cmd_text,
                    "expected": str(item.get("expected", "")),
                    # T045: deterministic verb-based floor — LLM may only escalate,
                    # never downgrade the inferred risk (i2cset/fw update ≠ read).
                    "risk": correct_command_risk(llm_risk, cmd_text),
                })
            elif isinstance(item, str):
                # Legacy format: plain string → wrap in dict
                clean_cmds.append({"cmd": item, "expected": "", "risk": correct_command_risk("read", item)})
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

    # Steps: list of dicts with action/actor/kind (+ optional command/expected)
    # actor: human = physical action, agent = directly executable command,
    #        remote = remote state change/write. Invalid actor → "agent".
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        data["steps"] = []
    else:
        clean_steps: list[dict] = []
        for item in raw_steps:
            if isinstance(item, str):
                item = {"action": item}
            if not isinstance(item, dict):
                continue
            action = str(item.get("action", "")).strip()
            if not action:
                continue
            actor = item.get("actor")
            if actor not in ("human", "agent", "remote"):
                actor = "agent"
            kind = item.get("kind")
            if kind not in ("action", "decision", "verify"):
                kind = "action"
            step: dict[str, Any] = {"action": action, "actor": actor, "kind": kind}
            command = str(item.get("command", "")).strip()
            if command:
                step["command"] = command
            expected = str(item.get("expected", "")).strip()
            if expected:
                step["expected"] = expected
            clean_steps.append(step)
        data["steps"] = clean_steps

    # applies_to: optional applicability metadata (spec 043 D6).
    # Keys fixed (product_line/test_stage/firmware); unknown keys dropped.
    raw_at = data.get("applies_to")
    if not isinstance(raw_at, dict):
        data.pop("applies_to", None)
    else:
        clean_at: dict[str, Any] = {}
        for key in ("product_line", "test_stage"):
            values = raw_at.get(key)
            if isinstance(values, list):
                # T047: placeholder noise ("unknown"/"n/a"/"未知"…) means
                # "no information" — drop the value, never store the literal.
                slugs = [str(v).strip() for v in values if str(v).strip() and not _is_placeholder(str(v))]
                if slugs:
                    clean_at[key] = slugs
        firmware = raw_at.get("firmware")
        if isinstance(firmware, str) and firmware.strip() and not _is_placeholder(firmware):
            clean_at["firmware"] = firmware.strip()
        if clean_at:
            data["applies_to"] = clean_at
        else:
            data.pop("applies_to", None)

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
        read_chunk_chars: int = 0,
        direct_mode_char_limit: int = 0,
    ) -> None:
        self.provider = provider
        self.model = model
        self.reporter: ProgressReporter = reporter or NullReporter()
        # Import tunables; non-positive or non-int (e.g. a MagicMock cfg in
        # tests) means "use the code default". Configurable via
        # `holmes config set read_chunk_chars|direct_mode_char_limit`.
        self._read_chunk_chars = (
            read_chunk_chars
            if isinstance(read_chunk_chars, int) and not isinstance(read_chunk_chars, bool) and read_chunk_chars > 0
            else READ_CHUNK_CHARS
        )
        self._direct_mode_char_limit = (
            direct_mode_char_limit
            if isinstance(direct_mode_char_limit, int) and not isinstance(direct_mode_char_limit, bool) and direct_mode_char_limit > 0
            else DIRECT_MODE_CHAR_LIMIT
        )
        # T033 read-coverage invariant: populated by run(); read by pipeline.
        self.last_read_ranges: list[tuple[int, int]] = []
        self.last_exhausted: bool = False
        self._last_system_prompt: str = ""

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
            resolution_branches, steps, and (optional) applies_to.
            None on complete failure.
        """
        type_label = suggested_type or "unknown"
        self.reporter.start(f"Summarizer: 提取文档摘要 (type={type_label})...")

        self.last_read_ranges = []
        self.last_exhausted = False

        # T039: inject the current applies_to vocabulary so the LLM prefers
        # existing values over inventing synonyms (spec 043 D6).
        vocabulary: dict[str, list[str]] = {}
        kb_root = ctx.get("kb_root")
        if kb_root:
            try:
                from holmes.kb.vocabulary import load_vocabulary
                vocabulary = load_vocabulary(Path(kb_root))
            except Exception:  # noqa: BLE001
                vocabulary = {}

        system_prompt = _build_system_prompt(suggested_type, vocabulary=vocabulary)
        self._last_system_prompt = system_prompt

        total_chars = len(source_text)

        # Extract document outline for guided reading
        outline = extract_document_outline(source_text)
        outline_block = format_outline_for_prompt(outline, total_chars)

        # Direct mode: for small documents, embed full text and skip tool-use loop
        if total_chars <= self._direct_mode_char_limit:
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
        n_steps = len(parsed.get("steps", []))
        has_tree = bool(parsed.get("decision_tree"))
        self.reporter.done(
            f"Summarizer: {n_facts} facts, {n_cmds} commands, "
            f"{n_syms} symptoms, {n_branches} branches, "
            f"{n_outline} outline sections, {n_steps} steps"
            + (", decision_tree=yes" if has_tree else "")
        )
        return parsed

    def ensure_coverage(
        self,
        summary: dict[str, Any],
        source_text: str,
        ctx: dict[str, Any],
    ) -> list[str]:
        """Enforce the read-coverage hard invariant (spec 043 D7/T033).

        Checks that every outline section's full char range was actually read
        via read_document_range during run(). Unread sections trigger one
        forced supplement pass (which itself reads them). Returns the list of
        section texts STILL unread after the supplement — callers must surface
        these in the import report (never silently drop).
        """
        outline = extract_document_outline(source_text)
        unread = find_unread_sections(outline, self.last_read_ranges)
        if not unread:
            return []
        self.reporter.info(
            f"Coverage: {len(unread)} 个 section 未被读取，强制补读: "
            + ", ".join(unread[:5])
        )
        supplemented = self._supplement_extraction(
            summary, unread, outline, ctx, self._last_system_prompt,
        )
        summary.update(supplemented)
        still_unread = find_unread_sections(outline, self.last_read_ranges)
        if still_unread:
            self.reporter.warn(
                f"Coverage: 补读后仍有 {len(still_unread)} 个 section 未读取: "
                + ", ".join(still_unread[:5])
            )
        return still_unread

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
            f"Summarizer: direct mode ({total_chars} chars < {self._direct_mode_char_limit})"
        )
        # Full document embedded → fully read by construction (T033).
        self.last_read_ranges = [(0, total_chars)] if total_chars else []

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
            f"Use read_document_range(start_char=0, end_char={min(total_chars, self._read_chunk_chars)}) "
            f"to start reading. For documents over {self._read_chunk_chars} chars, make additional calls "
            f"to read the remaining parts (up to {self._read_chunk_chars} chars per call).\n\n"
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
                        if tc.name == "read_document_range" and "start_char" in result:
                            self.last_read_ranges.append(
                                (result["start_char"], result["end_char"])
                            )
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

        # Iteration cap hit without converging — pipeline must not treat this
        # as a clean return (T033: no silent truncation).
        self.last_exhausted = True
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
            "key_facts, commands, symptoms, steps, and resolution_branches. "
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
                    if tc.name == "read_document_range" and "start_char" in result:
                        self.last_read_ranges.append(
                            (result["start_char"], result["end_char"])
                        )
                results.append((tc.id, json.dumps(result)))
            messages = self.provider.append_tool_results(messages, results)

        raw = self._extract_text(messages)
        supplement = self._parse_summary(raw)
        if supplement is None:
            self.reporter.warn("Summarizer: 补充提取 JSON 解析失败")
            return existing

        # Merge: append new items to existing lists
        for key in ("key_facts", "commands", "symptoms", "steps"):
            new_items = supplement.get(key, [])
            if new_items:
                existing[key] = existing.get(key, []) + new_items

        new_branches = supplement.get("resolution_branches", [])
        if new_branches:
            existing["resolution_branches"] = (
                existing.get("resolution_branches", []) + new_branches
            )

        # applies_to: union merge (supplement may find applicability info in
        # sections missed by the first pass).
        new_at = supplement.get("applies_to")
        if isinstance(new_at, dict) and new_at:
            old_at = existing.get("applies_to") or {}
            merged_at: dict[str, Any] = {}
            for key in ("product_line", "test_stage"):
                merged = sorted(set(old_at.get(key, [])) | set(new_at.get(key, [])))
                if merged:
                    merged_at[key] = merged
            merged_at["firmware"] = new_at.get("firmware") or old_at.get("firmware")
            merged_at = {k: v for k, v in merged_at.items() if v}
            if merged_at:
                existing["applies_to"] = merged_at

        self.reporter.info(
            f"Summarizer: 补充提取完成 — "
            f"+{len(supplement.get('key_facts', []))} facts, "
            f"+{len(supplement.get('commands', []))} cmds, "
            f"+{len(supplement.get('steps', []))} steps, "
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
