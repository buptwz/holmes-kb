# Tasks: Import Pipeline Performance Optimization

**Input**: Design documents from `specs/028-import-pipeline-perf/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/cli-contract.md ✓

---

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: User story (US1–US5)

---

## Phase 1: Setup

**Purpose**: No new project structure needed — all changes are in-place modifications to existing files. Verify baseline test suite passes before any changes.

- [ ] T001 Verify full test suite passes on current `main` branch: `cd kb && python -m pytest tests/ -q`

---

## Phase 2: Foundational — Config Extension

**Purpose**: Extend `HolmesConfig` with the 5 new optional fields consumed by all optimizations. Must be complete before any other phase.

**⚠️ CRITICAL**: All other phases read `extractor_concurrency`, `dir_concurrency`, and `retry_*` from config. This phase MUST complete first.

- [ ] T002 Add `extractor_concurrency: int = 4`, `dir_concurrency: int = 4`, `retry_max_attempts: int = 5`, `retry_base_delay: float = 1.0`, `retry_max_delay: float = 60.0` optional fields to `HolmesConfig` in `kb/holmes/config.py`
- [ ] T003 Confirm `holmes config set extractor_concurrency 1` and `holmes config show` round-trip correctly (manual smoke test)

**Checkpoint**: `HolmesConfig` has 5 new fields with defaults. All existing tests still pass.

---

## Phase 3: User Story 4 — `list_entries` In-Process Cache (Priority: P2) 🎯 Highest ROI

**Goal**: Eliminate O(n) disk scan on every `list_entries` call within a single import run. Cache is populated on first call and invalidated on any KB write.

**Why first (before P1 stories)**: Fully self-contained, zero risk of quality regression, immediately measurable via `store.py` unit tests. Unblocks accurate baseline measurements for all other phases.

**Independent Test**: `python -m pytest tests/kb/test_store_cache.py -v` passes. Instrument `list_entries` and confirm `rglob` is called at most once per import invocation on a KB with 20+ entries.

### Implementation

- [ ] T004 [P] [US4] Add module-level `_CACHE: dict[tuple[str, bool], list[EntryMeta]] = {}` and `invalidate_cache() -> None` function to `kb/holmes/kb/store.py` (above `list_entries`)
- [ ] T005 [US4] Refactor `list_entries` in `kb/holmes/kb/store.py` to: on first call populate `_CACHE[(str(kb_root), include_pending)]`; apply `kb_type`/`category`/`query`/`limit`/`offset` filters in-memory after cache hit; return filtered results
- [ ] T006 [US4] Call `invalidate_cache()` at the end of `write_entry()` in `kb/holmes/kb/store.py`
- [ ] T007 [P] [US4] Call `invalidate_cache()` at the end of `write_pending()` in `kb/holmes/kb/pending.py` (after `atomic_write` succeeds)
- [ ] T008 [US4] Write `kb/tests/kb/test_store_cache.py`: test cache hit (second call returns same list without disk scan), cache invalidation after `write_entry`, cache invalidation after `write_pending`, `include_pending=True` and `include_pending=False` are cached under separate keys
- [ ] T009 [US4] Run `python -m pytest tests/kb/test_store_cache.py tests/kb/test_store.py -v` — all pass

**Checkpoint**: Cache hit/miss/invalidation verified. All existing store tests pass.

---

## Phase 4: User Story 3 — Rate-Limit Retry + AnthropicProvider Error Coverage (Priority: P2)

**Goal**: Both providers automatically retry on rate-limit and 5xx errors with exponential backoff + jitter. `AnthropicProvider` gains full error-type parity with `OpenAIProvider`.

**Independent Test**: `python -m pytest tests/kb/agent/provider/test_retry.py -v` passes. Simulate `RateLimitError` from mock provider — confirm pipeline retries up to `retry_max_attempts` times before raising `RuntimeError`.

### Implementation

- [ ] T010 [P] [US3] Add `_call_with_retry(fn, max_attempts, base_delay, max_delay) -> Any` module-level helper to `kb/holmes/kb/agent/provider/base.py`: loop `max_attempts` times; on `RateLimitError` or 5xx `APIStatusError` sleep `min(base_delay * 2**attempt, max_delay) + random.uniform(0, 1)` and retry; on last attempt re-raise as `RuntimeError("Rate limit not resolved after N retries")`. Import `time`, `random` at top of file.
- [ ] T011 [US3] Wrap `self._client.messages.create(...)` call in `AnthropicProvider.complete()` in `kb/holmes/kb/agent/provider/anthropic_provider.py` with `_call_with_retry`; add `except anthropic.AuthenticationError` fast-fail (same message as OpenAIProvider); add `except anthropic.RateLimitError` and `except anthropic.APIStatusError` (5xx) to trigger retry
- [ ] T012 [US3] Wrap `self._client.messages.create(...)` call in `AnthropicProvider.simple_complete()` in `kb/holmes/kb/agent/provider/anthropic_provider.py` with the same retry wrapper
- [ ] T013 [US3] Store `retry_max_attempts`, `retry_base_delay`, `retry_max_delay` as instance attrs in `AnthropicProvider.__init__` (read from `cfg`); pass them to `_call_with_retry` calls
- [ ] T014 [P] [US3] Replace the bare `except openai.RateLimitError: raise RuntimeError(...)` blocks in `OpenAIProvider.complete()` and `OpenAIProvider.simple_complete()` in `kb/holmes/kb/agent/provider/openai_provider.py` with calls to `_call_with_retry`; store retry params in constructor the same way
- [ ] T015 [US3] Write `kb/tests/kb/agent/provider/test_retry.py`: mock provider that raises `RateLimitError` then succeeds; assert retry count; mock that always raises — assert final `RuntimeError`; assert auth error is NOT retried; assert delay values are within expected bounds (with `time.sleep` patched)
- [ ] T016 [US3] Run `python -m pytest tests/kb/agent/provider/test_retry.py tests/kb/agent/provider/ -v` — all pass

**Checkpoint**: Both providers retry on rate-limit; auth errors fail fast; existing provider tests pass.

---

## Phase 5: User Story 1 — Phase 3 Per-KP Context Isolation (Priority: P1) 🎯 MVP

**Goal**: Each knowledge-point draft in Phase 3 runs its own isolated LLM tool-use loop with a fresh `messages=[]`. No KP ever sees sibling drafts or their tool results in its context.

**Independent Test**: `python -m pytest tests/kb/agent/test_pipeline_phase3_isolation.py -v` passes. Verify that for a 3-KP import, `provider.complete()` is called at least 3 separate times with `messages` that never contain drafts from other KPs.

### Implementation

- [ ] T017 [US1] Refactor `ThreePhaseImportPipeline._run_extraction_loop()` in `kb/holmes/kb/agent/pipeline.py`: replace the single mega-loop with `for kp_id, draft in kp_drafts.items()`: build `per_kp_user_prompt` containing only `source_hash + file + SOURCE TEXT (scoped slice or full fallback) + single draft block`; initialize `messages = [{"role": "user", "content": per_kp_user_prompt}]`; run the tool-use loop to completion; discard `messages` after the loop ends
- [ ] T018 [US1] In the per-KP `SOURCE TEXT` section, use `kp.section_start:kp.section_end` slice from `knowledge_map` when the KP has non-zero bounds; fall back to full `source_text` when bounds are zero or unknown. Look up the KP from `report.knowledge_map` by `kp_id`.
- [ ] T019 [US1] Scale `iteration_limit` per KP to `max(MAX_TOOL_ITERATIONS, 6)` (instead of `len(kp_drafts) * 6`) since each loop handles only one draft now
- [ ] T020 [US1] Add `skip_git_commit: bool = False` parameter to `ThreePhaseImportPipeline.__init__` and store as `self.skip_git_commit`; in `_run_extraction_loop` wrap the `runner._git_commit(...)` call with `if not self.skip_git_commit:`
- [ ] T021 [US1] Update phase_traces reporting to say `Verifier+Writer: N created, M updated (per-KP isolated context)` in `kb/holmes/kb/agent/pipeline.py`
- [ ] T022 [US1] Write `kb/tests/kb/agent/test_pipeline_phase3_isolation.py`: mock provider recording all `messages` args; run a 3-KP pipeline; assert that for each LLM call sequence, no call's `messages[0]["content"]` contains draft content from a different KP; assert all 3 KPs result in `write_kb_entry` tool calls
- [ ] T023 [US1] Run `python -m pytest tests/kb/agent/test_pipeline_phase3_isolation.py tests/kb/agent/test_pipeline.py -v` — all pass

**Checkpoint**: Phase 3 runs once per draft. Context never grows beyond a single KP. All existing pipeline tests pass.

---

## Phase 6: User Story 2 — Extractor Parallelism (Priority: P1)

**Goal**: Extractor agents for all knowledge points run concurrently in a `ThreadPoolExecutor`. Each worker gets its own `DocumentCursor` copy. Results are merged into the main `report` after all futures complete.

**Independent Test**: `python -m pytest tests/kb/agent/test_extractor_parallel.py -v` passes. For a 4-KP document, verify that Extractor workers start concurrently (mock provider records call timestamps; all 4 start within 0.5s of each other).

### Implementation

- [ ] T024 [US2] Add `ExtractorResult` dataclass to `kb/holmes/kb/agent/pipeline.py` (before `ThreePhaseImportPipeline`): fields `kp_id: str`, `draft: Optional[str]`, `repaired: Optional[str]`, `errors: list[str]`, `warnings: list[str]`, `phase_traces: list[str]`
- [ ] T025 [US2] Add `_extract_single_kp(kp, knowledge_map, ctx_copy, force_type) -> ExtractorResult` private function in `kb/holmes/kb/agent/pipeline.py`: creates a fresh `ExtractorAgent` instance, runs `extractor.run(kp, knowledge_map, ctx_copy)`, applies `_validate_and_repair_draft`, applies `DraftNormalizer`, applies `force_type` override, applies verbatim resolution fallback — returns `ExtractorResult` with all outputs and accumulated errors/warnings. This is the body currently inside the serial for-loop at lines 240-281.
- [ ] T026 [US2] Replace the serial Extractor for-loop in `ThreePhaseImportPipeline.run()` in `kb/holmes/kb/agent/pipeline.py` with `ThreadPoolExecutor(max_workers=self.cfg.extractor_concurrency)`: for each `kp` submit `_extract_single_kp(kp, knowledge_map, ctx_copy, self.force_type)` where `ctx_copy` is a shallow copy of `ctx` with `ctx_copy["doc_cursor"] = DocumentCursor(source_text)` (new cursor per worker); collect `Future` objects; iterate `as_completed(futures)` to merge `ExtractorResult` into `kp_drafts` and `report`
- [ ] T027 [US2] Update the Extractor phase_trace to say `Extractor: N/M knowledge points extracted (parallel, K workers)` where K is `min(extractor_concurrency, len(kps))` in `kb/holmes/kb/agent/pipeline.py`
- [ ] T028 [US2] Import `concurrent.futures`, `copy` (for ctx shallow copy), `DocumentCursor` at the top of `kb/holmes/kb/agent/pipeline.py`
- [ ] T029 [US2] Write `kb/tests/kb/agent/test_extractor_parallel.py`: mock `ExtractorAgent.run()` with a sleep + return; run with 4 KPs and `extractor_concurrency=4`; assert all 4 ran; assert total wall time < 2× single-worker time; assert `kp_drafts` has 4 entries; assert `report.errors` and `report.warnings` are merged correctly
- [ ] T030 [US2] Run `python -m pytest tests/kb/agent/test_extractor_parallel.py tests/kb/agent/test_pipeline.py -v` — all pass

**Checkpoint**: Extractor phase is concurrent. Serial behavior confirmed with `extractor_concurrency=1`. All pipeline tests pass.

---

## Phase 7: User Story 5 — `--dir` Concurrent Batch + Single Git Commit (Priority: P2)

**Goal**: `holmes import --dir` processes files concurrently with a configurable limit. All files share one final git commit. Failures do not abort remaining files.

**Independent Test**: `python -m pytest tests/kb/test_cli_dir_batch.py -v` passes. Verify that a 5-file --dir import produces exactly one git commit and that all 5 files' `runner.run()` calls overlap in time.

### Implementation

- [ ] T031 [US5] Add `--dir-concurrency` option (type=int, default=None) to the `import` command in `kb/holmes/cli.py`; when `None`, fall back to `cfg.dir_concurrency` (default 4)
- [ ] T032 [US5] Replace the serial `for idx, f in enumerate(importable, 1):` loop in the `--dir` branch of `kb/holmes/cli.py` with `ThreadPoolExecutor(max_workers=dir_concurrency)`: submit each file as `executor.submit(_import_one_file, f, idx, total, runner_factory, kb_root_path)`; collect results via `as_completed`; print each result line as it arrives (thread-safe via `click.echo` which acquires GIL per call)
- [ ] T033 [US5] Extract the per-file logic into a `_import_one_file(f, idx, total, runner_factory) -> tuple[str, ImportReport | Exception]` helper function in `kb/holmes/cli.py`: creates its own `ThreePhaseImportPipeline` with `skip_git_commit=True`; returns `(prefix, report)` on success or `(prefix, exc)` on error
- [ ] T034 [US5] After all futures complete in the `--dir` branch of `kb/holmes/cli.py`: call `_make_runner()._git_commit(f"holmes import --dir: {len(importable)} file(s)")` exactly once, only if `total_entries > 0`; update the Done summary line
- [ ] T035 [US5] Update `_make_runner()` or pipeline constructor call in `kb/holmes/cli.py` single-file path to also pass `skip_git_commit=False` (explicit default, no behavior change)
- [ ] T036 [US5] Write `kb/tests/kb/test_cli_dir_batch.py`: mock `ThreePhaseImportPipeline.run()` with sleep + return report; run CLI `--dir` with 5 files; assert `_git_commit` called exactly once; assert all 5 files' `run()` were called; assert a single failed file does not abort others; assert `--dir-concurrency 1` behaves identically to serial
- [ ] T037 [US5] Run `python -m pytest tests/kb/test_cli_dir_batch.py tests/kb/test_cli.py -v` — all pass

**Checkpoint**: `--dir` is concurrent with single final commit. Serial fallback verified. Failures collected and reported.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Observability improvements, full regression run, and verification against spec success criteria.

- [ ] T038 [P] Add `"Provider: rate limit hit, retrying (attempt N/M, delay Xs)"` log line inside `_call_with_retry` when a retry sleep occurs in `kb/holmes/kb/agent/provider/base.py`
- [ ] T039 [P] Update `phase_traces` in `ThreePhaseImportPipeline.run()` to include `"Extractor: concurrency={extractor_concurrency}"` when `extractor_concurrency > 1` in `kb/holmes/kb/agent/pipeline.py`
- [ ] T040 Run full test suite: `cd kb && python -m pytest tests/ -q` — all pass, zero regressions
- [ ] T041 Manual smoke test: `holmes import <5-kp-doc>` — observe Extractor starts 4 workers nearly simultaneously in phase_traces output
- [ ] T042 Manual smoke test: `holmes import --dir ./tests/fixtures/` — observe concurrent processing, single git commit in `git log --oneline`
- [ ] T043 Verify success criteria SC-006 (no quality regressions): run `python -m pytest tests/kb/agent/ -v` — same entries produced for same input as before this feature

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — verify baseline
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user story phases
- **Phase 3 (US4 cache)**: Depends on Phase 2 — self-contained, no cross-story deps
- **Phase 4 (US3 retry)**: Depends on Phase 2 — self-contained, can run parallel with Phase 3
- **Phase 5 (US1 Phase 3 isolation)**: Depends on Phase 2 — adds `skip_git_commit` used by Phase 7
- **Phase 6 (US2 Extractor parallel)**: Depends on Phase 5 (needs `ExtractorResult` pattern established) — can begin immediately after Phase 5 checkpoint
- **Phase 7 (US5 --dir batch)**: Depends on Phase 5 (`skip_git_commit` param) — can run parallel with Phase 6
- **Phase 8 (Polish)**: Depends on all story phases complete

### User Story Dependencies

| Story | Depends On | Can Parallel With |
|-------|-----------|-------------------|
| US4 (cache) | Phase 2 | US3 |
| US3 (retry) | Phase 2 | US4 |
| US1 (Phase 3 isolation) | Phase 2 | US3, US4 |
| US2 (Extractor parallel) | US1 (ExtractorResult pattern) | US5 |
| US5 (--dir batch) | US1 (skip_git_commit) | US2 |

### Within Each Story

- Implementation tasks before test tasks (tests validate implementation)
- `_call_with_retry` helper before provider wrappers (T010 before T011-T014)
- `ExtractorResult` dataclass before `_extract_single_kp` before ThreadPool wiring (T024 → T025 → T026)
- `skip_git_commit` added in T020 before `--dir` uses it in T033/T034

---

## Parallel Execution Opportunities

```text
# After Phase 2 completes, these can run in parallel:

Session A: Phase 3 (US4 cache) → T004, T005, T006, T007, T008, T009
Session B: Phase 4 (US3 retry) → T010, T011, T012, T013, T014, T015, T016

# After Phase 5 (US1) completes:

Session A: Phase 6 (US2 Extractor parallel) → T024–T030
Session B: Phase 7 (US5 --dir batch)        → T031–T037

# Within Phase 4 (US3 retry), parallel tasks:
T010 [P] _call_with_retry helper (base.py)
T014 [P] OpenAIProvider retry wiring (openai_provider.py)
  → both can be written simultaneously, T011-T013 depend on T010
```

---

## Implementation Strategy

### MVP (Lowest-Risk, Highest-ROI First)

1. Phase 1: Verify baseline (T001)
2. Phase 2: Config extension (T002–T003)
3. Phase 3: list_entries cache (T004–T009) — zero quality risk, easy to verify
4. **STOP and VALIDATE**: full test suite passes, cache tests green
5. Phase 4: Retry logic (T010–T016) — zero quality risk
6. **STOP and VALIDATE**: provider tests pass

### Incremental Delivery

7. Phase 5: Phase 3 isolation (T017–T023) — P1 quality improvement
8. **VALIDATE**: `test_pipeline_phase3_isolation.py` + `test_pipeline.py` pass
9. Phase 6: Extractor parallel (T024–T030) — P1 speed improvement
10. Phase 7: --dir batch (T031–T037) — P2 batch improvement
11. Phase 8: Polish (T038–T043)

### Rollback Strategy

Each optimization is gated by a config field:
- `extractor_concurrency=1` → serial Extractor (same as today)
- `dir_concurrency=1` → serial --dir (same as today)
- `retry_max_attempts=1` → no retry (same as today)
- Cache can be disabled by passing `_bust_cache=True` to `list_entries` in tests

---

## Notes

- All 5 optimizations preserve output quality. Existing tests must not change results.
- `extractor_concurrency=1` is the canonical "no change" regression baseline.
- `[P]` tasks touch different files and have no data dependency on incomplete sibling tasks.
- Each phase ends with a test run checkpoint — do not advance until checkpoint passes.
- Commit after each phase, not after each individual task.
