# Feature Specification: Import Pipeline Performance Optimization

**Feature Branch**: `028-import-pipeline-perf`

**Created**: 2026-06-22

**Status**: Draft

**Input**: Import pipeline 性能优化：Phase 3 per-draft 隔离（消除上下文膨胀）、Extractor 并行化（独立 ctx）、Rate limit 指数退避重试+jitter（含 AnthropicProvider 错误处理补全）、list_entries 进程内缓存（消除每次 import 的全量磁盘扫描）、--dir 批量并发+合并 git commit

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Single Document Import Completes Faster (Priority: P1)

A developer imports a document containing multiple knowledge points. Today the pipeline is slow because Phase 3 builds a growing context window that includes all prior drafts and the full source text for every knowledge point it writes. After this change, each knowledge point in Phase 3 gets its own isolated context, so the LLM never has to process an ever-growing message history.

**Why this priority**: Phase 3 context bloat is the single largest source of latency in single-document imports and can cause errors when context exceeds model limits. It also improves output quality by preventing cross-KP interference.

**Independent Test**: Run `holmes import` on a document with 5+ knowledge points. Measure total time and peak token count per LLM call. Can be validated independently by observing that no single Phase 3 call contains content from more than one knowledge point draft.

**Acceptance Scenarios**:

1. **Given** a document with 5 knowledge points, **When** `holmes import <file>` is run, **Then** each Phase 3 writer LLM call contains only the source text relevant to its knowledge point and its own draft — never the drafts of sibling knowledge points.
2. **Given** a document whose full text is 10,000 characters, **When** the Phase 3 writer processes KP #3, **Then** the user-facing prompt size is bounded by a single-KP limit rather than growing linearly with the number of KPs processed so far.

---

### User Story 2 - Extractor Phase Runs in Parallel (Priority: P1)

The Extractor phase processes each knowledge point serially today. With independent context per KP (already guaranteed by the existing design), Extractor calls can be parallelized. A document with 4 knowledge points should see the Extractor phase take roughly the time of the slowest single KP, not 4× that time.

**Why this priority**: Extractor is the most time-consuming phase for multi-KP documents. Parallelizing it provides a near-linear speedup proportional to the number of KPs, with zero quality impact since each KP already has its own isolated context.

**Independent Test**: Import a document with 4+ knowledge points. Compare Extractor phase wall-clock time before and after. Validates independently via log timestamps showing all KP Extractors started within a short window rather than sequentially.

**Acceptance Scenarios**:

1. **Given** a document with 4 knowledge points, **When** `holmes import <file>` is run, **Then** all 4 Extractor agents start within 2 seconds of each other (concurrent), not one after the other.
2. **Given** parallel Extractors running, **When** they write their results, **Then** the results are identical in content and ordering to a serial run on the same document.

---

### User Story 3 - API Rate Limit Errors Are Retried Automatically (Priority: P2)

When the LLM provider (OpenAI or Anthropic) returns a rate-limit or transient error, the pipeline currently crashes. After this change, any rate-limit or transient server error triggers an automatic retry with exponential backoff and jitter, up to a configurable maximum number of attempts.

**Why this priority**: Rate limit errors are common during batch imports and currently require manual restarts. Auto-retry eliminates this friction without affecting output quality.

**Independent Test**: Simulate a rate-limit response from the provider. Observe that the pipeline waits and retries rather than crashing. Validates independently via log output showing retry attempts and backoff durations.

**Acceptance Scenarios**:

1. **Given** the provider returns a rate-limit error on the first attempt, **When** the pipeline calls the LLM, **Then** it retries automatically after a short delay with jitter, up to 5 attempts total.
2. **Given** 5 consecutive rate-limit errors, **When** the maximum retry count is exhausted, **Then** the pipeline raises a clear error explaining the rate limit was not resolved, rather than silently failing or hanging.
3. **Given** an Anthropic provider call, **When** an authentication error occurs, **Then** the pipeline raises a human-readable error immediately (no retry), consistent with how OpenAI provider currently behaves.

---

### User Story 4 - KB Entry Listing Is Cached Within a Run (Priority: P2)

The `list_entries` function scans all KB files from disk on every call. During a single `holmes import` run it is called over a dozen times. After this change, the result is cached in-process for the duration of the run, so repeated calls within the same invocation read from memory rather than disk.

**Why this priority**: Each `list_entries` call is O(number of KB files) with a `frontmatter.load()` per file. As the KB grows, this compounds. Caching eliminates redundant I/O without affecting correctness (KB entries do not change mid-import).

**Independent Test**: Instrument `list_entries` to count filesystem calls. Run `holmes import` on any document. Validate that the number of `rglob` calls equals 1 (or a small constant) regardless of how many KB operations occur during the run.

**Acceptance Scenarios**:

1. **Given** a KB with 50 entries, **When** `holmes import <file>` is run, **Then** the KB entry list is loaded from disk at most once per import invocation, with subsequent in-process calls served from cache.
2. **Given** the cache is populated, **When** a new entry is written during the import, **Then** the cache is invalidated or updated so that subsequent reads within the same run see the new entry.

---

### User Story 5 - Batch Directory Import Runs Concurrently with One Git Commit (Priority: P2)

When using `holmes import --dir <path>`, each file is currently processed serially with a separate git commit per file. After this change, files are imported concurrently (bounded parallelism), and all results are combined into a single git commit at the end.

**Why this priority**: Batch imports are the primary use case for large KB build-outs. Serial processing means N files take N× the time of one file. Concurrent processing and a single combined commit make batch imports practical for real-world knowledge bases.

**Independent Test**: Run `holmes import --dir <path>` on a directory with 5 markdown files. Observe that all 5 start processing within a short window and that git log shows exactly one new commit after the run.

**Acceptance Scenarios**:

1. **Given** a directory with 5 markdown files, **When** `holmes import --dir <path>` is run, **Then** files are processed concurrently with a configurable concurrency limit (default: 4).
2. **Given** all files have been processed, **When** the `--dir` import completes, **Then** git log shows exactly one new commit containing all newly written KB entries (not one commit per file).
3. **Given** one file fails during import (e.g., parse error), **When** the batch completes, **Then** the successfully processed files are still committed and the failure is reported without aborting the entire batch.

---

### Edge Cases

- What happens when all parallel Extractor agents hit rate limits simultaneously? (They each retry independently with jitter to avoid thundering herd.)
- What happens when a --dir batch contains a file that has already been imported? (Deduplication logic still applies; the file is skipped and not included in the git commit.)
- What happens if the KB cache becomes stale because a concurrent process writes to the KB mid-run? (Cache is scoped to a single process invocation; concurrent external writes are not expected and out of scope.)
- What happens when Extractor parallelism is set to 1 (disabled)? (Behavior is identical to current serial execution.)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Phase 3 writer MUST process each knowledge point with an isolated LLM context containing only that KP's draft and its relevant source section, not the full accumulated message history from other KPs.
- **FR-002**: The Extractor phase MUST support concurrent processing of multiple knowledge points using a thread or async pool, with a configurable maximum concurrency (default: 4).
- **FR-003**: Each Extractor worker MUST receive its own independent copy of the document context so that concurrent reads do not interfere or corrupt shared state.
- **FR-004**: The LLM provider layer (both OpenAI and Anthropic) MUST automatically retry on rate-limit and transient server errors using exponential backoff with jitter.
- **FR-005**: The retry mechanism MUST be configurable: maximum attempts (default: 5), base delay (default: 1s), maximum delay (default: 60s).
- **FR-006**: The AnthropicProvider MUST handle authentication errors, rate-limit errors, and server errors with the same error-type coverage as OpenAIProvider currently provides.
- **FR-007**: The `list_entries` function MUST support an in-process cache that is populated on first call and reused for subsequent calls within the same invocation.
- **FR-008**: The cache MUST be invalidatable (cleared or updated) when a new entry is written to the KB during the same process invocation.
- **FR-009**: The `--dir` batch import MUST process multiple files concurrently with a configurable concurrency limit (default: 4 files in parallel).
- **FR-010**: The `--dir` batch import MUST produce a single git commit containing all entries created across all files in the batch, rather than one commit per file.
- **FR-011**: The `--dir` batch import MUST continue processing remaining files when one file fails, collecting errors and reporting them at the end.
- **FR-012**: All optimizations MUST preserve output quality: the content of generated KB entries MUST be identical (or equivalent) to what the current serial pipeline produces.

### Key Entities

- **LLMProvider**: Abstraction over Anthropic and OpenAI APIs; gains retry/backoff logic and error normalization.
- **ExtractorAgent**: Processes one knowledge point in isolation; gains the ability to run in a thread pool with its own DocumentCursor copy.
- **ThreePhaseImportPipeline**: Orchestrates all phases; Phase 3 gains per-KP context isolation; `--dir` batch gains concurrent scheduling and deferred git commit.
- **EntryListCache**: In-process cache for `list_entries` results; scoped to a single process invocation; invalidated on write.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Single-document import of a 5-KP document completes at least 30% faster than baseline (measured wall-clock, same document, same model).
- **SC-002**: Extractor phase wall-clock time for a 4-KP document is no more than 1.5× the time for the slowest single-KP extraction (versus 4× for serial).
- **SC-003**: A batch `--dir` import of 5 files completes in no more than 2× the time of the slowest single-file import (versus 5× for serial).
- **SC-004**: After a `--dir` batch import, `git log --oneline` shows exactly one new commit regardless of how many files were processed.
- **SC-005**: When the LLM provider returns a rate-limit error, the pipeline automatically recovers and completes the import without manual intervention in at least 4 out of 5 retries.
- **SC-006**: The content of KB entries produced by the optimized pipeline is equivalent to those produced by the current pipeline on the same input document (no regressions in existing test suite).
- **SC-007**: `list_entries` disk I/O calls during a single `holmes import` run are reduced by at least 80% compared to baseline.

## Assumptions

- The LLM provider API keys and endpoints are already configured; this feature does not change authentication setup.
- Knowledge point IDs are stable and unique within a document; concurrent Extractors writing to `kp_drafts` by KP ID are safe without a lock (dict assignment in CPython is GIL-protected).
- The KB data directory is not modified by external processes concurrently with an import run; the in-process cache is safe for single-process use.
- `DocumentCursor._record()` is safe to call from concurrent threads when each thread has its own cursor instance; shared state from the original cursor is copied (not shared) before dispatch.
- Exponential backoff with jitter is sufficient to resolve rate-limit errors for both OpenAI and Anthropic providers; no provider-specific retry-after header parsing is required for v1.
- The `--dir` batch concurrency limit defaults to 4 to balance speed against provider rate limits; this is tunable via a CLI flag or config.
- Mobile/offline scenarios are out of scope; internet connectivity to the LLM provider is assumed.
- Phase 2.5 (semantic dedup) and Phase 1 (Reader) are not parallelized in this feature; only Extractor (Phase 2) and Phase 3 per-KP isolation are addressed.
