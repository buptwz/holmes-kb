# Feature Specification: Import Pipeline Quality Normalization

**Feature Branch**: `018-import-quality-normalizer`

**Created**: 2026-06-09

**Status**: Draft

**Input**: v15 usage report — all open issues across 50 use cases × 10 dimensions (gpt-4o + deepseek-v4-flash)

## Background

The v15 usage report (2026-06-08) tested the import pipeline across 50 use cases using two models: gpt-4o and deepseek-v4-flash. Despite feature 016/017 fixes, systemic and individual issues remain. This feature addresses all of them:

**Root Cause A (QA structural failures)**: Pipeline relies on LLM to produce compliant structure. Models differ in instruction-following fidelity: Chinese section headers, missing tags, empty titles, wrong categories. Needs a deterministic post-processing Normalizer layer.

**Root Cause B (Category schema too narrow)**: Only 4 legal category values. 17 entries have invalid categories; 13 are "kubernetes" — a valid real-world category the schema doesn't support.

**Root Cause C (Skill generation is model-dependent)**: `run.sh` content is LLM-written. deepseek produces empty templates; gpt-4o produces quote-escaping bugs. `{PARAM}` placeholders not extracted. `detect_commands()` exists but is unused for generation.

**Root Cause D (No document type pre-classification)**: Reader has no pre-step. Meeting notes and port tables are imported as KB. Runbooks are split into micro-entries. Reader has no per-type KP granularity guidance.

**Root Cause E (Extractor command hallucination — D-2 persists)**: Extractor rewrites/summarizes commands instead of verbatim copying from source. Verifier CLEARs the hallucinated commands, leaving `## Resolution` empty in pitfall entries. No fallback recovers commands from source text.

**Standalone Bugs (E-1, E-4, E-5, E-6, E-8, E-11, E-12)**: Skill trigger mechanism fails for single-document Runbooks; Skill LINK not implemented; interactive Skill confirmation gate does not fire; OPTIONAL skill threshold misidentifies 2-step commands; `--dry-run` shows no preview; `--dir` batch output shows pending IDs not titles; API errors are exposed as raw JSON.

## User Scenarios & Testing

### User Story 1 — Deterministic Entry Normalization After Extraction (Priority: P1)

A user imports a Chinese-language incident runbook using deepseek-v4-flash. The model produces an entry with `## 症状` headers, a 90-character title, no tags, and `category: kubernetes` (invalid in current schema). After the fix, the pipeline automatically normalizes all structural issues before writing to pending — regardless of which model was used.

**Why this priority**: Directly eliminates the majority of QA failures observed in the v15 report. Model-agnostic by design (deterministic code, not LLM). Fixes Root Cause A. Covers: QA-9, QA-11, QA-12, QA-14, QA-15, QA-16.

**Independent Test**: Import a document where the LLM extractor produces non-compliant output (Chinese headers, long title, missing tags, bad category). Assert the pending entry written to disk has: English section headers, title ≤60 chars, ≥3 auto-extracted tags, valid normalized category.

**Acceptance Scenarios**:

1. **Given** an extractor draft with `## 症状`, `## 根因`, `## 解决方案` headers, **When** normalization runs, **Then** headers become `## Symptoms`, `## Root Cause`, `## Resolution`.
2. **Given** a draft with a 95-character title, **When** normalization runs, **Then** title is truncated to ≤60 characters (trimmed at word boundary if possible).
3. **Given** a draft with an empty or missing `tags` field, **When** normalization runs, **Then** tags are auto-extracted as ≥3 lowercase keywords from `title` + `root_cause` fields.
4. **Given** a `guideline` type entry containing a `## Symptoms` section, **When** normalization runs, **Then** the `## Symptoms` section is removed (type-level structural constraint).
5. **Given** a `pitfall` type entry with an empty `## Resolution` section, **When** normalization runs, **Then** a warning is added to the import report: "pitfall entry missing Resolution content".
6. **Given** a `title: null` or `title: ''` in the draft, **When** normalization runs, **Then** a placeholder title is generated from the first sentence of `root_cause` and a warning is logged.

---

### User Story 2 — Expanded Category Schema (Priority: P2)

A user imports a Kubernetes pod eviction incident. The LLM correctly classifies it as `kubernetes`. Currently the pipeline rejects it or falls back to `system`. After the fix, `kubernetes` is a first-class category value and all prompts, validation, and normalization logic accept it.

**Why this priority**: 13 of 17 invalid-category entries in v15 were `kubernetes`. Small schema change, high coverage impact. Fixes Root Cause B. Covers: QA-4, QA-13.

**Independent Test**: Import a document that the LLM naturally classifies as `kubernetes`, `messaging`, `cache`, or `monitoring`. Assert the pending entry has one of these new values without any override or fallback.

**Acceptance Scenarios**:

1. **Given** a Kubernetes pod eviction document, **When** imported, **Then** pending entry has `category: kubernetes`.
2. **Given** a Kafka consumer lag incident, **When** imported, **Then** pending entry has `category: messaging`.
3. **Given** a Redis OOM incident, **When** imported, **Then** pending entry has `category: cache`.
4. **Given** a Prometheus alerting misconfiguration, **When** imported, **Then** pending entry has `category: monitoring`.
5. **Given** any document producing a category not in the 8-value set, **When** normalization runs, **Then** it is mapped to the closest valid category or `system` as fallback, and a warning is logged with the original and corrected values.

---

### User Story 3 — Deterministic Skill Generation (Priority: P3)

A user approves a pending entry and the pipeline generates a skill. Currently, deepseek-v4-flash produces an empty `run.sh` template; gpt-4o produces a script with broken quote escaping; neither model extracts `{PARAM}` placeholders. After the fix, `run.sh` is generated by deterministic code using `detect_commands()`, and the LLM is not involved in writing script content.

**Why this priority**: Eliminates model-capability dependency in skill generation. Fixes Root Cause C. Covers: E-3, E-8, E-9, E-10.

**Independent Test**: Approve a KB entry whose Resolution section contains shell commands with `{PARAM}` placeholders. Assert: (a) `run.sh` contains the exact extracted commands, (b) `SKILL.md` `params:` field lists all `{PARAM}` names, (c) output is identical whether gpt-4o or deepseek-v4-flash is used, (d) a 2-step command entry produces a suggestion recommendation, not an auto-created Skill.

**Acceptance Scenarios**:

1. **Given** a Resolution section with `kubectl delete pod {POD_NAME} -n {NAMESPACE}`, **When** skill is generated, **Then** `run.sh` contains that exact command and `SKILL.md` params lists `POD_NAME`, `NAMESPACE`.
2. **Given** any model (gpt-4o or deepseek), **When** skill is generated for the same entry, **Then** `run.sh` content is byte-for-byte identical.
3. **Given** a Resolution section with no shell commands, **When** skill generation runs, **Then** no `run.sh` is created and the skill record is marked as documentation-only.
4. **Given** commands with quote characters or special characters, **When** written to `run.sh`, **Then** the file passes `bash -n` syntax check.
5. **Given** a Resolution section with exactly 1–2 shell commands, **When** skill generation evaluates, **Then** the result is a `SUGGESTED` recommendation only — no Skill is auto-created unless the user confirms.

---

### User Story 4 — Document Type Pre-Classification Before Reader (Priority: P4)

A user imports a meeting notes document. Currently the pipeline creates spurious KB entries from it. After the fix, a lightweight pre-Reader classifier identifies the document as `non-kb` type and rejects it immediately. A user imports a 40-page runbook — the classifier identifies it as `runbook` and instructs the Reader to extract 3–8 high-level entries, not individual command steps.

**Why this priority**: Prevents category pollution and entry explosion. Fixes Root Cause D. Covers: QA-3, QA-5, D-3.

**Independent Test**: (a) Import a meeting notes file — assert `report.warnings` contains a rejection reason and 0 entries are created. (b) Import a runbook — assert Reader is given "coarse granularity" instruction and produces ≤10 KPs.

**Acceptance Scenarios**:

1. **Given** a meeting notes document, **When** imported, **Then** pipeline exits after classification with `report.warnings` containing a rejection reason and creates 0 pending entries.
2. **Given** a port allocation table, **When** imported, **Then** pipeline exits after classification with a `non-kb` rejection message.
3. **Given** a multi-incident report (5 incidents), **When** imported, **Then** Reader receives `multi-incident` guidance and produces one KP per incident.
4. **Given** a single incident postmortem, **When** imported, **Then** Reader receives `single-incident` guidance (standard fine-grained extraction).
5. **Given** a runbook with 20 steps, **When** imported, **Then** Reader receives `runbook` guidance and produces ≤8 KPs covering distinct procedures.
6. **Given** a document that cannot be confidently classified, **When** imported, **Then** classification defaults to `single-incident` (safe fallback, no rejection).

---

### User Story 5 — Extractor Command Verbatim Copy + Verifier Fallback (Priority: P5)

A user imports an incident report. The Extractor paraphrases the bash commands in the Resolution section. The Verifier cannot verify the paraphrase against the source and CLEARs the field, leaving the pending entry's `## Resolution` empty. After the fix, the Extractor is constrained to copy commands verbatim; and when Verifier CLEARs resolution_commands anyway, a deterministic fallback extracts commands directly from the source text section and restores them.

**Why this priority**: D-2 has persisted through feature 016. Empty Resolution in pitfall entries makes KB entries non-actionable. Fixes Root Cause E. Covers: D-2, QA-16 (remaining cases).

**Independent Test**: Import a document where the Extractor would normally paraphrase commands. Assert: (a) the pending entry's `## Resolution` section contains the exact commands from the source text, not a paraphrase; (b) if Verifier CLEARs, the fallback restores at least the raw extracted commands with a note.

**Acceptance Scenarios**:

1. **Given** a source document with `kubectl rollout restart deployment/api -n prod`, **When** Extractor runs, **Then** the draft's `## Resolution` contains that exact string verbatim.
2. **Given** the Extractor still produces a paraphrase that Verifier CLEARs, **When** the CLEAR happens, **Then** a fallback applies `detect_commands()` to the matching source section and inserts the raw commands into `## Resolution` with a `[auto-recovered from source]` annotation.
3. **Given** a document with no commands in the Resolution section, **When** Verifier CLEARs the field, **Then** no fallback is applied and the entry is written without a Resolution section (correct behavior for command-free entries).
4. **Given** the fallback is triggered, **When** the import report is printed, **Then** `report.warnings` includes a message identifying which entry had commands auto-recovered.

---

### User Story 6 — Skill Lifecycle Correctness (Priority: P6)

Three related Skill lifecycle bugs: (a) single-document process/runbook entries with verified resolution_commands don't trigger Skill generation at all (E-1); (b) importing a second document on the same topic creates a duplicate Skill instead of linking to the existing one (E-11); (c) the interactive confirmation gate for RECOMMENDED Skills never fires — Skills are auto-created even in interactive mode (E-12).

**Why this priority**: Makes Skill generation reliable and non-redundant. Covers: E-1, E-11, E-12.

**Independent Test**: (a) Import a single Runbook with type=process and verified resolution_commands — assert skill: ≥1 generated. (b) Import two documents on the same topic — assert second import produces `skill: 0 generated, 1 linked` not `1 generated`. (c) In interactive mode with a RECOMMENDED Skill candidate, assert user is prompted before creation.

**Acceptance Scenarios**:

1. **Given** a single-document process entry with `type: process` and verified resolution_commands, **When** `_finalize_skill_generation` runs, **Then** skill: ≥1 generated (E-1 fix).
2. **Given** a Skill named "CrashLoopBackOff Recovery" already exists, **When** a second entry with the same Skill name is imported, **Then** the pipeline outputs `skill: 0 generated, 1 linked` and no duplicate Skill directory is created (E-11 fix).
3. **Given** a RECOMMENDED Skill candidate in interactive mode (no `--no-interactive`), **When** the pipeline reaches Skill creation, **Then** the user is prompted "Create skill? [y/n]" before creating it (E-12 fix).
4. **Given** `--no-interactive` is set, **When** a RECOMMENDED Skill is encountered, **Then** it is auto-created and recorded in `auto_decisions` without prompting (existing correct behavior preserved).

---

### User Story 7 — CLI Output Clarity (Priority: P7)

Two CLI output bugs: (a) `--dry-run` does not run LLM analysis, so "Would create: " shows nothing — users cannot preview what would be imported (E-4); (b) in `--dir` batch import, the progress line for some entries shows a pending ID (e.g., `pending-20260608-131751-i9tq`) instead of the entry title (E-6).

**Why this priority**: Low risk changes; directly improves usability. Covers: E-4, E-6.

**Independent Test**: (a) Run `holmes import doc.md --dry-run` — assert output contains at least the document filename and estimated knowledge point count. (b) Run `holmes import --dir ./docs` — assert each `[N/M]` progress line shows the entry title, not a pending ID.

**Acceptance Scenarios**:

1. **Given** `--dry-run` on a valid document, **When** the command runs, **Then** output contains `[DRY RUN] Would process: <filename> (~N knowledge points estimated)` based on a lightweight Reader pass (no write, no Extractor/Verifier).
2. **Given** `--dry-run` on a document that would be rejected by DocumentClassifier, **When** the command runs, **Then** output contains `[DRY RUN] Would reject: <filename> — non-kb document`.
3. **Given** `--dir` batch import with 4 files, **When** each file is processed, **Then** the `[N/M]` line shows the entry's `title` field (or filename if no title extracted yet), not the pending ID.

---

### User Story 8 — API Error User-Friendly Messages (Priority: P8)

When the LLM API returns a 401, 429, or 5xx error, the pipeline currently prints the raw JSON error object (e.g., `{'error': {'message': '无效的令牌 (request id: ...)', 'type': 'one_api_error'}}`). Users see no actionable guidance.

**Why this priority**: Low implementation effort, high user experience impact. Covers: E-5.

**Independent Test**: Configure an invalid API key. Run `holmes import doc.md`. Assert output contains a human-readable message with the error type and a suggested next step; assert the raw JSON is not printed.

**Acceptance Scenarios**:

1. **Given** an invalid API key (401), **When** the import runs, **Then** output is: `Error: Authentication failed — API key rejected. Check your key with: holmes config set api_key <KEY>` and exits with code 1.
2. **Given** a rate-limit response (429), **When** the import runs, **Then** output is: `Error: Rate limit reached. Wait a moment and retry, or check your plan quota.` and exits with code 1.
3. **Given** a server error (5xx), **When** the import runs, **Then** output is: `Error: LLM provider returned a server error (HTTP <status>). Check provider status or retry.` and exits with code 1.
4. **Given** any API error, **When** the error is displayed, **Then** the raw JSON error body is NOT printed to stdout or stderr.

---

### Edge Cases

- Normalizer cannot parse YAML frontmatter → leave draft unchanged, log repair warning (existing `_validate_and_repair_draft` handles this).
- `detect_commands()` extracts zero commands from Resolution section → Skill is documentation-only; no `run.sh` generated.
- DocumentClassifier LLM call fails (timeout, parse error) → default to `single-incident`; import continues with a warning.
- Chinese header with no mapping → leave unchanged; log normalization warning.
- Title truncation at 60 chars would cut mid-word → trim to last word boundary; append `…` only if content was cut.
- Extractor verbatim fallback: source text has no detectable section matching the KP → no fallback applied; entry written without Resolution; warning logged.
- Skill LINK: two Skill names match case-insensitively → treat as same Skill; link rather than create.
- `--dry-run` + Reader phase fails → report failure inline; show 0 estimated KPs with a note.

## Requirements

### Functional Requirements

**Normalizer (Root A):**
- **FR-001**: System MUST apply a deterministic Normalizer step after each `ExtractorAgent.run()` call and before `_validate_and_repair_draft()`, with no LLM invocation inside the Normalizer.
- **FR-002**: Normalizer MUST translate known Chinese/non-standard section headers to English standard equivalents via a hardcoded mapping table.
- **FR-003**: Normalizer MUST enforce `title` non-empty and ≤60 characters, truncating at word boundary; generate a fallback title from `root_cause` when title is null/empty.
- **FR-004**: Normalizer MUST auto-extract ≥3 lowercase keyword tags from `title` + `root_cause` when `tags` is missing or has fewer than 3 entries.
- **FR-005**: Normalizer MUST enforce type-level structural constraints: `guideline` entries must not contain `## Symptoms`; `pitfall` entries must have non-empty `## Resolution`.
- **FR-006**: Normalizer MUST normalize `category` to the canonical set; unrecognized values mapped to closest or `system`, with a named warning in the report.

**Category schema (Root B):**
- **FR-007**: System MUST expand the canonical `category` value set from 4 to 8: add `kubernetes`, `messaging`, `cache`, `monitoring`.
- **FR-008**: All category validation logic, prompts, and schema definitions MUST be updated in a single shared constant so changes propagate automatically.

**Deterministic Skill generation (Root C):**
- **FR-009**: Skill `run.sh` MUST be generated by calling `detect_commands()` on the Resolution section text only, not by LLM output.
- **FR-010**: `{PARAM}` placeholders (`{UPPERCASE_NAME}` pattern) in extracted commands MUST be parsed and written to `SKILL.md` `params:` field.
- **FR-011**: Skill OPTIONAL threshold: entries with 1–2 commands MUST produce a `SUGGESTED` recommendation only; auto-creation requires ≥3 commands or explicit user confirmation.

**Document pre-classification (Root D):**
- **FR-012**: System MUST add a `DocumentClassifier` step before `ReaderAgent`, using a single LLM call to classify document type: `single-incident`, `multi-incident`, `runbook`, `guideline`, `non-kb`.
- **FR-013**: `non-kb` documents MUST be rejected immediately; import report MUST include a human-readable rejection reason; zero pending entries created.
- **FR-014**: For `multi-incident`, `runbook`, and `guideline` types, the Reader MUST receive type-appropriate KP granularity guidance via the pipeline context.
- **FR-015**: DocumentClassifier MUST default to `single-incident` on any failure and continue the pipeline normally.

**Extractor verbatim commands + Verifier fallback (Root E):**
- **FR-016**: Extractor prompt MUST include an explicit constraint: resolution section commands must be copied verbatim from the source text, not paraphrased or summarized.
- **FR-017**: When Verifier CLEARs `resolution_commands` for a `pitfall` entry, system MUST apply a deterministic fallback: run `detect_commands()` on the source text section corresponding to the KP and insert recovered commands into `## Resolution` with an `[auto-recovered from source]` annotation.
- **FR-018**: If the fallback recovers commands, `report.warnings` MUST include a message identifying the affected entry.

**Skill lifecycle (E-1, E-11, E-12):**
- **FR-019**: `_finalize_skill_generation` MUST trigger Skill creation for any entry with `type: process` AND non-empty verified resolution_commands, regardless of whether the source document contains one or multiple KPs.
- **FR-020**: Before creating a new Skill, system MUST check for an existing Skill with the same name (case-insensitive). If found, it MUST link the entry to the existing Skill instead of creating a duplicate.
- **FR-021**: In interactive mode (no `--no-interactive`), RECOMMENDED Skill candidates MUST prompt the user with "Create skill? [y/n]" before creation. In `--no-interactive` mode, auto-create and record in `auto_decisions`.

**CLI output (E-4, E-6):**
- **FR-022**: `--dry-run` MUST execute the Reader phase (no writes, no Extractor/Verifier) and display `[DRY RUN] Would process: <filename> (~N knowledge points estimated)` per file.
- **FR-023**: In `--dir` batch import, the `[N/M]` progress line MUST show the entry's `title` field. If no title is available yet, show the source filename.

**API error handling (E-5):**
- **FR-024**: All LLM provider HTTP errors (4xx, 5xx) MUST be caught and mapped to human-readable messages with a suggested action. The raw JSON error body MUST NOT appear in stdout or stderr.

### Key Entities

- **Normalizer**: Pure-Python deterministic post-processing module; stateless; takes a draft string, returns (normalized_draft, warnings_list).
- **DocumentClassifier**: Single-LLM-call pre-Reader step; returns `DocumentType` enum + optional rejection reason string.
- **DocumentType**: Enum — `single_incident`, `multi_incident`, `runbook`, `guideline`, `non_kb`.
- **Category**: Canonical 8-value set defined in a single shared constant.
- **SkillGenerator**: Refactored to use `detect_commands()` + `{PARAM}` regex parser; LLM not involved in script content.
- **SkillLinker**: Checks existing Skill names before creation; links rather than duplicates.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Category validation failures drop from 17/50 (34%) to ≤2/50 (≤4%) across both models.
- **SC-002**: Section header non-compliance (Chinese headers) drops to 0 across both models.
- **SC-003**: Skill `run.sh` content is byte-for-byte identical for the same input regardless of model used.
- **SC-004**: Non-KB documents produce 0 pending entries and appear in `report.warnings`.
- **SC-005**: Runbook imports produce ≤10 KPs instead of 20–30 micro-entries.
- **SC-006**: Tags field populated with ≥3 entries in 100% of pending entries written.
- **SC-007**: Pitfall entries with non-empty source Resolution section have non-empty `## Resolution` in the pending entry (either verbatim or auto-recovered).
- **SC-008**: Duplicate Skill directories are not created for entries sharing the same Skill name.
- **SC-009**: API authentication errors produce a user-readable message with a suggested fix command, not raw JSON.
- **SC-010**: All 582 existing tests continue to pass after changes.

## Assumptions

- `detect_commands()` is already implemented and handles command extraction from text; the Skill generation refactor calls it on the Resolution section only (per existing CLAUDE.md constraint).
- The `{PARAM}` placeholder pattern is `{UPPERCASE_NAME}` (regex `\{[A-Z_]+\}`); this is already established in the codebase.
- DocumentClassifier uses the same LLM provider and model already in the pipeline context — no new provider configuration needed.
- Chinese section header mappings are a finite enumerable set; a hardcoded mapping table is sufficient.
- The 8 expanded category values cover the real-world distribution observed in v15; further expansion is a separate feature.
- `--dry-run` Reader-only pass uses the full Reader phase; the cost of one extra LLM call is acceptable for accurate preview.
- Skill LINK matching is case-insensitive exact match on Skill name; fuzzy matching is out of scope.
- Extractor verbatim fallback only applies to `pitfall` entries; `guideline` entries without commands are expected and need no fallback.
