"""Unit tests for KnowledgeMap and KnowledgePoint (T008)."""

from __future__ import annotations

import json

import pytest

from holmes.kb.agent.knowledge_map import KnowledgeMap, KnowledgePoint


# ---------------------------------------------------------------------------
# KnowledgePoint
# ---------------------------------------------------------------------------


class TestKnowledgePoint:
    def test_basic_creation(self):
        kp = KnowledgePoint(id="kp-1", description="Redis OOM", section_start=0, section_end=500)
        assert kp.id == "kp-1"
        assert kp.type_hint == "pitfall"
        assert kp.language == "en"
        assert kp.extracted is False

    def test_section_end_must_be_gt_start(self):
        with pytest.raises(ValueError, match="section_end"):
            KnowledgePoint(id="kp-1", description="x", section_start=100, section_end=100)

    def test_section_end_less_than_start_raises(self):
        with pytest.raises(ValueError, match="section_end"):
            KnowledgePoint(id="kp-1", description="x", section_start=200, section_end=50)

    def test_invalid_type_hint_raises(self):
        with pytest.raises(ValueError, match="type_hint"):
            KnowledgePoint(id="kp-1", description="x", section_start=0, section_end=10, type_hint="invalid")

    def test_all_valid_type_hints(self):
        for t in ("pitfall", "model", "guideline", "process", "decision"):
            kp = KnowledgePoint(id="kp-1", description="x", section_start=0, section_end=1, type_hint=t)
            assert kp.type_hint == t

    def test_to_dict_round_trip(self):
        kp = KnowledgePoint(
            id="kp-2",
            description="MySQL slow query",
            section_start=100,
            section_end=800,
            type_hint="pitfall",
            category_hint="database",
            language="zh",
            extracted=True,
        )
        d = kp.to_dict()
        assert d["id"] == "kp-2"
        assert d["extracted"] is True
        assert d["language"] == "zh"

        restored = KnowledgePoint.from_dict(d)
        assert restored.id == kp.id
        assert restored.description == kp.description
        assert restored.section_start == kp.section_start
        assert restored.section_end == kp.section_end
        assert restored.type_hint == kp.type_hint
        assert restored.category_hint == kp.category_hint
        assert restored.language == kp.language
        assert restored.extracted == kp.extracted

    def test_extracted_state_transition(self):
        kp = KnowledgePoint(id="kp-1", description="x", section_start=0, section_end=10)
        assert kp.extracted is False
        kp.extracted = True
        assert kp.extracted is True


# ---------------------------------------------------------------------------
# KnowledgeMap
# ---------------------------------------------------------------------------


class TestKnowledgeMap:
    def _make_km(self) -> KnowledgeMap:
        kps = [
            KnowledgePoint(id="kp-1", description="Redis OOM", section_start=0, section_end=300),
            KnowledgePoint(id="kp-2", description="MySQL slow", section_start=400, section_end=900),
        ]
        return KnowledgeMap(
            knowledge_points=kps,
            total_chars=1000,
            chars_read=900,
            reading_passes=2,
        )

    def test_coverage_pct(self):
        km = self._make_km()
        assert km.coverage_pct == 90.0

    def test_coverage_pct_empty(self):
        km = KnowledgeMap(total_chars=0)
        assert km.coverage_pct == 100.0

    def test_unextracted(self):
        km = self._make_km()
        assert len(km.unextracted) == 2
        km.knowledge_points[0].extracted = True
        assert len(km.unextracted) == 1
        assert km.unextracted[0].id == "kp-2"

    def test_get_by_id(self):
        km = self._make_km()
        kp = km.get_by_id("kp-2")
        assert kp is not None
        assert kp.description == "MySQL slow"

    def test_get_by_id_missing(self):
        km = self._make_km()
        assert km.get_by_id("kp-99") is None

    def test_validate_duplicate_ids(self):
        kp1 = KnowledgePoint(id="kp-1", description="A", section_start=0, section_end=10)
        kp2 = KnowledgePoint(id="kp-1", description="B", section_start=20, section_end=30)
        km = KnowledgeMap(knowledge_points=[kp1, kp2])
        with pytest.raises(ValueError, match="Duplicate"):
            km.validate()

    def test_to_dict_contains_schema(self):
        km = self._make_km()
        d = km.to_dict()
        assert d["$schema"] == "holmes-km-v1"
        assert len(d["knowledge_points"]) == 2
        assert d["total_chars"] == 1000
        assert d["coverage_pct"] == 90.0

    def test_json_round_trip(self):
        km = self._make_km()
        json_str = km.to_json()
        # Confirm it's valid JSON
        raw = json.loads(json_str)
        assert raw["$schema"] == "holmes-km-v1"

        restored = KnowledgeMap.from_json(json_str)
        assert len(restored.knowledge_points) == 2
        assert restored.total_chars == 1000
        assert restored.chars_read == 900
        assert restored.reading_passes == 2

    def test_from_dict_validates(self):
        """from_dict should call validate() and raise on duplicate IDs."""
        data = {
            "knowledge_points": [
                {"id": "kp-1", "description": "A", "section_start": 0, "section_end": 10},
                {"id": "kp-1", "description": "B", "section_start": 20, "section_end": 30},
            ],
            "total_chars": 100,
        }
        with pytest.raises(ValueError, match="Duplicate"):
            KnowledgeMap.from_dict(data)

    def test_diminishing_returns_default(self):
        km = KnowledgeMap()
        assert km.diminishing_returns is False

    def test_diminishing_returns_serialized(self):
        km = KnowledgeMap(
            knowledge_points=[
                KnowledgePoint(id="kp-1", description="x", section_start=0, section_end=5)
            ],
            diminishing_returns=True,
            total_chars=100,
        )
        d = km.to_dict()
        assert d["diminishing_returns"] is True
        restored = KnowledgeMap.from_dict(d)
        assert restored.diminishing_returns is True
