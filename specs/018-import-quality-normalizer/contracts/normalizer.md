# Contract: DraftNormalizer

**Module**: `holmes/kb/agent/normalizer.py`

## Interface

```python
class DraftNormalizer:
    def normalize(self, draft: str, kb_type: str | None = None) -> tuple[str, list[str]]:
        ...
```

### Input

| Parameter | Type | Description |
|-----------|------|-------------|
| `draft` | `str` | Raw KB entry Markdown string with YAML frontmatter (output of ExtractorAgent.run()) |
| `kb_type` | `str \| None` | Optional type override; if None, type is read from frontmatter |

### Output

| Field | Type | Description |
|-------|------|-------------|
| `normalized_draft` | `str` | Normalized Markdown string; structurally compliant |
| `warnings` | `list[str]` | List of human-readable normalization actions taken |

### Guarantees

- **Idempotent**: calling `normalize(normalize(draft)[0])[0]` == `normalize(draft)[0]`
- **No LLM calls**: pure deterministic Python
- **No side effects**: does not read/write files; does not mutate input
- **Parse failure**: if YAML frontmatter cannot be parsed, returns `(draft, ["warning: could not parse frontmatter — skipped normalization"])`

### Warnings Format

Each warning is a human-readable string beginning with one of:
- `"header: "` — section header translation
- `"title: "` — title enforcement action
- `"tags: "` — tags extraction action
- `"category: "` — category normalization action
- `"structure: "` — type-level structural constraint applied

---

## Contract: DocumentClassifier

**Module**: `holmes/kb/agent/phases/classifier.py`

## Interface

```python
class DocumentClassifier:
    def __init__(self, provider: LLMProvider, model: str) -> None: ...
    def classify(self, source_text: str) -> ClassificationResult: ...
```

### Input

| Parameter | Type | Description |
|-----------|------|-------------|
| `source_text` | `str` | Full untruncated source document text |

### Output (`ClassificationResult`)

| Field | Type | Description |
|-------|------|-------------|
| `doc_type` | `DocumentType` | One of: `single_incident`, `multi_incident`, `runbook`, `guideline`, `non_kb` |
| `reason` | `str` | LLM rationale (≤100 chars) |
| `granularity_hint` | `str` | Instruction string to pass to ReaderAgent |

### Guarantees

- **Never raises**: all exceptions result in `ClassificationResult(doc_type=DocumentType.single_incident, reason="classification failed — default", granularity_hint="")`
- **Single LLM call**: no retries; fail-fast default
- **Deterministic output format**: always returns `ClassificationResult` regardless of LLM response quality

### Granularity Hints by Type

| `doc_type` | `granularity_hint` |
|------------|-------------------|
| `single_incident` | `""` (no extra hint, standard Reader behavior) |
| `multi_incident` | `"Extract one knowledge point per distinct incident. Do not merge incidents."` |
| `runbook` | `"Extract 3–8 high-level operational procedure KPs. Do not split individual command steps into separate KPs."` |
| `guideline` | `"Extract one knowledge point per rule or principle. Do not sub-divide within a single rule."` |
| `non_kb` | N/A — pipeline rejects before Reader |
