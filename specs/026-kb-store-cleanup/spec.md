# Feature Specification: KB Store Internal Cleanup

**Feature Branch**: `026-kb-store-cleanup`

**Created**: 2026-06-11

**Status**: Draft

**Input**: User description: "KB Store 内部清理：移除死代码 update_references() 及其孤立字段，修复搜索 evidence 加载性能。三个问题：(1) update_references() 从未被任何调用方使用（agent 通过 append_evidence() 写回证据，CLI 无对应命令），与 append_evidence() 形成两套并行 maturity 逻辑，应删除；(2) EntryMeta.last_referenced 和 reference_count 字段由 update_references() 维护，随其删除一起清理（decay._get_reference_date() 已有正确 fallback，不受影响）；(3) LinearScanBackend.search() 对每条匹配结果单独调用 load_evidence() 读取 sidecar 文件，O(n×m) I/O，改为在 search() 开始时一次性扫描所有 evidence sidecar 目录建立 {entry_id: last_date} 内存索引，再在结果循环中查表，降为 O(m) 一次性读取。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Remove Dead Code update_references() (Priority: P1)

A developer maintaining the KB codebase encounters `update_references()` in `store.py`. It duplicates the maturity-update logic already handled by `append_evidence()`, yet is never called by any code path. Its presence creates confusion about which function owns the maturity lifecycle. Removing it eliminates the ambiguity and makes `append_evidence()` the sole authoritative path.

**Why this priority**: Dead code with parallel logic is the highest-risk maintenance hazard. Any future developer might accidentally invoke or extend `update_references()`, causing maturity state divergence. Removing it is a zero-risk, high-clarity win.

**Independent Test**: Run the full KB test suite after deletion — all tests should still pass. Grep the codebase for `update_references` — zero occurrences should remain.

**Acceptance Scenarios**:

1. **Given** `update_references()` exists in `kb/holmes/kb/store.py`, **When** it is deleted along with its dead import of `datetime.timezone` (if only used there), **Then** `python -m pytest kb/` passes with no regressions.
2. **Given** no caller of `update_references()` exists anywhere in the codebase, **When** the function is removed, **Then** `grep -r "update_references" .` returns zero results outside of git history.

---

### User Story 2 - Remove Orphaned EntryMeta Fields (Priority: P2)

`EntryMeta.last_referenced` and `EntryMeta.reference_count` are fields that were maintained exclusively by `update_references()`. With that function removed, these fields become dead weight: they are populated from frontmatter but never written back (since `update_references()` is gone), and no active code path reads them for any functional purpose. The decay system already uses `_get_reference_date()` with a fallback chain that does not rely on these fields.

**Why this priority**: Follows directly from US1. Once `update_references()` is gone, its data fields are orphaned. Leaving them in the dataclass misleads readers into thinking they have a purpose.

**Independent Test**: Remove both fields from `EntryMeta`, update any field reads in `list_entries()` that populate them, run `python -m pytest kb/` — all tests pass. Confirm `decay.py` tests still pass (they should not reference these fields).

**Acceptance Scenarios**:

1. **Given** `EntryMeta` has `last_referenced` and `reference_count` fields, **When** they are removed from the dataclass and from the `list_entries()` frontmatter-reading block, **Then** no `AttributeError` is raised anywhere in the test suite.
2. **Given** `decay._get_reference_date()` uses evidence → last_referenced → updated_at fallback chain, **When** `last_referenced` is removed from `EntryMeta`, **Then** decay tests pass because `_get_reference_date()` reads from the entry object's frontmatter metadata directly, not from `EntryMeta`.

---

### User Story 3 - Fix Search Evidence Loading O(n×m) → O(m) (Priority: P3)

`LinearScanBackend.search()` currently calls `load_evidence(kb_root, entry_id)` inside the per-entry scan loop. For a KB with N entries and M sidecar directories, this is O(N×M) filesystem I/O on every search call. The fix is to scan all sidecar directories once at the start of `search()`, build an in-memory `{entry_id: last_date}` index, and replace per-entry `load_evidence()` calls with a simple dict lookup.

**Why this priority**: Correctness improvement over performance — the current code is not wrong, just slow for large KBs. P3 because the KB is currently small enough that the issue is latent, but it should be fixed while we are already editing this file.

**Independent Test**: The existing `test_search_ranks_evidence_entry_higher` and `test_search_no_evidence_falls_back_to_score` tests must pass unchanged. A new test verifies that with 50 entries and 10 evidence sidecars, search completes in under 500ms (or alternatively, verify through code inspection that `load_evidence()` is no longer called in the scan loop).

**Acceptance Scenarios**:

1. **Given** a KB with multiple entries and evidence sidecar files, **When** `search()` is called, **Then** the sidecar directories are scanned exactly once (not once per matched entry) and results are ranked identically to before.
2. **Given** an entry with no sidecar directory, **When** the index lookup runs, **Then** it returns `None` for `last_evidence_date` (same behavior as before).
3. **Given** the two existing search ranking tests, **When** run against the refactored code, **Then** both pass without modification.

---

### Edge Cases

- What if the `contributions/evidence/` directory does not exist? The index-building function must handle absence gracefully and return an empty dict.
- What if an entry's `entry_id` contains path-unsafe characters? The sidecar directory name uses the same `entry_id` as the key — must match exactly.
- What if `EntryMeta` fields are referenced in test fixtures? All affected test assertions must be updated.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST remove `update_references()` from `kb/holmes/kb/store.py` entirely, including its body and docstring.
- **FR-002**: System MUST remove `last_referenced` and `reference_count` fields from the `EntryMeta` dataclass in `kb/holmes/kb/store.py`.
- **FR-003**: System MUST remove the corresponding frontmatter reads (`meta.get("last_referenced", "")` and `meta.get("reference_count", 0)`) from the `list_entries()` function body.
- **FR-004**: System MUST replace the per-entry `load_evidence()` + `get_last_evidence_date()` calls in `LinearScanBackend.search()` with a single upfront index built by scanning `contributions/evidence/*/` once before the entry scan loop.
- **FR-005**: System MUST ensure all existing KB tests pass after each change (no regressions).
- **FR-006**: System MUST NOT modify `decay.py` — it already uses a correct fallback chain independent of the removed fields.
- **FR-007**: System MUST NOT modify any test that does not reference the removed code (only update tests that directly assert on removed fields or functions).

### Key Entities

- **`update_references()`**: Dead function in `kb/holmes/kb/store.py` (lines 348–394). Zero callers. To be deleted.
- **`EntryMeta`**: Dataclass in `kb/holmes/kb/store.py`. Fields `last_referenced: str` and `reference_count: int` to be removed.
- **`LinearScanBackend`**: Class in `kb/holmes/kb/search.py`. `search()` method's evidence-loading loop to be replaced with upfront index scan.
- **`_build_evidence_date_index(kb_root)`**: New private helper in `search.py` — scans `contributions/evidence/*/` once, returns `dict[str, str]` mapping `entry_id → max_date`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `python -m pytest kb/ -q` passes with zero failures after all three changes.
- **SC-002**: `grep -r "update_references" kb/` returns zero results (function fully removed).
- **SC-003**: `grep -r "last_referenced\|reference_count" kb/holmes/` returns zero results (fields fully removed from production code; test files may reference them only in assertions that were updated).
- **SC-004**: `LinearScanBackend.search()` calls `load_evidence()` zero times during a search (verified by code inspection or mock assertion in test).
- **SC-005**: Net line count in `kb/holmes/kb/store.py` decreases by at least 50 lines (dead code removal is substantial).

## Assumptions

- `update_references()` has zero callers — confirmed by grep across the full codebase.
- `decay._get_reference_date()` reads evidence sidecar directly (not via `EntryMeta`) — confirmed by reading `decay.py`.
- `EntryMeta.last_referenced` and `reference_count` are never read by any active code path outside `update_references()` — confirmed by grep.
- The `contributions/evidence/` directory structure is `<entry_id>/<session_id>.json` — sidecar dirs are named by entry_id, enabling O(1) index lookup.
- No external consumers (CLI commands, agent tools) call `update_references()` — confirmed by grep across `kb/`, `agent/`, and `tui/` directories.
