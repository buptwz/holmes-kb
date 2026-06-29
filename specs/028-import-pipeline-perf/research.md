# Research: Import Pipeline Performance Optimization

**Feature**: 028-import-pipeline-perf
**Date**: 2026-06-22
**Phase**: 0 — Research

---

## R-001: Phase 3 Context Bloat Root Cause and Fix

**Investigation**: `pipeline.py:_run_extraction_loop` (lines 380–498) builds one `user_prompt`
that concatenates **all** kp_drafts separated by `--- Draft for {kp_id} ---` dividers, then runs
a **single** LLM tool-use loop that processes all KPs in one message thread. As the LLM calls
`verify_content` and `write_kb_entry` for each KP, tool results accumulate in `messages`, so by
KP #N the context contains the full source text + N-1 drafts + all their tool results.

**Decision**: Replace the single loop with a **per-KP outer loop** in `_run_extraction_loop`.
For each `kp_id, draft` in `kp_drafts`:
1. Build a fresh `messages = [{"role": "user", "content": per_kp_prompt}]`
2. Run the tool-use loop to completion (stop or max iterations)
3. Discard the messages after completion

**Per-KP prompt** contains:
- `source_hash` + `file` header
- `SOURCE TEXT:` only the KP's section slice (`source_text[kp.section_start:kp.section_end]`) when available; full source text as fallback (same quality guarantee as today)
- The single draft block

**Rationale**: Each KP is independently verifiable. No KP draft needs to see sibling drafts.
Scoped source slice avoids sending 10k chars when the KP lives in a 500-char section.

**Alternatives considered**:
- Batching: group 2-3 KPs per LLM call — partial improvement but context still grows; rejected.
- Streaming: would reduce latency perception but not token count — orthogonal concern, not in scope.

**Quality guarantee**: `verify_content` tool receives `ctx["source_text"]` (always the full untruncated text) as its fallback, so the verifier has full context even when the per-KP prompt uses a slice.

---

## R-002: Extractor Parallelism — Thread Safety Analysis

**Investigation**: `ExtractorAgent` is instantiated once per pipeline run and reused across KPs
(`extractor = ExtractorAgent(...)`). Its state:
- `self._provider` and `self._model`: read-only, safe to share across threads.
- `messages` list: local variable inside `extractor.run(kp, knowledge_map, ctx)`, rebuilt fresh per call. Safe.
- `ctx["doc_cursor"]` (DocumentCursor): shared across all KPs. `_record()` is a compound read-modify-write. **NOT thread-safe.**
- `ctx["report"]`: `report.errors`, `report.warnings`, `report.phase_traces` lists mutated during extraction. **NOT thread-safe.**
- `kp_drafts[kp.id]` dict assignment: CPython GIL-protected for simple key assignments. Safe if workers each write to distinct keys.

**Decision**: Use `concurrent.futures.ThreadPoolExecutor(max_workers=extractor_concurrency)`.
For each KP worker thread:
- Create a **per-worker shallow ctx copy** with its own fresh `DocumentCursor(source_text)` (same source_text string is immutable — shared read is safe).
- Collect per-worker `(errors, warnings, phase_traces)` as local lists.
- After all futures complete, merge results into the main `report` (serial merge, no lock needed).
- `kp_drafts` dict is populated from the main thread after futures complete (from `future.result()`).

**Concurrency limit default**: 4. Balances throughput against provider rate limits. Configurable via `HolmesConfig.extractor_concurrency` (int, default 4).

**Alternatives considered**:
- `asyncio`: would require async refactor of provider SDKs — too invasive for this feature.
- Process pool: pickling overhead and no shared memory benefits; rejected for this use case.

---

## R-003: Retry with Exponential Backoff + Jitter

**Investigation**: `AnthropicProvider.complete/simple_complete` has zero error handling. `OpenAIProvider` raises `RuntimeError` on `RateLimitError` — it surfaces the error but does not retry.

**Decision**: Add a `_call_with_retry` module-level helper in `provider/base.py`:

```python
def _call_with_retry(fn, max_attempts=5, base_delay=1.0, max_delay=60.0):
    for attempt in range(max_attempts):
        try:
            return fn()
        except <RateLimitError|ServiceUnavailable>:
            if attempt == max_attempts - 1:
                raise RuntimeError("Rate limit not resolved after N retries.")
            delay = min(base_delay * 2**attempt, max_delay) + random.uniform(0, 1)
            time.sleep(delay)
```

- Anthropic rate-limit: `anthropic.RateLimitError`
- Anthropic server error: `anthropic.APIStatusError` (status >= 500)
- OpenAI rate-limit: `openai.RateLimitError`
- OpenAI server error: `openai.APIStatusError` (status >= 500)
- Auth errors: do NOT retry, raise `RuntimeError` immediately.

Both `AnthropicProvider` and `OpenAIProvider` use the same helper. Retry logic lives in provider layer, transparent to pipeline.

**Configuration**: `HolmesConfig` gains optional `retry_max_attempts` (int, default 5), `retry_base_delay` (float, default 1.0), `retry_max_delay` (float, default 60.0). Passed down from config to provider constructor.

**Alternatives considered**:
- `tenacity` library: adds a dependency for a 20-line helper. Rejected — keep dependencies minimal.
- Per-SDK retry (e.g. Anthropic SDK's built-in retry): Anthropic SDK has `max_retries` param but it only covers connection errors, not rate-limit 429s in older versions. Custom retry in our code is more portable.

---

## R-004: list_entries In-Process Cache

**Investigation**: `list_entries` in `store.py` calls `d.rglob("*.md")` + `frontmatter.load()` per file every invocation. Called ~13 times per import (in `tools.py:_find_entry_by_hash`, `_find_all_entries_by_hash`, `read_kb_entries_by_category`, `update_kb_entry`, `append_evidence`, `add_contributor`, `skill/manager.py:_find_existing_skill`, `pending.py:write_pending`).

With 50 KB entries each taking ~5ms to parse, that's ~650ms in pure I/O per import — 13× avoidable.

**Decision**: Module-level cache in `store.py`:

```python
_CACHE: dict[tuple[str, bool], list[EntryMeta]] = {}

def invalidate_cache() -> None:
    _CACHE.clear()

def list_entries(..., _bust_cache: bool = False) -> list[EntryMeta]:
    cache_key = (str(kb_root), include_pending)
    if not _bust_cache and cache_key in _CACHE:
        return _apply_filters(_CACHE[cache_key], kb_type, category, query, limit, offset)
    entries = _scan_disk(kb_root, include_pending)
    _CACHE[cache_key] = entries
    return _apply_filters(entries, kb_type, category, query, limit, offset)
```

`write_entry` in `store.py` calls `invalidate_cache()` after writing. `atomic_write` in `atomic.py` does NOT call it (it's for arbitrary files). `write_pending` in `pending.py` calls `invalidate_cache()` after a successful write.

**Cache scope**: module-level (process-scoped). Safe because KB files are only modified by this process during an import run. External mutations are outside the designed concurrency contract.

**Filtering**: `kb_type`, `category`, `query`, `limit`, `offset` filters are applied in-memory after cache hit — no re-scan needed.

**Alternatives considered**:
- TTL cache: unnecessary complexity — import runs are short-lived, cache is valid for the full run.
- LRU cache on the function: `functools.lru_cache` doesn't support mutable arguments (Path, optional lists). Manual dict is cleaner.

---

## R-005: --dir Concurrent Batch + Single Git Commit

**Investigation**: `cli.py:380-358` runs a serial for-loop over files, calling `runner.run(source_text, file_path=f)` which internally calls `_git_commit` at the end of `_run_extraction_loop` (pipeline.py:496). N files → N git commits.

**Decision**:

1. **Suppress per-file git commit in batch mode**: Add `skip_git_commit: bool = False` parameter to `ThreePhaseImportPipeline.__init__` and `ImportAgentRunner.__init__`. When `True`, `_git_commit` in `_run_extraction_loop` is skipped.

2. **CLI concurrent dispatch**: Use `ThreadPoolExecutor(max_workers=dir_concurrency)` in the `--dir` branch of `cli.py`. Default `dir_concurrency = 4`. Each file gets its own pipeline instance (no shared state between file pipelines).

3. **Single final commit**: After all futures complete (with error collection), CLI calls `runner._git_commit(f"holmes import --dir: {len(importable)} file(s)")` once. If no files succeeded, skip the commit.

**Thread safety of --dir parallel**: Each file has a separate `ThreePhaseImportPipeline` instance → separate `LLMProvider` instance → separate HTTP connections. `write_pending` uses unique `pending_id` filenames (timestamp+4-char random). `append_log` uses POSIX `open("a")` — safe for small appends. `list_entries` cache is process-wide; concurrent writes from parallel pipelines call `invalidate_cache()` which clears the dict (GIL-protected for dict clear). Parallel reads between invalidations may re-scan disk but this is safe (just adds a small re-scan, not incorrect behavior).

**Configurable concurrency**: `--dir-concurrency N` CLI flag (default 4). Also readable from `HolmesConfig.dir_concurrency`.

**Alternatives considered**:
- `asyncio` for --dir: would require async refactor of pipeline. Too invasive; rejected.
- Single shared runner for all files: `runner.run()` is not re-entrant (it modifies `self._current_report`). Each file needs its own runner/pipeline instance.

---

## R-006: AnthropicProvider Error Coverage Completion

**Decision**: After adding retry wrapping (R-003), also add the same auth error fast-fail path:

```python
except anthropic.AuthenticationError:
    raise RuntimeError(
        "Authentication failed — API key rejected. "
        "Check your key with: holmes config set api_key <KEY>"
    ) from None
```

This matches the existing `OpenAIProvider` auth error handling and gives consistent UX regardless of which provider is configured.

---

## Summary of Decisions

| Area | Approach | Files Changed |
|------|----------|---------------|
| Phase 3 isolation | Per-KP loop with fresh messages | pipeline.py |
| Extractor parallelism | ThreadPoolExecutor, per-worker ctx copy | pipeline.py |
| Retry + backoff | `_call_with_retry` helper in base.py | provider/base.py, anthropic_provider.py, openai_provider.py |
| Anthropic error coverage | Match OpenAIProvider auth/rate/server errors | provider/anthropic_provider.py |
| list_entries cache | Module-level dict, invalidated on write | store.py, pending.py |
| --dir batch | ThreadPoolExecutor + deferred single commit | cli.py, pipeline.py |
| Config | extractor_concurrency, dir_concurrency, retry_* | config.py |
