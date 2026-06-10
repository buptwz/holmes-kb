"""Unit tests for DocumentCursor and doc_access tool functions (T009)."""

from __future__ import annotations

import pytest

from holmes.kb.agent.doc_access import (
    DocumentCursor,
    get_read_coverage,
    read_document_range,
    search_in_document,
)


# ---------------------------------------------------------------------------
# DocumentCursor
# ---------------------------------------------------------------------------


class TestDocumentCursorRangeRead:
    SOURCE = "Hello, World! This is a test document."

    def test_basic_read(self):
        c = DocumentCursor(source_text=self.SOURCE)
        text = c.read_range(0, 5)
        assert text == "Hello"

    def test_read_records_range(self):
        c = DocumentCursor(source_text=self.SOURCE)
        c.read_range(0, 5)
        assert c.read_ranges == [(0, 5)]

    def test_read_merges_adjacent(self):
        c = DocumentCursor(source_text=self.SOURCE)
        c.read_range(0, 5)
        c.read_range(5, 10)
        assert c.read_ranges == [(0, 10)]

    def test_read_merges_overlapping(self):
        c = DocumentCursor(source_text=self.SOURCE)
        c.read_range(0, 10)
        c.read_range(5, 15)
        assert c.read_ranges == [(0, 15)]

    def test_clamps_negative_start(self):
        c = DocumentCursor(source_text=self.SOURCE)
        text = c.read_range(-10, 5)
        assert text == "Hello"

    def test_clamps_end_beyond_total(self):
        c = DocumentCursor(source_text=self.SOURCE)
        text = c.read_range(0, 9999)
        assert text == self.SOURCE

    def test_empty_result_when_start_ge_end(self):
        c = DocumentCursor(source_text=self.SOURCE)
        text = c.read_range(10, 5)
        assert text == ""
        assert c.read_ranges == []

    def test_empty_document(self):
        c = DocumentCursor(source_text="")
        text = c.read_range(0, 100)
        assert text == ""
        assert c.coverage_pct() == 100.0


class TestDocumentCursorCoverage:
    SOURCE = "A" * 100

    def test_coverage_starts_at_zero(self):
        c = DocumentCursor(source_text=self.SOURCE)
        assert c.coverage_pct() == 0.0
        assert c.chars_read() == 0

    def test_coverage_after_partial_read(self):
        c = DocumentCursor(source_text=self.SOURCE)
        c.read_range(0, 50)
        assert c.coverage_pct() == 50.0
        assert c.chars_read() == 50

    def test_coverage_full(self):
        c = DocumentCursor(source_text=self.SOURCE)
        c.read_range(0, 100)
        assert c.coverage_pct() == 100.0

    def test_coverage_non_overlapping_ranges(self):
        c = DocumentCursor(source_text=self.SOURCE)
        c.read_range(0, 25)
        c.read_range(75, 100)
        assert c.chars_read() == 50
        assert c.coverage_pct() == 50.0

    def test_overlapping_reads_not_double_counted(self):
        c = DocumentCursor(source_text=self.SOURCE)
        c.read_range(0, 60)
        c.read_range(40, 80)
        assert c.chars_read() == 80


class TestDocumentCursorFindSection:
    SOURCE = (
        "# Title\n\nIntro text.\n\n"
        "## Section One\n\nContent one.\n\n"
        "## Section Two\n\nContent two.\n"
    )

    def test_find_existing_section(self):
        c = DocumentCursor(source_text=self.SOURCE)
        result = c.find_section("## Section One")
        assert result is not None
        start, end = result
        assert "Section One" in self.SOURCE[start:end]

    def test_section_end_before_next_same_level(self):
        c = DocumentCursor(source_text=self.SOURCE)
        result = c.find_section("## Section One")
        assert result is not None
        _, end = result
        # "## Section Two" should not be included in Section One's range
        assert "Section Two" not in self.SOURCE[result[0]:end]

    def test_find_nonexistent_section(self):
        c = DocumentCursor(source_text=self.SOURCE)
        result = c.find_section("## Does Not Exist")
        assert result is None

    def test_last_section_ends_at_doc_end(self):
        c = DocumentCursor(source_text=self.SOURCE)
        result = c.find_section("## Section Two")
        assert result is not None
        _, end = result
        assert end == len(self.SOURCE)


# ---------------------------------------------------------------------------
# Tool functions
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

    def test_creates_cursor_if_absent(self):
        ctx = self._ctx()
        assert "doc_cursor" not in ctx
        read_document_range(ctx, {"start_char": 0, "end_char": 3})
        assert "doc_cursor" in ctx

    def test_reuses_existing_cursor(self):
        ctx = self._ctx()
        read_document_range(ctx, {"start_char": 0, "end_char": 3})
        cursor_first = ctx["doc_cursor"]
        read_document_range(ctx, {"start_char": 3, "end_char": 7})
        assert ctx["doc_cursor"] is cursor_first

    def test_coverage_accumulates(self):
        ctx = self._ctx()
        read_document_range(ctx, {"start_char": 0, "end_char": 5})
        read_document_range(ctx, {"start_char": 5, "end_char": 10})
        cov = get_read_coverage(ctx, {})
        assert cov["coverage_pct"] == 100.0


class TestGetReadCoverage:
    def test_initial_coverage_zero(self):
        ctx = {"source_text": "A" * 200}
        result = get_read_coverage(ctx, {})
        assert result["coverage_pct"] == 0.0
        assert result["chars_read"] == 0
        assert result["total_chars"] == 200

    def test_after_partial_read(self):
        ctx = {"source_text": "A" * 100}
        read_document_range(ctx, {"start_char": 0, "end_char": 40})
        result = get_read_coverage(ctx, {})
        assert result["coverage_pct"] == 40.0
        assert result["chars_read"] == 40


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
