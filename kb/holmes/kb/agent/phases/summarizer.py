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
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.progress import NullReporter, ProgressReporter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SUMMARIZER_ITERATIONS = 15  # tool-call iterations (safety cap)
DIRECT_MODE_CHAR_LIMIT = 8000   # docs under this size skip tool-use loop


# ---------------------------------------------------------------------------
# Document skeleton — programmatic outline extraction (zero LLM calls)
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


def extract_document_outline(source: str) -> list[dict[str, Any]]:
    """Extract headings from source document as a structured outline.

    Returns list of {"level": int, "text": str, "offset": int, "length": int}.
    ``length`` is the character count from this heading to the next heading
    (or end of document).
    """
    headings: list[dict[str, Any]] = []
    for m in _HEADING_RE.finditer(source):
        headings.append({
            "level": len(m.group(1)),
            "text": m.group(2).strip(),
            "offset": m.start(),
        })
    # Compute section lengths
    total = len(source)
    for i, h in enumerate(headings):
        next_offset = headings[i + 1]["offset"] if i + 1 < len(headings) else total
        h["length"] = next_offset - h["offset"]
    return headings


# Sections above this threshold get a size warning in the prompt
_LARGE_SECTION_CHARS = 3000


def format_outline_for_prompt(outline: list[dict[str, Any]], total_chars: int) -> str:
    """Format outline into a concise string for injection into LLM prompt."""
    if not outline:
        return ""
    lines = [f"Document outline ({len(outline)} sections, {total_chars} chars total):"]
    for h in outline:
        indent = "  " * (h["level"] - 1)
        length = h.get("length", 0)
        size_hint = f"  ⚠ LARGE ({length} chars)" if length >= _LARGE_SECTION_CHARS else ""
        lines.append(
            f"{indent}{'#' * h['level']} {h['text']}  "
            f"[char {h['offset']}–{h['offset'] + length}]{size_hint}"
        )
    lines.append("")
    lines.append(
        "Ensure ALL sections above are covered in your extraction. "
        "For LARGE sections, make multiple read_document_range calls to cover the full content."
    )
    return "\n".join(lines)


def check_outline_coverage(
    outline: list[dict[str, Any]],
    summary: dict[str, Any],
) -> list[str]:
    """Check which outline ### sections are not reflected in the summary.

    Only checks ### (level 3) headings — these are the content-level sections
    most likely to represent distinct branches or steps. ## headings are
    structural (Symptoms, Resolution) and covered by type-level checks elsewhere.

    Returns list of uncovered section texts (empty = full coverage).
    """
    if not outline:
        return []

    # Only check ### headings (level 3) — the content sections
    h3_headings = [h for h in outline if h["level"] == 3]
    if not h3_headings:
        return []

    # Build a lowercase search corpus from all summary fields
    corpus_parts: list[str] = []
    corpus_parts.append(summary.get("brief", ""))
    corpus_parts.extend(summary.get("key_facts", []))
    for cmd_item in summary.get("commands", []):
        if isinstance(cmd_item, dict):
            corpus_parts.append(cmd_item.get("cmd", ""))
            corpus_parts.append(cmd_item.get("expected", ""))
        else:
            corpus_parts.append(str(cmd_item))
    corpus_parts.extend(summary.get("symptoms", []))
    for b in summary.get("resolution_branches", []):
        if isinstance(b, dict):
            corpus_parts.append(b.get("when", ""))
            corpus_parts.append(b.get("label", ""))
    corpus = "\n".join(str(p) for p in corpus_parts).lower()

    # Common heading prefixes that appear in many sections — not distinctive
    _STOP_TERMS = frozenset({
        "路径", "step", "步骤", "分支", "path", "branch", "phase", "阶段",
        "问题", "issue", "处理", "排查",
    })

    uncovered: list[str] = []
    for h in h3_headings:
        text = h["text"]
        # Extract CJK bigrams + ASCII words as search tokens
        # This handles "物理连接问题" → ["物理", "理连", "连接", "接问", "问题"]
        tokens: list[str] = []
        # ASCII/mixed tokens
        tokens.extend(re.findall(r"[A-Za-z0-9]{2,}", text.lower()))
        # CJK: sliding 2-gram window for substring matching
        cjk_chars = re.findall(r"[\u4e00-\u9fff]+", text)
        for run in cjk_chars:
            if len(run) >= 2:
                for i in range(len(run) - 1):
                    tokens.append(run[i:i+2])

        # Filter out stop terms
        tokens = [t for t in tokens if t not in _STOP_TERMS]
        if not tokens:
            continue

        # A section is "covered" if at least one token appears in corpus
        covered = any(t in corpus for t in tokens)
        if not covered:
            uncovered.append(text)

    return uncovered

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

## commands (list of objects, required)

Every command, code snippet, config fragment, or API call in the document, WITH context.

Each item: `{{"cmd": "<exact command>", "expected": "<what output means>", "risk": "<read|write|danger>"}}`

Fields:
- `cmd`: Copy EXACTLY as written in the source — character for character, including flags, \
  pipes, variable names, and line continuations. Drop leading `$ ` prompt prefix.
- `expected`: What the output tells the engineer. Extract from the source document — \
  look for text AFTER the command that explains normal vs abnormal output, success \
  criteria, or decision logic. If the source says nothing about expected output, write \
  a brief interpretation based on the command's purpose (e.g., "shows PCI device list; \
  empty output means device not detected"). This field is critical — without it, the \
  agent cannot interpret command results.
- `risk`: How dangerous is this command?
  - `"read"` — read-only, zero side effects (lspci, cat, grep, dmesg, ipmitool sensor list)
  - `"write"` — modifies state but recoverable (service restart, config change, BIOS setting)
  - `"danger"` — irreversible or can damage hardware (firmware flash, sel clear, fdisk, \
    factory reset). When in doubt between write and danger, choose danger.

Rules:
- Each item = one logical command or one code block. Multi-line commands stay as one item.
- Include: shell commands, API calls (curl), config snippets, file paths used as commands.
- Exclude: output/result text, prose descriptions of what to do manually.
- If the document has no commands or code, return `[]`.

## symptoms (list of strings — extract if present in any document type)

Observable signs that an engineer would see or measure. Each symptom must be \
specific enough to match against a real situation.

Good: "lspci 无法识别 GPU 卡，或识别为 unknown device"
Good: "BMC SEL 日志中 Memory ECC Error 事件递增，集中在 slot A1/DIMM 0"
Bad:  "系统有问题" ← too vague
Bad:  "需要排查" ← not an observable symptom

Rules:
- Include error messages, log patterns, LED states, metric thresholds, behavioral anomalies.
- Each symptom = one observable condition. Do not combine multiple symptoms.
- If the document has NO observable failure symptoms, return `[]`.
- Do NOT invent symptoms — only extract symptoms explicitly described in the source.

## resolution_branches (list of objects — extract if present in any document type)

Distinct diagnostic/resolution paths in the document. Each branch represents a \
different route an engineer takes based on what they observe.

Rules:
- `"when"`: the observable condition or decision point that leads to this branch.
- `"label"`: a short name for this branch/path.
- Only extract branches when the document describes DIAGNOSTIC BRANCHING — different \
  fix paths chosen based on different observable symptoms/conditions.
- "If X symptom → do A; if Y symptom → do B" = 2 branches.
- A procedure with sequential phases (Step 1 → Step 2 → Rollback) is NOT branching — \
  those are sequential steps, not symptom-driven alternatives. Return `[]` in this case.
- If the document has no branching, return `[]`.

## outline (list of objects, required)

The table of contents for the KB entry you are summarizing. This defines the \
section structure of the final knowledge document. The Generator will follow \
this outline EXACTLY — it cannot add or remove sections.

Each item: `{{"section": "<heading>", "description": "<one-line description>"}}`

Rules:
- One entry per major section (## heading) the KB entry should have.
- Do NOT include "Contents" itself — it is auto-generated from this outline.
- Based on the document's ACTUAL CONTENT, pick the best-matching template below \
  and use its EXACT ENGLISH section names (these are standardized for the KB system):
  - Failure/incident/troubleshooting: **Symptoms**, **Root Cause**, **Resolution**
  - Knowledge/concept/mechanism: **Overview**, **Key Concepts**, **Usage**
  - Rules/standards/policies: **Context**, **Guideline**, **Rationale**
  - Step-by-step procedure: **Purpose**, **Steps**, **Outcome**
  - Architecture/design decision: **Context**, **Decision**, **Rationale**
- ALWAYS use the English section names above, even for Chinese documents. \
  Do NOT translate them to Chinese (e.g. use "Symptoms" not "症状", "Resolution" not "排查过程").
- You may add extra sections (e.g. Prerequisites, Rollback Procedure) using \
  English names if the source has important content outside the template.
- Description should be concise (≤80 chars) and mention COUNTS and KEY TOPICS.
  Example: "4 个可观测现象：lspci 不可见、BIOS POST 超时、dmesg AER 错误、link 降级"
- Use the document's language for descriptions (Chinese doc → Chinese descriptions).

## decision_tree (string, only when ≥3 resolution_branches)

An ASCII decision tree showing the diagnostic flow. Only include when the \
document has 3 or more resolution branches (complex branching).

Rules:
- Root = the top-level symptom or problem.
- Each branch point = an observable condition the engineer can check.
- Use `[A]`, `[B]`, `[C]` labels that match resolution_branches[].label.
- Terminal nodes show the fix with ✓ prefix.
- Cross-branch jumps use → 转 [X].

Example:
```
PCIe link training 失败
├─ lspci 完全看不到设备? ─→ [A] 物理连接问题
│   ├─ 换 slot 后可识别 ─→ ✓ Riser card 损坏，更换
│   └─ 所有 slot 均不识别 ─→ ✓ GPU 卡故障，RMA
├─ 设备可见但 link 降级? ─→ [B] 信号完整性问题
└─ AER 错误风暴? ─→ [C] 电气兼容性问题
```

If fewer than 3 branches, omit this field entirely (do NOT output `"decision_tree": ""`).

# Output format

```json
{{
  "brief": "one sentence ≤150 chars",
  "key_facts": ["fact 1", "fact 2", "..."],
  "commands": [{{"cmd": "lspci -nn", "expected": "shows PCI devices; empty = device missing", "risk": "read"}}, "..."],
  "symptoms": ["symptom 1", "..."],
  "resolution_branches": [{{"when": "...", "label": "..."}}, "..."],
  "outline": [{{"section": "...", "description": "..."}}, "..."],
  "decision_tree": "(only when ≥3 branches)"
}}
```
"""


def _build_system_prompt(suggested_type: str | None) -> str:
    """Assemble the full system prompt with type-specific guidance.

    Type guidance is provided as a HINT to help the LLM focus extraction,
    but all fields (symptoms, branches, etc.) are always extracted if present
    in the source document regardless of the suggested type.
    """
    guidance = _TYPE_GUIDANCE.get(suggested_type or "", "")
    if not guidance:
        guidance = (
            "## Type-specific extraction focus\n\n"
            "No specific type was identified. Extract all facts, commands, "
            "symptoms (if any), and resolution branches (if any) faithfully."
        )
    # Prepend a reminder that extraction is type-agnostic
    guidance = (
        "**IMPORTANT**: The type hint below is a preliminary guess that may be wrong. "
        "Always extract ALL fields from the actual document content:\n"
        "- Extract symptoms if the document describes observable failure signs (even if type hint says 'process').\n"
        "- Extract resolution_branches only for genuine diagnostic branching (symptom → different fix path), "
        "NOT for sequential procedure phases.\n"
        "- Choose outline sections based on what the document ACTUALLY contains, not the type hint.\n\n"
        + guidance
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
