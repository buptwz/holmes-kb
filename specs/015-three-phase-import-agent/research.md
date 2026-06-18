# Research: Three-Phase Import Agent

**Feature**: 015-three-phase-import-agent
**Date**: 2026-06-08

---

## R-001: Pipeline Isolation Strategy

**Decision**: Each phase runs as a completely independent LLM call sequence with its own `messages` list starting from empty. No shared mutable state between phases.

**Rationale**: Borrowing the "forked agent" pattern from Claude Code (`forkedAgent.ts`): each background task runs with isolated mutable state so it cannot corrupt the parent's context. In our case, Reader/Extractor/Verifier phases have different goals and different prompt contexts; sharing message history causes earlier extractions to bias later ones (the context pollution bug observed in T3/V3 tests).

**Alternatives considered**:
- Single loop with phase markers in the system prompt — rejected because earlier tool results contaminate LLM attention for later knowledge points.
- Shared message history with `<phase_boundary>` system messages — rejected because the LLM still attends to prior phases' content.

---

## R-002: Document Access Model

**Decision**: Store the full original `source_text` in the shared pipeline context dictionary. Provide three lightweight Python tools callable by the LLM agent:
- `read_document_range(start_char, end_char)` — returns a slice of the source.
- `get_read_coverage()` — returns how many chars have been read, total doc length, and percentage.
- `search_in_document(query)` — returns the character offset + surrounding context of the first match.

These tools do not call the LLM; they are deterministic string operations backed by the `source_text` stored in `ctx["source_text"]`.

**Rationale**: "Document as addressable resource" — the agent never receives the entire document in its initial prompt. Instead it receives a brief header (title, total length, section outline) and reads on demand. This eliminates truncation entirely: the document is always fully accessible, and `verify_content` always operates on the full text (W1-F1 root cause fixed at the model level).

**Alternatives considered**:
- Pre-chunking by `##` headings before the agent loop — better than naive truncation but requires guessing heading language/format before reading.
- Embedding the full document in every phase prompt — prohibitive token cost for 15K+ char docs; also defeats context isolation.

---

## R-003: KnowledgeMap Structure

**Decision**: The Reader phase produces a KnowledgeMap as a Python dataclass (JSON-serializable). Schema:

```json
{
  "knowledge_points": [
    {
      "id": "kp-1",
      "description": "Short one-sentence description of the knowledge point",
      "section_start": 0,
      "section_end": 2400,
      "type_hint": "pitfall",
      "category_hint": "database",
      "language": "zh",
      "extracted": false
    }
  ],
  "total_chars": 12000,
  "chars_read": 12000,
  "coverage_pct": 100,
  "diminishing_returns": false,
  "reading_passes": 2
}
```

**Rationale**: The KnowledgeMap is the "episodic memory" handoff between Reader and Extractor (analogous to Claude Code's memory file written after each session). It encodes what was found without encoding all the raw text, keeping Extractor prompts small. `section_start`/`section_end` allows each Extractor to request exactly the relevant portion via `read_document_range`.

**Alternatives considered**:
- Passing full source text + highlighted spans to each Extractor — too much token overhead per knowledge point.
- Natural language description only (no offsets) — Extractor would have to re-scan the document to find the relevant section, adding latency and risk of reading the wrong section.

---

## R-004: Diminishing Returns Detection

**Decision**: After each Reader reading pass, count new knowledge points discovered. If two consecutive passes yield 0 new knowledge points, set `diminishing_returns=True` and stop reading. Also stop if `coverage_pct >= 100`.

**Rationale**: Directly inspired by Claude Code's `tokenBudget.ts` diminishing returns check: `isDiminishing = continuationCount >= 3 && deltaSinceLastCheck < DIMINISHING_THRESHOLD`. For document reading, the equivalent is: if reading the next section produces no new knowledge, we have covered everything worth covering.

**Alternatives considered**:
- Fixed number of passes (e.g., always 3 passes) — wasteful for short documents, insufficient for densely packed ones.
- Reading until 100% coverage regardless — could be very expensive for documents with large "boilerplate" sections (appendices, license text).

---

## R-005: Extractor Execution Order

**Decision**: Extractor phases run serially (one per knowledge point, in order). Each Extractor has its own fresh `messages` list and receives: (a) the Reader system prompt, (b) the KnowledgeMap in JSON, (c) the specific knowledge point ID to extract.

**Rationale**: Serial execution is simpler, easier to debug, and avoids concurrent API calls which could trigger rate limits. The Extractor for KP-N receives only the KnowledgeMap + document access tools — it does not see KP-1 through KP-N-1 in its message history. This is the core isolation guarantee.

**Alternatives considered**:
- Parallel extraction (asyncio.gather) — higher throughput but concurrent writes to shared report state require locking; deferred to a future performance feature flag.
- A single Extractor pass with all KPs listed in the prompt — LLM tends to merge/confuse them; serial isolation is empirically better for quality.

---

## R-006: Backward Compatibility Strategy

**Decision**: `ImportAgentRunner.run(source_text, file_path)` → `ImportReport` signature is unchanged. Internally, `run()` delegates to a new `ThreePhaseImportPipeline`. All existing tests that mock `ImportAgentRunner.run` or that use the tool-call loop continue to pass because the public API is identical.

The `_finalize_skill_generation`, `_gate_*`, `_dispatch_tool` methods remain on `ImportAgentRunner` for now but are gradually migrated to phase classes. This is an incremental refactor, not a big-bang rewrite.

**Rationale**: Existing 455 tests pass. No external callers need to change. The CLI (`holmes import`) is unaffected.

**Alternatives considered**:
- Introduce `ThreePhaseImportRunner` as a new class alongside existing `ImportAgentRunner` — creates confusion about which to use; prefer single entry point.
- Swap out the implementation behind a feature flag — possible but unnecessary complexity given backward-compatible signatures.

---

## R-007: File Structure for New Modules

**Decision**: Add a `phases/` sub-package under `holmes/kb/agent/` containing the Reader and Extractor phase implementations. Add `knowledge_map.py` and `doc_access.py` as siblings. The existing `verifier.py` (ContentVerifier) and `tools.py` are enhanced in-place; no rename.

```
holmes/kb/agent/
├── runner.py           # Existing: thin delegate to pipeline
├── pipeline.py         # NEW: ThreePhaseImportPipeline orchestrator
├── knowledge_map.py    # NEW: KnowledgeMap dataclass + JSON serialization
├── doc_access.py       # NEW: document range access tools (read_document_range, etc.)
├── phases/
│   ├── __init__.py     # NEW
│   ├── reader.py       # NEW: ReaderAgent (Phase 1)
│   └── extractor.py    # NEW: ExtractorAgent (Phase 2)
├── verifier.py         # EXISTING: ContentVerifier — enhanced for Phase 3 with full doc access
├── tools.py            # EXISTING: add doc_access tool definitions
├── skill_advisor.py    # EXISTING: C-2c threshold fix already applied
├── report.py           # EXISTING: unchanged
├── curator.py          # EXISTING: unchanged
└── provider/           # EXISTING: unchanged
```

**Rationale**: Single-responsibility (each file has one clear role), avoids polluting the existing `tools.py` with new doc_access logic, and keeps the `phases/` package clearly separate from the existing infrastructure. Follows constitution principle: "良好的文件拆分，不要都写在同一个目录".

---

## R-008: Skill Generation in Three-Phase Pipeline

**Decision**: Skill generation moves to the end of Phase 3 (Verifier). After each entry is verified and written to pending, `_finalize_skill_generation` runs deterministically using the same SkillAdvisor logic (already patched with Chinese headers C-2a and expanded CLI tool patterns C-2b). The Verifier phase has access to the full verified entry content, so `_extract_resolution_section` receives complete markdown, not a truncated version.

**Rationale**: The Verifier has the most complete view of the entry. Running Skill generation here ensures it sees the finalized, verified content (not a draft). This also defers Skill generation until after content quality is confirmed — no point creating a Skill for an entry that verification might significantly modify.

**Alternatives considered**:
- Skill generation in Extractor phase — too early; entry content may be modified by Verifier.
- Skill generation as a separate Phase 4 — unnecessary extra phase; Verifier already has all needed context.
