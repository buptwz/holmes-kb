"""Tests for kb/holmes/kb/validator.py — 3-gate confirm validation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from holmes.kb.store import write_entry
from holmes.kb.validator import check_duplicate, generate_id, validate_schema


_PITFALL_TEMPLATE = """\
---
id: {entry_id}
type: pitfall
title: {title}
maturity: draft
category: database
tags: [redis]
created_at: "2026-01-01"
updated_at: "2026-01-01"
---

## Symptoms
{title} symptoms.

## Root Cause
Root cause text.

## Resolution
Resolution text.
"""


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    (tmp_path / "pitfall" / "database").mkdir(parents=True)
    (tmp_path / "contributions" / "pending").mkdir(parents=True)
    return tmp_path


def test_validate_schema_passes_complete_entry():
    content = _PITFALL_TEMPLATE.format(entry_id="PT-DB-001", title="Redis Timeout")
    result = validate_schema(content)
    assert result.valid is True
    assert result.errors == []


def test_validate_schema_rejects_missing_frontmatter(kb_root: Path):
    content = """\
---
type: pitfall
maturity: draft
---
## Symptoms
...
"""
    result = validate_schema(content)
    assert result.valid is False
    assert len(result.errors) > 0


def test_validate_schema_rejects_missing_section():
    content = """\
---
id: PT-NET-001
type: pitfall
title: DNS Fail
maturity: draft
category: network
tags: []
created_at: ""
updated_at: ""
---
## Symptoms
Failure.
"""
    result = validate_schema(content)
    assert result.valid is False
    assert any("Root Cause" in e or "Resolution" in e for e in result.errors)


def test_check_duplicate_no_match(kb_root: Path):
    existing = _PITFALL_TEMPLATE.format(entry_id="PT-DB-001", title="Redis Connection Pool")
    write_entry(kb_root / "pitfall" / "database" / "PT-DB-001.md", existing)

    new_entry = _PITFALL_TEMPLATE.format(entry_id="PT-DB-999", title="MySQL Replication Lag")
    dup = check_duplicate(kb_root, new_entry)
    assert dup.blocked is False
    assert dup.similar_entries == []


def test_check_duplicate_blocks_high_similarity(kb_root: Path):
    existing = _PITFALL_TEMPLATE.format(entry_id="PT-DB-001", title="Redis Connection Timeout")
    write_entry(kb_root / "pitfall" / "database" / "PT-DB-001.md", existing)

    # Nearly identical title — should be blocked.
    new_entry = _PITFALL_TEMPLATE.format(
        entry_id="PT-DB-999", title="Redis Connection Timeout"
    )
    dup = check_duplicate(kb_root, new_entry, threshold=0.85)
    assert dup.blocked is True
    assert len(dup.similar_entries) >= 1


def test_generate_id_format(kb_root: Path):
    new_id = generate_id(kb_root, "pitfall", "database")
    assert re.fullmatch(r"PT-DB-[0-9a-f]{6}", new_id)


def test_generate_id_avoids_existing(kb_root: Path):
    existing = _PITFALL_TEMPLATE.format(entry_id="PT-DB-a3f8c2", title="Existing Entry")
    write_entry(kb_root / "pitfall" / "database" / "PT-DB-a3f8c2.md", existing)
    new_id = generate_id(kb_root, "pitfall", "database")
    assert re.fullmatch(r"PT-DB-[0-9a-f]{6}", new_id)
    assert new_id != "PT-DB-a3f8c2"


def test_generate_id_retries_on_collision(kb_root: Path, monkeypatch: pytest.MonkeyPatch):
    existing = _PITFALL_TEMPLATE.format(entry_id="PT-DB-a3f8c2", title="Existing Entry")
    write_entry(kb_root / "pitfall" / "database" / "PT-DB-a3f8c2.md", existing)
    tokens = iter(["a3f8c2", "b1e4d7"])
    monkeypatch.setattr("holmes.kb.validator.secrets.token_hex", lambda n: next(tokens))
    new_id = generate_id(kb_root, "pitfall", "database")
    assert new_id == "PT-DB-b1e4d7"


def test_generate_id_gives_up_after_max_retries(kb_root: Path, monkeypatch: pytest.MonkeyPatch):
    existing = _PITFALL_TEMPLATE.format(entry_id="PT-DB-a3f8c2", title="Existing Entry")
    write_entry(kb_root / "pitfall" / "database" / "PT-DB-a3f8c2.md", existing)
    monkeypatch.setattr("holmes.kb.validator.secrets.token_hex", lambda n: "a3f8c2")
    with pytest.raises(RuntimeError, match="unique ID"):
        generate_id(kb_root, "pitfall", "database")


def test_generate_id_different_category(kb_root: Path):
    (kb_root / "pitfall" / "network").mkdir(parents=True)
    new_id = generate_id(kb_root, "pitfall", "network")
    assert re.fullmatch(r"PT-NET-[0-9a-f]{6}", new_id)
