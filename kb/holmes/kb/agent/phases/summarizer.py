"""SummarizerAgent — whole-document structured extraction (042).

Single LLM call per document. Extracts brief, key_facts, commands,
symptoms, and resolution_branches from the entire source document.

Type-aware: uses suggested_type from Classifier to guide extraction
toward the dimensions most useful for each KB type.

Output is a plain dict (no KnowledgeMap dependency):
  {
    "brief": str,
    "key_facts": [str, ...],
    "commands": [str, ...],
    "symptoms": [str, ...],           # pitfall only
    "resolution_branches": [dict, ...]  # pitfall only
  }
"""

from __future__ import annotations

import json
from typing import Any, Optional

from holmes.kb.agent.doc_access import DOC_ACCESS_TOOL_DEFINITIONS, DOC_ACCESS_TOOL_HANDLERS
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.progress import NullReporter, ProgressReporter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SUMMARIZER_ITERATIONS = 15  # tool-call iterations (safety cap)

# ---------------------------------------------------------------------------
# Per-type extraction guidance — injected into the system prompt
# ---------------------------------------------------------------------------

_TYPE_GUIDANCE: dict[str, str] = {
    "pitfall": """\
## Type-specific extraction focus: pitfall

A pitfall documents a FAILURE → ROOT CAUSE → FIX cycle. Extract along these dimensions:

### Matching signals (critical for kb_browse — how the agent finds this entry)
- Error messages VERBATIM (exact text from logs, dmesg, BMC SEL, CLI output)
- Observable anomalies: LED states, metric thresholds, behavioral symptoms
- The more specific the symptom, the better the match. \
"Memory ECC Error from slot A1/DIMM 0" >> "memory has issues"

### Root cause chain (critical for kb_read summary — why the agent trusts this entry)
- Extract the REASONING, not just the conclusion: cause → intermediate effect → visible symptom
- "Single-bit ECC errors accumulate under sustained high-temp load → exceed BIOS uncorrectable \
threshold → system reboots" is far more useful than "DIMM was faulty"
- If multiple root causes exist, extract each one separately

### Branch conditions (critical for multi-path pitfalls)
- The OBSERVABLE CONDITION that determines which resolution path to take
- "lspci sees nothing → Path A; sees device but degraded → Path B"
- Extract as structured resolution_branches, not prose

### Diagnostic checkpoints
- Tests that CONFIRM the root cause BEFORE committing to a fix
- "Swap DIMM → if error follows DIMM → confirmed DIMM body fault, not slot fault"

### Resolution steps
- Ordered steps with exact commands, physical actions, and decision points
- Each step: what to do + what to expect + what if unexpected

### Verification
- How to confirm the problem is actually fixed: "72h burn-in, ECC count = 0"

### Lessons / thresholds
- Experience-based judgment rules: "ECC > 500/h is suspicious" "burn-in < 72h is insufficient"

### What NOT to extract
- Narrative filler: "we then proceeded to investigate"
- Organizational context: "the NOC team was notified"
- Duplicate restatements of the same fact""",

    "model": """\
## Type-specific extraction focus: model

A model document explains HOW SOMETHING WORKS — mechanisms, architectures, parameters. \
The agent needs this to interpret observations and make recommendations during troubleshooting.

### Concept definitions (critical for kb_browse — is this model relevant?)
- One-sentence definition of each concept: \
"PROCHOT is an Intel signal indicating the processor has reached Tjunction max"

### Mechanisms (critical for kb_read full — explaining what's happening)
- How each mechanism works: trigger condition → behavior → consequence
- "PROCHOT asserted → CPU drops to min P-state → 50-80% performance loss"
- Extract the CHAIN, not just isolated facts

### Key parameters
- Quantitative specs: thresholds, limits, ranges, timeouts
- "Tjunction max = 100-105°C" "PL2 window = 28 seconds"
- These are what the agent uses to interpret engineer's observations

### Relationships between concepts
- Hierarchy, sequence, conflicts: "RAPL → PROCHOT → THERMTRIP form layered defense"
- How components interact, dependencies, ordering

### Diagnostic relevance
- How to observe/measure each mechanism: "rdmsr 0x19C bit 0 = PROCHOT active"
- Concrete commands to check mechanism state

### NPI validation implications
- What this model means for testing: "Test at max inlet temp" \
"Verify PROCHOT activates before THERMTRIP in fan-failure mode"

### What NOT to extract
- Textbook-level basics the agent already knows
- Historical evolution of a technology
- Marketing-level descriptions without technical content""",

    "guideline": """\
## Type-specific extraction focus: guideline

A guideline documents RULES THAT MUST BE FOLLOWED — standards, policies, safety requirements. \
The agent checks and enforces these rules during operations.

### Scope (critical for kb_browse — does this guideline apply?)
- When, where, and to whom this guideline applies
- "All NPI team members in the lab environment"

### Rules as specific statements (critical for kb_read summary)
- Each rule as a concrete, actionable statement
- "Must wear ESD wristband before touching any electronic component" — \
NOT "be careful with ESD"
- Distinguish MUST (hard rules) from SHOULD (recommendations)

### Quantitative criteria
- Measurable compliance standards: "Wristband resistance 1MΩ ± 10%"
- Specific numbers that let the agent verify compliance

### Rationale
- WHY each rule exists — the consequence of violation
- "ESD-damaged components may pass initial tests but fail weeks later → high RMA cost"
- Engineers follow rules better when they understand the reason

### Verification methods
- How to check compliance: "Daily wristband resistance test" "Weekly ion fan calibration"

### Severity classification
- Which rules are hard (must) vs soft (should)
- "Wireless wristband is NOT acceptable" (hard) vs "Recommended to use anti-static tray" (soft)

### What NOT to extract
- Organizational reporting structure
- Training schedule logistics
- Generic safety disclaimers not specific to the technical domain""",

    "process": """\
## Type-specific extraction focus: process

A process document is a STEP-BY-STEP PROCEDURE — the agent acts as a GPS navigator, \
guiding the engineer through each step.

### Purpose & scope (critical for kb_browse — is this the right procedure?)
- What this procedure accomplishes, when to use it

### Prerequisites
- What must be true before starting: tools needed, access required, approvals, maintenance window
- The agent MUST verify these before guiding the engineer through steps

### Risk warnings
- What can go wrong, what's irreversible
- "Failed BMC flash → bricked management controller → physical board replacement"

### Ordered steps with commands (critical — the core content)
- Each step: action + exact command + expected output
- PRESERVE STEP ORDERING — the agent presents one step at a time
- Include every command and its expected result

### Checkpoints
- After each major step, how to verify success before proceeding
- "Verify firmware version matches target" "Confirm BMC is responsive after reboot"

### Critical mid-process warnings
- Points of no return: "Do NOT power cycle during flash"
- These must be associated with the correct step, not front-loaded

### Completion criteria
- What the final state should look like
- "BMC at target version, sensors readable, server powers on, network intact"

### Rollback / recovery
- What to do if the procedure fails at each stage

### What NOT to extract
- Explanations of WHY each step works (that's model territory)
- Alternative approaches not part of this procedure
- Historical context of why this procedure was created""",

    "decision": """\
## Type-specific extraction focus: decision

A decision document records WHY A CHOICE WAS MADE — an Architecture Decision Record (ADR). \
The agent uses this to explain rationale and evaluate whether conditions have changed.

### Problem statement (critical for kb_browse — is this decision relevant?)
- What situation required a decision: constraints, requirements, timeline pressure

### Options considered
- Each alternative with SPECIFIC pros and cons
- "Option A: Gen5 for all → Pro: max bandwidth, Con: 15% link training failure on slots 3-6"
- NOT vague: include quantitative data where available

### Chosen option
- Which option was selected, with implementation details (commands, configuration)

### Key trade-off (critical for kb_read summary — the decisive reasoning)
- The decisive factor: "Stability over speed: 15% random failure wastes more engineering time \
than Gen4 performance gap"
- The REASONING, not just the conclusion

### Scope & constraints
- Where this decision applies: "Granite platform, Rev B PCB, until Rev C arrives"
- Temporal and platform boundaries

### Revisit triggers
- When to reconsider: "Revisit when Rev C PCB arrives (2024-Q3)"
- The agent can proactively flag that conditions may have changed

### What NOT to extract
- Meeting process details (who attended, how many rounds of discussion)
- Emotional reasoning ("the team felt that...")
- Options that were considered but had zero viability""",
}

# ---------------------------------------------------------------------------
# System prompt — assembled dynamically based on suggested_type
# ---------------------------------------------------------------------------

_SUMMARIZER_BASE_PROMPT = """\
You are the Summarizer in a knowledge base pipeline for NPI hardware engineers. \
Your job is to read the entire source document and extract ALL important information \
into a structured JSON object. You decide WHAT to keep — the next phase decides how \
to present it.

# Procedure

1. Call `read_document_range` to read the full document. For documents over 8000 \
   chars, make multiple calls to cover every section.
2. Extract information into the JSON format below, guided by the type-specific \
   extraction focus.
3. Output ONLY the JSON object — no markdown fences, no commentary, no preamble.

# Cross-type extraction principles

These apply regardless of document type:

1. **Specificity > generality**: "ECC error > 500/h from slot A1/DIMM 0" beats \
   "memory errors detected". Specific facts enable the agent to MATCH and ACT precisely.

2. **Self-contained facts**: Each key_fact must be understandable alone, without \
   needing other facts for context. The agent may retrieve individual facts.

3. **Commands are sacred**: Every command, code block, config snippet, and API call \
   must be extracted VERBATIM. These are the most actionable part of the KB.

4. **Preserve cause-effect chains**: Don't extract just conclusions ("it was a DIMM fault"). \
   Extract the reasoning chain ("swap DIMM → error followed → confirmed DIMM body fault").

5. **Extract for retrieval, not for reading**: Optimize for the agent to find and match \
   against engineer's questions. Completeness and precision > prose quality.

{type_guidance}

# Extraction rules — field by field

## brief (string, required)

One sentence (≤ 150 chars) capturing the core knowledge. An engineer should be able \
to judge relevance from this sentence alone.

Good: "Samsung DDR5 DIMM 颗粒缺陷导致 ECC 错误累积，48h burn-in 后触发服务器重启"
Bad:  "内存问题排查"  ← too vague, no actionable detail
Bad:  "本文档描述了一个关于..."  ← meta-description, not a summary

Rules:
- State the specific problem/topic and its consequence/purpose.
- Use the document's own language (Chinese doc → Chinese brief).
- Include the most distinctive technical detail (component name, error type, threshold).

## key_facts (list of strings, required)

Every important factual statement in the document. This is the core of extraction — \
downstream quality depends entirely on completeness here.

What IS a key_fact:
- Cause-effect relationships: "ECC corrected error > 2000/h 触发 BIOS uncorrectable 阈值"
- Quantitative thresholds: "burn-in 时间不应少于 72 小时"
- Technical conditions: "DIMM 交换后 ECC 错误跟随 DIMM 迁移到新 slot → 确认 DIMM 本体故障"
- Environment specs: "Intel Sapphire Rapids 双路，Samsung DDR5-4800 RDIMM 32GB × 16"
- Behavioral rules: "腕带电阻应在 1MΩ ± 10% 范围内"
- Design rationale: "选择 Gen4 因为 Gen5 有 15% link training 失败率"
- Outcome/conclusion: "更换 DIMM 后 72h burn-in ECC 错误为 0，问题解决"

What is NOT a key_fact:
- Vague filler: "进行了排查" "检查了一下" — no specific information
- Duplicate of another fact already extracted
- Pure formatting/structural text: "如下表所示" "详见附录"

Rules:
- One fact per item. Do NOT merge multiple facts into one sentence.
- Write each fact as a complete, standalone sentence.
- Preserve specific numbers, model names, version strings, error messages verbatim.
- For a typical document, expect 10-30 key_facts. Fewer than 5 suggests under-extraction.

## commands (list of strings, required)

Every command, code snippet, config fragment, or API call in the document.

Rules:
- Copy EXACTLY as written in the source — character for character, including flags, \
  pipes, variable names, and line continuations.
- Each item = one logical command or one code block. Multi-line commands stay as one item.
- Include: shell commands, API calls (curl), config snippets, file paths used as commands.
- Exclude: output/result text, prose descriptions of what to do manually.
- Drop leading `$ ` prompt prefix if present.
- If the document has no commands or code, return `[]`.

## symptoms (list of strings, required for pitfall; empty [] for other types)

Observable signs that an engineer would see or measure. Each symptom must be \
specific enough to match against a real situation.

Good: "lspci 无法识别 GPU 卡，或识别为 unknown device"
Good: "BMC SEL 日志中 Memory ECC Error 事件递增，集中在 slot A1/DIMM 0"
Bad:  "系统有问题" ← too vague
Bad:  "需要排查" ← not an observable symptom

Rules:
- Include error messages, log patterns, LED states, metric thresholds, behavioral anomalies.
- Each symptom = one observable condition. Do not combine multiple symptoms.
- For non-pitfall documents (process, guideline, model, decision), return `[]`.

## resolution_branches (list of objects, required for pitfall; empty [] for other types)

Distinct diagnostic/resolution paths in the document. Each branch represents a \
different route an engineer takes based on what they observe.

Rules:
- `"when"`: the observable condition or decision point that leads to this branch.
- `"label"`: a short name for this branch/path.
- If the document describes a LINEAR resolution (no branching), return one branch.
- If the document has explicit paths like "路径 A / 路径 B" or "If X → do A; if Y → do B", \
  extract each as a separate branch.
- For non-pitfall documents, return `[]`.

# Output format

```json
{{
  "brief": "one sentence ≤150 chars",
  "key_facts": ["fact 1", "fact 2", "..."],
  "commands": ["cmd 1", "cmd 2", "..."],
  "symptoms": ["symptom 1", "..."],
  "resolution_branches": [{{"when": "...", "label": "..."}}, "..."]
}}
```
"""


def _build_system_prompt(suggested_type: str | None) -> str:
    """Assemble the full system prompt with type-specific guidance."""
    guidance = _TYPE_GUIDANCE.get(suggested_type or "", "")
    if not guidance:
        guidance = (
            "## Type-specific extraction focus\n\n"
            "No specific type was identified. Extract all facts, commands, "
            "symptoms (if any), and resolution branches (if any) faithfully."
        )
    return _SUMMARIZER_BASE_PROMPT.format(type_guidance=guidance)


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
    for key in ("key_facts", "commands", "symptoms"):
        val = data.get(key)
        if val is None:
            data[key] = []
        elif not isinstance(val, list):
            data[key] = [str(val)]
        else:
            data[key] = [str(item) for item in val]

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
        messages: list[Any] = [
            {
                "role": "user",
                "content": (
                    f"Extract a complete summary from this document "
                    f"({total_chars} characters total). "
                    f"Document type: {type_label}.\n\n"
                    f"Use read_document_range(start_char=0, end_char={min(total_chars, 8000)}) "
                    f"to start reading. For documents over 8000 chars, make additional calls "
                    f"to read the remaining parts.\n\n"
                    f"Then output the JSON summary."
                ),
            }
        ]

        # Tool-use loop
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

        # Extract text output
        raw = self._extract_text(messages)
        if not raw:
            # Nudge LLM to emit JSON
            self.reporter.info("Summarizer: 催促输出 JSON...")
            messages.append({
                "role": "user",
                "content": (
                    "You have read enough. Now output the JSON summary immediately. "
                    "Output ONLY the JSON object, nothing else."
                ),
            })
            _, _, messages, _ = self.provider.complete(
                messages=messages,
                system=system_prompt,
                model=self.model,
                max_tokens=4096,
                tools=[],
            )
            raw = self._extract_text(messages)

        parsed = self._parse_summary(raw)
        if parsed is not None:
            n_facts = len(parsed.get("key_facts", []))
            n_cmds = len(parsed.get("commands", []))
            n_syms = len(parsed.get("symptoms", []))
            n_branches = len(parsed.get("resolution_branches", []))
            self.reporter.done(
                f"Summarizer: {n_facts} facts, {n_cmds} commands, "
                f"{n_syms} symptoms, {n_branches} branches"
            )
            return parsed

        _preview = raw[:200].replace("\n", "\\n") if raw else "(empty)"
        self.reporter.warn(f"Summarizer: JSON 解析失败 | raw: {_preview}")
        return None

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
