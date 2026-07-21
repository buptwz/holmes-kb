# Implementation Plan: KB Access Control & Governance

**Branch**: `003-kb-governance` | **Date**: 2026-06-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-kb-governance/spec.md`

## Summary

Adds evidence-driven governance to the Holmes KB CLI: (1) **write protection** — all writes (including draft edits) go through `write-pending → confirm`; no direct `write-entry` command exists; `write-pending` rejects duplicate titles with hard error; (2) **correction workflow** — `write-pending --corrects <id>` creates a correction proposal; `confirm` detects it, saves a VersionSnapshot to `.history/`, and replaces the original; (3) **evidence array** — `holmes kb update-refs --ids <id,...>` appends `EvidenceRecord` objects to each entry's `evidence` array at session end; maturity is auto-derived from evidence count (≥1 → `verified`; ≥2 different sessions + ≥2 contributors → `proven`); (4) **maturity decay** — `holmes kb decay` scans entries and demotes overdue ones, saving a VersionSnapshot on each demotion; (5) **contributors field** — each entry tracks who has validated it; (6) **conflict handling** — concurrent maturity conflicts retain lower value and set `contradiction: true`; (7) **archive** — orphaned draft entries move to `contributions/archive/`. CLAUDE.md is updated to instruct Agent to call `update-refs` at session end.

---

## Technical Context

**Language/Version**: Python 3.11+ (existing project language)

**Primary Dependencies**: click, python-frontmatter, PyYAML (all already installed)

**Storage**: Markdown files with YAML frontmatter in `$HOLMES_KB_PATH/`; new `.history/` and `contributions/archive/` subdirectories

**Testing**: pytest (existing test suite in `kb/tests/`)

**Target Platform**: Linux (Ubuntu, per constitution)

**Performance Goals**: `decay` command <10s for ≤1000 entries (SC-003); `update-refs` is per-session O(n) where n = referenced entries

**Constraints**: Soft-constraint only (no chmod); decay is offline batch; no external services; evidence array is append-only for git-merge friendliness

**Scale/Scope**: ≤1000 KB entries typical workload

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| 开闭原则 | PASS | New `governance.py`, `history.py`, `decay.py` modules; existing CLI extended via new commands only |
| 依赖倒置原则 | PASS | CLI stays thin; business logic in domain modules |
| 单一职责原则 | PASS | `governance.py` = guard only; `history.py` = snapshots only; `decay.py` = decay only |
| 接口隔离原则 | PASS | Each new module exposes a minimal function set |
| 渐进式实现原则 | PASS | No speculative abstractions; each class does exactly what this feature needs |
| 环境配置原则 | PASS | Decay thresholds in `kb-config.yml`; no hardcoded values (defaults used as fallback only) |
| 验证原则 | PASS | New modules each get their own test file |
| 可观测性原则 | PASS | All governance events logged to `contributions/log.md` |
| 安全 | PASS | Soft constraint is explicitly spec-mandated; no sensitive data handling |

---

## Project Structure

### Documentation (this feature)

```text
specs/003-kb-governance/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── cli-commands.md  # Phase 1 output
└── tasks.md             # Phase 2 output (from /speckit-tasks)
```

### Source Code (repository root)

```text
kb/holmes/kb/
├── governance.py        ← NEW: title duplicate guard + write-protection check
├── history.py           ← NEW: VersionSnapshot write/read (.history/)
├── decay.py             ← NEW: maturity decay scan logic
├── store.py             ← MODIFIED: add append_evidence(), derive_maturity(), update contributors
├── pending.py           ← MODIFIED: add title duplicate check + corrects param
└── cli.py               ← MODIFIED: update update-refs (evidence array); extend write-pending + confirm;
                                      remove write-entry command; add decay command

kb/tests/
├── test_governance.py   ← NEW
├── test_history.py      ← NEW
├── test_decay.py        ← NEW
├── test_store.py        ← MODIFIED (add evidence/contributors/maturity tests)
├── test_integration.py  ← MODIFIED (add governance + correction integration tests)
└── (existing test files unchanged)
```

### CLAUDE.md Updates

Both `~/.holmes/CLAUDE.md` and `~/holmes-kb/CLAUDE.md` updated:
- Step 2.5: Remove per-read `touch`; replace with session-end `update-refs` batch call
- Add note about write protection: all writes through `write-pending`; correction via `--corrects`
- Add note about `knowledgeReferences`: structured output format for session-end ref tracking

---

## Module Specifications

### `governance.py` (new)

```python
# Public API
def check_title_duplicate(kb_root: Path, title: str, exclude_corrects: Optional[str] = None) -> Optional[str]:
    """Returns matching entry ID if title matches a verified/proven entry, else None.
       If exclude_corrects is provided, skip that entry (for correction workflow)."""

def is_write_protected(kb_root: Path, entry_id: str) -> tuple[bool, str]:
    """Returns (protected, error_message). Protected if maturity is verified/proven."""
```

### `history.py` (new)

```python
# Public API
def save_snapshot(kb_root: Path, entry_id: str, original_content: str, replaced_by: str, reason: str = "correction") -> Path:
    """Write .history/<entry_id>-<timestamp>.md. Returns snapshot path.
       reason: 'correction' or 'decay'"""

def list_snapshots(kb_root: Path, entry_id: str) -> list[Path]:
    """List all snapshots for an entry_id, sorted by timestamp."""
```

### `decay.py` (new)

```python
@dataclass
class DecayChange:
    id: str
    old_maturity: str
    new_maturity: str
    last_evidence_date: Optional[str]   # from evidence array (max date) or updated_at
    months_unreferenced: int

@dataclass
class DecayResult:
    scanned: int
    changes: list[DecayChange]
    errors: list[str]

def run_decay(kb_root: Path, dry_run: bool = False, kb_type: Optional[str] = None) -> DecayResult:
    """Scan entries, compute decay from evidence array, apply (unless dry_run).
       Save VersionSnapshot for each demoted entry. Log each change."""
```

### `store.py` extensions

```python
def append_evidence(kb_root: Path, entry_id: str, evidence: dict) -> bool:
    """Append one EvidenceRecord to entry's evidence array.
       Deduplicates by session_id. Returns True if appended, False if duplicate."""

def derive_maturity(evidence: list[dict]) -> str:
    """Compute maturity from evidence array:
       - 0 records → 'draft'
       - ≥1 record → 'verified'
       - ≥2 different session_ids AND ≥2 unique contributors → 'proven'"""

def add_contributor(kb_root: Path, entry_id: str, contributor: str) -> None:
    """Append contributor to entry's contributors list (dedup)."""

def get_last_evidence_date(evidence: list[dict]) -> Optional[str]:
    """Return the most recent date from evidence array, or None if empty."""

def resolve_maturity_conflict(local: str, incoming: str) -> tuple[str, bool]:
    """On merge conflict: return (lower_maturity, contradiction_flag)."""
```

---

## Key Implementation Details

### All Writes via Pending Flow (FR-003)

No `holmes kb write-entry` command is provided. All writes (including Agent edits to `draft` entries) go through `write-pending → confirm`. This guarantees a human review checkpoint for every change to the public KB.

```python
# cli.py — no write-entry command
# write-pending handles all Agent write intents:
#   New knowledge: holmes kb write-pending --content "..."
#   Correct existing: holmes kb write-pending --corrects <id> --content "..."
```

### Write Protection Guard (FR-001)

`governance.py` exposes `is_write_protected()` — used internally when the `confirm` path needs to verify the target entry still exists and is writable. Also callable from CLI if future tooling needs it.

```python
WRITABLE_MATURITIES = {"draft"}

def is_write_protected(kb_root, entry_id):
    entry = read_entry(kb_root, entry_id)
    if entry is None:
        return False, ""  # not found = no protection (allow create)
    post = frontmatter.loads(entry)
    maturity = post.metadata.get("maturity", "draft")
    if maturity in WRITABLE_MATURITIES:
        return False, ""
    return True, f"Write blocked: entry {entry_id!r} has maturity {maturity!r}. Use --corrects to submit a correction."
```

### Title Duplicate Check (FR-004)

In `pending.py` / `write_pending()`:
```python
def write_pending(kb_root, content, corrects=None, contributor=None, ...):
    if not corrects:
        post = frontmatter.loads(content)
        title = post.metadata.get("title", "")
        dup_id = check_title_duplicate(kb_root, title)
        if dup_id:
            raise DuplicateTitleError(title, dup_id)
    ...
```

### Evidence Array (FR-010, FR-011, FR-012)

`update-refs` appends one `EvidenceRecord` per entry per session (deduped):

```python
# EvidenceRecord structure in frontmatter:
evidence:
  - session_id: "session-20260601-abc123"
    contributor: "wangzhi"
    date: "2026-06-01T15:30:00+00:00"
    project: "holmes"        # optional
    context: "US1 debugging" # optional

# append_evidence() in store.py:
def append_evidence(kb_root, entry_id, evidence_record):
    post = load_entry(kb_root, entry_id)
    existing = post.metadata.get("evidence", [])
    # dedup by session_id
    if any(e["session_id"] == evidence_record["session_id"] for e in existing):
        return False
    existing.append(evidence_record)
    post.metadata["evidence"] = existing
    # recompute maturity
    new_maturity = derive_maturity(existing)
    post.metadata["maturity"] = new_maturity
    # update contributors
    contributor = evidence_record.get("contributor")
    if contributor:
        contribs = post.metadata.get("contributors", [])
        if contributor not in contribs:
            contribs.append(contributor)
        post.metadata["contributors"] = contribs
    save_entry(kb_root, entry_id, post)
    return True
```

### Evidence-Driven Maturity Promotion (FR-011)

```python
def derive_maturity(evidence: list[dict]) -> str:
    if not evidence:
        return "draft"
    sessions = {e["session_id"] for e in evidence}
    contributors = {e["contributor"] for e in evidence if e.get("contributor")}
    if len(sessions) >= 2 and len(contributors) >= 2:
        return "proven"
    return "verified"
```

### Maturity Conflict Handling (FR-016)

When git merge results in conflicting maturity values (e.g., one branch raises to `proven`, another decays to `draft`):

```python
MATURITY_ORDER = {"draft": 0, "verified": 1, "proven": 2}

def resolve_maturity_conflict(local: str, incoming: str) -> tuple[str, bool]:
    """Keep lower maturity value; flag contradiction for maintainer review."""
    local_rank = MATURITY_ORDER.get(local, 0)
    incoming_rank = MATURITY_ORDER.get(incoming, 0)
    lower = local if local_rank <= incoming_rank else incoming
    return lower, True  # (maturity, contradiction=True)
```

The `contradiction: true` field is added to the entry frontmatter and logged to `contributions/log.md`.

### Correction Confirm (FR-007, FR-008, FR-009)

In `cli.kb_confirm()`, after existing gates:
```python
corrects_id = post.metadata.get("corrects")
if corrects_id:
    original = read_entry(kb_root, corrects_id)
    if original is None:
        click.echo(f"Error: corrects target not found: {corrects_id}", err=True); sys.exit(1)
    snapshot_path = save_snapshot(kb_root, corrects_id, original, pending_id, reason="correction")
    # Overwrite original with proposal content
    orig_path = _find_entry_path(kb_root, corrects_id)
    new_post = fm.loads(raw)
    new_post.metadata["id"] = corrects_id
    new_post.metadata["maturity"] = "verified"
    new_post.metadata["updated_at"] = now_iso
    # preserve original evidence array and contributors
    orig_post = fm.loads(original)
    new_post.metadata["evidence"] = orig_post.metadata.get("evidence", [])
    new_post.metadata["contributors"] = orig_post.metadata.get("contributors", [])
    del new_post.metadata["corrects"]
    write_entry(orig_path, fm.dumps(new_post))
    delete_pending(kb_root, pending_id)
    rebuild_index_files(kb_root)
    click.echo(f"✓ Correction applied: {corrects_id} (snapshot: {snapshot_path.name})")
    return
```

### Decay Logic (FR-013, FR-014, FR-015)

Reference date is derived from evidence array (max date), falling back to `updated_at`:

```python
def _get_reference_date(entry_metadata: dict) -> datetime:
    evidence = entry_metadata.get("evidence", [])
    if evidence:
        dates = [e["date"] for e in evidence if e.get("date")]
        if dates:
            return max(parse(d) for d in dates)
    # fallback: last_referenced (legacy) or updated_at
    for field in ("last_referenced", "updated_at"):
        val = entry_metadata.get(field)
        if val:
            return parse(str(val))
    return datetime.min.replace(tzinfo=timezone.utc)

# Decay application:
if maturity == "proven" and months_ago > proven_threshold:
    new_maturity = "verified"
    save_snapshot(kb_root, entry_id, original_content, "decay", reason="decay")
elif maturity == "verified" and months_ago > verified_threshold:
    new_maturity = "draft"
    save_snapshot(kb_root, entry_id, original_content, "decay", reason="decay")
```

Decay change reason format: `decay: unreferenced {N} months`

### Draft Archive (FR-015)

`holmes kb archive-orphans` (or via `holmes kb lint --archive`): moves Lint-flagged orphan drafts to `contributions/archive/`:

```python
def archive_orphan(kb_root: Path, entry_id: str) -> Path:
    """Move orphaned draft entry to contributions/archive/. Return new path."""
    src = find_entry_path(kb_root, entry_id)
    dst = kb_root / "contributions" / "archive" / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    rebuild_index_files(kb_root)
    append_log(kb_root, f"archived orphan: {entry_id}")
    return dst
```

### CLAUDE.md Update

Remove Step 2.5 per-read `touch`; replace with session-end batch call.

After existing "Step 2 — Read matching entries", remove old `touch` step. At session end section, add:

```markdown
### Session End — Update Reference Records
After completing troubleshooting, call `update-refs` once with all entries consulted:
  ```bash
  holmes --kb-path $HOLMES_KB_PATH kb update-refs \
    --ids PT-DB-001,GL-002,MOD-003 \
    --session-id "$HOLMES_SESSION_ID" \
    --contributor "$HOLMES_CONTRIBUTOR"
  ```
  This appends one EvidenceRecord per entry to the evidence array, driving maturity promotion.
  Same-session reads are deduplicated automatically.
```

Also update write guidance:
```markdown
- To propose new knowledge: `holmes --kb-path $HOLMES_KB_PATH kb write-pending --content "..."`
- To correct a **verified/proven** entry: `holmes --kb-path $HOLMES_KB_PATH kb write-pending --corrects <id> --content "..."`
  Then tell user: "Correction submitted as pending. Run `holmes kb confirm <pending_id>` to apply."
- Note: No direct write command exists for draft entries. All Agent writes go through pending.
```
