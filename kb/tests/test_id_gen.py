"""Tests for holmes.kb.agent.dag.id_gen — T010."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from holmes.kb.agent.dag.id_gen import (
    _make_slug,
    generate_entry_ids,
    get_or_create_import_seq,
)


# ---------------------------------------------------------------------------
# _make_slug
# ---------------------------------------------------------------------------


def test_make_slug_filename():
    assert _make_slug("hardware-init-failure.md") == "hardware-init-failure"


def test_make_slug_title_ascii():
    assert _make_slug("GPU Init Failure") == "gpu-init-failure"


def test_make_slug_non_ascii_stripped():
    slug = _make_slug("GPU 初始化失败 — 固件修复")
    # Non-ASCII chars removed; at minimum "gpu" survives
    assert "gpu" in slug


def test_make_slug_empty_falls_back():
    assert _make_slug("") == "doc"


def test_make_slug_max_length():
    long_title = "a" * 100
    assert len(_make_slug(long_title)) <= 40


# ---------------------------------------------------------------------------
# get_or_create_import_seq
# ---------------------------------------------------------------------------


def test_get_or_create_import_seq_empty_dir(tmp_path):
    seq = get_or_create_import_seq(tmp_path)
    assert seq == "001"


def test_get_or_create_import_seq_existing_seq(tmp_path):
    existing = tmp_path / "abc123.dag.json"
    existing.write_text(json.dumps({"import_seq": "003"}), encoding="utf-8")
    seq = get_or_create_import_seq(tmp_path)
    assert seq == "004"


def test_get_or_create_import_seq_current_file_reused(tmp_path):
    current = tmp_path / "abc123.dag.json"
    current.write_text(json.dumps({"import_seq": "007"}), encoding="utf-8")
    seq = get_or_create_import_seq(tmp_path, current_dag_path=current)
    assert seq == "007"


def test_get_or_create_import_seq_nonexistent_dir(tmp_path):
    missing_dir = tmp_path / "nonexistent"
    seq = get_or_create_import_seq(missing_dir)
    assert seq == "001"


def test_get_or_create_import_seq_skips_current(tmp_path):
    current = tmp_path / "abc.dag.json"
    current.write_text(json.dumps({"import_seq": "005"}), encoding="utf-8")
    other = tmp_path / "def.dag.json"
    other.write_text(json.dumps({"import_seq": "003"}), encoding="utf-8")
    # Providing current skips it, takes max of others (003) + 1
    seq = get_or_create_import_seq(tmp_path, current_dag_path=current)
    assert seq == "005"  # current's own seq reused


# ---------------------------------------------------------------------------
# generate_entry_ids
# ---------------------------------------------------------------------------


def _make_dag_json(tmp_path: Path, nodes: list[dict], **extra) -> Path:
    data: dict = {
        "title": "test-dag",
        "source_file": "test-doc.md",
        "nodes": nodes,
        **extra,
    }
    p = tmp_path / "_import-state" / "abc12345.dag.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_generate_entry_ids_assigns_process_nodes(tmp_path):
    nodes = [
        {"id": "N1", "complexity": "process"},
        {"id": "N2", "complexity": "process"},
        {"id": "N3", "complexity": "simple"},
    ]
    dag_path = _make_dag_json(tmp_path, nodes)
    ids = generate_entry_ids(dag_path)

    assert "N1" in ids
    assert "N2" in ids
    assert "N3" not in ids  # simple node excluded
    assert "root" in ids
    assert ids["root"].endswith("-root-001")
    assert ids["N1"].endswith("-N1-001")
    assert ids["N2"].endswith("-N2-001")


def test_generate_entry_ids_idempotent(tmp_path):
    nodes = [{"id": "N1", "complexity": "process"}]
    dag_path = _make_dag_json(tmp_path, nodes)
    ids1 = generate_entry_ids(dag_path)
    ids2 = generate_entry_ids(dag_path)
    assert ids1 == ids2


def test_generate_entry_ids_persists_to_file(tmp_path):
    nodes = [{"id": "N1", "complexity": "process"}]
    dag_path = _make_dag_json(tmp_path, nodes)
    generate_entry_ids(dag_path)
    data = json.loads(dag_path.read_text(encoding="utf-8"))
    assert "entry_ids" in data
    assert "import_seq" in data


def test_generate_entry_ids_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate_entry_ids(tmp_path / "missing.dag.json")


def test_generate_entry_ids_invalid_json(tmp_path):
    p = tmp_path / "bad.dag.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        generate_entry_ids(p)


def test_generate_entry_ids_slug_from_source_file(tmp_path):
    nodes = [{"id": "N1", "complexity": "process"}]
    dag_path = _make_dag_json(tmp_path, nodes, source_file="my-doc.md")
    ids = generate_entry_ids(dag_path)
    assert "my-doc" in ids["root"]


def test_generate_entry_ids_slug_from_title_when_no_source_file(tmp_path):
    data = {
        "title": "hardware-init",
        "source_file": "",
        "nodes": [{"id": "N1", "complexity": "process"}],
    }
    p = tmp_path / "x.dag.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    ids = generate_entry_ids(p)
    assert "hardware-init" in ids["root"]
