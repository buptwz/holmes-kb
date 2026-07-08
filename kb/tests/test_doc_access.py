"""Unit tests for doc_access tool functions (042 — no DocumentCursor)."""

from __future__ import annotations

from holmes.kb.agent.doc_access import (
    read_document_range,
    search_in_document,
)


# ---------------------------------------------------------------------------
# read_document_range
# ---------------------------------------------------------------------------


class TestReadDocumentRange:
    SOURCE = "0123456789"

    def _ctx(self) -> dict:
        return {"source_text": self.SOURCE}

    def test_basic_range(self):
        result = read_document_range(self._ctx(), {"start_char": 2, "end_char": 5})
        assert result["text"] == "234"
        assert result["start_char"] == 2
        assert result["end_char"] == 5
        assert result["total_chars"] == 10

    def test_clamps_to_bounds(self):
        result = read_document_range(self._ctx(), {"start_char": -5, "end_char": 999})
        assert result["text"] == self.SOURCE
        assert result["start_char"] == 0
        assert result["end_char"] == 10

    def test_empty_source(self):
        result = read_document_range({"source_text": ""}, {"start_char": 0, "end_char": 10})
        assert result["text"] == ""
        assert result["total_chars"] == 0

    def test_start_ge_end_returns_empty(self):
        result = read_document_range(self._ctx(), {"start_char": 5, "end_char": 3})
        assert result["text"] == ""


# ---------------------------------------------------------------------------
# search_in_document
# ---------------------------------------------------------------------------


class TestSearchInDocument:
    SOURCE = "Redis connection pool exhausted. Redis timeout. MySQL deadlock."

    def _ctx(self) -> dict:
        return {"source_text": self.SOURCE}

    def test_finds_match(self):
        result = search_in_document(self._ctx(), {"query": "Redis"})
        assert result["total_matches"] == 2
        assert len(result["results"]) == 2

    def test_case_insensitive(self):
        result = search_in_document(self._ctx(), {"query": "redis"})
        assert result["total_matches"] == 2

    def test_max_results_respected(self):
        result = search_in_document(self._ctx(), {"query": "redis", "max_results": 1})
        assert len(result["results"]) == 1
        assert result["total_matches"] == 2

    def test_no_match(self):
        result = search_in_document(self._ctx(), {"query": "Nginx"})
        assert result["total_matches"] == 0
        assert result["results"] == []

    def test_empty_query(self):
        result = search_in_document(self._ctx(), {"query": ""})
        assert result["total_matches"] == 0

    def test_result_includes_context(self):
        result = search_in_document(self._ctx(), {"query": "MySQL"})
        assert result["total_matches"] == 1
        hit = result["results"][0]
        assert "offset" in hit
        assert "context" in hit
        assert "MySQL" in hit["context"]

    def test_offset_is_correct(self):
        result = search_in_document(self._ctx(), {"query": "MySQL"})
        hit = result["results"][0]
        assert self.SOURCE[hit["offset"]:hit["offset"] + 5] == "MySQL"
