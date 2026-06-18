# Data Model: Import Pipeline v3 Bug Fixes

## Entity 1: KB Entry Frontmatter (modified)

The YAML frontmatter block at the top of each KB entry `.md` file.

**Fields added/enforced by this feature**:

| Field | Type | Rule | Enforced by |
|-------|------|------|-------------|
| `language` | `str` (`"zh"` or `"en"`) | MUST be present; inferred from content if missing | `DraftNormalizer.normalize()` — new step 4a |
| `tags` | `list[str]` | MUST have ≥1 element; auto-extracted when empty | `DraftNormalizer._extract_tags()` — existing, now guaranteed to run after YAML repair |
| `source_hash` | `str` (16 chars) | Written by `write_kb_entry`; used for document-level dedup | `ThreePhaseImportPipeline.run()` pre-check + `write_kb_entry` |

**Existing required fields** (unchanged): `id`, `title`, `type`, `category`, `maturity`, `created_at`, `updated_at`.

---

## Entity 2: ImportReport (modified)

The report object returned by the pipeline after each import run.

**Fields relevant to this feature**:

| Field | Type | Change |
|-------|------|--------|
| `skipped` | `list[str]` | Now populated at document level when pre-check fires (entries are IDs or placeholder strings) |
| `warnings` | `list[str]` | May include `"document already imported (source_hash=...)"` from the pre-check |

No new fields. `skipped` list semantics are extended: previously only entry-level duplicates; now also document-level duplicates.

---

## Entity 3: DraftNormalizer (modified)

**New normalization step** (inserted between step 3 title-length and step 4 tag-extraction):

**Step 3a: Language detection**
- Input: existing `meta.get("language", "")` + full `body` string + `title`
- Logic: if `language` already set → no-op; else scan `title + body` for CJK characters (`\u4e00-\u9fff`); if found → `language = "zh"`; else → `language = "en"`
- Output: `meta["language"]` set; warning appended if field was injected

---

## Entity 4: ThreePhaseImportPipeline (modified)

**New pre-check block** in `run()` method, added immediately after `source_hash = compute_source_hash(source_text)`:

```
if not dry_run and not force:
    existing_entries = _find_all_entries_by_hash(kb_root, source_hash)
    if existing_entries:
        report.skipped = [e.id for e in existing_entries]
        report.warnings.append(f"document already imported (source_hash={source_hash[:8]}...)")
        return report
```

**Pipeline order change** in the KP extraction loop:
- Before (buggy): `normalizer.normalize()` → `_validate_and_repair_draft()`
- After (fixed): `_validate_and_repair_draft()` → `normalizer.normalize()`

---

## Entity 5: _find_all_entries_by_hash (new function in tools.py)

New helper alongside existing `_find_entry_by_hash`:

```
def _find_all_entries_by_hash(kb_root: Path, source_hash: str) -> list[KBEntryMeta]:
    """Return all approved + pending entries matching source_hash."""
```

Scans the same paths as `_find_entry_by_hash` but collects ALL matches instead of returning on the first. Returns a list of lightweight entry descriptors (id, file_path).
