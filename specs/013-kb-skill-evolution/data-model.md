# Data Model: Holmes KB Autonomous Import Agent

**Feature**: `013-kb-skill-evolution` | **Date**: 2026-06-07

---

## Entity 1: ImportSource

Represents the raw input to the import pipeline. Created at the start of each `holmes import` invocation.

**Fields**:

| Field | Type | Constraint | Description |
|-------|------|-----------|-------------|
| `raw_text` | `str` | Non-empty, ≥50 chars | Raw input text extracted from file/stdin/arg |
| `source_hash` | `str` | 16-char hex string | SHA-256 of `raw_text` truncated to 16 chars |
| `file_path` | `Optional[Path]` | Valid path or None | Source file path (None for stdin/inline) |
| `dry_run` | `bool` | Default: False | If True, no writes occur |
| `no_interactive` | `bool` | Default: False | If True, skip all confirmation gates |

**Computed**:
- `source_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]`

---

## Entity 2: KBEntry (extended)

Existing entity in `kb/holmes/kb/schema.py` and Markdown frontmatter. Two new fields added.

**New fields** (additive, backward-compatible):

| Field | Type | Constraint | Description |
|-------|------|-----------|-------------|
| `source_hash` | `Optional[str]` | 16-char hex or absent | Hash of the original import source |
| `import_confidence` | `Optional[float]` | 0.0–1.0 or absent | LLM classification confidence at import time |

**Existing frontmatter fields** (unchanged):

```yaml
id: ""                 # Assigned on confirm (pending: pending-YYYYMMDD-HHMMSS-xxxx)
type: pitfall          # pitfall | model | guideline | process | decision
title: ""
maturity: draft        # draft | verified | proven | deprecated
category: database     # for pitfall only
tags: []
created_at: ""
updated_at: ""
skill_refs: []         # Added by skill link
source_hash: ""        # NEW
import_confidence: 0.9 # NEW
```

**State transitions** (unchanged from 003-kb-governance):

```
draft → verified → proven → deprecated
         ↑ evidence accumulation
```

---

## Entity 3: SkillUsageRecord

Stored as `.skill_usage.json` in each skill's directory (e.g., `skills/pg-recovery/.skill_usage.json`).

**JSON Schema**:

```json
{
  "created_at": "2026-06-07T10:00:00Z",
  "agent_created": true,
  "use_count": 0,
  "last_used_at": null,
  "patch_count": 0,
  "last_patched_at": null,
  "absorbed_into": null
}
```

**Field constraints**:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `created_at` | ISO-8601 string | required | When skill was created |
| `agent_created` | bool | false | True if created by import agent (not by user) |
| `use_count` | int | 0 | Times skill was run |
| `last_used_at` | ISO-8601 string or null | null | Last run timestamp |
| `patch_count` | int | 0 | Times SKILL.md was patched |
| `last_patched_at` | ISO-8601 string or null | null | Last patch timestamp |
| `absorbed_into` | str or null | null | Name of skill this was merged into on delete |

**State transitions**:
- `agent_created` set at creation, immutable after
- `absorbed_into` set on deletion via `manage --action delete --absorbed-into`; makes record a tombstone
- No time-based archiving per user requirement

**Python dataclass**:
```python
@dataclass
class SkillUsageRecord:
    created_at: str
    agent_created: bool = False
    use_count: int = 0
    last_used_at: Optional[str] = None
    patch_count: int = 0
    last_patched_at: Optional[str] = None
    absorbed_into: Optional[str] = None
```

**Persistence**: `kb/holmes/kb/skill/usage.py` — `read_usage(skill_dir)`, `write_usage(skill_dir, record)`, `bump_use(skill_dir)`, `bump_patch(skill_dir)`, `mark_agent_created(skill_dir)`.

---

## Entity 4: ImportReport

In-memory result of a single `holmes import` run. Printed to stdout on completion.

**Python dataclass**:
```python
@dataclass
class ImportReport:
    created: list[str]          # Entry titles created
    updated: list[str]          # Entry IDs updated (hash mismatch, same root cause)
    skipped: list[str]          # Entry IDs skipped (exact hash match)
    skills_generated: list[str] # Skill names created
    skills_linked: list[str]    # Skill names linked (already existed)
    suggestions: list[str]      # Human-readable suggestions (skill candidates, etc.)
    warnings: list[str]         # Low-confidence decisions, missing fields, etc.
    errors: list[str]           # Per-item failures (LLM error, validation fail, etc.)
    dry_run: bool
    auto_decisions: list[str]   # Decisions made automatically in --no-interactive mode
```

**Summary output format** (FR-020):
```
✓ 1 created, 0 updated, 1 skipped (duplicate) | skill: 1 generated, 0 merged | 1 suggestion: check-connections may warrant a skill
```

**Verbose output** (FR-021): Full decision trace per knowledge point.

---

## Entity 5: CuratorFinding

Output of the incremental skill curation pass (FR-014). Collected into `ImportReport.suggestions`.

**Python dataclass**:
```python
@dataclass
class CuratorFinding:
    finding_type: str           # "merge_candidate" | "oversized" | "update_candidate"
    skill_names: list[str]      # Affected skill name(s)
    reason: str                 # Human-readable explanation
    confidence: float = 1.0     # For merge_candidate: LLM confirmation confidence
```

**Examples**:
- `merge_candidate`: `["check-pg-connections", "check-pg-pool"]` — "Description Jaccard 0.72; LLM confirms same intent"
- `oversized`: `["pg-full-recovery"]` — "SKILL.md body is 4,200 chars (limit: 3,000)"
- `update_candidate`: `["pg-connection-recovery"]` — "patch_count=0; linked entry PT-DB-001 updated 2026-06-01"

---

## Entity 6: AgentTool (internal)

Each tool exposed to the Anthropic agent. Defined in `agent/tools.py`.

| Tool Name | Input | Output | Purpose |
|-----------|-------|--------|---------|
| `check_source_hash` | `{hash: str}` | `{match: bool, entry_id: str, same_root_cause: bool}` | Idempotency check |
| `write_kb_entry` | `{content: str, source_hash: str, confidence: float}` | `{pending_id: str}` | Write structured entry to pending |
| `update_kb_entry` | `{entry_id: str, patch: dict}` | `{success: bool}` | Merge-update existing entry |
| `read_kb_entries_by_category` | `{type: str, category: str}` | `{entries: list}` | Retrieve candidates for dedup |
| `compare_root_cause` | `{new_summary: str, existing_id: str}` | `{same: bool, confidence: float}` | LLM semantic dedup |
| `verify_content` | `{source: str, draft: str}` | `{unsupported_fields: list, confidence: float}` | Self-verification |
| `evaluate_skill` | `{resolution_text: str, entry_id: str}` | `{recommendation: str, skill_name: str}` | Skill generation advisory |
| `create_skill_for_entry` | `{name: str, entry_id: str, content: str}` | `{created: bool, linked: bool}` | Create + link skill |
| `report_item` | `{type: str, message: str}` | `{ok: bool}` | Append to ImportReport |

---

## Relationships

```
ImportSource ──[1:1]──> ImportReport
ImportSource ──[1:N]──> KBEntry (creates or updates)
KBEntry ──[1:N]──> SkillUsageRecord (via skill_refs links)
ImportReport ──[0:N]──> CuratorFinding (via suggestions)
AgentTool ──[executes]──> KBEntry, SkillUsageRecord
```

---

## File Layout Summary

| Entity | Storage Location | Format |
|--------|-----------------|--------|
| ImportSource | In-memory only | Python dataclass |
| KBEntry | `~/.holmes-kb/<type>/<category>/<id>.md` | Markdown + YAML frontmatter |
| SkillUsageRecord | `~/.holmes-kb/skills/<name>/.skill_usage.json` | JSON |
| ImportReport | In-memory + stdout | Python dataclass + formatted text |
| CuratorFinding | In-memory (in ImportReport.suggestions) | Python dataclass |
