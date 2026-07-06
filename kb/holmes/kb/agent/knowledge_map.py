"""KnowledgeMap — structured knowledge summary handoff across pipeline phases.

KnowledgeMap encodes the structured knowledge identified by Reader and enriched
by Summarizer. It is the central artifact flowing through the pipeline:
  Reader (identify) → Summarizer (enrich) → Review → Generator (format).

Entities:
    KnowledgePoint  — one discrete unit of knowledge with structured summary.
    KnowledgeMap    — ordered collection of knowledge points + reading statistics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

_VALID_TYPES = frozenset({"pitfall", "model", "guideline", "process", "decision"})


@dataclass
class KnowledgePoint:
    """A single discrete unit of knowledge identified by Reader, enriched by Summarizer.

    Reader populates: id, description, section_start/end, type_hint, category_hint, language.
    Summarizer populates: key_facts, commands, related_kps (the structured summary).
    Generator consumes the full KP to produce the final KB entry.

    Attributes:
        id: Stable identifier within the KnowledgeMap (e.g. "kp-1").
        description: One-sentence summary of what this knowledge point is about.
        section_start: Start character offset in the original source text (inclusive).
        section_end: End character offset in the original source text (exclusive).
        type_hint: Reader's best-guess KB type.
        category_hint: Reader's best-guess category.
        language: Detected language ISO 639-1 code (e.g. "zh", "en").
        extracted: True after Generator has successfully processed this KP.
        parent_kp: Optional parent KP id for tree relationships.
        confidence: LLM self-assessed confidence (0.0-1.0).
        key_facts: Key facts extracted by Summarizer (each a standalone statement).
        commands: Commands/code/config extracted verbatim by Summarizer.
        related_kps: IDs of related KPs (prerequisite, follow-up, complement).
        summarized: True after Summarizer has enriched this KP.
    """

    id: str
    description: str
    section_start: int
    section_end: int
    type_hint: str = "pitfall"
    category_hint: str = ""
    language: str = "en"
    extracted: bool = False
    parent_kp: Optional[str] = None
    confidence: float = 1.0
    key_facts: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    related_kps: list[str] = field(default_factory=list)
    summarized: bool = False

    def __post_init__(self) -> None:
        if self.section_end <= self.section_start:
            raise ValueError(
                f"KnowledgePoint {self.id}: section_end ({self.section_end}) "
                f"must be > section_start ({self.section_start})"
            )
        if self.type_hint not in _VALID_TYPES:
            raise ValueError(
                f"KnowledgePoint {self.id}: type_hint must be one of {_VALID_TYPES}, "
                f"got {self.type_hint!r}"
            )

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "description": self.description,
            "section_start": self.section_start,
            "section_end": self.section_end,
            "type_hint": self.type_hint,
            "category_hint": self.category_hint,
            "language": self.language,
            "extracted": self.extracted,
        }
        if self.parent_kp is not None:
            d["parent_kp"] = self.parent_kp
        if self.confidence != 1.0:
            d["confidence"] = self.confidence
        if self.key_facts:
            d["key_facts"] = self.key_facts
        if self.commands:
            d["commands"] = self.commands
        if self.related_kps:
            d["related_kps"] = self.related_kps
        if self.summarized:
            d["summarized"] = self.summarized
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgePoint":
        return cls(
            id=str(data["id"]),
            description=str(data.get("description", "")),
            section_start=int(data["section_start"]),
            section_end=int(data["section_end"]),
            type_hint=str(data.get("type_hint", "pitfall")),
            category_hint=str(data.get("category_hint", "")),
            language=str(data.get("language", "en")),
            extracted=bool(data.get("extracted", False)),
            parent_kp=data.get("parent_kp"),
            confidence=float(data.get("confidence", 1.0)),
            key_facts=list(data.get("key_facts", [])),
            commands=list(data.get("commands", [])),
            related_kps=list(data.get("related_kps", [])),
            summarized=bool(data.get("summarized", False)),
        )


@dataclass
class KnowledgeMap:
    """Structured summary of all knowledge points found in a source document.

    Produced by Reader, enriched by Summarizer, consumed by Generator.
    Serves as the central artifact flowing through the pipeline.

    Attributes:
        knowledge_points: Ordered list of identified knowledge points.
        total_chars: Total character count of the source document.
        chars_read: Characters processed by the Reader (≤ total_chars).
        diminishing_returns: True when Reader stopped early due to no new KPs.
        reading_passes: Number of reading passes the Reader performed.
    """

    knowledge_points: list[KnowledgePoint] = field(default_factory=list)
    total_chars: int = 0
    chars_read: int = 0
    diminishing_returns: bool = False
    reading_passes: int = 0

    @property
    def coverage_pct(self) -> float:
        """Percentage of document characters read (0.0–100.0)."""
        if self.total_chars <= 0:
            return 100.0
        return min(100.0, round(self.chars_read / self.total_chars * 100, 1))

    @property
    def unextracted(self) -> list[KnowledgePoint]:
        """Knowledge points not yet processed by the Extractor."""
        return [kp for kp in self.knowledge_points if not kp.extracted]

    def get_by_id(self, kp_id: str) -> Optional[KnowledgePoint]:
        """Return the KnowledgePoint with the given id, or None."""
        for kp in self.knowledge_points:
            if kp.id == kp_id:
                return kp
        return None

    def validate(self) -> None:
        """Raise ValueError if invariants are violated."""
        seen_ids: set[str] = set()
        for kp in self.knowledge_points:
            if kp.id in seen_ids:
                raise ValueError(f"Duplicate KnowledgePoint id: {kp.id!r}")
            seen_ids.add(kp.id)

    def to_dict(self) -> dict:
        return {
            "$schema": "holmes-km-v1",
            "knowledge_points": [kp.to_dict() for kp in self.knowledge_points],
            "total_chars": self.total_chars,
            "chars_read": self.chars_read,
            "coverage_pct": self.coverage_pct,
            "diminishing_returns": self.diminishing_returns,
            "reading_passes": self.reading_passes,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeMap":
        kps = [KnowledgePoint.from_dict(kp) for kp in data.get("knowledge_points", [])]
        km = cls(
            knowledge_points=kps,
            total_chars=int(data.get("total_chars", 0)),
            chars_read=int(data.get("chars_read", 0)),
            diminishing_returns=bool(data.get("diminishing_returns", False)),
            reading_passes=int(data.get("reading_passes", 0)),
        )
        km.validate()
        return km

    @classmethod
    def from_json(cls, text: str) -> "KnowledgeMap":
        return cls.from_dict(json.loads(text))
