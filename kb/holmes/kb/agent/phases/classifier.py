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

    incident = "incident"                  # Problem-solution pair (simple or complex)
    runbook = "runbook"                    # Sequential operational procedure
    guideline = "guideline"               # Best-practice / standard document
    mixed = "mixed"                        # Multiple knowledge types in one document
    non_kb = "non_kb"                     # No objective reusable knowledge: pure admin/logistics/OKR content

    # Legacy aliases — kept for backward compatibility with existing tests/code
    single_incident = "incident"
    multi_incident = "incident"


class DiagnosticComplexity(Enum):
    """Complexity of diagnostic content — drives DAG vs Classic routing."""

    simple = "simple"             # Linear: one problem, one solution path
    complex_branching = "complex"  # Multi-branch diagnostic tree (≥2 decision points)


# Granularity hint injected into ReaderAgent system prompt per document type.
GRANULARITY_HINTS: dict[DocumentType, str] = {
    DocumentType.incident: "",
    DocumentType.runbook: (
        "Extract 3-8 high-level operational procedure KPs. "
        "Do not split individual command steps into separate KPs."
    ),
    DocumentType.guideline: (
        "Extract one knowledge point per rule or principle. "
        "Do not sub-divide within a single rule."
    ),
    DocumentType.mixed: (
        "This document contains multiple knowledge types. "
        "Extract each knowledge point with its correct type_hint."
    ),
    DocumentType.non_kb: "",
}

_DEFAULT_RESULT_ARGS = {
    "doc_type": DocumentType.incident,
    "reason": "classification failed — default",
    "granularity_hint": "",
    "complexity": DiagnosticComplexity.simple,
}

_CLASSIFIER_SYSTEM_PROMPT = """\
## Role

You are a document classifier for a technical knowledge base import pipeline.
Classify the document by type and diagnostic complexity.

## Task

Read the document and output exactly one JSON object — no markdown, no explanation.

## Constraints

- DO classify by content knowledge value, not by document format or title.
- DO NOT classify as non_kb unless the document contains zero objective, reusable
  technical knowledge. A meeting note describing a real incident is NOT non_kb.

## Type Definitions

| type | classify when the document… |
|------|-----------------------------|
| incident | describes one or more incidents, failures, bugs, or problem-solution pairs |
| runbook | provides a step-by-step operational procedure, playbook, or how-to |
| guideline | states best-practice rules, standards, principles, or design decisions |
| mixed | contains multiple knowledge types that don't fit a single category above |
| non_kb | contains NO objective reusable knowledge — pure logistics, scheduling, OKR scores, personal preferences, org charts with no technical content |

**Distinguishing similar types**

| situation | correct type |
|-----------|-------------|
| Doc describes a failure event with symptoms + fix | incident |
| Doc describes multiple distinct failures in one document | incident |
| Doc lists "how to do X in N steps" | runbook |
| Doc states "you SHOULD do X because Y" | guideline |
| Doc records a technology selection rationale | guideline |
| Doc contains an incident report + best-practice guidelines + architecture decisions | mixed |
| Doc is a meeting agenda with no technical content | non_kb |

## Complexity (evaluate ONLY when type=incident)

| complexity | characteristics |
|------------|----------------|
| simple | One problem, one solution path, no branching decisions |
| complex | ≥2 independent decision points, each leading to different diagnostic/action branches |

Examples:
- "Redis connection pool exhausted → increase max_connections" → simple
- "API timeout → check network or server? Network: DNS/routing/firewall. Server: load/GC/DB" → complex

When unsure, choose simple. The DAG pipeline is expensive — use only when certain.

## Output Format

```json
{"doc_type": "<type>", "complexity": "<simple|complex>", "reason": "<≤80 char rationale>"}
```
"""


@dataclass
class ClassificationResult:
    """Result of a DocumentClassifier.classify() call."""

    doc_type: DocumentType
    reason: str
    granularity_hint: str
    complexity: DiagnosticComplexity = DiagnosticComplexity.simple

    @property
    def needs_dag(self) -> bool:
        """True when the document should be routed to the DAG pipeline."""
        return (
            self.doc_type == DocumentType.incident
            and self.complexity == DiagnosticComplexity.complex_branching
        )


class DocumentClassifier:
    """Classify a source document type before the Reader phase (018 Root D).

    A single LLM call determines the document type. On any failure the default
    (incident/simple) is returned so the pipeline continues normally.
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
        snippet = source_text[:8000]
        messages = [{"role": "user", "content": f"Document:\n\n{snippet}"}]

        _, _, updated, _ = self._provider.complete(
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
        doc_type_str = str(data.get("doc_type", "incident"))
        reason = str(data.get("reason", ""))[:100]

        # Map legacy type names to new enum values.
        _LEGACY_MAP = {
            "single_incident": "incident",
            "multi_incident": "incident",
        }
        doc_type_str = _LEGACY_MAP.get(doc_type_str, doc_type_str)

        try:
            doc_type = DocumentType(doc_type_str)
        except ValueError:
            doc_type = DocumentType.incident

        # Parse complexity (only meaningful for incident).
        complexity_str = str(data.get("complexity", "simple"))
        try:
            complexity = DiagnosticComplexity(complexity_str)
        except ValueError:
            complexity = DiagnosticComplexity.simple

        granularity_hint = GRANULARITY_HINTS.get(doc_type, "")
        return ClassificationResult(
            doc_type=doc_type,
            complexity=complexity,
            reason=reason,
            granularity_hint=granularity_hint,
        )
