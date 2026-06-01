"""Tests for kb/holmes/kb/merger.py — 5-scenario conflict detection and resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from holmes.kb.merger import (
    ConflictFile,
    auto_resolve,
    classify_conflict,
    parse_conflicts,
)


_BASE = """\
---
id: PT-DB-001
type: pitfall
title: Redis Timeout
maturity: {maturity}
category: database
tags: [redis]
created_at: "2026-01-01"
updated_at: {updated}
---

## Symptoms
Timeout errors under load.

## Root Cause
Connection pool is too small.

## Resolution
{resolution}
"""


def _base(maturity: str = "draft", updated: str = '"2026-01-01"', resolution: str = "Increase pool size.") -> str:
    return _BASE.format(maturity=maturity, updated=updated, resolution=resolution)


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    (tmp_path / "pitfall" / "database").mkdir(parents=True)
    return tmp_path


# ---------------------------------------------------------------------------
# parse_conflicts
# ---------------------------------------------------------------------------


def test_parse_conflicts_finds_marker(kb_root: Path):
    conflicted = (
        "---\nid: PT-DB-001\ntype: pitfall\ntitle: T\nmaturity: draft\n"
        "category: database\ntags: []\ncreated_at: \"\"\nupdated_at: \"\"\n---\n"
        "<<<<<<< HEAD\nLocal content.\n=======\nRemote content.\n>>>>>>> branch\n"
    )
    path = kb_root / "pitfall" / "database" / "PT-DB-001.md"
    path.write_text(conflicted)
    conflicts = parse_conflicts(kb_root)
    assert len(conflicts) == 1
    assert "Local content" in conflicts[0].local_content
    assert "Remote content" in conflicts[0].remote_content


def test_parse_conflicts_no_markers(kb_root: Path):
    (kb_root / "pitfall" / "database" / "PT-DB-001.md").write_text(_base())
    conflicts = parse_conflicts(kb_root)
    assert conflicts == []


# ---------------------------------------------------------------------------
# classify_conflict
# ---------------------------------------------------------------------------


def test_classify_pure_new_empty_local():
    scenario = classify_conflict("", _base())
    assert scenario == "pure_new"


def test_classify_maturity_change():
    local = _base(maturity="draft")
    remote = _base(maturity="verified")
    assert classify_conflict(local, remote) == "maturity_change"


def test_classify_evidence_append():
    local = _base(resolution="Increase pool size.")
    remote = _base(resolution="Increase pool size.\n\nAlso restart the service.")
    scenario = classify_conflict(local, remote)
    assert scenario in ("evidence_append", "content_contradiction")


def test_classify_content_contradiction():
    local = _base(resolution="Increase pool size.")
    remote = local.replace("Connection pool is too small.", "Network latency causes the issue.")
    assert classify_conflict(local, remote) == "content_contradiction"


# ---------------------------------------------------------------------------
# auto_resolve
# ---------------------------------------------------------------------------


def test_auto_resolve_pure_new():
    cf = ConflictFile(
        path=Path("/tmp/fake.md"),
        local_content="",
        remote_content=_base(),
    )
    resolved = auto_resolve(cf)
    assert resolved is not None
    assert "Redis Timeout" in resolved


def test_auto_resolve_maturity_change():
    cf = ConflictFile(
        path=Path("/tmp/fake.md"),
        local_content=_base(maturity="draft"),
        remote_content=_base(maturity="verified"),
    )
    resolved = auto_resolve(cf)
    assert resolved is not None
    assert "maturity: verified" in resolved


def test_auto_resolve_content_contradiction_returns_none():
    local = _base(resolution="Increase pool size.")
    remote = local.replace("Connection pool is too small.", "Something completely different.")
    cf = ConflictFile(path=Path("/tmp/fake.md"), local_content=local, remote_content=remote)
    assert auto_resolve(cf) is None
