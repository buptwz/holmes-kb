# Research: Import Pipeline v3 Bug Fixes — English Metadata & Document-Level Dedup

## Decision 1: Root Cause of English Metadata Bug (US1)

**Decision**: Two independent defects combine to cause missing `language` and `tags` fields for English documents.

**Root Cause A — No language injection in DraftNormalizer**: `DraftNormalizer.normalize()` has 7 normalization steps (header translation, title truncation, tag extraction, structural constraints, category normalization). None of the steps sets the `language` field. When the LLM omits `language` from the frontmatter, no code path adds it. The normalizer cannot infer language from nothing.

**Root Cause B — Wrong pipeline order (repair after normalize)**: In `pipeline.py`, the order is:
1. `normalizer.normalize(draft)` — tries to parse YAML; if it fails, returns draft unchanged with a warning
2. `ExtractorAgent._validate_and_repair_draft(draft)` — repairs malformed YAML

If the LLM generates malformed YAML (common for English documents due to LLM prompt bias toward Chinese formatting), step 1 silently returns the draft unchanged (frontmatter.loads raises, function returns early at line 109-110 of normalizer.py). Step 2 then repairs the YAML, but by then normalization has already been skipped — so `language` and `tags` are never injected.

**Decision**: Fix both defects:
- Add language detection as a normalization step in `DraftNormalizer.normalize()`: if `language` not in frontmatter, detect from draft content using a simple heuristic (presence of CJK characters → `zh`, else → `en`).
- Swap the order in `pipeline.py`: call `_validate_and_repair_draft` FIRST, then call `normalizer.normalize()` on the repaired output.

**Rationale**: Language detection by CJK character presence is deterministic, zero-cost, and already reliable — the HEADER_MAP in normalizer.py uses the same CJK character range (`\u4e00-\u9fff`). The order swap is a one-line change with high leverage: it ensures normalization always runs on valid YAML.

**Alternatives considered**:
- LLM prompt engineering to enforce language field: fragile, non-deterministic.
- Post-write patch of pending entries: violates write-once-and-correct principle; harder to test.

---

## Decision 2: Root Cause of Document-Level Dedup Bug (US2)

**Decision**: Entry-level dedup in `write_kb_entry` is insufficient because it relies on the LLM consistently passing the correct `source_hash` in every tool call.

**Root Cause**: The pipeline computes `source_hash = compute_source_hash(source_text)` and puts it in the user prompt (`source_hash: {hash}\n...`). The `write_kb_entry` tool definition marks `source_hash` as **required**, but the LLM may:
1. Pass a different value (e.g., hash of extracted content instead of full document)
2. Omit it entirely on non-deterministic runs

When `source_hash` is empty in the tool input, line 164 of tools.py (`if source_hash and not force`) skips the dedup check entirely, allowing a duplicate entry to be created.

The report shows: second import of TC-M01 produces `1 skipped + 1 created` — the LLM made two `write_kb_entry` calls; one included the correct hash (deduped), one did not (created duplicate).

**Decision**: Add a **document-level pre-check** in `pipeline.py` immediately after `compute_source_hash`. Before running Reader/Extractor/any LLM call:
1. Scan all existing entries (approved + pending) for a matching `source_hash`
2. If found: collect all entries with that hash, report them as skipped, return early
3. If `--force`: bypass this check (consistent with entry-level force flag)

This makes dedup **deterministic and LLM-independent**: the pipeline either runs fully (new document) or not at all (known document). The LLM never sees duplicate documents.

**Rationale**: `_find_entry_by_hash` in tools.py already scans both approved and pending dirs. We need a variant (`_find_all_entries_by_hash`) that returns ALL matching entries (not just the first), so the skipped count is accurate. The new pre-check calls this before any LLM work.

**Alternatives considered**:
- Strengthen LLM prompt to always include source_hash: fragile, still LLM-dependent.
- Store document hashes in a separate index file: over-engineering; scanning existing entries is fast enough for typical KB sizes (<10k entries).

---

## Decision 3: Language Detection Heuristic

**Decision**: Use CJK character presence (`\u4e00-\u9fff`) in the combined title + body as the language signal. If ≥1 CJK character is found → `zh`. Otherwise → `en`.

**Rationale**: This is the same token pattern already used in `_TOKEN_RE` in normalizer.py. It correctly handles the full range of Chinese, Japanese, Korean characters. Edge cases (mixed-language entries with mostly English but some CJK terms) are handled correctly: if the document is English but uses Chinese technical terms in the resolution, the title and root cause will be English, giving correct `en` classification.

**Alternatives considered**:
- `langdetect` library: unnecessary external dependency; overkill for binary zh/en classification.
- Checking filename extension or document metadata: not available during normalization.

---

## Decision 4: Fallback Tag for English Entries

**Decision**: The existing `_extract_tags` method already auto-extracts tags from `title + root_cause` when fewer than `MIN_TAGS=3` tags are present. After fixing the pipeline order (repairing YAML before normalizing), this existing logic will naturally fire for English entries too.

**Additional safety**: If tag extraction yields 0 tags even after auto-extraction (e.g., title and root_cause are empty), inject one fallback tag derived from `category` (e.g., `category: network` → tag `network`). This ensures the "at least 1 tag" guarantee from FR-002.

**Rationale**: Minimal change — reuses existing auto-extraction logic. The category fallback is a 3-line addition to `_extract_tags`.

---

## Decision 5: Affected Files

| Fix | Files | Lines changed (est.) |
|-----|-------|----------------------|
| US1-A: language injection | `kb/holmes/kb/agent/normalizer.py` | +10 |
| US1-B: pipeline order swap | `kb/holmes/kb/agent/pipeline.py` | +5, reorder 2 lines |
| US2: document-level dedup | `kb/holmes/kb/agent/pipeline.py` + `kb/holmes/kb/agent/tools.py` | +20 |
| Tests | `kb/tests/test_normalizer.py` + `kb/tests/test_pipeline.py` | +40 |

No new files needed. All changes are isolated to existing modules.
