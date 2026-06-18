# Feature Specification: Three-Phase Pipeline Stability Fixes (D-1~D-7)

**Feature Branch**: `016-fix-pipeline-stability`

**Created**: 2026-06-08

**Status**: Draft

**Input**: User description: "三阶段 Import Pipeline 稳定性修复：修复 v14 使用报告中发现的 D-1～D-7 问题"

## Background

The v14 usage report revealed seven quality and stability issues in the three-phase import pipeline (feature 015). Two are blocking (D-1, D-2): they cause the majority of knowledge extraction attempts to silently fail or produce unusable output. The remaining five degrade reliability, observability, and output quality.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Multi-Section Document Produces Expected KB Entries (Priority: P1)

An operator runs `holmes import` on a document containing multiple distinct incidents. They expect one KB entry per incident. Currently, the majority of entries are silently discarded due to draft formatting errors (D-1), or produce entries with all actionable fields cleared because commands were paraphrased instead of copied verbatim (D-2).

**Why this priority**: D-1 alone causes 67–80% of extracted knowledge points to be dropped in multi-topic documents. D-2 causes every runbook-type document to produce entries with no actionable commands. Together they make the pipeline unusable for the most common import scenarios.

**Independent Test**: Import `tests/fixtures/multi_kp_postmortem.md` (3-incident document). Assert exactly 3 pending entries are created, each with a non-empty resolution section containing actual commands.

**Acceptance Scenarios**:

1. **Given** a 3-incident document, **When** `holmes import` runs, **Then** all 3 KB entries are created (0 silently dropped due to YAML format errors).
2. **Given** a runbook with 3 shell commands in the resolution section, **When** `holmes import` runs, **Then** the created entry's resolution section contains those commands verbatim (not paraphrased summaries).
3. **Given** an Extractor draft with a malformed YAML frontmatter (e.g., missing closing `---`), **When** the pipeline processes it, **Then** the error is logged with the affected knowledge point ID and processing continues for remaining knowledge points.

---

### User Story 2 — Runbook Import Produces a Usable Skill (Priority: P1)

An operator imports a runbook document with numbered steps and shell commands. They expect the generated Skill's execution script to contain the actual commands. Currently, the generated Skill's script is an empty template with no commands (D-6), and this is caused upstream by D-2 (commands paraphrased, so Skill detection finds nothing to extract).

**Why this priority**: A Skill with no commands is not executable and provides no operational value. This is a direct consequence of D-2 and represents the most user-visible failure mode.

**Independent Test**: Import `tests/fixtures/redis_runbook_zh.md`. Assert the generated Skill's execution script contains at least one command from the source document's resolution section.

**Acceptance Scenarios**:

1. **Given** a runbook containing `redis-cli INFO replication` and `redis-cli DEBUG SLEEP 0` in its resolution section, **When** `holmes import` runs and a Skill is recommended, **Then** the Skill's execution script contains both commands.
2. **Given** a runbook whose resolution section contains only prose descriptions and no shell commands, **When** `holmes import` runs, **Then** no Skill is created and the reason is included in the import report.

---

### User Story 3 — Single-Incident Document Creates One Focused Entry (Priority: P2)

An operator imports a standard incident report covering one problem (with symptoms, root cause, and resolution). They expect one KB entry. Currently, the Reader identifies 7–8 knowledge points by treating symptoms, root cause, and resolution steps as separate items (D-3), producing fragmented low-quality entries.

**Why this priority**: Over-splitting wastes extraction capacity and degrades entry quality. However, the pipeline still produces at least one entry, making this a quality issue rather than a blocking failure.

**Independent Test**: Import `tests/fixtures/large_runbook_15k.md` (single-incident document). Assert exactly 1 pitfall-type KB entry is created.

**Acceptance Scenarios**:

1. **Given** a document describing one incident with symptoms, root cause, and resolution all under one narrative, **When** the Reader phase runs, **Then** it identifies 1 knowledge point — not separate ones for symptoms, root cause, and resolution.
2. **Given** a document with 3 clearly distinct incidents each under its own top-level heading, **When** the Reader phase runs, **Then** it identifies 3 knowledge points (one per incident).

---

### User Story 4 — Import Failures Are Reported, Not Silently Dropped (Priority: P2)

An operator runs `holmes import` and receives `0 created, 0 updated, 0 skipped` with no explanation. They cannot tell whether the document contained no knowledge, the model failed silently, or the entry was a duplicate. This is caused by D-4 (silent 0-KP exit) and D-5 (semantic deduplication not firing in the new pipeline, causing unexpected duplicates or unexpected non-creation).

**Why this priority**: Silent failures erode operator trust. Without feedback, operators cannot retry, investigate, or determine if the import succeeded.

**Independent Test**: Import a document with no recognizable incident structure. Assert the output includes a human-readable warning explaining why no entries were created.

**Acceptance Scenarios**:

1. **Given** a document from which the Reader extracts 0 knowledge points, **When** `holmes import` completes, **Then** the output includes a warning: "No knowledge points identified."
2. **Given** a document highly similar to an existing KB entry, **When** `holmes import` runs, **Then** the existing entry is updated (not a new duplicate entry created) — matching pre-015 deduplication behavior.
3. **Given** a document where 3 of 5 knowledge point drafts fail validation, **When** `holmes import` completes, **Then** the output reports the number of failures alongside the number of successes, with failure reasons.

---

### User Story 5 — Verbose Output Shows Clear, Non-Contradictory Field Status (Priority: P3)

An operator using `--verbose` sees trace lines showing `resolution_commands ← (verified)` immediately followed by `resolution_commands ← [CLEARED]` for the same entry. The final state is CLEARED but the trace implies both, causing confusion about what actually happened (D-7).

**Why this priority**: Display-only issue. The underlying KB entry state is correct; only the trace output is misleading.

**Independent Test**: Import a multi-KP document with `--verbose`. Assert no field appears with both `(verified)` and `[CLEARED]` in the same entry's trace block.

**Acceptance Scenarios**:

1. **Given** a document that triggers multiple verification rounds for the same entry, **When** `--verbose` output is displayed, **Then** each field appears exactly once per entry trace, showing only its final state.

---

### Edge Cases

- What happens when a draft has valid `---` delimiters but invalid YAML inside (e.g., unescaped colon)? The pipeline must log the error and skip that knowledge point, not crash.
- What happens when command extraction finds commands in multiple sections of an entry? Only commands from the resolution section should be used for Skill creation.
- What happens when a document is identical to an existing KB entry? Deduplication must detect it and skip creation without logging it as a failure.
- What happens when the Reader identifies 0 knowledge points but the document is non-empty? The warning must appear regardless of document length.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When an Extractor draft has a malformed YAML frontmatter, the pipeline MUST log a warning with the affected knowledge point ID and continue processing remaining knowledge points.
- **FR-002**: The Extractor MUST copy shell commands verbatim from the source document's resolution section into the generated draft; paraphrasing or summarizing commands is not acceptable.
- **FR-003**: The Reader MUST treat one incident as one knowledge point; it MUST NOT split the symptoms, root cause, and resolution of the same incident into separate knowledge points.
- **FR-004**: When the Reader identifies 0 knowledge points, the pipeline MUST add a human-readable warning to the import report.
- **FR-005**: Semantic deduplication against existing KB entries MUST be active in the three-phase pipeline, restoring pre-015 behavior where similar documents triggered updates rather than new entry creation.
- **FR-006**: When a Skill is created, its execution script MUST contain the actual shell commands from the entry's resolution section; an empty template script is not acceptable.
- **FR-007**: When `--verbose` is used, each field's trace MUST show only its final verification status per entry; intermediate states from earlier verification rounds must not appear.
- **FR-008**: The import report MUST include a count of knowledge points that failed draft validation alongside the created/updated counts.

### Key Entities

- **ImportReport**: Extended with a `warnings` list for pipeline-level warnings (e.g., 0-KP detection) and a `failed_kps` count for per-knowledge-point extraction failures.
- **ExtractorAgent**: Modified to validate draft format and copy resolution commands verbatim.
- **ReaderAgent**: Modified with prompt guidance to prevent knowledge point over-splitting.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a 3-incident document, all 3 expected KB entries are created — 0% silent drop rate due to draft format errors (v14 baseline: 67%).
- **SC-002**: For a runbook with 2+ shell commands in the resolution section, the created entry contains those commands verbatim in at least 90% of imports (v14 baseline: 0%).
- **SC-003**: For a single-incident document, the Reader produces 1 knowledge point in at least 80% of imports (v14 baseline: 7–8 KPs per single incident).
- **SC-004**: When `holmes import` produces 0 created entries, at least one explanatory warning is present in the output — 100% of the time (v14 baseline: 0%).
- **SC-005**: Importing a document similar to an existing KB entry triggers an update, not a new entry — matching pre-015 deduplication behavior (v14 baseline: new entry always created).
- **SC-006**: Generated Skill execution scripts contain at least one actual command in at least 80% of imports where a Skill is recommended (v14 baseline: 0% — all empty templates).
- **SC-007**: Verbose trace output for any single entry contains no contradictory field status lines (v14 baseline: `(verified)` + `[CLEARED]` co-occurring).
- **SC-008**: All 546 existing automated tests continue to pass after all fixes are applied.

---

## Assumptions

- All fixes are contained within the existing three-phase pipeline (015 architecture); no structural changes to the Reader → Extractor → Verifier flow are needed.
- D-5 (semantic deduplication) was likely dropped when the 015 refactor moved the verification loop into `pipeline.py`; the fix is to restore the call site, not redesign deduplication logic.
- The verbatim command requirement (FR-002) applies only to the `## Resolution` section content; other sections (symptoms, root cause) may still be paraphrased by the Extractor.
- Fixes must work with both gpt-4o and Claude model families.
- The v14 report tested on branch `013-kb-skill-evolution`; these fixes target the current `016-fix-pipeline-stability` branch which builds on 015.
