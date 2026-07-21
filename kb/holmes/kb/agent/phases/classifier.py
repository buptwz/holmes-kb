"""DocumentClassifier — classify source document type for import pipeline (042).

Single LLM call to determine document type, suggested KB type, language,
and multi-topic detection. Never raises — returns a safe default on failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from holmes.kb.agent.observability import observe
from holmes.kb.agent.outline import extract_document_outline, format_outline_for_prompt
from holmes.kb.agent.prompts.classifier_prompts import _CLASSIFIER_SYSTEM_PROMPT
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

    @observe(name="classifier")
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
        total_chars = len(source_text)

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

        # T032: for truncated documents, attach the FULL-document outline so
        # the LLM sees the whole structure and emits topic_boundaries in
        # full-document coordinates (previously boundaries were guessed from
        # the 8K snippet but applied to the full text).
        if total_chars > len(snippet):
            outline = extract_document_outline(source_text)
            outline_block = format_outline_for_prompt(outline, total_chars)
            doc_block = (
                f"{outline_block}\n"
                f"NOTE: The document is {total_chars} chars; below is only the "
                f"first {len(snippet)} chars. The outline above covers the FULL "
                f"document — its char offsets are absolute positions in the full "
                f"document. Base type / branch / multi-topic judgments on BOTH "
                f"the excerpt and the outline.\n\n"
                f"Document excerpt:\n\n{snippet}"
            )
        else:
            doc_block = f"Document:\n\n{snippet}"

        messages = [{"role": "user", "content": f"{structure_block}\n{doc_block}"}]

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
