# Data Model: Three-Phase Pipeline Stability Fixes (D-1~D-7)

**Feature**: 016-fix-pipeline-stability
**Date**: 2026-06-08

This feature modifies existing data structures and adds no new persistent entities.
All changes are backward-compatible additions.

---

## Modified: `ImportReport` (report.py)

`ImportReport` already has a `warnings: list[str]` field. D-4 fix appends to it when 0 KPs are found.

`ImportReport` already has `errors: list[str]`. D-1 fix appends formatted KP failure messages to `errors` when a draft cannot be repaired.

**No schema changes needed** — existing fields cover both new use cases.

---

## Modified: `DecisionTrace` (report.py)

`DecisionTrace` has:
- `field_sources: dict[str, str]` — field name → source fragment for verified fields
- `unsupported_fields: list[str]` — field names that were cleared

**D-7 invariant added** (enforced at mutation, not in dataclass):
- A field name MUST NOT appear in both `field_sources` and `unsupported_fields` simultaneously.
- Last write wins: adding to one list removes from the other.
- No change to the dataclass definition — invariant enforced at call sites.

---

## Modified: `create_skill()` in `manager.py`

```python
# Before (015):
def create_skill(kb_root, name, description, platforms="linux,macos") -> Path

# After (016):
def create_skill(kb_root, name, description, platforms="linux,macos",
                 commands: list[str] | None = None) -> Path
```

When `commands` is non-empty, `run.sh` is populated with those commands instead of the placeholder comment. The script header (shebang, set -euo pipefail, description echo) is always written by `generate_run_sh_template()`.

---

## Modified: `create_skill_for_entry` tool schema

```yaml
# Added optional field to tool input schema:
resolution_commands:
  type: array
  items:
    type: string
  description: >
    Shell commands extracted from the entry's ## Resolution section.
    When provided, these are written verbatim to the Skill's run.sh.
  required: false
```

---

## Modified: `ExtractorAgent` (extractor.py)

Added static method:
```python
@staticmethod
def _validate_and_repair_draft(draft: str) -> tuple[str, str | None]:
    """
    Returns (repaired_draft, warning_or_None).
    - Strips prose before first '---'
    - Ensures closing '---'
    - Validates YAML is parseable
    - Returns (draft, None) if valid
    - Returns (repaired, warning_message) if repaired
    - Returns ("", error_message) if unrecoverable
    """
```

---

## No New Entities

All data flows through existing structures:
- `KnowledgeMap` / `KnowledgePoint` — unchanged
- `ImportReport` — existing `warnings`/`errors` fields absorb new messages
- `DecisionTrace` — invariant enforced at call sites, no schema change
- `create_skill` — optional `commands` parameter (backward compatible, defaults to None)
