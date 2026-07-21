# Implementation Plan: Import Pipeline Quality Normalization

**Branch**: `018-import-quality-normalizer` | **Date**: 2026-06-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/018-import-quality-normalizer/spec.md`

## Summary

Add a deterministic Normalizer layer and DocumentClassifier to the three-phase import pipeline; expand the category schema to 8 values; replace LLM-written Skill content with `detect_commands()`; add verbatim command fallback for Verifier-CLEARed Resolution sections; fix Skill lifecycle bugs (E-1, E-11, E-12, E-8); fix CLI UX bugs (E-4, E-6, E-5). All fixes are model-agnostic — they work identically on gpt-4o and deepseek-v4-flash.

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: `python-frontmatter`, `click`, `openai` (SDK), `pytest`

**Storage**: File system (KB data at `~/.holmes-kb/`; pending entries at `contributions/pending/*.md`; skills at `skills/*/`)

**Testing**: pytest; existing 582 tests in `kb/tests/`

**Target Platform**: Linux (Ubuntu), developer machine

**Project Type**: CLI tool + Python library

**Performance Goals**: Normalizer adds ≤5ms per draft (pure Python, no I/O). DocumentClassifier adds 1 LLM call per import (acceptable overhead for preview accuracy).

**Constraints**: No new pip dependencies; all fixes contained to `kb/` subtree; no breaking changes to existing `ImportReport`, `KnowledgeMap`, `SkillAdvice` public APIs.

**Scale/Scope**: Single-developer KB; 50–500 imports per week; ≤1000 pending entries.

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| 开闭原则 | ✅ | Category expansion is additive. Normalizer and Classifier are new modules, no existing code modified beyond injection points. |
| 依赖倒置原则 | ✅ | Normalizer takes `str` input/output (no dependency on LLM or provider). Classifier depends on `LLMProvider` interface. |
| 单一职责原则 | ✅ | `DraftNormalizer` only normalizes drafts. `DocumentClassifier` only classifies. `SkillAdvisor` only advises. |
| 接口隔离原则 | ✅ | `normalize(draft, kb_type)` is minimal. `classify(source_text)` is minimal. |
| 验证原则 | ✅ | New modules `test_normalizer.py` and `test_classifier.py` required. All modified existing files have existing tests to extend. |
| 渐进式实现原则 | ✅ | No speculative abstractions. Normalizer is a single class with one public method. |
| 可观测性原则 | ✅ | All Normalizer actions surface in `report.warnings`. Classifier result logged to `report.phase_traces`. |
| 环境配置原则 | ✅ | No new config. Reuses `HolmesConfig`. |
| 代码规范 | ✅ | Google Python style; type annotations; docstrings. |

## Project Structure

### Documentation (this feature)

```text
specs/018-import-quality-normalizer/
├── plan.md              # This file
├── research.md          # Technical decisions
├── data-model.md        # Entities and interfaces
├── quickstart.md        # Integration scenarios
├── contracts/
│   └── normalizer.md   # DraftNormalizer + DocumentClassifier contracts
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code Changes

```text
kb/
├── holmes/kb/
│   ├── schema.py                          # MODIFY: expand VALID_PITFALL_CATEGORIES (4→8); TITLE_MAX_LENGTH→60 note
│   ├── agent/
│   │   ├── normalizer.py                  # NEW: DraftNormalizer class
│   │   ├── pipeline.py                    # MODIFY: inject Classifier + Normalizer + Resolution fallback
│   │   ├── report.py                      # MODIFY: format_dry_run_plan uses knowledge_map KP count
│   │   ├── runner.py                      # MODIFY: fix _finalize_skill_generation; fix _dispatch_tool; {PARAM} extraction
│   │   ├── skill_advisor.py               # MODIFY: threshold ≥3; add _find_similar_skill
│   │   └── phases/
│   │       ├── classifier.py              # NEW: DocumentClassifier + DocumentType enum
│   │       └── extractor.py              # MODIFY: EXTRACTOR_SYSTEM_PROMPT verbatim constraint
│   ├── skill/
│   │   └── manager.py                    # MODIFY: create_skill accepts param_names; writes params to SKILL.md
│   └── provider/
│       └── openai_provider.py            # MODIFY: wrap 401/429/5xx errors
│
├── cli.py                                 # MODIFY: dry-run Reader pass; batch title display
│
└── tests/
    ├── test_normalizer.py                 # NEW: unit tests for DraftNormalizer
    ├── test_classifier.py                 # NEW: unit tests for DocumentClassifier
    ├── test_schema.py                     # EXTEND: new category values
    ├── test_skill_advisor.py              # EXTEND: threshold + LINK tests
    ├── test_pipeline.py                   # EXTEND: Normalizer + Classifier integration
    └── test_agent_runner.py              # EXTEND: skill gate, {PARAM} tests
```

## Implementation Details

### Root A — DraftNormalizer (`normalizer.py`)

**Class**: `DraftNormalizer`
**Method**: `normalize(draft: str, kb_type: str | None = None) -> tuple[str, list[str]]`

**Operations** (applied in order):

1. **Parse frontmatter**: `frontmatter.loads(draft)`. If parse fails → return `(draft, ["warning: ..."])`.
2. **Header translation**: scan body for `## <chinese>` headers, replace using `HEADER_MAP`. Log each translation.
3. **Title enforcement**: if `len(title) > 60`, truncate at last space ≤60 chars. If title is null/empty, generate from first 60 chars of `root_cause`. Log action.
4. **Tags extraction**: if `tags` is missing or `len(tags) < 3`, extract keywords. Log count added.
5. **Type-level structural constraints** (only if `kb_type` or frontmatter `type` known):
   - `guideline` + body contains `## Symptoms`: remove that section. Log.
   - `pitfall` + body `## Resolution` empty: add warning (do not remove).
6. **Category normalization**: if `category` not in `VALID_PITFALL_CATEGORIES`, map or default to `system`. Log original + corrected.
7. **Serialize**: `frontmatter.dumps(post)` → return.

**Injection point in `pipeline.py`**:
```python
draft = extractor.run(kp, knowledge_map, ctx)
if draft:
    # NEW: deterministic normalization (Root A)
    normalizer = DraftNormalizer()
    kb_type_hint = kp.type_hint or ""
    draft, norm_warnings = normalizer.normalize(draft, kb_type=kb_type_hint)
    for w in norm_warnings:
        report.warnings.append(f"{kp.id}: {w}")
    # ... existing _validate_and_repair_draft call
```

---

### Root B — Category Schema Expansion (`schema.py`)

```python
VALID_PITFALL_CATEGORIES: frozenset[str] = frozenset({
    "network", "system", "application", "database",
    "kubernetes", "messaging", "cache", "monitoring",  # NEW
})
```

**Prompt updates** (4 files):
- `runner.py` line ~47: `"network/system/application/database"` → `"network/system/application/database/kubernetes/messaging/cache/monitoring"`
- `extractor.py` EXTRACTOR_SYSTEM_PROMPT category field: update enum list
- `reader.py` category description: update example list
- `importer.py` template comment: update list

---

### Root C — Deterministic Skill Generation

**`skill_advisor.py`**: revert RECOMMENDED threshold from ≥2 to ≥3.

**`manager.py` `create_skill()`**: add `param_names: Optional[list[str]] = None` parameter. When non-empty, write `params:` block to SKILL.md frontmatter:
```yaml
params:
  - name: POD_NAME
    description: POD_NAME
    required: false
    default: ""
```

**`runner.py` `_run_skill_and_curation()`**: after `detect_commands(resolution_text)`, extract `{UPPERCASE_NAME}` patterns:
```python
import re
_PARAM_RE = re.compile(r"\{([A-Z_]+)\}")
param_names = list(dict.fromkeys(
    p for cmd in extracted_commands for p in _PARAM_RE.findall(cmd)
))
```
Pass `param_names` to `create_skill_for_entry` or directly to `create_skill()`.

**`runner.py` `_dispatch_tool()`**: for `create_skill_for_entry` tool calls from LLM, override `resolution_commands` in `tool_input` with `detect_commands()` result from `_created_entry_contents[entry_id]`'s Resolution section. This ensures LLM-path Skill generation is also deterministic.

---

### Root D — DocumentClassifier (`phases/classifier.py`)

**Injection point in `pipeline.py` `run()`**, before Reader:
```python
classifier = DocumentClassifier(provider=self._provider, model=self.cfg.model)
classification = classifier.classify(source_text)
report.phase_traces.append(f"Classifier: {classification.doc_type.value} — {classification.reason}")

if classification.doc_type == DocumentType.non_kb:
    report.warnings.append(f"non-kb document: {classification.reason} — skipped")
    return report

ctx["granularity_hint"] = classification.granularity_hint
```

**ReaderAgent prompt update**: if `ctx.get("granularity_hint")`, prepend hint to Reader system prompt for that run.

---

### Root E — Verbatim Command Fallback (`pipeline.py`)

After `_validate_and_repair_draft()` in the extraction loop:
```python
# Root E: restore empty Resolution for pitfall entries
if kb_type == "pitfall" and _is_resolution_empty(repaired):
    source_slice = source_text[kp.section_start:kp.section_end]
    recovered_cmds = detect_commands(source_slice)
    if recovered_cmds:
        repaired = _inject_resolution(repaired, recovered_cmds)
        report.warnings.append(f"{kp.id}: resolution auto-recovered from source ({len(recovered_cmds)} commands)")
```

Helper functions `_is_resolution_empty(draft)` and `_inject_resolution(draft, commands)` are module-level functions in `pipeline.py`.

---

### E-1 Fix — `_finalize_skill_generation`

Remove the early-return that skips all entries when any skill was already generated:
```python
# BEFORE (buggy):
if report.skills_generated or report.skills_linked:
    return

# AFTER: skip only if ALL entries were already processed
# (check is now per-entry via SkillAdvisor._find_existing_skill)
```

The per-entry `_run_skill_and_curation` already uses `SkillAdvisor` which checks `skill_refs` in frontmatter; duplicate detection is per-entry, not per-report.

---

### E-11 Fix — Skill LINK (`skill_advisor.py`)

Add `_find_similar_skill(kb_root, proposed_description)` that:
1. Scans `kb_root / "skills"` for `*/SKILL.md` files.
2. Loads each SKILL.md frontmatter, extracts `description` field.
3. Computes token-overlap ratio: `len(tokens(a) ∩ tokens(b)) / len(tokens(a) ∪ tokens(b))` (Jaccard similarity).
4. If any existing skill has ratio ≥ 0.7 with proposed description, return that skill's name.
5. Returns `None` if no similar skill found.

Called in `advise()` before creating a new RECOMMENDED slug.

---

### E-12 Fix — Interactive Skill Gate in Tool Path

In `runner.py` `_dispatch_tool()`, for `create_skill_for_entry`:
```python
if name == "create_skill_for_entry":
    skill_name = tool_input.get("name", "")
    # E-12: interactive gate for LLM-called create_skill_for_entry
    if not self.no_interactive:
        confirmed = self._gate_skill_create(skill_name)
        if not confirmed:
            return {"created": False, "linked": False, "action": "skipped (user declined)"}
    # ... proceed with actual create
```

---

### E-4 Fix — Dry-Run Preview (`pipeline.py` + `report.py`)

In `pipeline.run()`, when `dry_run=True`:
1. Run DocumentClassifier (cheap).
2. Run ReaderAgent (no writes; reads source only).
3. Skip Extractor, Verifier, Writer phases.
4. Return report with `report.knowledge_map = knowledge_map`.

In `report.py` `format_dry_run_plan()`:
```python
if self.knowledge_map and self.knowledge_map.knowledge_points:
    kp_count = len(self.knowledge_map.knowledge_points)
    lines.append(f"  Would process: (~{kp_count} knowledge points estimated)")
elif self.warnings and any("non-kb" in w for w in self.warnings):
    lines.append(f"  Would reject: non-kb document")
else:
    lines.append(f"  Would process: (Reader phase not run)")
```

---

### E-6 Fix — Batch Title Display (`cli.py`)

In `import_cmd()` per-file loop, after `_print_report`:
```python
# E-6: use entry title instead of pending ID for batch display
display_name = source_file.name
if report.created:
    # extract title from first created entry's pending file
    display_name = _get_pending_title(report.created[0], kb_root) or source_file.name
click.echo(f"[{idx}/{total}] {display_name} — {summary}")
```

Helper `_get_pending_title(pending_id, kb_root)` reads the pending file and extracts the `title` frontmatter field.

---

### E-5 Fix — API Error Messages (`openai_provider.py`)

```python
try:
    response = self._client.chat.completions.create(...)
except openai.AuthenticationError:
    raise RuntimeError(
        "Authentication failed — API key rejected. "
        "Check your key with: holmes config set api_key <KEY>"
    ) from None
except openai.RateLimitError:
    raise RuntimeError(
        "Rate limit reached. Wait a moment and retry, or check your plan quota."
    ) from None
except openai.APIStatusError as exc:
    raise RuntimeError(
        f"LLM provider returned a server error (HTTP {exc.status_code}). "
        "Check provider status or retry."
    ) from None
```

## Complexity Tracking

No constitution violations. All changes are either additive (new modules) or targeted bug fixes in existing methods.

## Test Strategy

| Test File | Coverage |
|-----------|---------|
| `test_normalizer.py` (new) | All 6 normalization operations; edge cases (null title, empty body, parse failure) |
| `test_classifier.py` (new) | All 5 document types; LLM failure fallback; non-kb rejection |
| `test_schema.py` (extend) | New 4 category values accepted; old 4 still valid; invalid still rejected |
| `test_skill_advisor.py` (extend) | ≥3→RECOMMENDED; 1-2→OPTIONAL; LINK by description similarity |
| `test_pipeline.py` (extend) | Normalizer injection; Classifier injection; Resolution fallback |
| `test_agent_runner.py` (extend) | `_finalize_skill_generation` early-return fix; {PARAM} extraction; E-12 interactive gate |
