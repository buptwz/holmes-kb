# Data Model: Import Pipeline Quality Normalization (018)

## Entities

### DraftNormalizer

**Module**: `kb/holmes/kb/agent/normalizer.py`

| Field | Type | Description |
|-------|------|-------------|
| `HEADER_MAP` | `dict[str, str]` | Class constant: Chinese/non-standard → English header mapping |
| `STOPWORDS` | `frozenset[str]` | Class constant: words excluded from tag extraction |
| `MAX_TITLE_LENGTH` | `int` | Class constant: 60 |
| `MIN_TAGS` | `int` | Class constant: 3 |
| `MAX_TAGS` | `int` | Class constant: 8 |

**Methods**:
- `normalize(draft: str, kb_type: str | None = None) -> tuple[str, list[str]]`
  - Returns `(normalized_draft, warnings)`
  - Stateless; safe to call in parallel
  - Operations applied in order: (1) header translation, (2) title enforcement, (3) tags extraction, (4) type structural constraints, (5) category normalization

**State transitions**: None (stateless pure function wrapped in class for testability)

---

### DocumentClassifier

**Module**: `kb/holmes/kb/agent/phases/classifier.py`

| Field | Type | Description |
|-------|------|-------------|
| `provider` | `LLMProvider` | Injected LLM provider |
| `model` | `str` | Model name from HolmesConfig |

**Methods**:
- `classify(source_text: str) -> ClassificationResult`
  - Makes one LLM call
  - Returns `ClassificationResult` (see below)
  - Never raises; returns `single-incident` default on any error

---

### ClassificationResult

**Module**: `kb/holmes/kb/agent/phases/classifier.py` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `doc_type` | `DocumentType` | Classified document type |
| `reason` | `str` | Human-readable classification rationale |
| `granularity_hint` | `str` | Instruction string passed to ReaderAgent |

---

### DocumentType (enum)

**Module**: `kb/holmes/kb/agent/phases/classifier.py`

| Value | Meaning | Reader Granularity Hint |
|-------|---------|------------------------|
| `single_incident` | One incident/failure event | Standard fine-grained extraction (default) |
| `multi_incident` | Multiple distinct incidents | One KP per distinct incident |
| `runbook` | Sequential operational procedure | 3–8 KPs covering distinct operational steps |
| `guideline` | Best-practice/standard document | One KP per rule/principle |
| `non_kb` | Meeting notes, tables, org content | Rejected — no KB extraction |

---

### Category (expanded constant)

**Module**: `kb/holmes/kb/schema.py`

```python
VALID_PITFALL_CATEGORIES: frozenset[str] = frozenset({
    # Original 4
    "network", "system", "application", "database",
    # New 4 (v15 real-world distribution)
    "kubernetes", "messaging", "cache", "monitoring",
})
```

All category references in prompts and validation logic derive from this constant. No other file hardcodes category values.

---

### SkillParam (extended)

**Module**: `kb/holmes/kb/skill/manager.py` (existing dataclass, extended)

Current:
```python
@dataclass
class SkillParam:
    name: str
    description: str
    required: bool = False
    default: str = ""
```

No schema change — the existing `SkillParam` dataclass is sufficient. The change is in how `create_skill()` receives params: instead of parsing from SKILL.md frontmatter, `_run_skill_and_curation` extracts `{UPPERCASE_NAME}` patterns from commands and passes them as `param_names: list[str]` to `create_skill()`.

**`create_skill()` signature update**:
```python
def create_skill(
    kb_root: Path,
    name: str,
    description: str,
    platforms: str = "linux,macos",
    commands: Optional[list[str]] = None,
    param_names: Optional[list[str]] = None,  # NEW
) -> Path
```

---

### ImportReport (extended)

**Module**: `kb/holmes/kb/agent/report.py` (existing dataclass, field added)

New field:
```python
knowledge_map: Optional[KnowledgeMap] = None  # already added in 016
```

The `format_dry_run_plan()` method is updated to use `self.knowledge_map` to show KP count estimate.

No new fields needed — `warnings` list already receives Normalizer output.

---

## Relationships

```
pipeline.run()
  │
  ├─► DocumentClassifier.classify(source_text)
  │     → ClassificationResult{doc_type, granularity_hint}
  │     → if non_kb: add to report.warnings, return report (exit)
  │
  ├─► ReaderAgent.run(source_text, ctx with granularity_hint)
  │     → KnowledgeMap
  │
  └─► for kp in knowledge_map:
        ExtractorAgent.run(kp, ...)
          → raw draft string
        DraftNormalizer.normalize(draft, kb_type)
          → (normalized_draft, warnings) → warnings → report.warnings
        _validate_and_repair_draft(normalized_draft)
          → (repaired_draft, repair_warning)
        [Root E fallback if pitfall + empty Resolution]
          → detect_commands(source_slice) → inject into Resolution
        kp_drafts[kp.id] = repaired_draft

      _run_extraction_loop(...)
        → for each created entry in _created_entry_contents:
            detect_commands(resolution_text) → commands
            extract {PARAM} from commands
            create_skill(commands=commands, param_names=params)

      _finalize_skill_generation(report)
        → per-entry, no early-return on existing skills_generated
```

## Validation Rules

| Entity | Rule | Error Behavior |
|--------|------|---------------|
| `DraftNormalizer` | Title ≤60 chars | Truncate at word boundary + warning |
| `DraftNormalizer` | title not null/empty | Generate from root_cause + warning |
| `DraftNormalizer` | tags ≥3 | Auto-extract + warning |
| `DraftNormalizer` | category in VALID_PITFALL_CATEGORIES | Map to closest or `system` + warning |
| `DraftNormalizer` | guideline has no ## Symptoms | Remove section + warning |
| `DraftNormalizer` | pitfall Resolution empty | Warning (do not remove; Root E fallback follows) |
| `DocumentClassifier` | LLM parse failure | Default to `single_incident`, no exception |
| `SkillAdvisor` | ≥3 commands → RECOMMENDED | Auto-create (no-interactive) or prompt |
| `SkillAdvisor` | 1–2 commands → OPTIONAL | Suggestion only, no create |
| `schema.VALID_PITFALL_CATEGORIES` | 8 values | ValidationResult.errors if not in set |
