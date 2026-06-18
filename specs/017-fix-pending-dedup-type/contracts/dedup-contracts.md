# Contracts: Pending Dedup & Type Override

**Branch**: `017-fix-pending-dedup-type` | **Date**: 2026-06-09

---

## Contract 1: `_find_entry_by_hash(kb_root, source_hash)`

**File**: `holmes/kb/agent/tools.py`

### Pre-conditions
- `kb_root` is a valid `Path` to the KB root directory.
- `source_hash` is a 16-character string (empty string is allowed; will not match).

### Post-conditions
- Returns `(entry_id, file_path)` of the **first** match found, searching approved KB first, then pending.
- Returns `(None, None)` if no match is found in either location.
- Never raises an exception; malformed files are silently skipped.

### Scan order (priority)
1. Approved KB entries via `list_entries(kb_root)` (unchanged behavior)
2. Pending entries via `(kb_root / PENDING_DIR).glob("*.md")` (new)

### Backward compatibility
- Return type unchanged: `tuple[str | None, str | None]`
- Existing callers (`check_source_hash`) unaffected.

---

## Contract 2: `ImportAgentRunner(force_type=...)`

**File**: `holmes/kb/agent/runner.py`

### Interface change
```python
def __init__(
    self,
    kb_root: Path,
    cfg: HolmesConfig,
    no_interactive: bool = False,
    verbose: bool = False,
    dry_run: bool = False,
    force_type: Optional[str] = None,   # NEW
) -> None:
```

### Invariants
- When `force_type` is `None`, behavior is identical to current.
- When `force_type` is a valid type string, it is propagated to `ThreePhaseImportPipeline`.
- `force_type` is NOT validated here; validation occurs in `cli.py` before construction.

---

## Contract 3: `ThreePhaseImportPipeline(force_type=...)`

**File**: `holmes/kb/agent/pipeline.py`

### Interface change
```python
def __init__(
    self,
    kb_root: Path,
    cfg: HolmesConfig,
    no_interactive: bool = False,
    verbose: bool = False,
    dry_run: bool = False,
    _provider: Optional[LLMProvider] = None,
    force_type: Optional[str] = None,   # NEW
) -> None:
```

### Enforcement point
After `extractor.run(kp, knowledge_map, ctx)` returns a draft string, and before `_validate_and_repair_draft()` is called:
```python
if self.force_type and draft:
    try:
        post = fm.loads(draft)
        post.metadata["type"] = self.force_type
        draft = fm.dumps(post)
    except Exception:
        pass  # malformed draft; let validate_and_repair handle it
```

### Invariants
- When `force_type` is `None`, behavior is identical to current.
- When set, every pending entry produced by this pipeline run has `type == force_type`.
- Enforcement is deterministic (not LLM-guided); LLM prompt guidance is supplementary.

---

## Contract 4: `holmes import --type <value>` CLI

**File**: `holmes/cli.py`

### Validation
Valid values: `pitfall`, `model`, `guideline`, `process`, `decision` (case-insensitive).

On invalid value:
```
Error: Invalid --type value '<value>'. Valid values: pitfall, model, guideline, process, decision.
```
Exit code 1. No LLM call made.

### Propagation
`kb_type` → `ImportAgentRunner(force_type=kb_type)` → `ThreePhaseImportPipeline(force_type=kb_type)`
