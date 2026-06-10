"""Semantic deduplication for KB import (US3 / FR-008, FR-009).

SemanticDeduplicator implements the three-way dedup logic:
  - SKIP: exact source_hash match (idempotency, FR-007/FR-008)
  - MERGE: same root cause semantically (LLM judgment, FR-009)
  - NEW_WITH_LINK: different root cause but related topic
  - CREATE: no similar entries found in category

LLM semantic judgment is used for root-cause comparison (research.md R-005),
not keyword matching.  No vector database is required.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import frontmatter as fm

from holmes.kb.store import list_entries


class DeduResultKind(Enum):
    """Outcome of a single deduplication check."""

    SKIP = "skip"              # Exact source_hash match → do nothing
    MERGE = "merge"            # Same root cause → update existing entry
    NEW_WITH_LINK = "new_with_link"   # Different root cause → new + link both ways
    CREATE = "create"          # No similar entries → create fresh


@dataclass
class DeduResult:
    """Result of SemanticDeduplicator.check().

    Attributes:
        kind: The dedup decision.
        entry_id: ID of the matched entry (None for CREATE).
        confidence: Confidence of the root-cause comparison (0.0–1.0).
        reason: Brief LLM explanation.
    """

    kind: DeduResultKind
    entry_id: Optional[str] = None
    confidence: float = 1.0
    reason: str = ""


class SemanticDeduplicator:
    """Check for exact and semantic duplicates before writing a new KB entry.

    Args:
        kb_root: Root directory of the knowledge base.
        client: Anthropic client instance (for LLM root-cause comparison).
        model: Model name for LLM calls.
    """

    def __init__(self, kb_root: Path, client: Any, model: str) -> None:
        self._kb_root = kb_root
        self._client = client
        self._model = model

    def check(
        self,
        source_hash: str,
        new_summary: str,
        kb_type: str,
        category: Optional[str] = None,
    ) -> DeduResult:
        """Run the full dedup pipeline for a new entry.

        1. Scan all existing entries for an exact source_hash match → SKIP.
        2. Load same-category candidates.
        3. For each candidate, use LLM to compare root causes.
           - First MERGE candidate found → MERGE.
           - Otherwise → NEW_WITH_LINK to the most similar candidate.
        4. If no candidates → CREATE.

        Args:
            source_hash: 16-char hash of the import source text.
            new_summary: Root cause / summary text of the new entry.
            kb_type: KB type (e.g., "pitfall").
            category: Category filter (e.g., "database").

        Returns:
            DeduResult with the dedup decision and matched entry_id.
        """
        # Step 1: exact hash match → immediate SKIP.
        exact_match = self._find_by_hash(source_hash)
        if exact_match:
            return DeduResult(
                kind=DeduResultKind.SKIP,
                entry_id=exact_match,
                confidence=1.0,
                reason="Exact source_hash match",
            )

        # Step 2: load same-category candidates.
        candidates = self._load_candidates(kb_type, category)
        if not candidates:
            return DeduResult(kind=DeduResultKind.CREATE)

        # Step 3: semantic root-cause comparison via LLM.
        best_candidate_id: Optional[str] = None
        best_confidence = 0.0
        best_reason = ""

        for candidate in candidates[:10]:  # cap at 10 to limit LLM calls
            result = self._compare_root_cause(new_summary, candidate)
            if result.get("same_root_cause"):
                return DeduResult(
                    kind=DeduResultKind.MERGE,
                    entry_id=candidate["id"],
                    confidence=float(result.get("confidence", 0.8)),
                    reason=result.get("reason", ""),
                )
            conf = float(result.get("confidence", 0.0))
            if conf > best_confidence:
                best_confidence = conf
                best_candidate_id = candidate["id"]
                best_reason = result.get("reason", "")

        # No exact semantic match — new entry but link to most similar.
        if best_candidate_id and best_confidence > 0.4:
            return DeduResult(
                kind=DeduResultKind.NEW_WITH_LINK,
                entry_id=best_candidate_id,
                confidence=best_confidence,
                reason=best_reason,
            )

        return DeduResult(kind=DeduResultKind.CREATE)

    def _find_by_hash(self, source_hash: str) -> Optional[str]:
        """Return entry_id if any existing entry has a matching source_hash."""
        for entry in list_entries(self._kb_root):
            file_path = Path(entry.file_path)
            if not file_path.exists():
                continue
            try:
                post = fm.load(str(file_path))
                if str(post.metadata.get("source_hash", "")) == source_hash:
                    return entry.id
            except Exception:  # noqa: BLE001
                pass
        return None

    def _load_candidates(
        self, kb_type: str, category: Optional[str]
    ) -> list[dict[str, Any]]:
        """Return lightweight candidate dicts for semantic comparison."""
        entries = list_entries(
            self._kb_root, kb_type=kb_type or None, category=category
        )
        candidates = []
        for meta in entries[:20]:  # limit scan
            file_path = Path(meta.file_path)
            root_cause_preview = ""
            if file_path.exists():
                try:
                    post = fm.load(str(file_path))
                    import re
                    body = post.content or ""
                    m = re.search(r"## Root Cause\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL)
                    if m:
                        root_cause_preview = m.group(1).strip()[:300]
                except Exception:  # noqa: BLE001
                    pass
            candidates.append({
                "id": meta.id,
                "title": meta.title,
                "root_cause_preview": root_cause_preview,
            })
        return candidates

    def _compare_root_cause(
        self, new_summary: str, candidate: dict[str, Any]
    ) -> dict[str, Any]:
        """Use LLM to compare new entry's root cause with a candidate."""
        system_prompt = (
            "You are comparing two KB entries to determine if they describe the same "
            "root cause. Same root cause = same fundamental technical problem, even if "
            "symptoms or resolution differ. Reply ONLY with valid JSON:\n"
            '{"same_root_cause": true/false, "confidence": 0.0-1.0, "reason": "..."}'
        )
        user_prompt = (
            f"Entry A (new):\n{new_summary}\n\n"
            f"Entry B (existing — {candidate['id']}):\n"
            f"{candidate.get('root_cause_preview', candidate.get('title', ''))}"
        )

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=256,
                messages=[
                    {"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"},
                ],
            )
            text = response.content[0].text.strip()
            return json.loads(text)
        except Exception:  # noqa: BLE001
            return {"same_root_cause": False, "confidence": 0.0, "reason": "LLM error"}
