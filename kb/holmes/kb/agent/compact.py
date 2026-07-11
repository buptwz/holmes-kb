"""Tool-use loop context compaction for pipeline agents.

When an agent's tool-use loop approaches the model's context window limit,
this module compacts the message history while preserving all information
the agent needs to continue its task.

Two levels of compaction:
1. **Programmatic snip** — replace old tool result payloads with stubs (zero
   LLM cost, always attempted first).
2. **Full checkpoint** — force the LLM to emit its in-progress state, then
   rebuild messages from a single checkpoint user message. Costs one extra
   LLM call but can reclaim 80%+ of context.

Phase-specific behavior is encapsulated in ``CompactAdapter`` subclasses.
Each pipeline phase (Summarizer, Generator) implements its own adapter that
knows *what* state to extract and *how* to rebuild the continuation prompt.

Usage inside a tool-use loop::

    compact_ctx = ToolLoopCompact(adapter, model, provider)

    for turn in range(MAX_ITERATIONS):
        stop, tool_calls, messages, usage = provider.complete(...)
        if compact_ctx.should_compact(usage):
            messages = compact_ctx.compact(messages, system_prompt)
        ...
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

from holmes.kb.progress import NullReporter, ProgressReporter

# ---------------------------------------------------------------------------
# Model context window sizes (tokens)
# ---------------------------------------------------------------------------

_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek-v4-pro": 128_000,
    "deepseek-v4-flash": 64_000,
    "deepseek-chat": 64_000,
    "deepseek-reasoner": 64_000,
}
DEFAULT_CONTEXT_WINDOW = 64_000

# Compact triggers when input_tokens exceeds this fraction of context window.
COMPACT_THRESHOLD_RATIO = 0.80

# After a snip, if tokens are still above this ratio, escalate to full
# checkpoint compact.
CHECKPOINT_ESCALATION_RATIO = 0.70


def get_context_window(model: str) -> int:
    """Return known context window size for *model*, else default."""
    # Exact match first, then prefix match for versioned names.
    if model in _MODEL_CONTEXT_WINDOWS:
        return _MODEL_CONTEXT_WINDOWS[model]
    for prefix, size in _MODEL_CONTEXT_WINDOWS.items():
        if model.startswith(prefix):
            return size
    return DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# Reading progress extraction (shared by all adapters)
# ---------------------------------------------------------------------------

def extract_read_ranges(messages: list[Any]) -> list[tuple[int, int]]:
    """Scan messages for read_document_range tool calls, return sorted ranges.

    Works with both OpenAI format (tool_calls[].function.arguments as JSON
    string) and pre-parsed dict format.
    """
    ranges: list[tuple[int, int]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "assistant":
            continue

        # OpenAI format: msg["tool_calls"] list
        tool_calls = msg.get("tool_calls", [])
        for tc in tool_calls:
            fname = ""
            args: dict[str, Any] = {}

            if isinstance(tc, dict):
                func = tc.get("function", {})
                fname = func.get("name", "")
                raw_args = func.get("arguments", "{}")
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except (json.JSONDecodeError, ValueError):
                        args = {}
                elif isinstance(raw_args, dict):
                    args = raw_args

            if fname == "read_document_range":
                start = int(args.get("start_char", 0))
                end = int(args.get("end_char", 0))
                if end > start:
                    ranges.append((start, end))

    ranges.sort()
    return ranges


def format_read_progress(
    outline: list[dict[str, Any]],
    read_ranges: list[tuple[int, int]],
    total_chars: int,
) -> str:
    """Format document outline annotated with read/unread status.

    A section is considered "read" if ≥70% of its character range is covered
    by the union of ``read_ranges``.
    """
    if not outline:
        # No headings — report raw range coverage
        covered = _covered_chars(read_ranges, 0, total_chars)
        return (
            f"Document ({total_chars} chars): "
            f"{covered}/{total_chars} chars read "
            f"({100 * covered // max(total_chars, 1)}%)"
        )

    lines = [f"Document outline ({total_chars} chars total):"]
    for h in outline:
        indent = "  " * (h["level"] - 1)
        sec_start = h["offset"]
        sec_end = sec_start + h.get("length", 0)
        covered = _covered_chars(read_ranges, sec_start, sec_end)
        sec_len = max(sec_end - sec_start, 1)
        ratio = covered / sec_len

        if ratio >= 0.70:
            status = "✓ 已读"
        elif ratio > 0:
            status = f"△ 部分已读 ({int(ratio * 100)}%)"
        else:
            status = "← 未读"

        lines.append(
            f"{indent}{'#' * h['level']} {h['text']}  "
            f"[char {sec_start}–{sec_end}] {status}"
        )

    return "\n".join(lines)


def _covered_chars(
    ranges: list[tuple[int, int]], start: int, end: int,
) -> int:
    """Count how many characters in [start, end) are covered by ranges."""
    total = 0
    for r_start, r_end in ranges:
        overlap_start = max(r_start, start)
        overlap_end = min(r_end, end)
        if overlap_end > overlap_start:
            total += overlap_end - overlap_start
    return total


# ---------------------------------------------------------------------------
# Tool result snipping
# ---------------------------------------------------------------------------

# Stub that replaces read_document_range result payload.
_SNIP_STUB = '[已处理，原文已压缩]'


def snip_old_tool_results(
    messages: list[Any],
    keep_recent: int = 2,
) -> list[Any]:
    """Replace old tool-result payloads with lightweight stubs.

    Keeps the *keep_recent* most recent tool-result messages intact.
    Older ones have their ``content`` replaced with a stub that preserves
    the range metadata but drops the raw text.

    Works with OpenAI format where tool results are separate messages
    with ``role: "tool"``.
    """
    # Find indices of all tool-result messages.
    tool_indices: list[int] = []
    for i, msg in enumerate(messages):
        if isinstance(msg, dict) and msg.get("role") == "tool":
            tool_indices.append(i)

    if len(tool_indices) <= keep_recent:
        return messages  # Nothing to snip.

    # Indices to snip (all except the most recent keep_recent).
    snip_set = set(tool_indices[:-keep_recent])

    result = []
    for i, msg in enumerate(messages):
        if i in snip_set:
            snipped = _snip_tool_message(msg)
            result.append(snipped)
        else:
            result.append(msg)
    return result


def _snip_tool_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Replace a tool-result message's content with a compact stub."""
    content = msg.get("content", "")
    # Try to parse and preserve range metadata.
    try:
        data = json.loads(content) if isinstance(content, str) else content
        if isinstance(data, dict) and "start_char" in data:
            stub = json.dumps({
                "text": _SNIP_STUB,
                "start_char": data.get("start_char"),
                "end_char": data.get("end_char"),
                "total_chars": data.get("total_chars"),
            }, ensure_ascii=False)
            return {**msg, "content": stub}
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # Fallback: generic stub.
    return {**msg, "content": _SNIP_STUB}


# ---------------------------------------------------------------------------
# Compact adapter interface
# ---------------------------------------------------------------------------

class CompactAdapter(ABC):
    """Phase-specific compact behavior.

    Each pipeline phase (Summarizer, Generator) subclasses this to define
    what state to preserve and how to build the continuation prompt.
    """

    @abstractmethod
    def force_emit_state(
        self,
        messages: list[Any],
        provider: Any,
        system_prompt: str,
        model: str,
    ) -> dict[str, Any]:
        """Force the LLM to output its current in-progress state.

        Injects a user message and calls provider.complete(tools=[]) to get
        a text response, then parses it into a state dict.

        Returns:
            Phase-specific state dict. Must be JSON-serializable.
            Empty dict if extraction fails (compact still proceeds with
            whatever reading progress we can infer).
        """

    @abstractmethod
    def build_checkpoint_message(
        self,
        state: dict[str, Any],
        outline: list[dict[str, Any]],
        read_ranges: list[tuple[int, int]],
        total_chars: int,
        extra_context: dict[str, Any],
    ) -> str:
        """Build the checkpoint user-message content.

        Args:
            state: Result of force_emit_state().
            outline: Document outline from extract_document_outline().
            read_ranges: Character ranges already read.
            total_chars: Total document length.
            extra_context: Phase-specific metadata (type, language, etc.).

        Returns:
            A single string to be used as the new user message content.
        """


# ---------------------------------------------------------------------------
# ToolLoopCompact — the orchestrator
# ---------------------------------------------------------------------------

class ToolLoopCompact:
    """Context compaction manager for a tool-use loop.

    Monitors token usage after each ``provider.complete()`` call and
    compacts the message history when approaching the context window limit.

    Args:
        adapter: Phase-specific compact adapter.
        model: Model identifier (used to look up context window size).
        provider: LLMProvider instance (needed for force_emit_state).
        outline: Document outline (list of heading dicts).
        total_chars: Total source document length.
        extra_context: Phase-specific metadata passed to adapter.
        reporter: Progress reporter.
        context_window_override: Override auto-detected context window.
    """

    def __init__(
        self,
        adapter: CompactAdapter,
        model: str,
        provider: Any,
        outline: list[dict[str, Any]],
        total_chars: int,
        extra_context: dict[str, Any] | None = None,
        reporter: ProgressReporter | None = None,
        context_window_override: int | None = None,
    ) -> None:
        self.adapter = adapter
        self.model = model
        self.provider = provider
        self.outline = outline
        self.total_chars = total_chars
        self.extra_context = extra_context or {}
        self.reporter: ProgressReporter = reporter or NullReporter()

        cw = context_window_override or get_context_window(model)
        self.compact_threshold = int(cw * COMPACT_THRESHOLD_RATIO)
        self.escalation_threshold = int(cw * CHECKPOINT_ESCALATION_RATIO)

        self._compact_count = 0

    @property
    def compact_count(self) -> int:
        """Number of compactions performed so far."""
        return self._compact_count

    def should_compact(self, usage: dict[str, int]) -> bool:
        """Check whether compaction is needed based on API usage."""
        input_tokens = usage.get("input_tokens", 0)
        return input_tokens > self.compact_threshold

    def compact(
        self,
        messages: list[Any],
        system_prompt: str,
    ) -> list[Any]:
        """Compact message history, returning new messages to continue with.

        Strategy:
        1. Try snipping old tool results first (cheap).
        2. If estimated savings are insufficient, escalate to full checkpoint.
        """
        self._compact_count += 1
        self.reporter.info(
            f"Compact #{self._compact_count}: 上下文接近限制，开始压缩..."
        )

        # --- Level 1: Snip old tool results ---
        snipped = snip_old_tool_results(messages, keep_recent=2)

        # Estimate whether snipping freed enough.  Rough heuristic:
        # count tool messages that were actually snipped (content changed).
        snipped_count = sum(
            1 for orig, new in zip(messages, snipped)
            if orig is not new
        )

        if snipped_count > 0:
            self.reporter.info(
                f"Compact #{self._compact_count}: snip 了 {snipped_count} 个旧 tool result"
            )

        # We can't know the exact post-snip token count without another API
        # call. Use a heuristic: if we snipped ≥3 results, that's likely
        # enough (~10K+ tokens freed). Otherwise escalate.
        if snipped_count >= 3:
            return snipped

        # --- Level 2: Full checkpoint compact ---
        self.reporter.info(
            f"Compact #{self._compact_count}: snip 不够，执行 checkpoint 压缩..."
        )

        # Force LLM to emit current state.
        state = self.adapter.force_emit_state(
            snipped, self.provider, system_prompt, self.model,
        )

        # Extract reading progress.
        read_ranges = extract_read_ranges(messages)

        # Build checkpoint.
        progress_text = format_read_progress(
            self.outline, read_ranges, self.total_chars,
        )

        checkpoint_content = self.adapter.build_checkpoint_message(
            state=state,
            outline=self.outline,
            read_ranges=read_ranges,
            total_chars=self.total_chars,
            extra_context={
                **self.extra_context,
                "read_progress_text": progress_text,
            },
        )

        self.reporter.info(
            f"Compact #{self._compact_count}: checkpoint 重建完成，继续处理"
        )

        return [{"role": "user", "content": checkpoint_content}]


# ---------------------------------------------------------------------------
# Summarizer compact adapter
# ---------------------------------------------------------------------------

_FORCE_EMIT_PROMPT = (
    "上下文即将压缩。请立即输出你目前已经提取的所有信息，格式为 JSON（与最终输出相同的 schema）。\n"
    "即使提取不完整也请输出当前进度。输出 ONLY JSON，不要其他内容。"
)


class SummarizerCompactAdapter(CompactAdapter):
    """Compact adapter for the Summarizer phase.

    State: partial extraction JSON (key_facts, commands, symptoms, branches).
    Checkpoint: partial JSON + outline with coverage + continue instructions.
    """

    def force_emit_state(
        self,
        messages: list[Any],
        provider: Any,
        system_prompt: str,
        model: str,
    ) -> dict[str, Any]:
        """Force Summarizer to output partial extraction JSON."""
        emit_messages = list(messages)
        emit_messages.append({
            "role": "user",
            "content": _FORCE_EMIT_PROMPT,
        })

        try:
            raw = provider.simple_complete(
                messages=emit_messages,
                system=system_prompt,
                max_tokens=4096,
            )
        except Exception:
            return {}

        return _try_parse_json(raw) or {}

    def build_checkpoint_message(
        self,
        state: dict[str, Any],
        outline: list[dict[str, Any]],
        read_ranges: list[tuple[int, int]],
        total_chars: int,
        extra_context: dict[str, Any],
    ) -> str:
        """Build Summarizer checkpoint message."""
        parts: list[str] = []

        doc_type = extra_context.get("suggested_type", "unknown")
        parts.append(
            f"你正在从一个文档中提取结构化摘要 "
            f"(type={doc_type}, {total_chars} chars)。"
            f"\n因为上下文窗口限制，之前的对话已压缩。"
        )

        # Partial extraction state
        if state:
            n_facts = len(state.get("key_facts", []))
            n_cmds = len(state.get("commands", []))
            n_syms = len(state.get("symptoms", []))
            n_branches = len(state.get("resolution_branches", []))
            parts.append(
                f"\n## 已提取数据 ({n_facts} facts, {n_cmds} cmds, "
                f"{n_syms} symptoms, {n_branches} branches)\n"
                f"```json\n{json.dumps(state, ensure_ascii=False, indent=2)}\n```"
            )
        else:
            parts.append(
                "\n## 已提取数据\n（提取进度丢失，请重新从未读部分提取）"
            )

        # Reading progress
        progress = extra_context.get("read_progress_text", "")
        if progress:
            parts.append(f"\n## 阅读进度\n{progress}")

        # Instructions
        parts.append(
            "\n## 任务\n"
            "继续阅读所有未读部分（使用 read_document_range），"
            "将新提取的信息合并到上面的已有数据中。\n"
            "全部读完后，输出完整的最终 JSON（包含之前已提取的 + 新提取的所有内容）。\n"
            "不要重复已提取的内容。\n"
            "注意：保留已有数据中的 outline 和 decision_tree 字段，不要重新生成。"
        )

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Generator compact adapter
# ---------------------------------------------------------------------------

_GENERATOR_FORCE_EMIT_PROMPT = (
    "上下文即将压缩。请立即输出你目前已经生成的 KB entry markdown（即使不完整）。\n"
    "输出你已经写好的部分，不要其他内容。"
)


class GeneratorCompactAdapter(CompactAdapter):
    """Compact adapter for the Generator phase.

    State: partial markdown draft.
    Checkpoint: summary JSON (input, unchanged) + partial draft + outline
    with coverage + continue instructions.
    """

    def force_emit_state(
        self,
        messages: list[Any],
        provider: Any,
        system_prompt: str,
        model: str,
    ) -> dict[str, Any]:
        """Force Generator to output partial markdown draft."""
        emit_messages = list(messages)
        emit_messages.append({
            "role": "user",
            "content": _GENERATOR_FORCE_EMIT_PROMPT,
        })

        try:
            raw = provider.simple_complete(
                messages=emit_messages,
                system=system_prompt,
                max_tokens=8192,
            )
        except Exception:
            return {}

        return {"partial_draft": raw.strip() if raw else ""}

    def build_checkpoint_message(
        self,
        state: dict[str, Any],
        outline: list[dict[str, Any]],
        read_ranges: list[tuple[int, int]],
        total_chars: int,
        extra_context: dict[str, Any],
    ) -> str:
        """Build Generator checkpoint message."""
        parts: list[str] = []

        parts.append(
            f"你正在将摘要格式化为 KB entry markdown "
            f"(文档 {total_chars} chars)。"
            f"\n因为上下文窗口限制，之前的对话已压缩。"
        )

        # Summary JSON (the Generator's input — must be preserved)
        summary_block = extra_context.get("summary_block", "")
        if summary_block:
            parts.append(
                f"\n## 输入摘要（所有 key_facts 和 commands 必须出现在输出中）\n"
                f"{summary_block}"
            )

        # Partial draft
        partial_draft = state.get("partial_draft", "")
        if partial_draft:
            parts.append(
                f"\n## 已生成的部分 draft\n"
                f"```markdown\n{partial_draft}\n```\n"
                f"从上面断开的地方继续写。"
            )
        else:
            parts.append(
                "\n## 已生成的部分 draft\n（生成进度丢失，请从头开始生成）"
            )

        # Reading progress
        progress = extra_context.get("read_progress_text", "")
        if progress:
            parts.append(f"\n## 原文阅读进度\n{progress}")

        # Instructions
        parts.append(
            "\n## 任务\n"
            "继续生成 KB entry。如果需要回查原文获取 verbatim 内容，"
            "使用 read_document_range。\n"
            "输出完整的最终 markdown（包含已生成部分 + 后续部分）。"
        )

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_parse_json(text: str) -> Optional[dict[str, Any]]:
    """Try to parse JSON from LLM output. Handles fences and embedded JSON."""
    if not text:
        return None
    text = text.strip()

    # Direct parse.
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Strip markdown fences.
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            data = json.loads(fence_match.group(1).strip())
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    # Find first { ... } block.
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        try:
            data = json.loads(text[first:last + 1])
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    return None
