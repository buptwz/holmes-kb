"""Tests for spec 043 D5 — relative index paths, poisoned-index guard, and
``kb merge`` handling of derived files (log.md / _index.md / index.json).

Covers T019 (index.json relative file_path + find_entry bounds check) and
T020 (kb merge no longer isolates/deletes derived files).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from holmes.cli import cli
from holmes.kb.store import find_entry, rebuild_index_files

from .conftest import make_entry


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# T019 — relative file_path in index.json
# ---------------------------------------------------------------------------


def test_rebuild_index_writes_relative_file_path(kb_root: Path) -> None:
    """rebuild_index_files stores file_path relative to kb_root, and
    find_entry resolves the relative path back to the entry (roundtrip)."""
    entry_path = make_entry(kb_root, "PT-DB-abc123")
    rebuild_index_files(kb_root)

    index = json.loads((kb_root / "index.json").read_text(encoding="utf-8"))
    assert index["total_entries"] == 1
    file_path = index["entries"][0]["file_path"]
    assert not Path(file_path).is_absolute()
    assert file_path == "pitfall/database/PT-DB-abc123.md"

    found = find_entry(kb_root, "PT-DB-abc123")
    assert found == entry_path


def test_find_entry_accepts_legacy_absolute_file_path(kb_root: Path) -> None:
    """Index files written by older versions (absolute paths) still resolve."""
    entry_path = make_entry(kb_root, "PT-DB-abc123")
    (kb_root / "index.json").write_text(json.dumps({
        "entries": [{"id": "PT-DB-abc123", "file_path": str(entry_path)}],
    }), encoding="utf-8")

    assert find_entry(kb_root, "PT-DB-abc123") == entry_path


def test_find_entry_rejects_out_of_bounds_file_path(
    kb_root: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A poisoned index pointing outside kb_root must not be followed —
    neither via absolute path nor via a relative ``..`` escape."""
    outside_root = tmp_path_factory.mktemp("outside-kb")
    outside_entry = make_entry(outside_root, "PT-DB-abc123")
    relative_escape = os.path.relpath(outside_entry, kb_root)
    assert relative_escape.startswith("..")

    for poisoned in (str(outside_entry), relative_escape):
        (kb_root / "index.json").write_text(json.dumps({
            "entries": [{"id": "PT-DB-abc123", "file_path": poisoned}],
        }), encoding="utf-8")
        assert find_entry(kb_root, "PT-DB-abc123") is None


def test_find_entry_out_of_bounds_falls_back_to_rglob(
    kb_root: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Out-of-bounds index entries are ignored; the rglob fallback still
    finds the real entry inside the KB with the same ID."""
    outside_root = tmp_path_factory.mktemp("outside-kb")
    outside_entry = make_entry(outside_root, "PT-DB-abc123")
    real_entry = make_entry(kb_root, "PT-DB-abc123")

    (kb_root / "index.json").write_text(json.dumps({
        "entries": [{"id": "PT-DB-abc123", "file_path": str(outside_entry)}],
    }), encoding="utf-8")

    assert find_entry(kb_root, "PT-DB-abc123") == real_entry


# ---------------------------------------------------------------------------
# T020 — kb merge and derived files
# ---------------------------------------------------------------------------


def _conflicted(local: str, remote: str) -> str:
    return f"<<<<<<< HEAD\n{local}=======\n{remote}>>>>>>> branch\n"


def _entry_side(root_cause: str) -> str:
    return (
        "---\n"
        "id: PT-DB-001\n"
        "type: pitfall\n"
        "title: Redis Timeout\n"
        "maturity: draft\n"
        "category: database\n"
        "tags: []\n"
        'created_at: "2026-01-01"\n'
        'updated_at: "2026-01-01"\n'
        "---\n\n"
        "## Symptoms\nTimeout errors under load.\n\n"
        f"## Root Cause\n{root_cause}\n\n"
        "## Resolution\nIncrease pool size.\n"
    )


@pytest.fixture()
def merged_kb(kb_root: Path) -> Path:
    """KB with conflict markers in log.md, _index.md, index.json and one
    ordinary entry (content contradiction); returns after `kb merge` ran."""
    entry_dir = kb_root / "pitfall" / "database"
    entry_dir.mkdir(parents=True)
    (kb_root / "contributions").mkdir()

    (kb_root / "contributions" / "log.md").write_text(
        "# Contribution Log\n"
        + _conflicted(
            "2026-01-01 | confirmed | PT-DB-aaa111 | entry from A\n",
            "2026-01-02 | confirmed | PT-DB-bbb222 | entry from B\n",
        ),
        encoding="utf-8",
    )
    (kb_root / "pitfall" / "_index.md").write_text(
        _conflicted("# pitfall Index (A)\n", "# pitfall Index (B)\n"),
        encoding="utf-8",
    )
    (kb_root / "index.json").write_text(
        _conflicted('{"entries": []}\n', '{"entries": [], "side": "B"}\n'),
        encoding="utf-8",
    )
    (entry_dir / "PT-DB-001.md").write_text(
        _conflicted(
            _entry_side("Connection pool is too small."),
            _entry_side("Network latency causes the issue."),
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["--kb-path", str(kb_root), "merge"])
    assert result.exit_code == 0, result.output
    return kb_root


def test_merge_log_md_union_not_deleted(merged_kb: Path) -> None:
    """log.md keeps lines from both sides and is never deleted/isolated."""
    log_path = merged_kb / "contributions" / "log.md"
    assert log_path.is_file()
    text = log_path.read_text(encoding="utf-8")
    assert "<<<<<<<" not in text
    assert "PT-DB-aaa111" in text
    assert "PT-DB-bbb222" in text


def test_merge_derived_indexes_rebuilt(merged_kb: Path) -> None:
    """_index.md / index.json conflicts are resolved by rebuilding, never
    isolated into contributions/conflicts/."""
    index_md = merged_kb / "pitfall" / "_index.md"
    text = index_md.read_text(encoding="utf-8")
    assert "<<<<<<<" not in text
    assert "# Pitfall Index" in text  # regenerated by rebuild_index_files

    index_json = json.loads((merged_kb / "index.json").read_text(encoding="utf-8"))
    assert "entries" in index_json

    conflicts_dir = merged_kb / "contributions" / "conflicts"
    isolated = [p for p in conflicts_dir.glob("*.json") if p.is_file()]
    for meta_path in isolated:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert not data["original_path"].endswith(("_index.md", "log.md", "index.json"))


def test_merge_ordinary_entry_still_isolated(merged_kb: Path) -> None:
    """Ordinary entries keep the 5-scenario logic: a content contradiction
    is still moved to contributions/conflicts/ for human review."""
    assert not (merged_kb / "pitfall" / "database" / "PT-DB-001.md").exists()
    conflicts_dir = merged_kb / "contributions" / "conflicts"
    metas = list(conflicts_dir.glob("conflict-*.json"))
    assert len(metas) == 1
    data = json.loads(metas[0].read_text(encoding="utf-8"))
    assert data["original_path"].endswith("PT-DB-001.md")
