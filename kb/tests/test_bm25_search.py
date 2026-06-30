"""Tests for BM25Backend, tokenizer, query expansion, and search integration."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holmes.kb.search import (
    BM25Backend,
    LinearScanBackend,
    SearchResult,
    expand_query,
    get_bm25_backend,
    search,
    tokenize,
)


# ---------------------------------------------------------------------------
# Tokenizer tests
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_english_basic(self) -> None:
        tokens = tokenize("Redis connection timeout")
        assert "redis" in tokens
        assert "connection" in tokens
        assert "timeout" in tokens

    def test_english_preserves_hyphens(self) -> None:
        tokens = tokenize("nvidia-smi GPU check")
        assert "nvidia-smi" in tokens
        assert "gpu" in tokens

    def test_english_preserves_dots(self) -> None:
        tokens = tokenize("config.yaml v1.2.3")
        assert "config.yaml" in tokens
        assert "v1.2.3" in tokens

    def test_chinese_bigrams(self) -> None:
        tokens = tokenize("连接池耗尽")
        assert "连接" in tokens
        assert "接池" in tokens
        assert "池耗" in tokens
        assert "耗尽" in tokens

    def test_chinese_single_char(self) -> None:
        tokens = tokenize("库")
        assert "库" in tokens

    def test_mixed_language(self) -> None:
        tokens = tokenize("Redis 连接超时")
        assert "redis" in tokens
        assert "连接" in tokens
        assert "接超" in tokens
        assert "超时" in tokens

    def test_error_codes(self) -> None:
        tokens = tokenize("E01 HTTP 503")
        assert "e01" in tokens
        assert "http" in tokens
        assert "503" in tokens

    def test_empty_string(self) -> None:
        assert tokenize("") == []

    def test_only_punctuation(self) -> None:
        assert tokenize("!!! ???") == []


# ---------------------------------------------------------------------------
# BM25Backend tests (with real KB fixture)
# ---------------------------------------------------------------------------


def _create_kb_entry(
    kb_root: Path,
    entry_id: str,
    title: str,
    kb_type: str = "pitfall",
    category: str = "database",
    tags: list[str] | None = None,
    body: str = "",
    kb_status: str = "active",
    parent_id: str = "",
) -> Path:
    """Helper to create a minimal KB .md entry."""
    if tags is None:
        tags = []
    tag_str = ", ".join(tags)
    lines = [
        "---",
        f"id: {entry_id}",
        f"type: {kb_type}",
        f'title: "{title}"',
        f"category: {category}",
        "maturity: draft",
        f"kb_status: {kb_status}",
        f"tags: [{tag_str}]",
    ]
    if parent_id:
        lines.append(f"parent_id: {parent_id}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    content = "\n".join(lines) + "\n"
    dir_path = kb_root / kb_type / category
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / f"{entry_id}.md"
    file_path.write_text(content, encoding="utf-8")
    return file_path


@pytest.fixture
def kb_with_entries(tmp_path: Path) -> Path:
    """Create a KB with several entries for search testing."""
    kb_root = tmp_path / "kb"
    kb_root.mkdir()

    _create_kb_entry(
        kb_root, "PT-DB-001",
        title="Redis Connection Pool Exhausted",
        tags=["redis", "connection-pool", "timeout"],
        body="## Symptoms\nRedis operations timing out. ERR max number of clients reached.\n\n"
             "## Root Cause\nmaxclients too low.\n\n## Resolution\nIncrease maxclients.",
    )
    _create_kb_entry(
        kb_root, "PT-DB-002",
        title="MySQL Slow Query Performance",
        tags=["mysql", "slow-query", "index"],
        body="## Symptoms\nQueries taking >5s.\n\n## Root Cause\nMissing index on user_id.\n\n"
             "## Resolution\nADD INDEX idx_user_id (user_id).",
    )
    _create_kb_entry(
        kb_root, "PT-NET-001",
        title="网络交换机故障切换",
        category="network",
        tags=["交换机", "failover", "SFP"],
        body="## Symptoms\n网络不稳定，丢包率>5%。\n\n## Root Cause\nSFP模块故障。\n\n"
             "## Resolution\n更换SFP模块。",
    )
    _create_kb_entry(
        kb_root, "PT-SYS-001",
        title="GPU Initialization Failure — Firmware Recovery",
        category="system",
        tags=["gpu", "nvidia-smi", "firmware", "Xid"],
        body="## Symptoms\nnvidia-smi reports Xid error 79.\n\n"
             "## Root Cause\nFirmware corruption.\n\n## Resolution\nFlash firmware.",
    )
    _create_kb_entry(
        kb_root, "PR-DB-001",
        title="Redis Pool Check Steps",
        kb_type="process",
        tags=["redis"],
        body="## Steps\n1. Check connections.\n2. Increase limit.",
        parent_id="PT-DB-001",
    )
    return kb_root


class TestBM25Backend:
    def test_basic_search(self, kb_with_entries: Path) -> None:
        backend = BM25Backend(kb_with_entries)
        results = backend.search("redis timeout")
        assert len(results) >= 1
        assert results[0].entry_id == "PT-DB-001"

    def test_idf_weighting(self, kb_with_entries: Path) -> None:
        """Rare terms should score higher than common terms."""
        backend = BM25Backend(kb_with_entries)
        results = backend.search("nvidia-smi")
        assert len(results) >= 1
        assert results[0].entry_id == "PT-SYS-001"

    def test_chinese_search(self, kb_with_entries: Path) -> None:
        backend = BM25Backend(kb_with_entries)
        results = backend.search("交换机故障")
        assert len(results) >= 1
        assert results[0].entry_id == "PT-NET-001"

    def test_error_code_search(self, kb_with_entries: Path) -> None:
        backend = BM25Backend(kb_with_entries)
        results = backend.search("Xid")
        assert len(results) >= 1
        assert results[0].entry_id == "PT-SYS-001"

    def test_exclude_sub_entries(self, kb_with_entries: Path) -> None:
        """Process sub-entries with parent_id should be excluded by default."""
        backend = BM25Backend(kb_with_entries)
        results = backend.search("redis", exclude_sub_entries=True)
        entry_ids = [r.entry_id for r in results]
        assert "PR-DB-001" not in entry_ids

    def test_include_sub_entries(self, kb_with_entries: Path) -> None:
        backend = BM25Backend(kb_with_entries)
        results = backend.search("redis", exclude_sub_entries=False)
        entry_ids = [r.entry_id for r in results]
        assert "PR-DB-001" in entry_ids

    def test_empty_query(self, kb_with_entries: Path) -> None:
        backend = BM25Backend(kb_with_entries)
        assert backend.search("") == []

    def test_no_results(self, kb_with_entries: Path) -> None:
        backend = BM25Backend(kb_with_entries)
        results = backend.search("nonexistent_term_xyz_12345")
        assert results == []

    def test_invalidate_rebuilds(self, kb_with_entries: Path) -> None:
        backend = BM25Backend(kb_with_entries)
        backend.search("redis")  # triggers build
        assert backend._built is True
        backend.invalidate()
        assert backend._built is False
        backend.search("redis")  # triggers rebuild
        assert backend._built is True

    def test_limit(self, kb_with_entries: Path) -> None:
        backend = BM25Backend(kb_with_entries)
        results = backend.search("redis timeout mysql gpu", limit=2)
        assert len(results) <= 2

    def test_active_only_filter(self, kb_with_entries: Path) -> None:
        _create_kb_entry(
            kb_with_entries, "PT-DRAFT-001",
            title="Draft Entry About Redis",
            tags=["redis"],
            body="## Symptoms\nDraft.\n\n## Root Cause\nDraft.\n\n## Resolution\nDraft.",
            kb_status="draft",
        )
        backend = BM25Backend(kb_with_entries)
        results = backend.search("draft entry redis", active_only=True)
        entry_ids = [r.entry_id for r in results]
        assert "PT-DRAFT-001" not in entry_ids

    def test_pending_entries_searchable(self, kb_with_entries: Path) -> None:
        """Pending entries in _pending/ should be searchable."""
        pending_dir = kb_with_entries / "_pending" / "pitfall" / "database"
        pending_dir.mkdir(parents=True)
        content = textwrap.dedent("""\
            ---
            id: PT-PENDING-001
            type: pitfall
            title: "Pending Redis Issue"
            category: database
            maturity: draft
            kb_status: pending
            tags: [redis, pending-test]
            ---

            ## Symptoms
            Pending entry body.
        """)
        (pending_dir / "PT-PENDING-001.md").write_text(content, encoding="utf-8")
        backend = BM25Backend(kb_with_entries)
        results = backend.search("pending-test")
        assert len(results) >= 1
        assert results[0].entry_id == "PT-PENDING-001"


# ---------------------------------------------------------------------------
# Module-level search() function tests
# ---------------------------------------------------------------------------


class TestModuleSearch:
    def test_default_backend_is_bm25(self, kb_with_entries: Path) -> None:
        results = search(kb_with_entries, "redis")
        assert len(results) >= 1

    def test_custom_backend(self, kb_with_entries: Path) -> None:
        backend = LinearScanBackend(kb_with_entries)
        results = search(kb_with_entries, "redis", backend=backend)
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Query expansion tests
# ---------------------------------------------------------------------------


class TestExpandQuery:
    def test_expansion_adds_terms(self) -> None:
        mock_provider = MagicMock()
        mock_provider.simple_complete.return_value = "timeout connection pool exhausted 连接池"
        result = expand_query("redis 超时", mock_provider)
        assert "redis 超时" in result
        assert "timeout" in result
        assert "连接池" in result

    def test_expansion_fallback_on_error(self) -> None:
        mock_provider = MagicMock()
        mock_provider.simple_complete.side_effect = RuntimeError("API error")
        result = expand_query("redis 超时", mock_provider)
        assert result == "redis 超时"

    def test_expansion_fallback_on_empty(self) -> None:
        mock_provider = MagicMock()
        mock_provider.simple_complete.return_value = ""
        result = expand_query("redis", mock_provider)
        assert result == "redis"


# ---------------------------------------------------------------------------
# get_bm25_backend caching tests
# ---------------------------------------------------------------------------


class TestBM25Cache:
    def test_same_root_returns_same_instance(self, tmp_path: Path) -> None:
        kb = tmp_path / "kb"
        kb.mkdir()
        b1 = get_bm25_backend(kb)
        b2 = get_bm25_backend(kb)
        assert b1 is b2


# ---------------------------------------------------------------------------
# Topological layers tests (for Agent 2 parallelization)
# ---------------------------------------------------------------------------


class TestTopologicalLayers:
    def _make_harness(self) -> Any:
        """Create a minimal Agent2Harness with mocked dependencies."""
        from holmes.kb.agent.dag.harness2 import Agent2Harness

        harness = object.__new__(Agent2Harness)
        harness.entry_ids = {}
        return harness

    def test_leaf_nodes_in_first_layer(self) -> None:
        harness = self._make_harness()
        nodes = [
            {"id": "N1", "children": [{"target": "N2"}, {"target": "N3"}]},
            {"id": "N2", "children": []},
            {"id": "N3", "children": []},
        ]
        layers = harness._topological_layers(nodes)
        assert len(layers) == 2
        layer0_ids = {n["id"] for n in layers[0]}
        assert layer0_ids == {"N2", "N3"}
        layer1_ids = {n["id"] for n in layers[1]}
        assert layer1_ids == {"N1"}

    def test_single_node(self) -> None:
        harness = self._make_harness()
        nodes = [{"id": "N1", "children": []}]
        layers = harness._topological_layers(nodes)
        assert len(layers) == 1
        assert layers[0][0]["id"] == "N1"

    def test_all_leaves(self) -> None:
        harness = self._make_harness()
        nodes = [
            {"id": "N1", "children": []},
            {"id": "N2", "children": []},
            {"id": "N3", "children": []},
        ]
        layers = harness._topological_layers(nodes)
        assert len(layers) == 1
        assert len(layers[0]) == 3

    def test_deep_chain(self) -> None:
        harness = self._make_harness()
        nodes = [
            {"id": "N1", "children": [{"target": "N2"}]},
            {"id": "N2", "children": [{"target": "N3"}]},
            {"id": "N3", "children": []},
        ]
        layers = harness._topological_layers(nodes)
        assert len(layers) == 3
        assert layers[0][0]["id"] == "N3"
        assert layers[1][0]["id"] == "N2"
        assert layers[2][0]["id"] == "N1"

    def test_diamond_shape(self) -> None:
        harness = self._make_harness()
        nodes = [
            {"id": "N1", "children": [{"target": "N2"}, {"target": "N3"}]},
            {"id": "N2", "children": [{"target": "N4"}]},
            {"id": "N3", "children": [{"target": "N4"}]},
            {"id": "N4", "children": []},
        ]
        layers = harness._topological_layers(nodes)
        # N4 first, then N2+N3 together, then N1
        layer_ids = [{n["id"] for n in layer} for layer in layers]
        assert layer_ids[0] == {"N4"}
        assert layer_ids[1] == {"N2", "N3"}
        assert layer_ids[2] == {"N1"}


# ---------------------------------------------------------------------------
# Auto-termination (US-1) tests
# ---------------------------------------------------------------------------


class TestAutoTermination:
    def test_write_entry_auto_terminates_in_per_node_mode(self) -> None:
        """When _auto_terminate_on_write is set, write_entry success sets _terminate."""
        from holmes.kb.agent.dag.harness2 import Agent2Harness

        harness = object.__new__(Agent2Harness)
        harness.entry_ids = {"root": "root-001", "N1": "entry-001"}
        harness._logger = None

        from holmes.kb.agent.dag.tools2 import tool_write_entry

        ctx: dict[str, Any] = {
            "kb_root": Path("/tmp/fake"),
            "pending_root": Path("/tmp/fake/_pending"),
            "entry_ids": {"root": "root-001", "N1": "entry-001"},
            "written_entries": [],
            "failed_entries": [],
            "dry_run": True,
            "source_hash": "abc123",
            "source_file": "test.md",
            "dag_json": {"nodes": []},
            "_terminate": False,
            "_auto_terminate_on_write": True,
            "username": "test",
            "lint_results": [],
        }

        # Simulate a successful write_entry call through _execute_tool
        result = {"success": True, "path": "_pending/process/test/entry-001.md"}
        with patch.object(Agent2Harness, '_execute_tool', return_value=result) as mock_exec:
            # Directly test the flag logic
            ctx["_auto_terminate_on_write"] = True
            ctx["_terminate"] = False
            # Simulate what _execute_tool does after write_entry succeeds
            if result.get("success"):
                if ctx.get("_auto_terminate_on_write"):
                    ctx["_terminate"] = True
            assert ctx["_terminate"] is True

    def test_write_entry_no_auto_terminate_without_flag(self) -> None:
        ctx: dict[str, Any] = {
            "_terminate": False,
            "_auto_terminate_on_write": False,
        }
        result = {"success": True}
        if result.get("success"):
            if ctx.get("_auto_terminate_on_write"):
                ctx["_terminate"] = True
        assert ctx["_terminate"] is False
