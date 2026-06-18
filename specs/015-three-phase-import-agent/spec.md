# Feature Specification: Three-Phase Import Agent

**Feature Branch**: `015-three-phase-import-agent`

**Created**: 2026-06-08

**Status**: Draft

**Input**: User description: "三阶段 import agent 架构重构：Reader → Extractor → Verifier 三阶段管道，借鉴 Claude Code 设计模式"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Large Document Import Without Data Loss (Priority: P1)

A KB maintainer runs `holmes import` on a long technical runbook (e.g. a 10,000-character operations manual). Today, fields that exist in the original document are silently cleared because the system only inspects the first portion of the document during verification. After this feature, every field in the resulting KB entry is verifiable against the full original document, and no valid field is ever cleared due to document length.

**Why this priority**: Silent data loss is worse than no import. Users who trust the pipeline lose confidence when verified entries are missing fields that were clearly present in the source. This is the highest-impact correctness issue.

**Independent Test**: Import a document longer than 8,000 characters where the resolution section appears after character 8,000. Verify that the resulting KB entry has a non-empty resolution section and that no fields have been cleared with a "no source support" reason.

**Acceptance Scenarios**:

1. **Given** a document of 12,000 characters with the resolution steps in the final third, **When** `holmes import` is run, **Then** the created entry contains the resolution steps verbatim and the import report shows zero falsely-cleared fields.
2. **Given** a document where the title is on line 1 and the resolution spans lines 200–250, **When** `holmes import` is run, **Then** both the title and the resolution are present in the created entry with full confidence.
3. **Given** a document that was previously producing a "title cleared: no source support" warning, **When** re-imported with the new pipeline, **Then** no such warning appears and the title is populated correctly.

---

### User Story 2 — Multi-Knowledge-Point Document: Independent Extraction (Priority: P1)

A KB maintainer imports a document that describes three distinct production incidents. Today all three knowledge points are extracted in a single pass where earlier extractions contaminate the context for later ones, leading to merged or garbled entries. After this feature, each knowledge point is extracted independently with a clean context, producing three separate, correctly scoped KB entries.

**Why this priority**: Multi-knowledge-point documents are common (incident post-mortems, weekly runbooks). Context pollution between knowledge points degrades quality for all entries in such documents.

**Independent Test**: Import a document containing three clearly distinct incidents separated by headings. Verify that exactly three pending entries are created, each scoped to its respective incident with no content from sibling incidents leaking in.

**Acceptance Scenarios**:

1. **Given** a document with three incidents (A, B, C) each with distinct symptoms and root causes, **When** `holmes import` is run, **Then** three separate entries are created, each matching only its own incident's facts.
2. **Given** a document where incident A mentions "Redis" and incident B mentions "MySQL" with no overlap, **When** `holmes import` is run, **Then** entry A does not mention MySQL and entry B does not mention Redis.
3. **Given** a document where knowledge point 3 has a longer resolution than knowledge points 1 and 2, **When** `holmes import` is run, **Then** knowledge point 3's entry contains its full resolution, not a truncated version.

---

### User Story 3 — Reliable Skill Generation for Any Language (Priority: P2)

A KB maintainer imports a Chinese-language runbook with step-by-step resolution commands. Today, Skill generation silently fails for Chinese documents because the system cannot locate the resolution section written in Chinese. After this feature, Skill generation works correctly regardless of whether the document is in English or Chinese, and the maintainer sees a Skill candidate in the import report.

**Why this priority**: KB-Skill linkage is a key differentiator of the system. Zero Skill generation across all tests (as reported in v13) means the feature is effectively non-functional. Chinese documents are the majority of real-world inputs.

**Independent Test**: Import a Chinese runbook with a `## 解决方案` section containing at least two shell commands. Verify that the import report contains a Skill recommendation or a created Skill entry.

**Acceptance Scenarios**:

1. **Given** a Chinese runbook with `## 诊断步骤` and two bash commands, **When** `holmes import` is run, **Then** the import report shows `skill candidate:` or `Would create skill:` for the entry.
2. **Given** an English runbook with `## Resolution` and three bash commands, **When** `holmes import` is run, **Then** a Skill is created and linked to the entry.
3. **Given** a document with no shell commands in the resolution, **When** `holmes import` is run, **Then** no Skill is created and no false positive Skill recommendation appears.

---

### User Story 4 — Consistent Import Quality Across Document Sizes (Priority: P2)

A KB maintainer imports a batch of documents ranging from 500 characters to 15,000 characters. Today, quality degrades unpredictably for longer documents. After this feature, the import quality score (field completeness, no false clears, correct type classification) is consistent regardless of document length, and the `--verbose` report accurately reflects the provenance of every field.

**Why this priority**: Predictable quality enables trust. Users should not need to worry about document length as a hidden quality variable.

**Independent Test**: Import five documents of increasing length (1K, 3K, 6K, 10K, 15K characters). Verify that field completeness does not degrade as document size increases.

**Acceptance Scenarios**:

1. **Given** five documents of increasing length all describing similar types of incidents, **When** each is imported, **Then** all five have equivalent field completeness scores (no systematic degradation).
2. **Given** a 15,000-character document, **When** `holmes import --verbose` is run, **Then** every field in the trace shows a specific source reference, not a generic "truncated" warning.
3. **Given** any document, **When** `holmes import` is run, **Then** the import completes without emitting a "Source truncated" warning unless the user is explicitly informed and no quality regression occurs.

---

### Edge Cases

- What happens when a document has no identifiable knowledge points (e.g., a pure configuration file with no incidents)?
- How does the pipeline handle a document where all content appears after character 15,000?
- What happens when knowledge points in a multi-point document share terminology (near-duplicate detection)?
- How does the system behave when the document is in a language other than English or Chinese (e.g., Japanese)?
- What happens when a Chinese resolution section header has a space (e.g., `## 解决 方案`)?
- How is import progress reported when processing a large document takes significantly longer than a short one?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The import pipeline MUST process the full content of any document regardless of length, without discarding or truncating knowledge from any section.
- **FR-002**: The pipeline MUST extract each distinct knowledge point from a multi-knowledge-point document in an isolated context, so that one knowledge point's content cannot influence another's extraction.
- **FR-003**: The verification step MUST have access to the complete original document when checking whether any field has source support, not a length-limited excerpt.
- **FR-004**: Skill generation MUST correctly identify resolution sections written in Chinese, including at minimum: `## 解决方案`, `## 解决步骤`, `## 诊断步骤`, `## 操作步骤`, `## 恢复步骤`, `## 修复步骤`.
- **FR-005**: Skill generation MUST correctly detect shell commands from database CLI tools (mysql, psql, mongosh, redis-cli, etc.) in addition to generic Unix commands.
- **FR-006**: The Skill recommendation threshold MUST produce a `RECOMMENDED` outcome for entries with 2 or more detected command steps (previously 3).
- **FR-007**: The import pipeline MUST produce a structured knowledge summary (KnowledgeMap) as an intermediate artifact after reading the document, capturing all identified knowledge points before entering extraction.
- **FR-008**: The pipeline MUST provide tools for on-demand access to specific sections of the original document by position or heading, rather than relying on a pre-truncated copy.
- **FR-009**: The pipeline MUST detect when additional reading of a document yields no new knowledge points (diminishing returns) and stop reading gracefully, reporting coverage percentage.
- **FR-010**: The `--verbose` report MUST show per-field source evidence even for documents longer than 8,000 characters.
- **FR-011**: Dry-run mode MUST NOT produce duplicate `Would create:` lines for the same entry.
- **FR-012**: Batch import MUST output per-entry decision traces when `--verbose` is specified, not only a summary line.

### Key Entities

- **KnowledgeMap**: An intermediate structured summary produced after reading the full document. Contains a list of identified knowledge points, each with: a brief description, the document section(s) it originates from, and whether it has been extracted yet.
- **KnowledgePoint**: One discrete unit of knowledge (e.g., one incident, one guideline, one operational procedure) identified within the source document.
- **DocumentCursor**: A record of which sections of the source document have been read so far, enabling incremental reading and coverage reporting.
- **VerificationContext**: The full original source text made available to the verification step, independent of any truncation applied to the LLM prompt.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Documents up to 20,000 characters produce KB entries with zero falsely-cleared fields attributable to document length (measured by re-importing the v13 test corpus W1 document and confirming no CLEARED warnings for fields present in the original).
- **SC-002**: A three-knowledge-point document produces exactly three entries with no cross-contamination (verified by checking that entry A contains no content from incident B or C, and vice versa).
- **SC-003**: Chinese-language runbooks with `## 诊断步骤` / `## 解决方案` sections produce a Skill recommendation in 100% of cases where the resolution contains at least 2 shell commands.
- **SC-004**: Import quality (field completeness) does not degrade by more than 5% between a 3,000-character document and a 15,000-character document of equivalent content density.
- **SC-005**: All 455 existing tests continue to pass after the refactor.
- **SC-006**: Dry-run mode produces exactly one `Would create:` line per unique planned entry with no duplicates.

## Assumptions

- The existing `ImportAgentRunner` public interface (`run(source_text, file_path)` → `ImportReport`) is preserved; callers are not affected by internal pipeline changes.
- The three-phase pipeline runs synchronously within the existing `holmes import` CLI command; no background processes or async job queues are introduced.
- LLM costs may increase slightly for large documents due to more thorough processing; this is acceptable given the quality improvement.
- The feature targets documents up to approximately 20,000 characters; documents beyond this length may still degrade in quality and can be addressed in a future iteration.
- Chinese document support covers Simplified Chinese; Traditional Chinese headers are treated as a best-effort extension.
- The `detect_commands()` utility continues to serve as the deterministic command-counting mechanism; the LLM is not used for command detection.
- Existing pending entries and KB data are not affected; the new pipeline only changes how new imports are processed.
