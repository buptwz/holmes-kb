# Tasks: KB Access Control & Governance

**Input**: Design documents from `specs/003-kb-governance/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/cli-commands.md ✓

**Organization**: Tasks grouped by user story — each story can be implemented, tested, and validated independently.

---

## Phase 1: Setup (New Module Stubs)

**Purpose**: Create new module files and test stubs so all phases can proceed with no import errors.

- [x] T001 [P] Create kb/holmes/kb/governance.py with module docstring, imports (pathlib, frontmatter, typing)
- [x] T002 [P] Create kb/holmes/kb/history.py with module docstring, imports (pathlib, frontmatter, datetime, shutil)
- [x] T003 [P] Create kb/holmes/kb/decay.py with module docstring, DecayChange and DecayResult dataclass stubs, imports
- [x] T004 [P] Create kb/tests/test_governance.py with import of governance module and empty placeholder test
- [x] T005 [P] Create kb/tests/test_history.py with import of history module and empty placeholder test
- [x] T006 [P] Create kb/tests/test_decay.py with import of decay module and empty placeholder test

**Checkpoint**: All new modules importable without error

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema updates and store.py evidence functions used by ALL user stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T007 [P] Update kb/holmes/kb/schema.py — add `evidence`, `contributors` to optional frontmatter fields; add `contradiction` as optional bool field; add `EvidenceRecord` TypedDict with fields: session_id, contributor, date, project (optional), context (optional)
- [x] T008 Implement append_evidence(kb_root, entry_id, evidence_record) → bool in kb/holmes/kb/store.py: load entry, dedup by session_id, append record, save entry
- [x] T009 Implement derive_maturity(evidence: list[dict]) → str in kb/holmes/kb/store.py: 0 records→draft, ≥1→verified, ≥2 sessions AND ≥2 contributors→proven
- [x] T010 Implement add_contributor(kb_root, entry_id, contributor) in kb/holmes/kb/store.py: dedup append to contributors list
- [x] T011 Implement get_last_evidence_date(evidence: list[dict]) → Optional[str] in kb/holmes/kb/store.py: return max date from evidence array or None
- [x] T012 Implement resolve_maturity_conflict(local, incoming) → tuple[str, bool] in kb/holmes/kb/store.py: keep lower maturity value, return (lower, True)
- [x] T013 Write unit tests for store.py evidence functions in kb/tests/test_store.py: test append_evidence dedup, derive_maturity thresholds (0/1/2 records), resolve_maturity_conflict ordering

**Checkpoint**: Foundation ready — `pytest kb/tests/test_store.py` passes

---

## Phase 3: User Story 1 — 已确认知识只读保护 (Priority: P1) 🎯 MVP

**Goal**: All Agent writes to verified/proven entries are blocked at CLI layer; no write-entry command exists.

**Independent Test**: `holmes kb write-entry <id>` returns command-not-found; `governance.is_write_protected()` returns True for verified/proven entries; Agent must use `write-pending` for any change.

### Implementation for User Story 1

- [x] T014 [US1] Implement check_title_duplicate(kb_root, title, exclude_corrects=None) → Optional[str] in kb/holmes/kb/governance.py: scan all verified/proven entries, return matching ID or None
- [x] T015 [US1] Implement is_write_protected(kb_root, entry_id) → tuple[bool, str] in kb/holmes/kb/governance.py: return (True, error_msg) if maturity is verified/proven
- [x] T016 [US1] Verify kb/holmes/cli.py has no write-entry command; if present, remove it entirely; ensure no reference to write-entry in CLI registration
- [x] T017 [US1] Write unit tests in kb/tests/test_governance.py: test check_title_duplicate (match verified, match proven, no match, exclude_corrects skips target), test is_write_protected (draft→False, verified→True, proven→True, missing entry→False)

**Checkpoint**: US1 independently testable — `pytest kb/tests/test_governance.py` passes

---

## Phase 4: User Story 2 — Agent 沉淀新知识到私有暂存区 (Priority: P1)

**Goal**: write-pending creates pending entry with title duplicate guard; confirm moves entry to public KB and appends first EvidenceRecord, auto-deriving maturity as `verified`.

**Independent Test**: Agent calls write-pending → entry in contributions/pending/; confirm → entry in type/ dir, evidence[0] present, maturity=verified, pending entry deleted.

### Implementation for User Story 2

- [x] T018 [US2] Add --corrects option to write_pending() in kb/holmes/kb/pending.py: accept corrects=None param, write corrects field to frontmatter when provided
- [x] T019 [US2] Add title duplicate check to write_pending() in kb/holmes/kb/pending.py: call check_title_duplicate(); if match found AND corrects not set, raise DuplicateTitleError with entry_id
- [x] T020 [US2] Add --corrects TEXT option to write-pending CLI command in kb/holmes/cli.py; pass through to write_pending(); on DuplicateTitleError return JSON error with exit code 1
- [x] T021 [US2] Extend kb_confirm() in kb/holmes/cli.py (normal path, no corrects): after assigning permanent ID, call append_evidence() with first EvidenceRecord (contributor from --contributor option or current user, session from --session-id or generated), call add_contributor(); maturity auto-set via derive_maturity()
- [x] T022 [US2] Write integration tests in kb/tests/test_integration.py: test write-pending→confirm evidence append, maturity→verified; test reject flow; test duplicate title rejection; test write-pending with corrects bypasses duplicate check

**Checkpoint**: US2 independently testable — run quickstart.md US2 scenario end-to-end

---

## Phase 5: User Story 5 — Evidence 驱动的成熟度自动晋升 (Priority: P2)

**Goal**: update-refs appends EvidenceRecord per entry at session end; ≥2 sessions + ≥2 contributors auto-promotes verified→proven.

**Independent Test**: Call update-refs with second session + different contributor on a verified entry → evidence has 2 records from different sessions/contributors → maturity auto-promoted to proven; same session repeated → evidence deduplicated, no double-count.

### Implementation for User Story 5

- [x] T023 [US5] Extend update-refs CLI command in kb/holmes/cli.py: add --session-id TEXT (required), --contributor TEXT (required), --project TEXT, --context TEXT options; for each ID in --ids, call append_evidence() with constructed EvidenceRecord; collect and return {updated, skipped_duplicate, not_found, maturity_promoted} JSON
- [x] T024 [US5] Write tests for update-refs in kb/tests/test_integration.py: test deduplication (same session_id skipped), test promotion to proven (≥2 sessions + ≥2 contributors), test not_found handling, test maturity_promoted report

**Checkpoint**: US5 independently testable — verify proven auto-promotion via update-refs

---

## Phase 6: User Story 3 — 修正已确认知识的工作流 (Priority: P2)

**Goal**: write-pending --corrects creates correction proposal; confirm saves VersionSnapshot, replaces original while preserving evidence array.

**Independent Test**: Submit --corrects PT-DB-001 → pending has corrects field; confirm → .history/ has snapshot, PT-DB-001 content updated, evidence array preserved, pending deleted.

### Implementation for User Story 3

- [x] T025 [US3] Implement save_snapshot(kb_root, entry_id, original_content, replaced_by, reason) → Path in kb/holmes/kb/history.py: write .history/<id>-<YYYYMMDD-HHmmss>.md with replaced_at, replaced_by, snapshot_reason fields injected; create .history/ dir if absent
- [x] T026 [US3] Implement list_snapshots(kb_root, entry_id) → list[Path] in kb/holmes/kb/history.py: glob .history/<id>-*.md, sort by timestamp suffix
- [x] T027 [US3] Add correction confirm path to kb_confirm() in kb/holmes/cli.py: detect corrects field; look up original; call save_snapshot(); overwrite original with proposal (preserve evidence[], contributors, set maturity=verified, updated_at=now, remove corrects key); delete pending; rebuild index; print snapshot path
- [x] T028 [US3] Add holmes kb history <id> command to kb/holmes/cli.py: call list_snapshots(); print table of snapshot filenames + replaced_at timestamps; support --json flag
- [x] T029 [US3] Write tests in kb/tests/test_history.py: test save_snapshot creates file in .history/ with correct fields; test list_snapshots returns sorted list; write integration test for correction confirm path (snapshot present, original updated, evidence preserved)

**Checkpoint**: US3 independently testable — run quickstart.md US3 scenario end-to-end

---

## Phase 7: User Story 4 — 知识成熟度自动衰减与归档 (Priority: P3)

**Goal**: decay command scans entries, demotes overdue ones, saves snapshots; archive-orphans moves evidence-less draft entries to contributions/archive/.

**Independent Test**: Seed proven entry with evidence date 13 months ago → `holmes kb decay --dry-run` reports it → `holmes kb decay` applies demotion + snapshot saved; seed draft with no evidence → `holmes kb archive-orphans` moves it to contributions/archive/.

### Implementation for User Story 4

- [x] T030 [US4] Implement _get_reference_date(metadata) → datetime in kb/holmes/kb/decay.py: check evidence array max date, fallback to last_referenced, fallback to updated_at
- [x] T031 [US4] Implement _load_decay_config(kb_root) → dict in kb/holmes/kb/decay.py: read kb-config.yml if present; return {proven_months: 12, verified_months: 6} defaults
- [x] T032 [US4] Implement run_decay(kb_root, dry_run=False, kb_type=None) → DecayResult in kb/holmes/kb/decay.py: scan all public entries, compute months_unreferenced, apply thresholds, call save_snapshot() on demotion, update frontmatter (maturity + updated_at), append log entry, collect DecayChange per demotion
- [x] T033 [US4] Add holmes kb decay command to kb/holmes/cli.py: call run_decay(); support --dry-run, --type, --json options; print human table or JSON per contract; exit 0 on success, exit 1 if any errors
- [x] T034 [US4] Implement archive_orphan(kb_root, entry_id) → Path in kb/holmes/kb/decay.py: move draft entry with empty evidence[] to contributions/archive/; rebuild index; append log entry
- [x] T035 [US4] Add holmes kb archive-orphans command to kb/holmes/cli.py: scan draft entries with empty evidence[], call archive_orphan() for each; print list of archived IDs
- [x] T036 [US4] Write tests in kb/tests/test_decay.py: test _get_reference_date (evidence max date, fallback paths), test run_decay dry_run flag (no writes), test proven→verified threshold, test verified→draft threshold, test no decay within threshold, test partial-failure logging

**Checkpoint**: US4 independently testable — `pytest kb/tests/test_decay.py` passes; run quickstart.md US4 decay scenario

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: CLAUDE.md update, conflict detection wiring, quickstart refresh.

- [x] T037 [P] Update ~/.holmes/CLAUDE.md: replace per-read touch step with session-end update-refs batch; add write-pending / --corrects write guidance; add knowledgeReferences structured output note
- [x] T038 [P] Update ~/holmes-kb/CLAUDE.md with identical changes as T037
- [x] T039 [P] Update specs/003-kb-governance/quickstart.md: remove touch and write-entry references; add update-refs example with --session-id/--contributor; update US4 decay seed to use evidence array instead of last_referenced_at
- [x] T040 Wire resolve_maturity_conflict() into log detection: add `holmes kb check-conflicts` command (or note in lint output) in kb/holmes/cli.py that scans for entries with `contradiction: true` and lists them; log event when contradiction detected
- [x] T041 Run full quickstart.md end-to-end validation across US1–US4 scenarios and confirm all expected outputs

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately; all T001–T006 are parallel
- **Phase 2 (Foundational)**: Depends on Phase 1; T007 parallel to T008–T012; T008→T009→T010→T011 are sequential (same file); T013 depends on T008–T012
- **Phase 3 (US1)**: Depends on Phase 2 — T014–T015 depend on governance.py stub (T001); T016 is independent
- **Phase 4 (US2)**: Depends on Phase 2 + Phase 3 (T014 check_title_duplicate used by T019)
- **Phase 5 (US5)**: Depends on Phase 4 (update-refs extends confirm flow)
- **Phase 6 (US3)**: Depends on Phase 2 + Phase 4 (cli.py correction path extends confirm)
- **Phase 7 (US4)**: Depends on Phase 2 + Phase 6 (T025 save_snapshot used by T032)
- **Phase 8 (Polish)**: Depends on all implementation phases

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 2 — no story dependencies
- **US2 (P1)**: Can start after Phase 2; uses check_title_duplicate from US1 (T014)
- **US5 (P2)**: Can start after US2 (Phase 4) — extends update-refs CLI
- **US3 (P2)**: Can start after Phase 2 + US2 (Phase 4); shares cli.py confirm extension
- **US4 (P3)**: Can start after Phase 2 + US3 (Phase 6); reuses save_snapshot from T025

### Within Each User Story

- Module implementations before CLI wiring
- CLI wiring before integration tests
- Integration tests should match quickstart.md scenarios

### Parallel Opportunities

- T001–T006 all run in parallel (different new files)
- T007 (schema.py) runs in parallel with T008–T012 (store.py) — different files
- T014 and T015 (both governance.py) can be written together in one pass
- T025 and T026 (history.py save + list) can be written in one pass
- T030–T032 (decay internals, same file) are sequential; T033 (CLI) depends on T032
- T037 and T038 (CLAUDE.md updates, different files) run in parallel

---

## Parallel Example: Phase 1

```bash
# All 6 module stubs can be created simultaneously:
Task T001: kb/holmes/kb/governance.py
Task T002: kb/holmes/kb/history.py
Task T003: kb/holmes/kb/decay.py
Task T004: kb/tests/test_governance.py
Task T005: kb/tests/test_history.py
Task T006: kb/tests/test_decay.py
```

## Parallel Example: Phase 2

```bash
# schema.py and store.py are different files — run in parallel:
Task T007: kb/holmes/kb/schema.py  (EvidenceRecord TypedDict + field additions)
Task T008: kb/holmes/kb/store.py   (append_evidence, derive_maturity, ...)
```

---

## Implementation Strategy

### MVP First (US1 + US2 Only)

1. Complete Phase 1 + Phase 2 (Foundational)
2. Complete Phase 3 (US1 — write protection)
3. Complete Phase 4 (US2 — pending + confirm with evidence)
4. **STOP and VALIDATE**: Run quickstart.md US1 + US2 scenarios
5. Maturity lifecycle works end-to-end

### Incremental Delivery

1. Phase 1 + Phase 2 → Evidence data model ready
2. Phase 3 (US1) → Write protection active
3. Phase 4 (US2) → Pending/confirm with evidence → MVP!
4. Phase 5 (US5) → update-refs and auto-promotion
5. Phase 6 (US3) → Correction workflow + history
6. Phase 7 (US4) → Decay + archive
7. Phase 8 → Polish + CLAUDE.md update

---

## Notes

- [P] = different files, no blocking dependencies — can run in parallel
- [Story] label maps each task to its user story for traceability
- T007–T012 are foundational — do not skip to user story phases
- quickstart.md US4 still references `touch` and `last_referenced_at` (old design) — T039 updates it
- `holmes kb history <id>` is a new command, not in old contracts — added in T028
- `holmes kb check-conflicts` (T040) is a lightweight scan for `contradiction: true` entries
- Commit after each phase checkpoint
