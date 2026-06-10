"""DocumentClassifier — pre-Reader document type classification (018 Root D).

Makes a single LLM call to classify the document before the Reader phase.
Provides granularity hints that guide ReaderAgent KP extraction.
Never raises — returns a safe default on any exception or parse failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from holmes.kb.agent.provider.base import LLMProvider

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class DocumentType(Enum):
    """Classification of a source document for import pipeline routing."""

    single_incident = "single_incident"    # One incident/failure event
    multi_incident = "multi_incident"      # Multiple distinct incidents
    runbook = "runbook"                    # Sequential operational procedure
    guideline = "guideline"               # Best-practice / standard document
    non_kb = "non_kb"                     # No objective reusable knowledge: pure admin/logistics/OKR content


# Granularity hint injected into ReaderAgent system prompt per document type.
GRANULARITY_HINTS: dict[DocumentType, str] = {
    DocumentType.single_incident: "",
    DocumentType.multi_incident: (
        "Extract one knowledge point per distinct incident. Do not merge incidents."
    ),
    DocumentType.runbook: (
        "Extract 3–8 high-level operational procedure KPs. "
        "Do not split individual command steps into separate KPs."
    ),
    DocumentType.guideline: (
        "Extract one knowledge point per rule or principle. "
        "Do not sub-divide within a single rule."
    ),
    DocumentType.non_kb: "",
}

_DEFAULT_RESULT_ARGS = {
    "doc_type": DocumentType.single_incident,
    "reason": "classification failed — default",
    "granularity_hint": "",
}

_CLASSIFIER_SYSTEM_PROMPT = """\
You are a document classifier for a technical knowledge base import pipeline.

Classify the document into exactly one of these types:
- single_incident: one incident, failure, or problem-solution pair
- multi_incident: multiple distinct incidents bundled together
- runbook: step-by-step operational procedure or playbook
- guideline: best-practice rules, standards, or design principles
- non_kb: content with NO objective, reusable knowledge — pure administrative/logistics
  content with no facts, insights, root causes, solutions, or procedures that help solve
  real problems (e.g., OKR reviews, meeting scheduling, personal preferences, org charts
  with no technical content)

IMPORTANT: Classify by CONTENT KNOWLEDGE VALUE, not by document format or type label.
A meeting note that describes a real incident and its resolution is NOT non_kb.
A service directory listing technical facts about services is NOT non_kb.
Only classify as non_kb when the document contains no objective reusable technical knowledge.

Examples:
- Meeting note recording a Redis OOM incident, root cause, and fix → single_incident (has knowledge)
- Service catalog listing API endpoints, owners, SLAs → guideline (has objective facts)
- Weekly team meeting logistics: attendees, next week schedule, action items only → non_kb
- OKR review doc: goals, scores, personal growth plans → non_kb
- Post-mortem with timeline, root cause, and prevention steps → single_incident

Respond with ONLY valid JSON, no markdown, no explanation:
{"doc_type": "<type>", "reason": "<≤80 char rationale>"}
"""


@dataclass
class ClassificationResult:
    """Result of a DocumentClassifier.classify() call."""

    doc_type: DocumentType
    reason: str
    granularity_hint: str


class DocumentClassifier:
    """Classify a source document type before the Reader phase (018 Root D).

    A single LLM call determines the document type. On any failure the default
    (single_incident) is returned so the pipeline continues normally.
    """

    def __init__(self, provider: LLMProvider, model: str) -> None:
        self._provider = provider
        self._model = model

    def classify(self, source_text: str) -> ClassificationResult:
        """Classify the document type with a single LLM call.

        Args:
            source_text: Full source document text.

        Returns:
            ClassificationResult; never raises.
        """
        try:
            return self._do_classify(source_text)
        except Exception:  # noqa: BLE001
            return ClassificationResult(**_DEFAULT_RESULT_ARGS)

    def _do_classify(self, source_text: str) -> ClassificationResult:
        """Perform the actual LLM call and parse the result."""
        # Truncate very large docs for the classifier call (cheap check).
        snippet = source_text[:4000]
        messages = [{"role": "user", "content": f"Document:\n\n{snippet}"}]

        _, _, updated = self._provider.complete(
            messages=messages,
            system=_CLASSIFIER_SYSTEM_PROMPT,
            model=self._model,
            max_tokens=128,
            tools=[],
        )

        # Extract text from the assistant's last message.
        raw_text = ""
        for msg in reversed(updated):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                raw_text = str(msg.get("content", "") or "")
                break

        if not raw_text.strip():
            return ClassificationResult(**_DEFAULT_RESULT_ARGS)

        return self._parse_response(raw_text)

    def _parse_response(self, raw: str) -> ClassificationResult:
        """Parse the JSON response from the LLM."""
        # Strip markdown code fences if present.
        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:])
            raw = raw.rstrip("`").strip()

        data = json.loads(raw)
        doc_type_str = str(data.get("doc_type", "single_incident"))
        reason = str(data.get("reason", ""))[:100]

        try:
            doc_type = DocumentType(doc_type_str)
        except ValueError:
            doc_type = DocumentType.single_incident

        granularity_hint = GRANULARITY_HINTS.get(doc_type, "")
        return ClassificationResult(
            doc_type=doc_type,
            reason=reason,
            granularity_hint=granularity_hint,
        )
