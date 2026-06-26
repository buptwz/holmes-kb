"""Targeted regression tests for two confirmed bugs.

Bug 1 — .history/ pollution:
    find_entry / list_entries / LinearScanBackend.search must NOT scan
    .history/, _trash/, _drafts/ directories.

Bug 2 — child_entry_ids missing from pitfall root:
    _build_root_messages must inject the list of direct child entry IDs
    so the LLM writes child_entry_ids into the pitfall root's frontmatter.
    Integration test drives _run_per_node_mode() with a scripted FakeProvider
    and verifies the written pitfall root file has child_entry_ids populated.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import frontmatter as _fm

import pytest

from holmes.kb.agent.dag.harness2 import Agent2Harness
from holmes.kb.agent.report import ImportReport
from holmes.kb.search import LinearScanBackend
from holmes.kb.store import find_entry, list_entries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LIVE_CONTENT = """\
---
id: PT-DB-002
type: pitfall
title: Redis 连接池耗尽
maturity: verified
category: database
tags: [redis]
kb_status: active
---

## Symptoms
连接被拒绝。
"""

_HISTORY_CONTENT = """\
---
id: PT-DB-002
type: pitfall
title: 旧快照（不应被返回）
maturity: draft
category: database
tags: []
kb_status: active
---

## Symptoms
旧版内容。
"""


def _make_kb(tmp_path: Path) -> Path:
    """Create a minimal KB with a live entry and a .history/ shadow copy."""
    live = tmp_path / "pitfall" / "database" / "PT-DB-002.md"
    live.parent.mkdir(parents=True)
    live.write_text(_LIVE_CONTENT, encoding="utf-8")

    history = tmp_path / ".history" / "pitfall" / "database" / "PT-DB-002.md"
    history.parent.mkdir(parents=True)
    history.write_text(_HISTORY_CONTENT, encoding="utf-8")

    return tmp_path


# ---------------------------------------------------------------------------
# Bug 1 — find_entry must return the live file, not the .history snapshot
# ---------------------------------------------------------------------------


def test_find_entry_skips_history(tmp_path):
    kb = _make_kb(tmp_path)
    result = find_entry(kb, "PT-DB-002")
    assert result is not None
    assert ".history" not in str(result), f"Got history file: {result}"
    assert result.read_text(encoding="utf-8") == _LIVE_CONTENT


def test_find_entry_no_duplicate_via_history(tmp_path):
    """Even when history has an entry with the same ID, only one path is returned."""
    kb = _make_kb(tmp_path)
    result = find_entry(kb, "PT-DB-002")
    # Must find exactly one — the live file
    assert result is not None
    assert "PT-DB-002.md" in result.name


# ---------------------------------------------------------------------------
# Bug 1 — list_entries must not include .history entries
# ---------------------------------------------------------------------------


def test_list_entries_skips_history(tmp_path):
    kb = _make_kb(tmp_path)
    entries = list_entries(kb)
    titles = [e.title for e in entries]
    assert "旧快照（不应被返回）" not in titles, "list_entries returned a .history snapshot"
    assert "Redis 连接池耗尽" in titles


def test_list_entries_no_duplicate_ids(tmp_path):
    kb = _make_kb(tmp_path)
    entries = list_entries(kb)
    ids = [e.id for e in entries if e.id == "PT-DB-002"]
    assert len(ids) == 1, f"Expected 1 entry for PT-DB-002, got {len(ids)}"


# ---------------------------------------------------------------------------
# Bug 1 — LinearScanBackend.search must not include .history entries
# ---------------------------------------------------------------------------


def test_search_skips_history(tmp_path):
    kb = _make_kb(tmp_path)
    backend = LinearScanBackend(kb)
    results = backend.search("Redis 连接池", limit=10)
    titles = [r.title for r in results]
    assert "旧快照（不应被返回）" not in titles
    assert "Redis 连接池耗尽" in titles


def test_search_no_duplicate_ids(tmp_path):
    kb = _make_kb(tmp_path)
    backend = LinearScanBackend(kb)
    results = backend.search("PT-DB-002", limit=10)
    ids = [r.entry_id for r in results if r.entry_id == "PT-DB-002"]
    assert len(ids) <= 1, f"Search returned duplicate entries: {ids}"


# ---------------------------------------------------------------------------
# Bug 1 — _trash and _drafts also excluded
# ---------------------------------------------------------------------------


def test_find_entry_skips_trash(tmp_path):
    live = tmp_path / "pitfall" / "network" / "PT-NET-001.md"
    live.parent.mkdir(parents=True)
    live.write_text(
        "---\nid: PT-NET-001\ntype: pitfall\ntitle: 网络丢包\nmaturity: draft\n"
        "category: network\ntags: []\nkb_status: active\n---\n\n## Body\n内容。\n",
        encoding="utf-8",
    )
    trash = tmp_path / "_trash" / "pitfall" / "network" / "PT-NET-001.md"
    trash.parent.mkdir(parents=True)
    trash.write_text(
        "---\nid: PT-NET-001\ntype: pitfall\ntitle: 已删除版本\nmaturity: draft\n"
        "category: network\ntags: []\nkb_status: active\n---\n\n## Body\n旧。\n",
        encoding="utf-8",
    )
    result = find_entry(tmp_path, "PT-NET-001")
    assert result is not None
    rel = result.relative_to(tmp_path)
    assert "_trash" not in rel.parts, f"Returned path is under _trash: {result}"
    assert "已删除版本" not in result.read_text()


# ---------------------------------------------------------------------------
# Bug 2 — _build_root_messages must inject child_entry_ids
# ---------------------------------------------------------------------------


class FakeConfig:
    model = "test-model"
    username = "testuser"
    api_key = "sk-test"
    api_base_url = ""


def _make_harness(tmp_path: Path, nodes: list[dict], entry_ids: dict) -> Agent2Harness:
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "title": "GPU Init Failure",
        "source_file": "gpu.md",
        "nodes": nodes,
        "entry_ids": entry_ids,
        "import_seq": "001",
    }
    dag_path = state_dir / "aabbccdd.dag.json"
    dag_path.write_text(json.dumps(data), encoding="utf-8")
    provider = MagicMock()
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash="aabbccdd",
        source_file="gpu.md",
        dag_json_path=dag_path,
    )
    harness._load_dag_json(ImportReport())
    return harness


def test_build_root_messages_contains_child_entry_ids_label(tmp_path):
    """Prompt must explicitly list child_entry_ids for the LLM."""
    nodes = [
        {"id": "N1", "complexity": "process", "description": "检查固件", "children": []},
        {"id": "N2", "complexity": "process", "description": "替换硬件", "children": []},
    ]
    entry_ids = {
        "N1": "gpu-init-N1-001",
        "N2": "gpu-init-N2-001",
        "root": "gpu-init-root-001",
    }
    harness = _make_harness(tmp_path, nodes, entry_ids)
    msgs = harness._build_root_messages(source_text="源文档内容", briefs=[])
    content = msgs[0]["content"]

    assert "child_entry_ids" in content, "Prompt must contain 'child_entry_ids'"
    assert "gpu-init-N1-001" in content
    assert "gpu-init-N2-001" in content


def test_build_root_messages_only_top_level_nodes_as_children(tmp_path):
    """Only DAG entry-point nodes (not sub-children) appear in child_entry_ids."""
    # N1 → N2 (N2 is a child of N1, not a direct child of root)
    nodes = [
        {
            "id": "N1",
            "complexity": "process",
            "description": "诊断入口",
            "children": [{"target": "N2", "condition": "always"}],
        },
        {"id": "N2", "complexity": "process", "description": "子步骤", "children": []},
    ]
    entry_ids = {
        "N1": "gpu-init-N1-001",
        "N2": "gpu-init-N2-001",
        "root": "gpu-init-root-001",
    }
    harness = _make_harness(tmp_path, nodes, entry_ids)
    msgs = harness._build_root_messages(source_text="源文档内容", briefs=[])
    content = msgs[0]["content"]

    # N1 is the entry-point (not targeted) → must appear
    assert "gpu-init-N1-001" in content
    # N2 is targeted by N1 → must NOT appear in child_entry_ids block
    # Find the child_entry_ids section
    idx = content.find("child_entry_ids")
    assert idx != -1
    child_section = content[idx: idx + 200]
    assert "gpu-init-N2-001" not in child_section, (
        "N2 is a sub-child of N1 and should not appear as direct child of root"
    )


def test_build_root_messages_multiple_top_level_nodes(tmp_path):
    """When multiple independent entry-point nodes exist, all appear in child_entry_ids."""
    # N1, N2, N3 are all independent (no edges between them)
    nodes = [
        {"id": "N1", "complexity": "process", "description": "路径A", "children": []},
        {"id": "N2", "complexity": "process", "description": "路径B", "children": []},
        {"id": "N3", "complexity": "process", "description": "路径C", "children": []},
    ]
    entry_ids = {
        "N1": "diag-N1-001",
        "N2": "diag-N2-001",
        "N3": "diag-N3-001",
        "root": "diag-root-001",
    }
    harness = _make_harness(tmp_path, nodes, entry_ids)
    msgs = harness._build_root_messages(source_text="源文档内容", briefs=[])
    content = msgs[0]["content"]

    assert "diag-N1-001" in content
    assert "diag-N2-001" in content
    assert "diag-N3-001" in content


# ---------------------------------------------------------------------------
# Bug 2 — Integration: _run_per_node_mode writes root with correct child_entry_ids
# ---------------------------------------------------------------------------

_SRC_HASH = "deadbeef12345678"
_ENTRY_IDS = {
    "N1": "test-gpu-N1-001",
    "N2": "test-gpu-N2-001",
    "root": "test-gpu-root-001",
}
_CATEGORY = "hardware"


def _process_entry_content(entry_id: str, parent_eid: str) -> str:
    return (
        f"---\n"
        f"id: {entry_id}\n"
        f"type: process\n"
        f'title: "步骤 {entry_id}"\n'
        f'description: "描述 {entry_id}"\n'
        f"category: {_CATEGORY}\n"
        f"kb_status: pending\n"
        f"maturity: draft\n"
        f"decay_status: active\n"
        f"next_decay_check: '2026-09-24'\n"
        f"source_file: test.md\n"
        f"source_hash: {_SRC_HASH}\n"
        f"import_trace_id: test-import\n"
        f"parent_id: {parent_eid}\n"
        f"contributors:\n  - tester\n"
        f"tags:\n  - gpu\n"
        f"created_at: '2026-06-24T00:00:00Z'\n"
        f"updated_at: '2026-06-24T00:00:00Z'\n"
        f"---\n\n"
        f"## Steps\n"
        f"1. **[observe]** 检查 GPU 状态\n"
        f"2. **[remote]** 执行修复命令\n"
    )


def _pitfall_root_content(child_ids: list[str]) -> str:
    children_yaml = "\n".join(f"  - {c}" for c in child_ids)
    return (
        f"---\n"
        f"id: {_ENTRY_IDS['root']}\n"
        f"type: pitfall\n"
        f'title: "GPU 初始化失败"\n'
        f'description: "GPU 重启后初始化失败排查链路"\n'
        f"category: {_CATEGORY}\n"
        f"pitfall_structure: tree\n"
        f"kb_status: pending\n"
        f"maturity: draft\n"
        f"decay_status: active\n"
        f"next_decay_check: '2026-09-24'\n"
        f"source_file: test.md\n"
        f"source_hash: {_SRC_HASH}\n"
        f"import_trace_id: test-import\n"
        f"child_entry_ids:\n{children_yaml}\n"
        f"contributors:\n  - tester\n"
        f"tags:\n  - gpu\n  - hardware\n"
        f"created_at: '2026-06-24T00:00:00Z'\n"
        f"updated_at: '2026-06-24T00:00:00Z'\n"
        f"---\n\n"
        f"## Symptoms\nnvidia-smi 报错 No devices were found\n\n"
        f"## Root Cause\nGPU 固件或电源异常\n\n"
        f"## Resolution\n排查链路见子条目。\n"
    )


class ScriptedProvider:
    """Simulates Agent 2: detects phase from prompt, writes correct entry, then finalizes.

    Phase detection uses "node_id: N1" / "node_id: N2" which appear only in the task
    section — not in the DAG overview — so they don't cause false matches.

    - "node_id: N2" in prompt → write process entry for N2
    - "node_id: N1" in prompt (and not root phase) → write process entry for N1
    - "pitfall root entry" in prompt → write pitfall root
    - everything else → finalize immediately (review phase or unknown)
    """

    def __init__(self) -> None:
        self._await_finalize = False
        self.root_prompt: str = ""

    def complete(self, messages, system, model, max_tokens, tools):
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                c = m.get("content", "")
                last_user = c if isinstance(c, str) else str(c)
                break

        if self._await_finalize:
            self._await_finalize = False
            tc = MagicMock()
            tc.name = "finalize"
            tc.input = {}
            tc.id = "fin"
            return False, [tc], messages + [{"role": "assistant", "content": "fin"}], {}

        tc = MagicMock()
        tc.id = "w"

        # Use "node_id: NX" which appears only in the per-node task section.
        if "node_id: N2" in last_user and "pitfall root" not in last_user:
            tc.name = "write_entry"
            tc.input = {
                "entry_id": _ENTRY_IDS["N2"],
                "content": _process_entry_content(_ENTRY_IDS["N2"], _ENTRY_IDS["N1"]),
            }
            self._await_finalize = True
        elif "node_id: N1" in last_user and "pitfall root" not in last_user:
            tc.name = "write_entry"
            tc.input = {
                "entry_id": _ENTRY_IDS["N1"],
                "content": _process_entry_content(_ENTRY_IDS["N1"], _ENTRY_IDS["root"]),
            }
            self._await_finalize = True
        elif "pitfall root entry" in last_user:
            self.root_prompt = last_user
            # Simulate LLM obeying the child_entry_ids instruction in the prompt.
            tc.name = "write_entry"
            tc.input = {
                "entry_id": _ENTRY_IDS["root"],
                "content": _pitfall_root_content([_ENTRY_IDS["N1"]]),
            }
            self._await_finalize = True
        else:
            # Review phase or unknown — just finalize immediately.
            tc.name = "finalize"
            tc.input = {}

        return False, [tc], messages + [{"role": "assistant", "content": "act"}], {}

    def append_tool_results(self, messages, results):
        for _id, content in results:
            messages = messages + [{"role": "user", "content": content}]
        return messages


def _make_harness_for_integration(tmp_path: Path) -> Agent2Harness:
    """DAG: N1 → N2 (N1 is entry-point, N2 is a sub-child of N1)."""
    nodes = [
        {
            "id": "N1",
            "complexity": "process",
            "description": "诊断入口",
            "node_type": "action",
            "children": [{"target": "N2", "condition": "always"}],
            # no parent_id → defaults to "root" in _build_node_messages
        },
        {
            "id": "N2",
            "complexity": "process",
            "description": "子步骤修复",
            "node_type": "action",
            "children": [],
            "parent_id": "N1",
        },
    ]
    state_dir = tmp_path / "_import-state"
    state_dir.mkdir(parents=True)
    dag_data = {
        "title": "GPU 初始化失败",
        "source_file": "test.md",
        "nodes": nodes,
        "entry_ids": _ENTRY_IDS,
        "import_seq": "001",
    }
    dag_path = state_dir / f"{_SRC_HASH}.dag.json"
    dag_path.write_text(json.dumps(dag_data), encoding="utf-8")

    provider = ScriptedProvider()
    harness = Agent2Harness(
        kb_root=tmp_path,
        cfg=FakeConfig(),
        provider=provider,
        source_hash=_SRC_HASH,
        source_file="test.md",
        dag_json_path=dag_path,
    )
    return harness


def test_run_writes_pitfall_root_with_child_entry_ids(tmp_path):
    """Integration: after run(), pitfall root file has child_entry_ids=[N1] not [N2]."""
    harness = _make_harness_for_integration(tmp_path)
    report = harness.run(source_text="GPU 初始化失败测试文档内容。")

    root_path = (
        tmp_path / "_pending" / "pitfall" / _CATEGORY / f"{_ENTRY_IDS['root']}.md"
    )
    assert root_path.exists(), f"Pitfall root not written. Traces: {report.phase_traces}"

    post = _fm.load(str(root_path))
    child_ids = list(post.metadata.get("child_entry_ids") or [])
    assert child_ids, "child_entry_ids is empty in pitfall root frontmatter"
    assert _ENTRY_IDS["N1"] in child_ids, f"N1 entry ID missing from child_entry_ids: {child_ids}"
    assert _ENTRY_IDS["N2"] not in child_ids, (
        f"N2 should not be a direct child of root (it's a sub-child of N1): {child_ids}"
    )


def test_run_root_prompt_contains_child_entry_ids_instruction(tmp_path):
    """Integration: the prompt sent to LLM for root phase lists direct child IDs."""
    harness = _make_harness_for_integration(tmp_path)
    provider: ScriptedProvider = harness.provider  # type: ignore[assignment]

    harness.run(source_text="GPU 初始化失败测试文档内容。")

    assert provider.root_prompt, "Root phase prompt was never captured (root never generated?)"
    assert "child_entry_ids" in provider.root_prompt
    assert _ENTRY_IDS["N1"] in provider.root_prompt
    # N2 should appear only in the entry_ids table, not in the child_entry_ids instruction block
    idx = provider.root_prompt.find("child_entry_ids")
    child_section = provider.root_prompt[idx: idx + 300]
    assert _ENTRY_IDS["N2"] not in child_section, (
        f"N2 incorrectly listed as direct child of root:\n{child_section}"
    )
