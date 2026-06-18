# Research: Import Pipeline Quality Normalization (018)

**Branch**: `018-import-quality-normalizer` | **Date**: 2026-06-09

## D-001 — Normalizer Injection Point

**Decision**: Inject Normalizer in `pipeline.py` after each `extractor.run()` call, before `_validate_and_repair_draft()`.

**Rationale**: The draft returned by `extractor.run()` is a raw string before validation. Normalizing at this point means `_validate_and_repair_draft` operates on structurally clean content, reducing the number of spurious repair warnings. The Normalizer is stateless (takes draft → returns normalized draft + warnings list), fits cleanly between extractor and validator without coupling to LLM context.

**Alternatives Considered**:
- Inject inside `ExtractorAgent.run()`: Would couple the Normalizer to the Extractor class, violating single-responsibility. Rejected.
- Inject after `_validate_and_repair_draft`: Too late — validation would still flag non-standard headers. Rejected.

---

## D-002 — Category Set Expansion

**Decision**: Expand `VALID_PITFALL_CATEGORIES` in `schema.py` from 4 to 8 values by adding `kubernetes`, `messaging`, `cache`, `monitoring`. Define canonical set in a single constant.

**Rationale**: 13 of 17 invalid-category entries in v15 were `kubernetes`. LLMs consistently identify the correct domain but the schema rejects it. All category references (prompts in `runner.py`, `extractor.py`, `reader.py`, `importer.py`, `schema.py`) must reference the shared constant. Hardcoding category strings in 5 different files was the source of the drift.

**Impact**: 5 files need updating — prompts must enumerate all 8 values. `VALID_PITFALL_CATEGORIES` constant is the single source of truth.

**Alternatives Considered**:
- Accept any string for category: Too permissive; schema integrity lost. Rejected.
- Add only `kubernetes`: Only fixes 13/17 cases; `messaging/cache/monitoring` also real. Rejected.

---

## D-003 — Normalizer: Section Header Translation

**Decision**: Use a hardcoded mapping table in `normalizer.py` for Chinese/non-standard → English standard header translation. Case-insensitive match on the full `## Header` pattern.

**Mapping table** (finite, confirmed from v15 QA-15 data):
```python
HEADER_MAP = {
    "## 症状": "## Symptoms",
    "## 现象": "## Symptoms",
    "## 故障现象": "## Symptoms",
    "## 故障背景": "## Symptoms",
    "## 根因": "## Root Cause",
    "## 根本原因": "## Root Cause",
    "## 根本根因": "## Root Cause",
    "## 解决": "## Resolution",
    "## 解决方案": "## Resolution",
    "## 解决步骤": "## Resolution",
    "## 修复": "## Resolution",
    "## 修复步骤": "## Resolution",
    "## 处理方案": "## Resolution",
    "## 处理步骤": "## Resolution",
    "## 恢复": "## Resolution",
    "## 恢复步骤": "## Resolution",
    "## 操作步骤": "## Resolution",
    "## 诊断步骤": "## Resolution",
    "## 经验": "## Resolution",  # "Lessons" → append to Resolution or drop
}
```

Unknown headers: leave unchanged, log warning. No ML matching.

---

## D-004 — Normalizer: Title Handling

**Decision**: Truncate title to ≤60 characters at the last word boundary. If title is null/empty/whitespace, generate a fallback from the first sentence of `root_cause` (≤60 chars). `TITLE_MAX_LENGTH` in `schema.py` stays at 100 (schema validation is for committed entries; Normalizer applies stricter 60-char limit for pending entries to improve search UX).

**Rationale**: Schema validation and pending-entry quality are separate concerns. The 100-char schema limit prevents egregiously long titles in committed KB; the 60-char Normalizer limit keeps titles searchable and readable in list views.

---

## D-005 — Normalizer: Tags Auto-Extraction

**Decision**: When `tags` field is missing or has fewer than 3 entries, extract keywords from `title` + `root_cause` combined text using stopword filtering + frequency ranking. Minimum ≥3 tags, maximum 8. Tags are lowercase, no special characters.

**Algorithm**:
1. Tokenize `title` + `root_cause` by splitting on whitespace and punctuation.
2. Lowercase all tokens.
3. Remove stopwords: common Chinese particles, English stopwords (a, the, in, of, etc.).
4. Remove tokens shorter than 3 chars.
5. Remove tokens that are only digits.
6. Deduplicate, take top 8 by frequency (falling back to first-occurrence order).
7. If fewer than 3 remain, include the top words from title regardless of stopwords.

**Rationale**: Tags drive KB search and filtering; 125/126 pending entries had empty tags. No ML needed — frequency-based keyword extraction is deterministic and sufficient for incident/ops terminology.

---

## D-006 — Normalizer: Type-Level Structural Constraints

**Decision**: Apply after header translation so checks use standardized English headers.
- `guideline` + has `## Symptoms` → remove the `## Symptoms` section entirely.
- `pitfall` + `## Resolution` section is empty (or missing) → add warning to report; do NOT remove the header (Root E verbatim fallback may fill it).

**Rationale**: Keeping the empty `## Resolution` header allows Root E fallback to inject content by matching the section; removing it would leave no hook for fallback. Warning (not error) because fallback runs next.

---

## D-007 — DocumentClassifier Design

**Decision**: Single LLM call before `ReaderAgent`. Returns a JSON object `{"doc_type": "...", "reason": "..."}`. Uses a short, targeted system prompt (≤200 tokens). Defaults to `single-incident` on any parse failure.

**Document types**:
- `single-incident` — one incident/failure, fine-grained KP extraction (default)
- `multi-incident` — multiple distinct incidents in one doc; Reader gets KP-per-incident guidance
- `runbook` — sequential operational procedure; Reader gets "≤8 high-level procedure KPs" guidance
- `guideline` — best-practice or standard; Reader gets "one KP per rule/principle" guidance
- `non-kb` — meeting notes, tables, org content; pipeline rejects, adds warning to report

**Timeout/Fallback**: If LLM call raises exception or JSON parse fails → `doc_type = "single-incident"`, no rejection, pipeline continues with a warning.

**Rationale**: One additional LLM call per document is acceptable overhead. Non-LLM heuristics (keyword detection) were considered but rejected — they have high false-positive rate on Chinese incident reports that contain meeting-style language.

---

## D-008 — Root E: Extractor Verbatim Constraint + Verifier Fallback

**Decision**: Two-part fix:
1. Add to `EXTRACTOR_SYSTEM_PROMPT`: "All commands in the ## Resolution section MUST be copied verbatim from the source text. Do NOT paraphrase, summarize, or reconstruct commands. If you cannot find the exact commands in your assigned section, write ONLY the commands that appear word-for-word in the source, and omit the rest."
2. After each `extractor.run()` → Normalizer → `_validate_and_repair_draft()`, add a pitfall-specific fallback: if draft is `pitfall` type AND `## Resolution` section is empty, call `detect_commands()` on the source text slice for that KP's character range and inject the result into `## Resolution` with an `[auto-recovered from source]` prefix.

**Where**: In `pipeline.py`, in the extraction loop, after repair step.

**Rationale**: Prompt constraint alone reduces D-2 occurrences. Deterministic fallback eliminates QA-16 for pitfall entries — even when Extractor hallucinates commands that get CLEARed, the fallback restores what was actually in the source.

---

## D-009 — Skill Run.sh Deterministic Generation (Root C)

**Decision**: The existing `create_skill` in `manager.py` already has D-6 fix (writes actual commands to run.sh when `commands` list is passed). The gap is {PARAM} extraction: `create_skill(commands=...)` doesn't extract `{UPPERCASE_NAME}` placeholders into `SKILL.md params:` field.

**Fix**: In `_run_skill_and_curation` (runner.py), after `detect_commands(resolution_text)`:
1. Collect all `{UPPERCASE_NAME}` matches from command strings using `re.findall(r"\{([A-Z_]+)\}", cmd)` for each cmd.
2. Deduplicate param names.
3. Pass `params=param_names` to `create_skill()`.
4. Update `create_skill()` to accept a `params` list and write the `params:` block to `SKILL.md` when non-empty.

**LLM path**: When the LLM calls `create_skill_for_entry` as a tool, the `resolution_commands` in the tool input should be replaced by the deterministically extracted commands. In `_dispatch_tool`, before calling `create_skill_for_entry`, apply `detect_commands()` on the entry's resolution section from `_created_entry_contents` and override `tool_input["resolution_commands"]`.

---

## D-010 — SkillAdvisor Threshold (E-8 fix)

**Decision**: Revert RECOMMENDED threshold from ≥2 to ≥3. The C-2c comment that lowered it was premature — v15 E-8 confirms this caused unwanted auto-creation for 2-step docs.

Updated criteria:
- ≥3 commands → `RECOMMENDED` (auto-create in no-interactive, prompt in interactive)
- 1–2 commands → `OPTIONAL` (suggestion only, no auto-create)
- 0 commands → `SKIP`

---

## D-011 — _finalize_skill_generation E-1 Fix

**Decision**: The current early-return `if report.skills_generated or report.skills_linked: return` is over-eager. It prevents skill generation for entries in the same pipeline run where any skill was already created/linked. Fix: remove this early-return. Only skip individual entries that already have a `skill_refs` set (checked per-entry by SkillAdvisor).

**Secondary cause**: E-1 is also caused by empty `## Resolution` in pending files (QA-16). Root E fallback fills the Resolution section before `_finalize_skill_generation` runs (both operate within the same pipeline.run() call flow in pipeline.py). So after Root E fix, `_extract_resolution_section` finds content and Skill generation proceeds.

---

## D-012 — Skill LINK (E-11 fix)

**Decision**: Before calling `create_skill()`, scan the skills/ directory for an existing skill whose SKILL.md `description` field has ≥70% token overlap with the proposed skill description. If found, link instead of create.

**Implementation**: Add `_find_similar_skill(kb_root, description)` to `SkillAdvisor` that reads all existing `SKILL.md` files and compares description using a simple token-overlap ratio. If ratio ≥ 0.7, return the existing skill name.

**Fallback**: If no similar skill found, create new. This avoids false positives for unrelated skills with coincidentally similar descriptions.

---

## D-013 — E-12: Interactive Skill Gate in LLM Tool Path

**Decision**: In `_dispatch_tool` (runner.py), when the LLM calls `create_skill_for_entry` in interactive mode (`not self.no_interactive`), call `self._gate_skill_create(name)` before invoking the tool function. If user declines, return a `{"action": "skipped (user declined)", "created": false, "linked": false}` response to the LLM.

---

## D-014 — Dry-Run Preview (E-4 fix)

**Decision**: In `pipeline.run()`, when `dry_run=True`, run the DocumentClassifier and ReaderAgent phases (read-only, no LLM writes), then return a report with `knowledge_map` populated. The `format_dry_run_plan()` method uses `report.knowledge_map` to display `~N knowledge points estimated`.

For `non-kb` classification: report shows "Would reject" and returns immediately.

**Cost**: One Reader LLM call per dry-run. Acceptable since users explicitly asked for preview.

---

## D-015 — Batch Title Display (E-6 fix)

**Decision**: In `cli.py`, the `[N/M]` progress line for `--dir` batch import currently uses the pending ID as the identifier. Fix: after `_print_report` processes a report, extract the `title` from the first created/updated entry in `report.created` or `report.updated`. If not available, fall back to the source filename.

**Where**: The per-file reporting loop in `import_cmd()` that formats `[N/M] filename — ...`.

---

## D-016 — API Error Handling (E-5 fix)

**Decision**: In `openai_provider.py`, wrap the `complete()` method's API call with specific exception handlers for `openai.AuthenticationError` (401), `openai.RateLimitError` (429), and `openai.APIStatusError` (5xx). Map each to a user-readable `RuntimeError` with a suggested action. The `cli.py` top-level `import_cmd()` already catches `Exception` and prints to stderr — it will print the user-friendly message.

**Message templates**:
- 401: `"Authentication failed — API key rejected. Check your key with: holmes config set api_key <KEY>"`
- 429: `"Rate limit reached. Wait a moment and retry, or check your plan quota."`
- 5xx: `"LLM provider returned a server error (HTTP {status}). Check provider status or retry."`

---

## D-017 — File Structure for New Modules

**New files**:
- `kb/holmes/kb/agent/normalizer.py` — `DraftNormalizer` class (stateless, deterministic)
- `kb/holmes/kb/agent/phases/classifier.py` — `DocumentClassifier` class + `DocumentType` enum
- `kb/tests/test_normalizer.py` — unit tests for all Normalizer scenarios
- `kb/tests/test_classifier.py` — unit tests for DocumentClassifier

**Modified files** (24 total):
- `kb/holmes/kb/schema.py` — expand category set; update title max to 60
- `kb/holmes/kb/agent/pipeline.py` — inject Normalizer; inject Classifier; add Resolution fallback
- `kb/holmes/kb/agent/phases/extractor.py` — update `EXTRACTOR_SYSTEM_PROMPT`
- `kb/holmes/kb/agent/runner.py` — fix `_finalize_skill_generation`; fix `_dispatch_tool`; fix `_gate_skill_create`; fix `_run_skill_and_curation` ({PARAM})
- `kb/holmes/kb/agent/skill_advisor.py` — revert threshold to ≥3; add `_find_similar_skill`
- `kb/holmes/kb/skill/manager.py` — update `create_skill` to accept + write `params`
- `kb/holmes/kb/agent/report.py` — update `format_dry_run_plan`
- `kb/holmes/kb/agent/provider/openai_provider.py` — wrap API errors
- `kb/holmes/cli.py` — dry-run Reader pass; batch title display
- `kb/holmes/kb/agent/runner.py` (line 47), `phases/extractor.py` (line 45), `phases/reader.py` (line 91), `kb/importer.py` (line 60) — category prompt strings → add 4 new categories
- `kb/tests/test_schema.py` — add tests for new categories
- `kb/tests/test_skill_advisor.py` — threshold + LINK tests
- `kb/tests/test_pipeline.py` — Normalizer integration, Classifier, verbatim fallback tests
- `kb/tests/test_agent_runner.py` — skill gate, dry-run tests

---

## D-018 — Constitution Compliance

- **单一职责**: `DraftNormalizer` and `DocumentClassifier` are independent modules; each has one job.
- **开闭原则**: Category set change is additive (new values, no removal). Normalizer header map is extensible.
- **验证原则**: All new modules require unit tests in existing test infrastructure (`pytest`).
- **渐进式实现**: No premature abstractions — Normalizer is a single class with a single `normalize()` method. Classifier is a single class with a single `classify()` method.
- **可观测性**: All Normalizer actions (header translations, truncations, tag extractions, category corrections) are returned as a `warnings` list that flows into `report.warnings`.
- **环境配置**: No new config; reuses existing `HolmesConfig` with provider/model.
