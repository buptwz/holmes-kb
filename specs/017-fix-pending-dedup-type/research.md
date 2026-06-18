# Research: Import Pipeline — Pending Dedup & Type Override

**Branch**: `017-fix-pending-dedup-type` | **Date**: 2026-06-09

---

## D-5: Pending Layer Deduplication

### Decision: Extend `_find_entry_by_hash()` to scan pending directory

**Rationale**: The function currently calls `list_entries(kb_root)` which only returns approved KB entries. The pending directory (`contributions/pending/`) stores `.md` files with YAML frontmatter that already contains `source_hash`. Scanning it with the existing `list_pending()` function (from `holmes.kb.pending`) or a direct glob is sufficient — no new abstractions needed.

**Exact change site**: `holmes/kb/agent/tools.py`, function `_find_entry_by_hash()` (line 61–73). Add a second loop after the approved-entries loop that iterates over `(kb_root / PENDING_DIR).glob("*.md")`, loads each file's frontmatter, and compares `source_hash`. Return `(pending_id, file_path)` if matched.

**Alternatives considered**:
- Call `list_pending()` instead of direct glob: `list_pending()` returns dicts without frontmatter data, so a direct glob + `fm.load()` is more direct.
- Add a separate `check_pending_hash` tool: unnecessary complexity; `_find_entry_by_hash` is the single source of truth.
- Store hashes in a separate index file: premature optimization; pending directory is small (<1000 files in practice).

**Edge cases**:
- Malformed pending file (unreadable frontmatter): silently skip; do not crash.
- Empty `source_hash` in pending frontmatter: empty string won't match a valid 16-char hash; safe.
- `PENDING_DIR` constant is already imported from `holmes.kb.pending` via `write_pending` in the same file — use the same import path.

---

## E-2: `--type` CLI Flag Force Override

### Decision: Thread `force_type` through runner → pipeline → extractor drafts + system prompt

**Rationale**: The override must be applied at two points:
1. **System prompt injection** (guidance): Tell the LLM which type to assign, reducing incorrect drafts.
2. **Post-extraction draft override** (enforcement): After each KP draft is produced by the Extractor, overwrite the `type:` frontmatter field to `force_type`. This is the authoritative enforcement point — it cannot be overridden by LLM hallucination.

Both points together give "prompt guidance + deterministic enforcement".

**Exact change sites**:

### Site 1 — `holmes/cli.py`
In `import_cmd()`, add `force_type=kb_type` to the `ImportAgentRunner(...)` constructor call.

### Site 2 — `holmes/kb/agent/runner.py`
In `ImportAgentRunner.__init__()`: add `force_type: Optional[str] = None`, store as `self.force_type`.
In `ImportAgentRunner.run()`: pass `force_type=self.force_type` to `ThreePhaseImportPipeline(...)`.

### Site 3 — `holmes/kb/agent/pipeline.py`
In `ThreePhaseImportPipeline.__init__()`: add `force_type: Optional[str] = None`, store as `self.force_type`.

In `ThreePhaseImportPipeline.run()`:
- After calling `extractor.run(kp, knowledge_map, ctx)` but before `_validate_and_repair_draft()`, if `self.force_type` is set, parse the draft frontmatter and overwrite `type:` then re-serialize with `fm.dumps()`.
- Also store `force_type` in `ctx["force_type"]` so phases can read it.

In `ThreePhaseImportPipeline._run_extraction_loop()` (the Verifier phase prompt):
- When building the pre-extracted drafts user message, if `force_type` is set, prepend: `"FORCE TYPE: All entries MUST have type={force_type}. Override any LLM-assigned type with this value."`

### Reader integration (optional, low priority):
- Pass `force_type` as `type_hint` override to `KnowledgePoint` via `ctx["force_type"]` — the Reader system prompt already instructs the LLM to record `type_hint`; the Extractor uses `kp.type_hint` when drafting. Overriding this propagates the hint earlier.
- This is optional because the deterministic post-extraction override (Site 3) already ensures correctness.

**Alternatives considered**:
- Modify `_IMPORT_SYSTEM_PROMPT` directly at module level: not feasible, it's a static string; would need to be a function or formatted on each `run()` call.
- Override at `write_kb_entry` tool level: too late — the draft has already been sent to the verifier. Post-extraction override is the right interception point.
- `_gate_classification()` in runner: that gate no longer exists in the three-phase pipeline; the pipeline owns classification now.

**Validation approach for `force_type` value**:
Valid values: `pitfall`, `model`, `guideline`, `process`, `decision`. Validate in `cli.py` before constructing the runner; emit a clear error on invalid value.

**Dry-run behavior**: When `force_type` is set and `dry_run=True`, the plan output must show `Would create: <title> (type: <force_type>)` to confirm the override is in effect.
