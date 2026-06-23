# Quickstart: Import Pipeline Performance Optimization

**Feature**: 028-import-pipeline-perf

---

## What Changed

- **Faster single imports**: Phase 3 now runs once per draft (not once for all drafts together). Each KP gets a fresh LLM context bounded to its own section of the source document.
- **Parallel extraction**: The Extractor phase processes all knowledge points concurrently (default: 4 workers). A 4-KP document takes ~1× instead of ~4× the per-KP time.
- **Auto-retry on rate limits**: Both OpenAI and Anthropic providers retry automatically with exponential backoff on rate-limit and server errors. No more manual restarts.
- **Faster KB lookups**: `list_entries` results are cached in-process. Repeated calls during one import hit memory instead of disk.
- **Faster batch imports**: `holmes import --dir` now processes files concurrently and creates a single git commit at the end.

---

## Configuration

All new settings go in `~/.holmes/config.json` (optional — defaults apply if absent):

```json
{
  "extractor_concurrency": 4,
  "dir_concurrency": 4,
  "retry_max_attempts": 5,
  "retry_base_delay": 1.0,
  "retry_max_delay": 60.0
}
```

Or via CLI:
```bash
holmes config set extractor_concurrency 8   # more aggressive parallelism
holmes config set retry_max_attempts 3      # fewer retries
holmes config set dir_concurrency 2         # conservative for low-quota keys
```

To disable parallelism (serial mode, same as before this feature):
```bash
holmes config set extractor_concurrency 1
holmes config set dir_concurrency 1
```

---

## Batch Import Example

```bash
# Import all .md files in a directory concurrently (4 in parallel by default)
holmes import --dir ./docs/runbooks/

# Override concurrency for this run (planned for future; today use config)
holmes import --dir ./docs/runbooks/
```

Output:
```
Importing 5 file(s) from docs/runbooks/
[1/5] oom-killer.md → ✓ 2 entries
[3/5] disk-full.md → ✓ 1 entry
[2/5] cpu-spike.md → ✓ 3 entries
[4/5] network-timeout.md → warn: Already in KB — skipping
[5/5] k8s-crashloop.md → ✓ 2 entries
Done: 8 pending entries. Review: holmes kb pending
```

Note: output lines may appear out of order (concurrent processing). The `Done:` summary always appears last.

---

## Observability

Phase traces in the import report now include concurrency information:

```
Extractor: 4/4 knowledge points extracted (parallel, 4 workers)
Verifier+Writer: 4 created, 0 updated
```

If a retry occurred:
```
Provider: rate limit hit, retrying (attempt 2/5, delay 2.3s)
```

---

## Running Tests

```bash
# Full test suite (includes new perf optimization tests)
cd kb && python -m pytest tests/ -v

# Only new tests for this feature
python -m pytest tests/kb/agent/test_pipeline_phase3_isolation.py \
                 tests/kb/agent/test_extractor_parallel.py \
                 tests/kb/agent/provider/test_retry.py \
                 tests/kb/test_store_cache.py \
                 tests/kb/test_cli_dir_batch.py -v
```
