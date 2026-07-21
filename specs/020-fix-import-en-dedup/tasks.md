---

description: "Task list for Import Pipeline v3 Bug Fixes — English Metadata & Document-Level Dedup (020)"

---

# Tasks: Import Pipeline v3 Bug Fixes — English Metadata & Document-Level Dedup

**Input**: Design documents from `specs/020-fix-import-en-dedup/`

**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ quickstart.md ✅

**Organization**: Phase 3 (US1, P1) is MVP — fixes English metadata. Phase 4 (US2, P2) fixes document-level dedup. US1 and US2 touch different parts of the pipeline and can be worked in parallel after T001.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

**Purpose**: Verify working environment and confirm existing test baseline.

- [X] T001 Run existing test suite (`cd kb && python -m pytest tests/ -q`) and record baseline pass count to confirm no pre-existing failures (648 passed)

---

## Phase 2: Foundational

No shared infrastructure needed — both fixes are isolated to existing modules.

---

## Phase 3: User Story 1 — English Document Produces Complete Metadata (Priority: P1) 🎯 MVP

**Goal**: Every entry generated from an English-language source document has `language: en` and at least one tag; zero YAML parse errors.

**Independent Test**: Import `TC-L02-english.md` → inspect pending entry frontmatter for `language: en` and non-empty `tags`; verify exit summary shows zero errors.

- [X] T002 [US1] In `kb/holmes/kb/agent/pipeline.py`, swap the order of YAML repair and normalization: move `ExtractorAgent._validate_and_repair_draft(draft)` call to BEFORE `normalizer.normalize(draft, ...)` so normalization always runs on valid YAML (currently lines ~179–186 in the KP extraction loop)
- [X] T003 [US1] In `kb/holmes/kb/agent/normalizer.py` `DraftNormalizer.normalize()`, add **Step 3a** between the existing step 3 (title enforcement) and step 4 (tag extraction): read `lang = meta.get("language", "") or ""`; if empty, scan `title + body` for CJK characters (`re.search(r'[\u4e00-\u9fff]', title + body)`); set `meta["language"] = "zh" if match else "en"`; append warning `f'language: injected "{meta["language"]}" (auto-detected)'`
- [X] T004 [US1] In `kb/holmes/kb/agent/normalizer.py` `DraftNormalizer._extract_tags()`, after the token extraction loop, add a category fallback: if `new_tags` is still empty after the loop, append `str(meta.get("category", "unknown"))` as a single fallback tag and add a warning
- [X] T005 [US1] Add unit tests in `kb/tests/test_normalizer.py`: (a) test that an entry with no `language` field and English content gets `language: en` injected; (b) test that an entry with no `language` field and Chinese content gets `language: zh` injected; (c) test that an existing `language` field is not overwritten; (d) test that an entry with no tags and no meaningful tokens gets the category as fallback tag

**Checkpoint**: After T002–T005, importing an English document produces entries with `language: en` and at least one tag; no YAML errors.

---

## Phase 4: User Story 2 — Re-importing the Same Document Is a Complete No-Op (Priority: P2)

**Goal**: Second import of any previously imported document produces `0 created` and all entries as skipped; no LLM calls made.

**Independent Test**: Import same document twice; verify `0 created` on second run; verify pending file count unchanged.

- [X] T006 [US2] In `kb/holmes/kb/agent/tools.py`, add helper function `_find_all_entries_by_hash(kb_root: Path, source_hash: str) -> list[tuple[str, str]]` below the existing `_find_entry_by_hash`: scans both `list_entries(kb_root)` (approved entries) and `pending_dir.glob("*.md")` (pending entries); collects ALL `(entry_id, file_path)` pairs where `source_hash` matches; returns the full list
- [X] T007 [US2] In `kb/holmes/kb/agent/pipeline.py` `ThreePhaseImportPipeline.__init__()`, add `force: bool = False` parameter and store as `self.force = force`
- [X] T008 [US2] In `kb/holmes/kb/agent/pipeline.py` `run()`, immediately after `source_hash = compute_source_hash(source_text)` and before the DocumentClassifier call, add the document-level pre-check: `if not self.dry_run and not self.force: existing = _find_all_entries_by_hash(self.kb_root, source_hash); if existing: for entry_id, _ in existing: report.skipped.append(entry_id); report.warnings.append(f"document already imported (source_hash={source_hash[:8]}...): {len(existing)} entries skipped"); return report`
- [X] T009 [US2] Wire the `--force` CLI flag through to `ThreePhaseImportPipeline`: `--force` already existed in CLI; added `force` param to `ImportAgentRunner` and `ThreePhaseImportPipeline`, passed through in `cli.py`
- [X] T010 [US2] Add unit tests in `kb/tests/test_pipeline.py`: (a) mock `_find_all_entries_by_hash` to return a non-empty list; call `pipeline.run(source_text)`; verify return is immediate (report has skipped entries, no LLM calls); (b) mock returns empty list; verify pipeline proceeds normally; (c) set `force=True`; mock returns non-empty list; verify pipeline proceeds (dedup bypassed); (d) `dry_run=True`; mock returns non-empty list; verify pipeline proceeds (dry-run bypasses doc-level dedup)

**Checkpoint**: After T006–T010, re-importing any document is a complete no-op; `--force` bypasses dedup.

---

## Phase 5: Polish & Validation

- [X] T011 Run full test suite (`cd kb && python -m pytest tests/ -q`) and verify pass count ≥ baseline + new tests; zero failures (656 passed, +8 new)
- [ ] T012 Run quickstart.md Scenario 4 (re-import no-op) and Scenario 1 (English metadata) to confirm end-to-end behaviour

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1** (T001): No dependencies — run first
- **Phase 3** (T002–T005): Depends on T001; can run in parallel with Phase 4 (different files)
- **Phase 4** (T006–T010): Depends on T001; can run in parallel with Phase 3 (T006 in tools.py; T007–T009 in pipeline.py)
- **Phase 5** (T011–T012): Depends on all prior phases

### Parallel Opportunities

- T002–T004 (normalizer.py + pipeline.py order) can run in parallel with T006 (tools.py)
- T005 (normalizer tests) can run in parallel with T010 (pipeline tests)
- T007–T009 are sequential (same pipeline.py file)

---

## Implementation Strategy

### MVP (User Story 1 Only)

1. T001 — verify baseline
2. T002–T004 — fix English metadata pipeline
3. T005 — add tests
4. T011 — verify tests pass
5. **STOP**: English document metadata is fixed

### Full Delivery

Complete phases in order: 1 → 3/4 (parallel) → 5.

---

## Notes

- T002 (order swap in pipeline.py) is the highest-leverage change: it unblocks normalization for ALL malformed drafts, not just English ones
- T003 (language injection) and T004 (fallback tag) are additive steps to DraftNormalizer — they do not change existing normalization logic
- T006 (`_find_all_entries_by_hash`) is a pure addition; it does not modify `_find_entry_by_hash`
- T009 (CLI wiring) may be a no-op if `--force` already flows through to pipeline; verify first
- Constitution: 验证原则 requires tests for each fix (T005, T010)
