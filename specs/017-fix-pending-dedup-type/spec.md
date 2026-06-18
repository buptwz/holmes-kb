# Feature Specification: Import Pipeline — Pending Dedup & Type Override

**Feature Branch**: `017-fix-pending-dedup-type`

**Created**: 2026-06-09

**Status**: Draft

**Input**: Fix D-5 (pending-layer dedup) and E-2 (`--type` override) from v15 verification report.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Duplicate Import Skipped at Pending Layer (Priority: P1)

A user imports the same document twice. The second import should detect the existing pending entry and skip creation instead of producing a duplicate.

**Why this priority**: Silent duplicate creation is the highest-impact correctness bug — it inflates pending counts, makes review harder, and wastes operator time. Every reimport scenario (retry after failure, re-run of automation) triggers this.

**Independent Test**: Import any document, then import the same document again without approving the first pending entry. Assert the second run reports `0 created, 1 skipped` and no new file appears in `contributions/pending/`.

**Acceptance Scenarios**:

1. **Given** a document has already been imported and a matching pending entry exists, **When** the same document is imported again, **Then** the import reports `0 created, 0 updated, 1 skipped` and no new pending file is written.
2. **Given** a document is imported twice in the same session (e.g., automation loop), **When** the second call completes, **Then** the pending directory contains exactly one entry for that document.
3. **Given** a pending entry exists for a document but it has been approved and moved to the main KB, **When** the same document is imported again, **Then** the existing approved entry is found and the import is skipped (not duplicated in pending).

---

### User Story 2 — `--type` Flag Forces Entry Classification (Priority: P2)

A user runs `holmes import <doc> --type pitfall` and expects the created entry to have `type: pitfall`, regardless of how the system would otherwise classify the document.

**Why this priority**: Without this, the `--type` CLI option is silently ignored — a severe correctness issue that undermines user trust, but less disruptive than duplicate entries because it affects new imports rather than accumulating state.

**Independent Test**: Import a document that would naturally be classified as `guideline` (e.g., a policy document) using `--type pitfall`. Assert the created pending entry has `type: pitfall` in its frontmatter.

**Acceptance Scenarios**:

1. **Given** a document that the system would classify as `guideline`, **When** imported with `--type pitfall`, **Then** the pending entry has `type: pitfall`.
2. **Given** any document imported with `--type process`, **When** the import completes, **Then** no pending entry for that document has a type other than `process`.
3. **Given** a document imported without `--type`, **When** the import completes, **Then** the system classifies the type automatically (unchanged behavior).
4. **Given** `--type` is combined with other flags (`--dry-run`, `--verbose`), **When** the import runs, **Then** the forced type appears in the plan/trace output and in the created entry.

---

### Edge Cases

- What happens when the pending directory contains a corrupt or unreadable file? (Dedup scan should skip it gracefully and not crash.)
- What happens when `--type` is given an invalid value (e.g., `--type unknown`)? (Should fail early with a clear error message.)
- What if the same document appears in both pending and approved KB? (Approved KB match takes priority; pending match is a secondary guard.)
- What if the document has no `source_hash` (empty file or non-text)? (Dedup is skipped; entry is created normally.)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The import system MUST check `contributions/pending/` for an existing entry with a matching source document hash before creating a new pending entry.
- **FR-002**: When a duplicate is detected in pending, the import MUST report the entry as skipped (not created) and MUST NOT write a new pending file.
- **FR-003**: Duplicate detection MUST cover both the approved KB and the pending directory.
- **FR-004**: The `--type` flag MUST cause the created entry's `type` field to be set to the user-supplied value, overriding any automatic classification.
- **FR-005**: The forced type MUST be visible in `--verbose` trace output and `--dry-run` plan output.
- **FR-006**: Importing without `--type` MUST continue to work exactly as before (auto-classification unchanged).
- **FR-007**: All existing tests MUST continue to pass (no regression).

### Key Entities

- **Pending Entry**: A draft KB entry file in `contributions/pending/`, identified by a `source_hash` frontmatter field derived from the original document content.
- **Source Hash**: A deterministic fingerprint of the imported document used to detect duplicates across both pending and approved entries.
- **Force Type**: A user-supplied KB entry type (`pitfall`, `model`, `guideline`, `process`, `decision`) that overrides automatic LLM classification.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Reimporting the same document twice produces exactly 1 pending entry and reports `1 skipped` on the second run — verified in 100% of test cases.
- **SC-002**: Importing with `--type X` produces a pending entry with `type: X` in 100% of test cases, regardless of document content.
- **SC-003**: All 571 existing tests continue to pass after both fixes are applied.
- **SC-004**: Dedup scan over a directory with 100 pending files completes in under 1 second (no perceptible delay).

## Assumptions

- Source hash computation is already implemented and stored in pending entry frontmatter; no new hash algorithm is needed.
- The valid set of `--type` values is fixed: `pitfall`, `model`, `guideline`, `process`, `decision`.
- Pending directory scanning reads only `.md` files and extracts `source_hash` from YAML frontmatter; binary or malformed files are skipped silently.
- The `--type` override applies only to the `type` field; category, tags, and all other fields remain auto-classified.
- Dry-run mode respects the forced type in its plan output but does not write any files.
