# Research: Three-Phase Pipeline Stability Fixes (D-1~D-7)

**Feature**: 016-fix-pipeline-stability
**Date**: 2026-06-08

No external research needed — all seven issues have clear root causes in the existing codebase confirmed by the v14 usage report and code inspection.

---

## D-1: Extractor Draft YAML Frontmatter Parse Errors

**Root cause confirmed**: `_extract_draft()` in `extractor.py` returns the raw LLM output without any format validation. The LLM sometimes outputs:
- Markdown fences without closing `---` (e.g., `---\ntitle: foo\n` with no closing `---`)
- Prose preamble before the frontmatter (`"Here is the KB entry:\n---\n..."`)
- Unescaped colons inside YAML values

**Decision**: Add a `_validate_and_repair_draft()` static method in `ExtractorAgent` that:
1. Strips prose preamble before `---`
2. Checks for closing `---`; if missing, appends it
3. Validates the frontmatter is parseable; if not, wraps with a minimal valid frontmatter
4. Returns `(repaired_draft, warning_message_or_None)`

In `pipeline.py`, before passing a draft to the verifier loop, call this method. If validation fails and repair is impossible, append a warning to `report.warnings` with the KP ID and continue (do not silently drop).

**Rationale**: Repair-first approach maximizes entry creation rate. The repaired entry may have lower quality, but it enters the verification loop where the verifier can further correct it — better than silent discard.

**Alternative considered**: Retry Extractor with a corrective prompt. Rejected: adds LLM cost for every malformed draft, and the root fix (D-2) reduces malformation frequency.

---

## D-2: Extractor Command Summarization

**Root cause confirmed**: `EXTRACTOR_SYSTEM_PROMPT` contains the instruction "Only include content that has direct support in the source section." The LLM interprets this as "paraphrase faithfully" rather than "copy verbatim." Shell commands are transformed into step descriptions.

**Decision**: Add explicit verbatim-copy instruction to `EXTRACTOR_SYSTEM_PROMPT`:
```
For the ## Resolution section: copy shell commands VERBATIM from the source text.
Do NOT paraphrase, summarize, or describe commands — paste them as-is, including
all flags, arguments, and syntax. Prose descriptions may be paraphrased, but
any text inside code blocks must be copied exactly.
```

**Rationale**: Explicit verbatim instruction is the minimum change to fix the root cause. No code change needed — prompt-only fix.

**Alternative considered**: Post-process extractor output to find/inject commands from source. Rejected: requires re-parsing the source, fragile, and complex.

---

## D-3: Reader KP Over-Splitting

**Root cause confirmed**: `READER_SYSTEM_PROMPT` instructs "Register EVERY distinct knowledge point" and "Do not merge unrelated topics." The LLM over-applies this: for a single incident, it registers symptoms, root cause, and resolution as three separate KPs.

**Decision**: Add scoping guidance to `READER_SYSTEM_PROMPT`:
```
KNOWLEDGE POINT SCOPING:
- One incident = ONE pitfall KP. Do NOT split symptoms, root cause, and
  resolution of the same problem into separate knowledge points.
- A knowledge point represents a PROBLEM + its SOLUTION, not a section of text.
- Split only when topics are clearly independent (different systems, different
  time periods, or explicitly labeled as separate incidents).
```

**Rationale**: Prompt-only fix. Clearest way to constrain KP granularity without adding complex logic.

**Alternative considered**: Post-process KPs to merge overlapping ranges. Rejected: heuristic merging is error-prone and harder to reason about.

---

## D-4: Silent 0-KP Exit

**Root cause confirmed**: `pipeline.py` `run()` calls `reader.run()` and proceeds normally even when `len(knowledge_map.knowledge_points) == 0`. The extraction loop is skipped due to the coverage gate, but no warning is surfaced.

**Decision**: After `reader.run()`, add a guard:
```python
if len(knowledge_map.knowledge_points) == 0:
    report.warnings.append(
        "No knowledge points identified — document may not contain "
        "incident or runbook content recognizable to the Reader."
    )
```

`ImportReport.warnings` already exists — no data model change needed.

**Rationale**: Minimal change. The existing `warnings` list is already rendered in `format_verbose()` and `format_summary()`.

---

## D-5: Semantic Deduplication Not Triggered

**Root cause confirmed** (by code inspection): `compare_root_cause` IS registered in `TOOL_DEFINITIONS` and `TOOL_HANDLERS`. It IS available in the extraction loop via `runner._dispatch_tool`. However, the pre-extracted drafts prompt in `_run_extraction_loop()` gives the LLM a 3-step instruction ("1. verify_content, 2. write_kb_entry, 3. evaluate_skill") that never mentions `compare_root_cause`. The LLM follows the explicit steps and never calls dedup.

**Decision**: Update the pre-extracted drafts prompt in `pipeline.py` `_run_extraction_loop()` to include dedup as step 0:
```
For each draft:
0. Call compare_root_cause with the draft title and root cause to check for
   existing similar entries. If a match is found (similarity ≥ 0.8), call
   write_kb_entry with update=True to merge instead of creating a new entry.
1. Call verify_content ...
2. Call write_kb_entry ...
3. Call evaluate_skill / create_skill_for_entry if appropriate.
```

**Rationale**: The tool and handler already work correctly. Only the LLM instruction is missing.

---

## D-6: Skill run.sh Empty Template

**Root cause confirmed**: `_run_skill_and_curation()` in `runner.py` calls `create_skill_for_entry()` in `tools.py`, which calls `create_skill()` in `manager.py`, which calls `generate_run_sh_template()` — a fixed template with no commands. The `resolution_text` (available in `_run_skill_and_curation`) is never passed to the skill creation path.

**Decision**:
1. Add `commands: list[str]` parameter to `create_skill()` in `manager.py`. When non-empty, write those commands to `run.sh` instead of the placeholder.
2. Add `resolution_commands: list[str]` to the `create_skill_for_entry` tool input schema.
3. In `_run_skill_and_curation()`, call `detect_commands(resolution_text)` and pass the result as `resolution_commands` when calling `create_skill_for_entry`.

`detect_commands()` already exists in `holmes/kb/agent/skill_advisor.py` (or equivalent). The command list is available at the point of Skill creation.

**Rationale**: Minimal change to the existing call chain. `generate_run_sh_template()` is still used for the script header; only the command body is filled in.

---

## D-7: Verbose Trace Mixed Signals

**Root cause confirmed**: `DecisionTrace` has two separate lists: `field_sources` (verified fields → source fragments) and `unsupported_fields` (cleared fields). When `write_kb_entry` or verifier-related tools update the trace for the same field across multiple verify_content calls, both lists can contain the same field name. `format_verbose()` renders both without checking for overlap.

**Decision**: In `write_kb_entry` (or wherever `DecisionTrace` field_sources/unsupported_fields are updated), enforce last-write-wins:
- When adding a field to `field_sources`, remove it from `unsupported_fields` if present.
- When adding a field to `unsupported_fields`, remove it from `field_sources` if present.

This is a one-line guard at each mutation point — no change to the `format_verbose()` rendering logic.

**Location**: `tools.py` `write_kb_entry()` function, where the `DecisionTrace` trace is updated.

---

## Summary of Decisions

| D# | Priority | Fix Type | Files Changed |
|----|----------|----------|--------------|
| D-1 | P1 | Code + validation | `extractor.py`, `pipeline.py` |
| D-2 | P1 | Prompt | `extractor.py` (EXTRACTOR_SYSTEM_PROMPT) |
| D-3 | P2 | Prompt | `reader.py` (READER_SYSTEM_PROMPT) |
| D-4 | P2 | Code (1 guard) | `pipeline.py` |
| D-5 | P2 | Prompt | `pipeline.py` (_run_extraction_loop user prompt) |
| D-6 | P2 | Code (pass commands) | `runner.py`, `tools.py`, `manager.py` |
| D-7 | P3 | Code (last-write-wins) | `tools.py` (write_kb_entry trace update) |
