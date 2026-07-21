# Feature Specification: Import Pipeline v3 Bug Fixes — English Metadata & Document-Level Dedup

**Feature Branch**: `020-fix-import-en-dedup`

**Created**: 2026-06-09

**Status**: Draft

**Input**: User description: "Import Pipeline v3 Bug 修复：修复英文文档导入时 language 和 tags 字段缺失、YAML parse error 的系统性问题；修复去重机制不完整问题（同一来源文档重复导入时，document-level source_hash 已存在应整批 skip、不再重新运行 LLM 提取）"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — English Document Produces Complete Metadata (Priority: P1)

A user imports an English-language incident document. Every generated KB entry must include a `language: en` field and a non-empty `tags` list in its frontmatter, and no YAML parse errors should be reported.

**Why this priority**: English is the second major input language after Chinese. Missing `language` and `tags` fields make these entries unsearchable by language filter or tag-based lookup, effectively orphaning them in the knowledge base. The YAML parse error signals an unstable generation path that could silently corrupt entries.

**Independent Test**: Import `TC-L02-english.md`; verify every generated pending entry has `language: en` and at least one tag; verify exit summary shows zero YAML errors.

**Acceptance Scenarios**:

1. **Given** an English-language source document, **When** the user runs `holmes import <doc>`, **Then** every generated entry frontmatter contains `language: en` and a non-empty `tags` list.
2. **Given** an English-language source document, **When** the user runs `holmes import <doc>`, **Then** the import summary reports zero YAML parse errors.
3. **Given** a Chinese-language source document, **When** the user runs `holmes import <doc>`, **Then** existing behavior is unchanged (`language: zh`, tags present).

---

### User Story 2 — Re-importing the Same Document Is a Complete No-Op (Priority: P2)

A user accidentally runs `holmes import` on a document that was already imported. The system detects that the document's identity hash already exists in the knowledge base and skips the entire import batch — no new entries are created, no LLM calls are made.

**Why this priority**: The current partial-skip behavior (`1 skipped + 1 created`) causes knowledge base pollution: near-identical duplicate entries degrade search quality and confuse reviewers. Full document-level dedup eliminates this class of problem.

**Independent Test**: Import the same document twice; verify the second run produces `0 created` and N skipped (where N = entries from first run); verify no new pending files exist after the second run.

**Acceptance Scenarios**:

1. **Given** a document previously imported, **When** the user runs `holmes import <same-doc>` a second time, **Then** the summary shows `0 created` and all entries appear as skipped.
2. **Given** a document previously imported, **When** the user runs `holmes import <same-doc>` a second time, **Then** the count of pending files is unchanged from after the first import.
3. **Given** a document previously imported, **When** the user runs `holmes import <same-doc> --force`, **Then** the document-level dedup check is bypassed and entries are re-created normally.
4. **Given** a document never imported before, **When** the user runs `holmes import <new-doc>`, **Then** the import proceeds normally and entries are created.

---

### Edge Cases

- What happens when a document contains both English and Chinese sections? Language is determined at document level by the existing classifier; mixed documents are treated as the detected primary language.
- What happens when tags cannot be inferred from the document content? The normalizer injects at least one fallback tag derived from the document category or title.
- What happens when `--force` is used on a document with an existing document-level hash? The dedup check is bypassed and a full re-import runs.
- What happens if the previous import's entries were already approved and moved out of `pending/`? The document-level hash check still fires — the document is considered already-imported regardless of pending status.

## Requirements *(mandatory)*

### Functional Requirements

**English Metadata Fix (US1)**

- **FR-001**: When generating a KB entry from an English-language source, the system MUST include `language: en` in the entry's frontmatter.
- **FR-002**: When generating a KB entry from any source language, the system MUST include a non-empty `tags` list in the entry's frontmatter; if the generation output contains no tags, the normalizer MUST inject at least one fallback tag.
- **FR-003**: The entry generation pipeline MUST NOT produce YAML parse errors for English-language documents under normal conditions; if the output contains malformed YAML, it MUST be repaired before writing.

**Document-Level Dedup Fix (US2)**

- **FR-004**: Before running LLM-based extraction, the system MUST check whether the source document's identity hash already exists among all KB entries (pending and approved); if it does, the import MUST be aborted entirely with all knowledge points reported as skipped.
- **FR-005**: The document-level hash check MUST execute before any LLM call, so no tokens are consumed on duplicate imports.
- **FR-006**: The `--force` flag MUST bypass the document-level hash check and allow full re-import.
- **FR-007**: The import summary MUST accurately report the count of skipped entries when a document-level duplicate is detected.

### Key Entities

- **Document identity hash**: A deterministic hash of the source document content that identifies whether a document has been previously imported; already stored as `source_hash` in each generated entry's frontmatter.
- **KB entry frontmatter**: The YAML block at the top of each `.md` entry file containing metadata fields including `language`, `tags`, `source_hash`, `type`, `category`, etc.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of entries generated from English-language documents contain both `language: en` and at least one tag — verifiable by importing TC-L02 and inspecting pending entries.
- **SC-002**: Zero YAML parse errors reported when importing any English-language test document.
- **SC-003**: Re-importing any previously imported document produces exactly `0 created` in the summary, regardless of how many entries the first import created.
- **SC-004**: The second import of a duplicate document makes zero LLM API calls — verifiable via mock in unit tests.
- **SC-005**: All existing tests continue to pass; new tests cover both fixes with at least 2 test cases each.

## Assumptions

- The source document language is detectable before the LLM extraction phase; the existing normalizer or classifier already has this signal available.
- "Document identity hash" means the hash of the full source document content, which is already computed and stored as `source_hash` — no new hashing infrastructure is needed.
- The `--force` flag already exists in the CLI; document-level bypass reuses the same flag for consistency.
- KB data files in `/home/wangzhi/holmes-kb/` are managed by users and the import pipeline only — this feature does not modify existing KB entries directly.
- Chinese-language document behavior must not regress; all existing tests for Chinese imports must continue to pass.
