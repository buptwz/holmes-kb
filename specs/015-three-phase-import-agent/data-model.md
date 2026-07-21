# Data Model: Three-Phase Import Agent

**Feature**: 015-three-phase-import-agent
**Date**: 2026-06-08

---

## Entity 1: KnowledgePoint

A single discrete unit of knowledge identified within a source document by the Reader phase.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | str | `kp-N`, unique within map | Stable identifier for this knowledge point |
| `description` | str | 1–200 chars | One-sentence summary of what this knowledge point is about |
| `section_start` | int | ≥ 0 | Start character offset in the original source text |
| `section_end` | int | > section_start | End character offset in the original source text |
| `type_hint` | str | one of: pitfall/model/guideline/process/decision | Reader's best-guess KB type |
| `category_hint` | str | one of: network/system/application/database/\* | Reader's best-guess category |
| `language` | str | ISO 639-1 code, e.g. `zh`, `en` | Detected language of the knowledge point's content |
| `extracted` | bool | default: False | Set to True after ExtractorAgent successfully processes this KP |

**Validation rules**:
- `section_end > section_start` (non-empty section)
- `type_hint` must be one of the five valid KB types
- `id` must be unique within a KnowledgeMap

---

## Entity 2: KnowledgeMap

The structured knowledge summary produced by the Reader phase and consumed by the Extractor phase. Acts as the episodic memory handoff between phases.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `knowledge_points` | list[KnowledgePoint] | ≥ 0 items | All identified knowledge points |
| `total_chars` | int | > 0 | Total character count of the source document |
| `chars_read` | int | 0 ≤ chars_read ≤ total_chars | Characters actually read/processed by the Reader |
| `coverage_pct` | float | 0.0–100.0 | `chars_read / total_chars * 100` |
| `diminishing_returns` | bool | default: False | True if Reader stopped due to no new KPs in last 2 passes |
| `reading_passes` | int | ≥ 1 | Number of reading passes the Reader performed |

**State transitions**:
```
KnowledgeMap.knowledge_points[*].extracted
  False → True  (set by ExtractorAgent after successful entry creation)
```

**Serialization**: JSON-serializable dataclass. Stored in-memory during pipeline run; optionally written to `--verbose` trace output.

---

## Entity 3: DocumentCursor

Tracks which portions of the source document the Reader has processed, enabling incremental reading and coverage reporting.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `source_text` | str | immutable after creation | Full original source text — never truncated |
| `read_ranges` | list[tuple[int,int]] | sorted, non-overlapping | Character ranges that have been read |
| `total_chars` | int | = len(source_text) | Cached total length |

**Methods** (behavioural contract):
- `read_range(start, end) → str` — returns `source_text[start:end]`, records range
- `coverage_pct() → float` — percentage of document covered by read_ranges
- `find_section(heading) → tuple[int,int] | None` — locates a heading and returns its span

---

## Entity 4: PhaseResult

The output contract of each pipeline phase, passed to the next phase or to the orchestrator.

| Field | Type | Description |
|-------|------|-------------|
| `phase` | str | `"reader"`, `"extractor"`, or `"verifier"` |
| `success` | bool | Whether this phase completed without error |
| `output` | Any | Phase-specific output: KnowledgeMap / draft entry str / verified entry str |
| `error` | str \| None | Error message if success=False |
| `tool_iterations` | int | Number of LLM tool-call iterations used |

---

## Entity 5: ImportReport (existing — extended)

The existing `ImportReport` dataclass is extended with two new fields to surface phase-level diagnostics.

| New Field | Type | Description |
|-----------|------|-------------|
| `knowledge_map` | KnowledgeMap \| None | The KnowledgeMap produced by the Reader phase (included in --verbose output) |
| `phase_traces` | list[str] | Per-phase summary lines appended to verbose output |

All existing fields (`created`, `updated`, `skipped`, `suggestions`, `warnings`, `traces`, `skills_generated`, `skills_linked`, `auto_decisions`) are unchanged.

---

## Entity Relationships

```
Source Document (str)
    │
    ▼ Phase 1: ReaderAgent
KnowledgeMap
  ├── KnowledgePoint (kp-1)  ──┐
  ├── KnowledgePoint (kp-2)  ──┼── Phase 2: ExtractorAgent × N (serial)
  └── KnowledgePoint (kp-N)  ──┘
                                    │
                                    ▼
                              Draft KB Entry (Markdown)
                                    │
                                    ▼ Phase 3: VerifierAgent
                              Verified KB Entry → pending/
                                    │
                                    ▼ Post-phase: SkillAdvisor
                              ImportReport (skills_generated / suggestions)
```

---

## Key Invariants

1. **Source text immutability**: `ctx["source_text"]` is set once at pipeline start and never modified. All phases read from this same reference.
2. **Phase isolation**: Each phase's `messages` list is initialised empty; no cross-phase message sharing.
3. **Single source of truth for document**: `DocumentCursor.source_text` is the canonical copy; `verify_content` always reads from `ctx["source_text"]`, not from tool_input (W1-F1 fix preserved).
4. **KnowledgeMap completeness gate**: Extractor phase only starts after `knowledge_map.coverage_pct >= coverage_threshold` (default: 95%) or `diminishing_returns=True`.
