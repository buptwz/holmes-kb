"""DocumentClassifier — classify source document type for import pipeline (042).

Single LLM call to determine document type, suggested KB type, language,
and multi-topic detection. Never raises — returns a safe default on failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.progress import NullReporter, ProgressReporter

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class DocumentType(Enum):
    """Classification of a source document for import pipeline routing."""

    incident = "incident"
    runbook = "runbook"
    guideline = "guideline"
    mixed = "mixed"
    non_kb = "non_kb"

    # Legacy aliases — kept for backward compatibility with existing tests/code
    single_incident = "incident"
    multi_incident = "incident"


@dataclass
class ClassificationResult:
    """Result of a DocumentClassifier.classify() call."""

    doc_type: DocumentType
    reason: str
    suggested_type: str = "pitfall"
    language: str = "en"
    is_multi_topic: bool = False
    topic_boundaries: list[int] = field(default_factory=list)
    has_complex_branching: bool = False  # ≥3 distinct resolution paths
    branch_count: int = 0  # estimated number of resolution branches
    # Backward compat stubs (removed in 042)
    complexity: Any = None
    granularity_hint: str = ""

    @property
    def needs_dag(self) -> bool:
        """Always False — DAG routing removed in 042."""
        return False


_DEFAULT_RESULT = ClassificationResult(
    doc_type=DocumentType.incident,
    reason="classification failed — default",
    suggested_type="pitfall",
    language="en",
)


# Map doc_type → default suggested KB type
_DOC_TYPE_TO_KB_TYPE = {
    "incident": "pitfall",
    "runbook": "process",
    "guideline": "guideline",
    "mixed": "pitfall",
    "non_kb": "pitfall",
}


# ---------------------------------------------------------------------------
# Backward compatibility stubs (removed in 042, kept for test imports)
# ---------------------------------------------------------------------------


class DiagnosticComplexity:
    """Stub — DAG routing removed in 042."""

    simple = "simple"
    complex_branching = "complex"

    def __init__(self, value: str = "simple") -> None:
        self.value = value


GRANULARITY_HINTS: dict = {}


def _extract_assistant_text(messages: list) -> str:
    """Extract text from the last assistant message, handling both str and list content."""
    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            texts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "\n".join(t for t in texts if t).strip()
    return ""


def _try_json(text: str) -> dict | None:
    """Try to parse text as a JSON dict. Returns None on failure."""
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


_CLASSIFIER_SYSTEM_PROMPT = """\
You classify technical documents for a knowledge base used by NPI (New Product \
Introduction) hardware engineers. Your output directly controls how the document \
is stored and presented — accuracy matters.

# Output

Exactly one JSON object. No markdown fences. No explanation.

```
{"doc_type":"...","suggested_type":"...","language":"...","is_multi_topic":false,"topic_boundaries":[],"branch_count":0,"reason":"..."}
```

# Classification procedure

Follow these steps IN ORDER. Stop at the first match.

## Step 1 — Reject non-knowledge documents

Set `doc_type = "non_kb"` and `suggested_type = "pitfall"` ONLY when the document \
contains zero reusable technical knowledge (meeting logistics, OKR, sprint planning, \
personal notes). A meeting note that describes a real technical incident IS knowledge.

## Step 2 — Determine `suggested_type` (most important field)

Ask these questions about the document's PRIMARY PURPOSE:

| Question | If YES → suggested_type |
|----------|------------------------|
| Does it describe a **specific failure** that happened, its root cause, and how to fix it? | `pitfall` |
| Does it define a **step-by-step procedure** someone should follow to complete an operation? | `process` |
| Does it state **rules, standards, or best practices** that people must follow? | `guideline` |
| Does it **explain a concept, mechanism, or technology** for reference? | `model` |
| Does it document a **choice between alternatives** with trade-off analysis? | `decision` |

### Disambiguation rules

These rules resolve ambiguity when a document seems to match multiple types:

- A document that has **"Option A / Option B / Option C" or "we chose X because"** \
  → `decision`, NOT pitfall. Decisions compare alternatives; pitfalls diagnose failures.
- A document that **explains how something works** (mechanisms, architecture, theory) \
  without describing a specific failure event → `model`, NOT pitfall.
- A document that lists **"must / should / 不允许 / 规范"** rules to follow \
  → `guideline`, NOT pitfall. Guidelines prescribe behavior; pitfalls react to failures.
- A document with **"Step 1, Step 2, Step 3" or "Prerequisites → Steps → Outcome"** \
  describing an operational procedure → `process`, NOT pitfall.
- **Structure analysis rule**: If the programmatic analysis shows ordered_steps ≥ 5 \
  AND step_ratio > 0.15, the document is almost certainly a `process`. The presence \
  of failure/symptom keywords does NOT override this — a process can describe what \
  goes wrong (e.g., "if BMC is bricked") while still being a procedure, not a pitfall.
- The presence of **commands or code snippets does NOT make it a pitfall**. Processes, \
  guidelines, and models can all contain commands.
- `pitfall` requires ALL THREE: (1) a specific failure event, (2) a root cause, \
  (3) a resolution or workaround. If any is missing, it is probably another type.

## Step 3 — Determine `doc_type`

| doc_type | maps from suggested_type |
|----------|--------------------------|
| `incident` | pitfall |
| `runbook` | process |
| `guideline` | guideline, decision, model |
| `mixed` | document contains multiple unrelated knowledge types |

## Step 4 — Detect language

Look at the prose in the document body (ignore code, commands, and English \
technical terms in otherwise-Chinese text):
- Majority Chinese characters → `"zh"`
- Majority English → `"en"`
- Other → ISO 639-1 code

## Step 5 — Multi-topic detection

Set `is_multi_topic = true` ONLY when the document contains multiple **unrelated** \
topics (e.g., a wiki page listing 10 different incidents). Provide `topic_boundaries` \
as character offsets where topics change.

A single incident with multiple resolution branches is NOT multi-topic. \
A document covering related sub-topics (e.g., 3 thermal mechanisms) is NOT multi-topic.

## Step 6 — Branch count estimation

Count the number of distinct resolution/diagnostic paths in the document. \
Look for patterns like "路径 A / 路径 B", "If X → do A; if Y → do B", \
"Case 1 / Case 2", "分支", conditional branches, or multiple ### subsections \
under a Resolution/Steps section.

Set `branch_count` to the number of distinct paths (0 if linear/no branching). \
Documents with branch_count ≥ 3 are considered complex and will get a Diagnostic \
Flow navigation diagram in the generated KB entry.

# Examples

Document: "GPU 初始化失败的排查...症状：lspci 无法识别...根因：金手指氧化...解决：重新插拔"
→ `{"doc_type":"incident","suggested_type":"pitfall","language":"zh",...}`

Document: "BMC 固件升级标准操作流程...前置条件...Step 1: 健康检查...Step 6: 签收"
→ `{"doc_type":"runbook","suggested_type":"process","language":"zh",...}`

Document: "ESD 防护操作规范...核心规则：必须佩戴防静电腕带...不允许裸手接触..."
→ `{"doc_type":"guideline","suggested_type":"guideline","language":"zh",...}`

Document: "Thermal Throttling Mechanisms...PROCHOT is a signal that...RAPL enforces..."
→ `{"doc_type":"guideline","suggested_type":"model","language":"en",...}`

Document: "Decision: Default PCIe Speed...Option A: Gen5...Option B: Gen4...We chose C"
→ `{"doc_type":"guideline","suggested_type":"decision","language":"en",...}`

# reason

≤80 characters explaining WHY you chose this suggested_type. Reference the key signal.
"""


def analyze_document_structure(source: str) -> dict[str, Any]:
    """Zero-LLM structural analysis — count patterns that distinguish types.

    Injected into the Classifier prompt so the LLM has quantitative signals,
    not just prose interpretation.
    """
    import re

    lines = source.splitlines()
    content_lines = [l for l in lines if l.strip() and not l.strip().startswith("#")]
    total_content = max(len(content_lines), 1)

    # Ordered steps: "1. ...", "Step 1:", "### Step N"
    numbered = len(re.findall(r"^\s*\d+\.\s", source, re.MULTILINE))
    h3_steps = len(re.findall(r"^###?\s+(Step|步骤)\s*\d+", source, re.MULTILINE | re.IGNORECASE))
    ordered_steps = numbered + h3_steps

    # Symptom/failure signals
    symptom_kw = len(re.findall(
        r"(症状|故障|异常|error|fail|crash|重启|宕机|不响应|unreachable|broken)",
        source, re.IGNORECASE,
    ))

    # Decision/option signals
    decision_kw = len(re.findall(
        r"(Option\s+[A-Z]|方案\s*[A-Z一二三]|we\s+chose|选择了|trade-?off|权衡)",
        source, re.IGNORECASE,
    ))

    # Rule/guideline signals
    rule_kw = len(re.findall(
        r"(必须|不允许|禁止|should|must\s+not|规范|规则|best\s+practice)",
        source, re.IGNORECASE,
    ))

    step_ratio = round(ordered_steps / total_content, 2)

    return {
        "ordered_steps": ordered_steps,
        "symptom_mentions": symptom_kw,
        "decision_mentions": decision_kw,
        "rule_mentions": rule_kw,
        "step_ratio": step_ratio,
    }


class DocumentClassifier:
    """Classify a source document type with a single LLM call.

    On any failure the default (incident/pitfall) is returned so the pipeline
    continues normally.
    """

    def __init__(self, provider: LLMProvider, model: str, reporter: ProgressReporter | None = None) -> None:
        self._provider = provider
        self._model = model
        self._reporter: ProgressReporter = reporter or NullReporter()

    def classify(self, source_text: str) -> ClassificationResult:
        """Classify the document type with a single LLM call.

        Args:
            source_text: Full source document text.

        Returns:
            ClassificationResult; never raises.
        """
        # Try up to 2 attempts (initial + 1 retry on parse failure)
        for attempt in range(2):
            try:
                result = self._do_classify(source_text)
                if result.reason and "parse failed" not in result.reason:
                    return result
                # JSON parse failed — retry once
                if attempt == 0:
                    self._reporter.info("Classifier: JSON 解析失败，重试...")
                    continue
                return result
            except Exception as exc:  # noqa: BLE001
                if attempt == 0:
                    self._reporter.warn(f"Classifier exception: {exc}, 重试...")
                    continue
                self._reporter.warn(f"Classifier 重试仍失败: {exc}")
                return ClassificationResult(
                    doc_type=_DEFAULT_RESULT.doc_type,
                    reason=f"exception: {str(exc)[:80]}",
                    suggested_type=_DEFAULT_RESULT.suggested_type,
                    language=_DEFAULT_RESULT.language,
                )
        # Should not reach here, but safety fallback
        return ClassificationResult(
            doc_type=_DEFAULT_RESULT.doc_type,
            reason="max retries",
            suggested_type=_DEFAULT_RESULT.suggested_type,
            language=_DEFAULT_RESULT.language,
        )

    def _do_classify(self, source_text: str) -> ClassificationResult:
        """Perform the actual LLM call and parse the result."""
        snippet = source_text[:8000]

        # Inject programmatic structure analysis so LLM has quantitative signals
        structure = analyze_document_structure(source_text)
        structure_block = (
            f"Document structure analysis (programmatic, not from LLM):\n"
            f"- Ordered steps found: {structure['ordered_steps']}\n"
            f"- Symptom/failure keyword mentions: {structure['symptom_mentions']}\n"
            f"- Decision/option keyword mentions: {structure['decision_mentions']}\n"
            f"- Rule/guideline keyword mentions: {structure['rule_mentions']}\n"
            f"- Step content ratio: {structure['step_ratio']} "
            f"(>0.15 with ≥5 steps strongly suggests process type)\n"
        )

        messages = [{"role": "user", "content": f"{structure_block}\nDocument:\n\n{snippet}"}]

        self._reporter.info("Classifier: LLM 调用中...")
        raw_text = self._provider.simple_complete(
            messages=messages,
            system=_CLASSIFIER_SYSTEM_PROMPT,
            max_tokens=512,
        )

        if not raw_text.strip():
            self._reporter.warn("Classifier: LLM 返回空内容")
            return ClassificationResult(
                doc_type=_DEFAULT_RESULT.doc_type,
                reason=_DEFAULT_RESULT.reason,
                suggested_type=_DEFAULT_RESULT.suggested_type,
                language=_DEFAULT_RESULT.language,
            )

        self._reporter.info(f"Classifier raw: {raw_text[:200]}")
        return self._parse_response(raw_text)

    def _parse_response(self, raw: str) -> ClassificationResult:
        """Parse the JSON response from the LLM.

        Handles: raw JSON, code-fenced JSON, JSON embedded in prose.
        """
        import re

        text = raw.strip()

        # Strategy 1: Direct JSON parse
        data = _try_json(text)

        # Strategy 2: Strip markdown code fences (```json ... ```)
        if data is None:
            fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
            if fence_match:
                data = _try_json(fence_match.group(1).strip())

        # Strategy 3: Find first { ... } block
        if data is None:
            first = text.find("{")
            last = text.rfind("}")
            if first != -1 and last > first:
                data = _try_json(text[first:last + 1])

        if data is None:
            self._reporter.warn(f"Classifier: JSON 解析失败 | raw: {text[:200]}")
            return ClassificationResult(
                doc_type=_DEFAULT_RESULT.doc_type,
                reason="JSON parse failed",
                suggested_type=_DEFAULT_RESULT.suggested_type,
                language=_DEFAULT_RESULT.language,
            )

        doc_type_str = str(data.get("doc_type", "incident"))
        reason = str(data.get("reason", ""))[:100]

        # Map legacy type names.
        _LEGACY_MAP = {
            "single_incident": "incident",
            "multi_incident": "incident",
        }
        doc_type_str = _LEGACY_MAP.get(doc_type_str, doc_type_str)

        try:
            doc_type = DocumentType(doc_type_str)
        except ValueError:
            doc_type = DocumentType.incident

        # Parse suggested KB type.
        suggested_type = str(data.get("suggested_type", ""))
        if suggested_type not in ("pitfall", "model", "guideline", "process", "decision"):
            suggested_type = _DOC_TYPE_TO_KB_TYPE.get(doc_type_str, "pitfall")

        # Parse language.
        language = str(data.get("language", "en")).strip().lower()[:5]
        if not language:
            language = "en"

        # Parse multi-topic.
        is_multi_topic = bool(data.get("is_multi_topic", False))
        topic_boundaries: list[int] = []
        if is_multi_topic:
            raw_bounds = data.get("topic_boundaries", [])
            if isinstance(raw_bounds, list):
                topic_boundaries = [int(b) for b in raw_bounds if isinstance(b, (int, float))]

        # Parse branch count.
        branch_count = 0
        raw_bc = data.get("branch_count")
        if isinstance(raw_bc, (int, float)):
            branch_count = int(raw_bc)

        return ClassificationResult(
            doc_type=doc_type,
            reason=reason,
            suggested_type=suggested_type,
            language=language,
            is_multi_topic=is_multi_topic,
            topic_boundaries=topic_boundaries,
            has_complex_branching=branch_count >= 3,
            branch_count=branch_count,
        )
