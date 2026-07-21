# Research: KB Access Control & Governance

**Feature**: 003-kb-governance
**Date**: 2026-06-01

---

## Decision 1: Write Protection Implementation Strategy

**Decision**: All Agent writes go through `write-pending → confirm`. No `write-entry` command is provided. `write-pending` enforces title duplicate check. `governance.py` provides `is_write_protected()` for internal use by `confirm` and any future tooling.

**Rationale**: Removing `write-entry` eliminates the bypass path where Agents could write directly to draft entries in the public KB, skipping the human review checkpoint. Per spec FR-003: "不提供直接写入公共区 draft 条目的 CLI 命令". The soft constraint on `verified`/`proven` entries is enforced by the absence of a write command, not by chmod.

**Alternatives considered**:
- `write-entry` with maturity guard: Still allows writing to `draft` entries, bypassing review
- chmod-based read-only files: Hard to manage, breaks maintainer direct access workflow
- Pre-commit git hooks: Too late in the flow, doesn't give Agent immediate feedback

---

## Decision 2: VersionSnapshot Storage

**Decision**: Store version snapshots as `<original_id>-<timestamp>.md` files in `$KB_ROOT/.history/` directory. Each snapshot is the complete original Markdown with frontmatter plus `replaced_at` and `replaced_by` fields. Snapshots are also saved when decay demotes an entry (with `reason: decay`).

**Rationale**:
- Spec explicitly states "存储在知识库内部 `.history/` 目录，不依赖 Git 历史"
- Flat files are easiest to read/display via `holmes kb history <id>`
- Sorting by timestamp suffix gives natural ordering
- Saving on decay (FR-013) enables maintainer review of what the entry looked like before demotion

**Alternatives considered**:
- JSON snapshot format: Loses Markdown readability
- Git history: Spec explicitly excludes this approach
- Only save on correction (not decay): Would miss traceable history for decay events

---

## Decision 3: Evidence Array vs Single `last_referenced_at`

**Decision**: Store each `EvidenceRecord` as a separate per-session JSON sidecar file at `contributions/evidence/<entry_id>/<session_id>.json`, rather than as a YAML list in the entry frontmatter. Maturity is derived from evidence count and contributor diversity. `update-refs` appends evidence at session end.

**Rationale**:
- **Per-session sidecar files are truly git-merge-friendly**: each `update-refs` call creates a *new* file (`<session_id>.json`). Two branches with different sessions add different files → no merge conflict (SC-006 satisfied).
- An in-frontmatter YAML list is NOT merge-friendly: two branches each transforming `evidence: []` → `evidence: [{record}]` always produce a git conflict because both branches modify the same lines from the same base.
- `append_evidence()` intentionally does NOT update `contributors` or `updated_at` in frontmatter (only maturity if promoted), so the entry `.md` file is never dirtied by concurrent evidence appends.
- `load_evidence(kb_root, entry_id)` aggregates sidecar files + any legacy frontmatter evidence (for backward compatibility with seeded entries).
- Decay reference date is `max(evidence[*].date)` across all sidecar + frontmatter records, giving accurate staleness signals.

**Alternatives considered**:
- In-frontmatter YAML list: Tested and confirmed to produce git conflicts for concurrent empty→append transitions.
- Single `last_referenced_at` + per-read `touch`: High git conflict rate in multi-user KB.
- Single field + batch update: Loses per-session contributor identity for maturity promotion.

---

## Decision 4: Evidence-Driven Maturity Promotion Rules

**Decision**: Maturity is auto-derived from evidence array content:
- 0 evidence records → `draft`
- ≥1 evidence record → `verified` (first confirm adds first record)
- ≥2 different `session_id` values AND ≥2 unique `contributor` values → `proven`

Human `confirm` appends the first evidence record (contributor = maintainer performing confirm).

**Rationale**: Maturity should reflect objective verification breadth, not a human-assigned label. This follows the Zhihu knowledge management design: maturity is earned through cross-session, multi-contributor validation. The thresholds (≥2 sessions, ≥2 contributors) balance rigor against practical reachability.

**Alternatives considered**:
- Human manually sets maturity on confirm: Maturity becomes a subjective label rather than an evidence-based metric
- Single contributor but multiple sessions enough for `proven`: Reduces trust — could be one person validating repeatedly

---

## Decision 5: Maturity Conflict Handling (Concurrent Writes)

**Decision**: When git merge results in conflicting maturity values (one side upgrades, other downgrades), keep the lower maturity value and set `contradiction: true` in the entry frontmatter. Log the event to `contributions/log.md`.

**Rationale**: Safety-first principle: in a conflict, erring toward lower (more conservative) maturity prevents premature promotion of possibly-stale knowledge. The `contradiction` flag alerts the maintainer to review without blocking normal workflows. This follows the Zhihu design's conflict resolution strategy for append-only evidence arrays.

**Alternatives considered**:
- Keep higher maturity: Risk of falsely elevating stale entries
- Require manual resolution on every merge: Too disruptive for normal collaboration
- Last-write-wins: Non-deterministic; depends on git merge order

---

## Decision 6: Correction Workflow (`corrects:` field)

**Decision**: `write-pending` accepts optional `--corrects <entry-id>` flag; this writes `corrects: <entry-id>` into the pending frontmatter. `kb confirm` detects `corrects:` field; if present, saves the original entry as a VersionSnapshot then overwrites the original file with the proposal content (preserving original `evidence` array and `contributors`). The pending entry is then deleted as normal.

**Rationale**: Reuses the existing `confirm` flow with minimal extension. No new approval system needed. Preserving the original evidence array ensures that the correction inherits the entry's established validation history.

**Alternatives considered**:
- Separate `kb correct` command: More CLI surface area for the same outcome
- Reset evidence on correction: Would incorrectly downgrade a well-validated entry after a minor fix

---

## Decision 7: New Module Organization

**Decision**: Introduce three new modules in `kb/holmes/kb/`:
- `governance.py` — title duplicate guard + write-protection check
- `history.py` — VersionSnapshot read/write (`.history/` directory management)
- `decay.py` — decay scan logic (reads all entries, applies decay rules, saves snapshots, archives orphans)

Extend `store.py` with: `append_evidence()`, `derive_maturity()`, `add_contributor()`, `get_last_evidence_date()`, `resolve_maturity_conflict()`.

**Rationale**: Single Responsibility Principle from constitution. Each module has a clearly bounded concern. `cli.py` remains thin; business logic lives in these modules.

**Alternatives considered**:
- All in `store.py`: Violates SRP; `store.py` already handles CRUD only
- All in `cli.py`: Untestable business logic mixed with CLI presentation

---

## Existing Code Reuse

| Component | Reused | How |
|-----------|--------|-----|
| `pending.write_pending()` | Modified | Add `corrects` param + title duplicate check |
| `store.write_entry()` | Reused | Used by confirm correction path |
| `store.list_entries()` | Reused | Used by governance guard and decay scan |
| `store.update_references()` | Deprecated path | Replaced by `append_evidence()` for evidence array |
| `validator.validate_schema()` | Reused | Unchanged |
| `pending.append_log()` | Reused | Decay changes and conflict events also logged |
| `cli.kb_confirm()` | Modified | Detect `corrects:` field, call history.save_snapshot |
| `cli.kb_update_refs()` | Modified | Append EvidenceRecord per entry, derive_maturity |
