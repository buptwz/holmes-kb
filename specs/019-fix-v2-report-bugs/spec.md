# Feature Specification: Import Pipeline v2 Report Bug Fixes

**Feature Branch**: `019-fix-v2-report-bugs`

**Created**: 2026-06-09

**Status**: Draft

**Input**: User description: "Import Pipeline v2 验证报告 Bug 修复"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Import Command No Longer Crashes (Priority: P1)

A user runs `holmes import` on any document containing shell commands in the Resolution section. Previously, the import always exited with "expected string or bytes-like object, got 'CommandCandidate'" before completing. After this fix, the import completes and produces a summary line.

**Why this priority**: The crash blocks all imports involving skill generation — which is most production documents. Everything else is unverifiable until this is fixed.

**Independent Test**: Run `holmes import <document-with-commands> --no-interactive` and verify exit code 0 and a `✓ N created` summary line appears.

**Acceptance Scenarios**:

1. **Given** a document with shell commands in `## Resolution`, **When** `holmes import --no-interactive` is run, **Then** the command exits with code 0 and prints a `✓ N created` summary, not a TypeError.
2. **Given** the same import, **When** skill generation is triggered, **Then** run.sh contains actual commands (not empty template) and SKILL.md contains a `params:` block for any `{PARAM}` placeholders found in those commands.

---

### User Story 2 - --type Flag Is Respected End-to-End (Priority: P2)

A user runs `holmes import doc.md --type guideline`. The resulting pending entry must have `type: guideline` regardless of what the LLM would otherwise classify it as.

**Why this priority**: `--type` is a user-facing override flag. If the LLM silently overrides it, the flag is useless and users can't trust the output.

**Independent Test**: Import a document that would naturally be classified as `pitfall` with `--type guideline` and verify the created pending entry has `type: guideline`.

**Acceptance Scenarios**:

1. **Given** a pitfall-like document, **When** imported with `--type guideline`, **Then** the pending entry frontmatter has `type: guideline` and `suggested_type: guideline`.
2. **Given** any `--type <value>` flag, **When** the LLM would classify differently, **Then** the user-supplied type always wins in the final written entry.

---

### User Story 3 - Re-importing the Same Document Is a No-Op (Priority: P2)

A user accidentally runs `holmes import` on the same document twice. The second run should detect the duplicate via source hash and skip writing, returning `0 created, 0 updated, 1 skipped`.

**Why this priority**: Without dedup, the pending queue fills with identical entries that the user must manually clean up. This breaks the workflow for anyone running batch imports.

**Independent Test**: Import the same document three times in a row; verify pending entry count increases by 1 total (not 3), and the second/third runs show `skipped`.

**Acceptance Scenarios**:

1. **Given** a document already in pending with the same source hash, **When** imported again, **Then** no new pending entry is created and the summary shows `skipped`.
2. **Given** a document already confirmed into the KB, **When** imported again, **Then** no new pending entry is created.
3. **Given** `--force` flag is passed, **When** imported again, **Then** the dedup check is bypassed and a new entry is created.

---

### User Story 4 - Skill Creation Confirmation Is Respected (Priority: P3)

A user runs `holmes import` interactively and answers "n" when prompted to create a skill. No skill is created — neither via the interactive tool loop nor via the deterministic fallback that runs afterwards.

**Why this priority**: If the fallback silently overrides the user's "n" answer, the interactive confirmation gate is meaningless and users lose control over KB content.

**Independent Test**: Import with a document that triggers skill creation, answer "n" to the prompt, verify no new skill directory is created.

**Acceptance Scenarios**:

1. **Given** interactive mode and a RECOMMENDED skill, **When** user answers "n", **Then** no skill directory is created by either the tool loop or the fallback.
2. **Given** interactive mode and a RECOMMENDED skill, **When** user answers "y", **Then** the skill is created exactly once (not twice).

---

### User Story 5 - Existing Similar Skill Is Linked Instead of Duplicated (Priority: P3)

When importing a document whose topic is already covered by an existing skill (similar title/description), the system links the new KB entry to the existing skill rather than creating a new duplicate skill directory.

**Why this priority**: Without this, repeated imports of similar incidents accumulate dozens of near-identical skills in the skills directory.

**Independent Test**: Import two documents about the same topic; verify only one skill directory exists and the second entry references the existing skill.

**Acceptance Scenarios**:

1. **Given** an existing skill for "nginx upstream config", **When** a new document with similar topic is imported, **Then** the new entry is linked to the existing skill (not a new skill created).
2. **Given** two unrelated topics, **When** both are imported, **Then** two separate skills are created.

---

### User Story 6 - Holmes KB Data Quality Cleanup (Priority: P3)

The committed KB entries `PT-DB-002` (duplicate section headers) and `PT-DB-005` (`body_additions` content stuck in frontmatter) are corrected so they render properly. Test-named entries `PT-DB-TEST2` and `PT-NET-TEST` are removed from the committed KB.

**Why this priority**: Data quality issues in committed KB entries affect all users reading the KB. Test entries pollute production data.

**Independent Test**: Read the fixed entries and verify no duplicate `## Symptoms/## Root Cause/## Resolution` headers, no `body_additions:` key in frontmatter, and the test files no longer exist.

**Acceptance Scenarios**:

1. **Given** PT-DB-002.md, **When** read, **Then** each of `## Symptoms`, `## Root Cause`, `## Resolution` appears exactly once.
2. **Given** PT-DB-005.md, **When** read, **Then** no `body_additions:` key in frontmatter; the entry body renders as valid markdown.
3. **Given** the committed KB, **When** listed, **Then** no files named `PT-DB-TEST2.md` or `PT-NET-TEST.md` exist.

---

### Edge Cases

- What if `source_hash` is missing or empty in the tool call? The dedup check must be skipped (not crash) and the entry is written normally.
- What if the user passes `--force`? Dedup check is bypassed entirely.
- What if the document has no commands in Resolution? Skill generation fallback must not crash; it exits silently.
- What if `_finalize_skill_generation` finds an entry whose `entry_id` was tracked as evaluated? It must be completely skipped, not re-evaluated.
- What if two entries in the same import session both have similar descriptions? Each is evaluated independently for LINK; the second may link to the skill created by the first.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The import pipeline MUST complete without error when the Resolution section contains shell commands with `{PARAM}` placeholders.
- **FR-002**: The `{PARAM}` placeholder names found in extracted commands MUST be written to `SKILL.md` as a `params:` block and defined as environment variable bindings in `run.sh`.
- **FR-003**: The `--type` flag value MUST be preserved in the final written pending entry's `type:` and `suggested_type:` fields, overriding any LLM classification.
- **FR-004**: `write_kb_entry` MUST check for an existing entry with the same source hash before writing; if found, it MUST return a `duplicate` response and skip writing.
- **FR-005**: When a user declines skill creation interactively, the deterministic fallback MUST NOT attempt skill creation for that same entry again.
- **FR-006**: The deterministic skill-generation fallback MUST pass the KB entry title as the description when checking for similar existing skills.
- **FR-007**: PT-DB-002.md MUST have each section header appear exactly once.
- **FR-008**: PT-DB-005.md MUST NOT contain a `body_additions:` key in its frontmatter.
- **FR-009**: `PT-DB-TEST2.md` and `PT-NET-TEST.md` MUST be removed from the committed KB.

### Key Entities

- **CommandCandidate**: Object returned by `detect_commands()`; has a `.line` string attribute containing the shell command text.
- **force_type**: User-supplied type override (`--type` CLI flag); must flow from pipeline context to the write tool.
- **source_hash**: 16-char hash of source document text; used for idempotency checking at both pending and approved KB layers.
- **_skill_evaluated_entries**: Set of pending IDs for which skill creation was already handled in the tool loop; prevents fallback from re-processing them.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `holmes import` with a Resolution-containing document completes with exit code 0 — zero TypeError crashes.
- **SC-002**: Importing the same document 3 times results in exactly 1 pending entry (not 3); second and third runs show `skipped`.
- **SC-003**: `--type guideline` on a pitfall-like document produces an entry with `type: guideline` 100% of the time.
- **SC-004**: Answering "n" to skill creation prompt results in 0 new skill directories created (tool loop + fallback combined).
- **SC-005**: All existing unit tests continue to pass (zero regressions); at least 10 new tests cover the fixed behaviors.
- **SC-006**: PT-DB-002, PT-DB-005 pass `grep "^## "` uniqueness check; test files no longer present in KB.

## Assumptions

- The `CommandCandidate` object's `.line` attribute always contains the raw string command — no further parsing is needed.
- `force_type` values are validated by the CLI before reaching the pipeline (only valid type values are passed).
- The holmes-kb data directory is at `/home/wangzhi/holmes-kb/`; the data fixes apply to that path.
- PT-DB-002.md should retain the HikariCP section (the one with kubectl commands) as the primary content, since it is more actionable and matches the skill_ref; the brief Redis section is the duplicate to remove.
- PT-DB-005.md's existing markdown body (Symptoms / Root Cause / Resolution) is the canonical content; the `body_additions:` frontmatter field should be removed.
