# CLI Contract: Import Pipeline Performance Optimization

**Feature**: 028-import-pipeline-perf

---

## New / Changed CLI Flags

### `holmes import --dir <PATH>`

**Existing behavior**: Serial processing, one commit per file.

**New behavior**: Concurrent processing with a single final commit.

**New flags added**:

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--dir-concurrency N` | int | 4 | Max files processed in parallel when using `--dir` |

**Output contract** (unchanged format):

```
Importing N file(s) from <path>
[1/N] file1.md → ✓ 2 entries
[2/N] file2.md → ✓ 1 entry
[3/N] file3.md → ✗ Import failed: <error>
...
Done: M pending entries (K files failed). Review: holmes kb pending
```

The output lines may appear out of order (concurrent processing). The `Done:` summary line always appears last.

**Git commit** (changed):
- Before: one commit per file (`holmes import: <hash[:8]>`)
- After: one commit for all files (`holmes import --dir: N file(s)`)
- If zero files succeeded, no git commit is created.

---

## Config Fields (holmes config)

New fields readable via `holmes config set` and `~/.holmes/config.json`:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `extractor_concurrency` | int | 4 | Parallel Extractor workers within a single-document import |
| `dir_concurrency` | int | 4 | Parallel file workers for `--dir` batch import |
| `retry_max_attempts` | int | 5 | LLM retry limit on rate-limit/server errors |
| `retry_base_delay` | float | 1.0 | Retry base delay (seconds) |
| `retry_max_delay` | float | 60.0 | Retry max delay cap (seconds) |

These fields are optional. Omitting them uses the defaults shown above.

---

## LLMProvider Error Contract (extended)

Both `AnthropicProvider` and `OpenAIProvider` now raise the same normalized `RuntimeError` subtypes:

| Condition | Behavior |
|-----------|----------|
| Authentication failure | Immediate `RuntimeError` with "Check your key" hint |
| Rate limit (after N retries exhausted) | `RuntimeError` with "Rate limit not resolved after N retries" |
| Server error 5xx (after N retries exhausted) | `RuntimeError` with "LLM provider returned a server error" |
| Transient connection error (after N retries) | `RuntimeError` with underlying message |

**No change** to the `LLMProvider` abstract interface (`base.py`). Retry logic is an implementation detail of each concrete provider.

---

## Backward Compatibility

- All existing CLI commands (`holmes import <file>`, `holmes import --dir`) behave identically to today when `extractor_concurrency=1`, `dir_concurrency=1`, and `retry_max_attempts=1`.
- Default concurrency (4) changes `--dir` behavior: files are no longer processed strictly in alphabetical order. Output lines interleave. The final commit and entry content are identical to serial processing.
- `list_entries` function signature is unchanged. The `_bust_cache` internal kwarg is not part of the public API.
