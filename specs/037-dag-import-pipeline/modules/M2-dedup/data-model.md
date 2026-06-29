# Data Model: M2-dedup

## EntryMeta (store.py — updated)

```python
@dataclass
class EntryMeta:
    id: str
    type: str
    title: str
    maturity: str
    category: Optional[str]
    tags: list[str]
    created_at: str
    updated_at: str
    file_path: str
    pending: bool = False
    kb_status: str = "active"
    parent_id: Optional[str] = None
    # M2: new optional fields (backwards-compatible, default "")
    source_hash: str = ""
    source_file: str = ""
```

**Population**: `list_entries()` reads `meta.get("source_hash", "")` and `meta.get("source_file", "")` for each entry file.

---

## New Functions (store.py)

### `find_entries_by_source_hash`

```
Input:  kb_root: Path, source_hash: str
Output: list[EntryMeta]

Algorithm:
  if source_hash is empty string → return []
  scan confirmed space: list_entries(kb_root, kb_status=None, exclude_sub_entries=False)
  scan pending space: contributions/pending/*.md
  return all EntryMeta where entry.source_hash == source_hash
```

### `find_entries_by_source_file`

```
Input:  kb_root: Path, source_file: str
Output: list[EntryMeta]

Algorithm:
  if source_file is empty string → return []
  normalise: canonical = Path(source_file).as_posix()
  scan confirmed space: list_entries(kb_root, kb_status=None, exclude_sub_entries=False)
  scan pending space: contributions/pending/*.md
  return all EntryMeta where Path(entry.source_file).as_posix() == canonical
```

**Implementation note**: Both functions build a combined list from confirmed + pending by:
1. Calling `list_entries(kb_root, kb_status=None, exclude_sub_entries=False)` for confirmed entries
2. Iterating `contributions/pending/*.md` directly (same pattern as existing `list_entries(include_pending=True)`)

---

## Step 0 State Transitions (pipeline.py)

```
source_hash computed
       │
       ▼
   self.force?
   YES ──────────────────────────────→ continue to existing pipeline
       │
       ▼ NO
   find_entries_by_source_hash(source_hash)
       │
   found? YES → report.skipped += ids
              → report.warnings += "已存在完全相同..."
              → return report        (EXIT)
       │
       ▼ NO
   source_file computed (or "" if outside kb_root)
       │
   source_file empty? → skip Step 0b
       │
       ▼ NOT EMPTY
   find_entries_by_source_file(source_file)
       │
   found? YES → print update notice
              → old_pending = [m for m in matches if _is_pending(m)]
              → old_pending non-empty AND NOT dry_run?
                  → _prompt_cancel_old_pending(old_pending)
              → continue to existing pipeline  (NO EXIT)
       │
       ▼ NO
   continue to existing pipeline  (new document)
```

---

## Helper: `_compute_source_file`

```python
def _compute_source_file(kb_root: Path, file_path: Optional[Path]) -> str:
    """Return path relative to kb_root, or '' if file_path is None / outside kb_root."""
    if file_path is None:
        return ""
    try:
        return file_path.relative_to(kb_root).as_posix()
    except ValueError:
        return ""  # file_path not under kb_root
```
