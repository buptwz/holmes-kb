"""Unit tests for SemanticDeduplicator (T018 [US3]).

Tests the three dedup outcomes:
  - SKIP: exact source_hash match
  - MERGE: LLM confirms same root cause
  - NEW_WITH_LINK: LLM finds different root cause
  - CREATE: no candidates in category
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestSemanticDedup:
    """T018: SemanticDeduplicator returns correct DeduResult based on LLM response."""

    def _make_llm_response(self, same_root_cause: bool, confidence: float = 0.9) -> MagicMock:
        block = MagicMock()
        block.text = json.dumps({
            "same_root_cause": same_root_cause,
            "confidence": confidence,
            "reason": "test reason",
        })
        resp = MagicMock()
        resp.content = [block]
        return resp

    def test_same_root_cause_returns_merge(self, tmp_path: Path):
        """T018a: LLM returns same_root_cause=true → DeduResult.MERGE with entry_id."""
        from holmes.kb.agent.dedup import DeduResult, DeduResultKind, SemanticDeduplicator

        kb_root = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending"):
            (kb_root / d).mkdir(parents=True, exist_ok=True)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._make_llm_response(True, 0.92)

        dedup = SemanticDeduplicator(kb_root=kb_root, client=mock_client, model="test")

        # Inject a fake candidate entry into the dedup candidates list.
        with pytest.MonkeyPatch().context() as m:
            m.setattr(
                "holmes.kb.agent.dedup.SemanticDeduplicator._load_candidates",
                lambda self_arg, kb_type, category: [
                    {
                        "id": "PT-DB-001",
                        "title": "PostgreSQL OOM",
                        "source_hash": "differenthash0001",
                        "root_cause_preview": "shared_buffers set too high",
                    }
                ],
            )
            result = dedup.check(
                source_hash="newhash000000001",
                new_summary="shared_buffers too large causing OOM",
                kb_type="pitfall",
                category="database",
            )

        assert result.kind == DeduResultKind.MERGE
        assert result.entry_id == "PT-DB-001"

    def test_different_root_cause_returns_new_with_link(self, tmp_path: Path):
        """T018b: LLM returns same_root_cause=false → DeduResult.NEW_WITH_LINK."""
        from holmes.kb.agent.dedup import DeduResult, DeduResultKind, SemanticDeduplicator

        kb_root = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending"):
            (kb_root / d).mkdir(parents=True, exist_ok=True)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._make_llm_response(False, 0.85)

        dedup = SemanticDeduplicator(kb_root=kb_root, client=mock_client, model="test")

        with pytest.MonkeyPatch().context() as m:
            m.setattr(
                "holmes.kb.agent.dedup.SemanticDeduplicator._load_candidates",
                lambda self_arg, kb_type, category: [
                    {
                        "id": "PT-DB-001",
                        "title": "PostgreSQL OOM",
                        "source_hash": "differenthash0001",
                        "root_cause_preview": "connection pool exhausted",
                    }
                ],
            )
            result = dedup.check(
                source_hash="newhash000000001",
                new_summary="WAL corruption on disk failure",
                kb_type="pitfall",
                category="database",
            )

        assert result.kind == DeduResultKind.NEW_WITH_LINK
        assert result.entry_id == "PT-DB-001"

    def test_no_candidates_returns_create(self, tmp_path: Path):
        """T018c: no candidates in category → DeduResult.CREATE."""
        from holmes.kb.agent.dedup import DeduResultKind, SemanticDeduplicator

        kb_root = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending"):
            (kb_root / d).mkdir(parents=True, exist_ok=True)

        mock_client = MagicMock()

        dedup = SemanticDeduplicator(kb_root=kb_root, client=mock_client, model="test")

        with pytest.MonkeyPatch().context() as m:
            m.setattr(
                "holmes.kb.agent.dedup.SemanticDeduplicator._load_candidates",
                lambda self_arg, kb_type, category: [],
            )
            result = dedup.check(
                source_hash="newhash000000002",
                new_summary="brand new kind of failure",
                kb_type="pitfall",
                category="network",
            )

        assert result.kind == DeduResultKind.CREATE
        assert result.entry_id is None
        # No LLM call needed when there are no candidates.
        mock_client.messages.create.assert_not_called()
