# Data Model: Import Pipeline Performance Optimization

**Feature**: 028-import-pipeline-perf
**Date**: 2026-06-22

---

## Entities

### 1. HolmesConfig (extended)

New optional fields added to the existing `HolmesConfig` dataclass / config loading:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `extractor_concurrency` | `int` | `4` | Max parallel Extractor workers per single-document import |
| `dir_concurrency` | `int` | `4` | Max parallel file workers for `--dir` batch import |
| `retry_max_attempts` | `int` | `5` | LLM call retries on rate-limit / 5xx errors |
| `retry_base_delay` | `float` | `1.0` | Seconds — base delay for exponential backoff |
| `retry_max_delay` | `float` | `60.0` | Seconds — maximum backoff cap |

All fields are optional in `~/.holmes/config.json`; defaults are applied at load time.

---

### 2. ThreePhaseImportPipeline (extended)

New constructor parameter:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip_git_commit` | `bool` | `False` | When `True`, suppresses the `_git_commit` call at the end of `_run_extraction_loop`. Used by `--dir` batch mode to allow the CLI to issue one final commit after all files are processed. |

No schema change — this is a runtime flag.

---

### 3. EntryListCache (new module-level state in store.py)

```
_CACHE: dict[CacheKey, list[EntryMeta]]
  CacheKey = tuple[str, bool]   # (str(kb_root), include_pending)
```

| Method | Behaviour |
|--------|-----------|
| `list_entries(...)` | On cache hit: apply filters in memory and return. On miss: scan disk, populate cache, apply filters. |
| `invalidate_cache()` | Clears all cached entries. Called by `write_entry` and `write_pending`. |

**Invariants**:
- Cache is process-local. No TTL.
- Filters (`kb_type`, `category`, `query`, `limit`, `offset`) are applied after cache retrieval, not stored in the cache key. This means the cache stores the full unfiltered list per `(kb_root, include_pending)` pair.
- The cache is invalidated (not partially updated) on any write. Next call re-scans from disk.

---

### 4. ProviderRetryConfig (implicit — no new class)

Retry parameters flow from `HolmesConfig` into provider constructors as keyword arguments. No new dataclass is introduced (constitution principle: no premature abstraction).

```
HolmesConfig.retry_* fields
    → create_provider(cfg) passes them to AnthropicProvider / OpenAIProvider constructors
    → provider stores them as instance attrs
    → _call_with_retry uses them at call time
```

---

### 5. ExtractorResult (new internal datatype)

Used to shuttle per-worker results from parallel Extractor threads back to the main thread:

```python
@dataclass
class ExtractorResult:
    kp_id: str
    draft: str | None          # None if extraction failed
    repaired: str | None       # After _validate_and_repair_draft
    errors: list[str]          # Errors encountered for this KP
    warnings: list[str]        # Warnings encountered for this KP
    phase_traces: list[str]    # Phase trace messages for this KP
```

This dataclass lives in `pipeline.py` (internal, not exported). Main thread merges all `ExtractorResult` objects into `report` and `kp_drafts` after all futures complete.

---

## State Transitions

### Extractor Phase (Parallel)

```
knowledge_map.knowledge_points
  │
  ├─ [Thread 1] kp1 → ExtractorAgent.run() → ExtractorResult(kp1)
  ├─ [Thread 2] kp2 → ExtractorAgent.run() → ExtractorResult(kp2)
  ├─ [Thread 3] kp3 → ExtractorAgent.run() → ExtractorResult(kp3)
  └─ [Thread 4] kp4 → ExtractorAgent.run() → ExtractorResult(kp4)
            ↓ (all complete)
  Main thread: merge ExtractorResult[] → kp_drafts + report
```

### Phase 3 (Per-KP Loop)

```
kp_drafts: {kp1: draft1, kp2: draft2, ...}
  │
  ├─ [Sequential] kp1: messages=[] → LLM loop → verify + write → done
  ├─ [Sequential] kp2: messages=[] → LLM loop → verify + write → done
  └─ ...
        ↓ (all complete)
  _git_commit (unless skip_git_commit=True)
```

Phase 3 remains sequential per-KP (not parallelized) to avoid concurrent `write_pending` calls on the same entry type/category creating ordering issues in the pending log. Phase 3 context isolation is the primary win here; parallelism is a Phase 2 (Extractor) concern.

### --dir Batch

```
importable: [file1, file2, file3, file4, file5]
  │
  ├─ [Thread 1] file1 → pipeline(skip_git_commit=True).run() → report1
  ├─ [Thread 2] file2 → pipeline(skip_git_commit=True).run() → report2
  ├─ [Thread 3] file3 → pipeline(skip_git_commit=True).run() → report3
  ├─ [Thread 4] file4 → pipeline(skip_git_commit=True).run() → report4
  └─ [Thread 1] file5 → pipeline(skip_git_commit=True).run() → report5
            ↓ (all complete — errors collected, not fatal)
  CLI: aggregate reports → print summary → single _git_commit
```

---

## Validation Rules

| Rule | Description |
|------|-------------|
| `extractor_concurrency >= 1` | Must be positive; 1 = serial (same as today) |
| `dir_concurrency >= 1` | Must be positive; 1 = serial (same as today) |
| `retry_max_attempts >= 1` | 1 means no retry; must be at least 1 |
| `retry_base_delay > 0` | Must be positive float |
| `retry_max_delay >= retry_base_delay` | Max delay must be ≥ base delay |
| Cache invalidation on write | `write_entry` and `write_pending` MUST call `invalidate_cache()` before returning |
