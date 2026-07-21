# Contract: Import Pipeline Public API

**Feature**: 015-three-phase-import-agent
**Type**: Python internal API (library contract)
**Date**: 2026-06-08

---

## C-001: ImportAgentRunner.run() — Unchanged Public Signature

The sole public entry point for the import pipeline. Signature is **unchanged** from the current implementation; this contract specifies what callers can rely on.

```python
def run(
    self,
    source_text: str,
    file_path: str | None = None,
) -> ImportReport:
```

**Inputs**:
| Parameter | Type | Constraint | Description |
|-----------|------|------------|-------------|
| `source_text` | str | len > 0 | Full original document text; never truncated before passing |
| `file_path` | str \| None | valid path or None | Source file path for audit trail; None for stdin/inline text |

**Outputs** (`ImportReport`):
| Field | Type | Guarantee |
|-------|------|-----------|
| `created` | list[str] | Entry titles of all new entries written to pending |
| `updated` | list[str] | Entry IDs of all updated entries |
| `skipped` | list[str] | Source hashes or entry IDs that were deduplicated |
| `suggestions` | list[str] | Skill candidates, optional recommendations; no duplicates |
| `warnings` | list[str] | Non-fatal warnings (e.g., low confidence) |
| `skills_generated` | list[str] | Skill names created by the pipeline |
| `skills_linked` | list[str] | Skill names linked to entries (pre-existing) |
| `dry_run` | bool | Mirrors the constructor's `dry_run` flag |

**Invariants**:
- Calling `run()` twice with identical `source_text` produces `skipped` on the second call (idempotent via source_hash).
- `dry_run=True` guarantees zero files written to disk; `suggestions` contains `Would create: ...` lines with no duplicates.
- After this feature: `warnings` must NOT contain `"Source truncated"` for documents ≤ 20,000 characters.

---

## C-002: KnowledgeMap JSON Schema

Produced by `ReaderAgent` and consumed by `ExtractorAgent`. Also included in `--verbose` output.

```json
{
  "$schema": "holmes-km-v1",
  "knowledge_points": [
    {
      "id": "kp-1",
      "description": "string (1-200 chars)",
      "section_start": 0,
      "section_end": 2400,
      "type_hint": "pitfall | model | guideline | process | decision",
      "category_hint": "string",
      "language": "zh | en | ...",
      "extracted": false
    }
  ],
  "total_chars": 12000,
  "chars_read": 12000,
  "coverage_pct": 100.0,
  "diminishing_returns": false,
  "reading_passes": 1
}
```

**Invariants**:
- `knowledge_points[*].id` is unique within the map.
- `section_end > section_start` for every knowledge point.
- `coverage_pct = chars_read / total_chars * 100` (computed, not stored).
- `extracted` starts `false`; set to `true` by ExtractorAgent upon completion.

---

## C-003: Document Access Tool Signatures

Three deterministic tools provided to all phases. They do NOT call the LLM; they are Python functions backed by `ctx["source_text"]`.

### read_document_range

```python
Input:  {"start_char": int, "end_char": int}
Output: {"text": str, "start_char": int, "end_char": int, "total_chars": int}
```
Returns `source_text[start_char:end_char]`. Clamps to document bounds silently.

### get_read_coverage

```python
Input:  {}
Output: {"chars_read": int, "total_chars": int, "coverage_pct": float}
```
Returns the DocumentCursor's current coverage statistics.

### search_in_document

```python
Input:  {"query": str, "max_results": int}  # max_results default: 3
Output: {
  "results": [
    {"offset": int, "context": str}  # 200 chars surrounding the match
  ],
  "total_matches": int
}
```
Case-insensitive substring search. Returns up to `max_results` matches.

---

## C-004: Phase Interface

Each phase class exposes a single `run()` method.

### ReaderAgent.run()

```python
def run(
    self,
    source_text: str,
    ctx: dict[str, Any],
) -> KnowledgeMap:
```
- Reads the document using doc_access tools.
- Stops when `coverage_pct >= 95` or `diminishing_returns=True`.
- Returns a KnowledgeMap; raises `PhaseError` on LLM failure.

### ExtractorAgent.run()

```python
def run(
    self,
    kp: KnowledgePoint,
    knowledge_map: KnowledgeMap,
    ctx: dict[str, Any],
) -> str:  # draft KB entry markdown
```
- Receives one KnowledgePoint at a time.
- Uses doc_access tools to read the relevant section.
- Returns the draft entry as Markdown+frontmatter string.

### VerifierAgent (enhanced ContentVerifier)

```python
def run(
    self,
    draft_content: str,
    ctx: dict[str, Any],
) -> VerifyResult:
```
- Always reads source from `ctx["source_text"]` (full, untruncated).
- Returns a `VerifyResult` (existing dataclass, unchanged).

---

## C-005: CLI Contract (unchanged)

The `holmes import` command signature is **unchanged**. All existing flags continue to work identically:

```
holmes import [FILE_OR_TEXT]
              [--dry-run]
              [--no-interactive]
              [--verbose]
              [--dir DIRECTORY]
              [--type TYPE]
              [--category CATEGORY]
              [--kb-path PATH]
```

The only user-visible change is the absence of `"Source truncated to N chars"` warnings for documents ≤ 20,000 characters.
