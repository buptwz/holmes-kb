"""Tests for kb/holmes/kb/store.py — CRUD and index operations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from holmes.kb.store import (
    EntryMeta,
    add_contributor,
    append_evidence,
    derive_maturity,
    get_last_evidence_date,
    list_entries,
    read_entry,
    rebuild_index_files,
    resolve_maturity_conflict,
    write_entry,
)


_SAMPLE_PITFALL = """\
---
id: PT-DB-001
type: pitfall
title: Redis Timeout
maturity: draft
category: database
tags: [redis]
created_at: "2026-01-01"
updated_at: "2026-01-01"
---

## Symptoms
Timeout errors.

## Root Cause
Small pool.

## Resolution
Increase pool size.
"""


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    """Create a minimal KB directory structure."""
    (tmp_path / "pitfall" / "database").mkdir(parents=True)
    (tmp_path / "model").mkdir()
    (tmp_path / "contributions" / "pending").mkdir(parents=True)
    return tmp_path


def test_write_and_read_entry(kb_root: Path):
    target = kb_root / "pitfall" / "database" / "PT-DB-001.md"
    write_entry(target, _SAMPLE_PITFALL)
    assert target.exists()
    content = read_entry(kb_root, "PT-DB-001")
    assert content is not None
    assert "Redis Timeout" in content


def test_read_entry_not_found(kb_root: Path):
    result = read_entry(kb_root, "XX-MISSING-999")
    assert result is None


def test_list_entries_returns_meta(kb_root: Path):
    target = kb_root / "pitfall" / "database" / "PT-DB-001.md"
    write_entry(target, _SAMPLE_PITFALL)
    entries = list_entries(kb_root)
    assert len(entries) == 1
    e = entries[0]
    assert e.id == "PT-DB-001"
    assert e.type == "pitfall"
    assert e.category == "database"


def test_list_entries_filtered_by_type(kb_root: Path):
    pitfall_path = kb_root / "pitfall" / "database" / "PT-DB-001.md"
    write_entry(pitfall_path, _SAMPLE_PITFALL)
    model_content = _SAMPLE_PITFALL.replace(
        "type: pitfall", "type: model"
    ).replace("id: PT-DB-001", "id: MD-SVC-001")
    model_path = kb_root / "model" / "MD-SVC-001.md"
    write_entry(model_path, model_content)

    pitfalls = list_entries(kb_root, kb_type="pitfall")
    assert all(e.type == "pitfall" for e in pitfalls)
    models = list_entries(kb_root, kb_type="model")
    assert all(e.type == "model" for e in models)


def test_rebuild_index_files(kb_root: Path):
    target = kb_root / "pitfall" / "database" / "PT-DB-001.md"
    write_entry(target, _SAMPLE_PITFALL)
    rebuild_index_files(kb_root)

    index_md = kb_root / "pitfall" / "_index.md"
    assert index_md.exists()
    assert "PT-DB-001" in index_md.read_text()

    index_json = kb_root / "index.json"
    assert index_json.exists()
    data = json.loads(index_json.read_text())
    assert data["total_entries"] == 1


def test_write_entry_creates_dirs(tmp_path: Path):
    """write_entry creates parent directories automatically."""
    deep_path = tmp_path / "a" / "b" / "c" / "entry.md"
    write_entry(deep_path, "---\n---\nHello")
    assert deep_path.exists()


# ---------------------------------------------------------------------------
# derive_maturity
# ---------------------------------------------------------------------------

class TestDeriveMaturiy:

    def test_empty_evidence_returns_draft(self):
        assert derive_maturity([]) == "draft"

    def test_one_record_returns_verified(self):
        evidence = [{"session_id": "s1", "contributor": "alice", "date": "2026-01-01"}]
        assert derive_maturity(evidence) == "verified"

    def test_two_sessions_two_contributors_returns_proven(self):
        evidence = [
            {"session_id": "s1", "contributor": "alice", "date": "2026-01-01"},
            {"session_id": "s2", "contributor": "bob", "date": "2026-02-01"},
        ]
        assert derive_maturity(evidence) == "proven"

    def test_two_sessions_same_contributor_not_proven(self):
        evidence = [
            {"session_id": "s1", "contributor": "alice", "date": "2026-01-01"},
            {"session_id": "s2", "contributor": "alice", "date": "2026-02-01"},
        ]
        assert derive_maturity(evidence) == "verified"

    def test_two_contributors_same_session_not_proven(self):
        evidence = [
            {"session_id": "s1", "contributor": "alice", "date": "2026-01-01"},
            {"session_id": "s1", "contributor": "bob", "date": "2026-02-01"},
        ]
        # Same session_id deduplication in derive_maturity — actually 1 unique session
        assert derive_maturity(evidence) == "verified"


# ---------------------------------------------------------------------------
# get_last_evidence_date
# ---------------------------------------------------------------------------

class TestGetLastEvidenceDate:

    def test_returns_none_for_empty(self):
        assert get_last_evidence_date([]) is None

    def test_returns_max_date(self):
        evidence = [
            {"session_id": "s1", "contributor": "a", "date": "2025-01-01T00:00:00+00:00"},
            {"session_id": "s2", "contributor": "b", "date": "2026-06-01T00:00:00+00:00"},
        ]
        result = get_last_evidence_date(evidence)
        assert result is not None
        assert "2026" in result


# ---------------------------------------------------------------------------
# append_evidence
# ---------------------------------------------------------------------------

_ENTRY_CONTENT = """\
---
id: PT-DB-001
type: pitfall
title: Redis Timeout
maturity: draft
category: database
tags: [redis]
created_at: "2026-01-01T00:00:00+00:00"
updated_at: "2026-01-01T00:00:00+00:00"
---

## Symptoms
Test.

## Root Cause
Test.

## Resolution
Test.
"""


class TestAppendEvidence:

    @pytest.fixture
    def kb_with_entry(self, tmp_path):
        path = tmp_path / "pitfall" / "database" / "PT-DB-001.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_ENTRY_CONTENT, encoding="utf-8")
        return tmp_path

    def test_appends_record(self, kb_with_entry):
        from holmes.kb.store import load_evidence
        ev = {"session_id": "s1", "contributor": "alice", "date": "2026-01-01T00:00:00+00:00"}
        result = append_evidence(kb_with_entry, "PT-DB-001", ev)
        assert result is True
        assert len(load_evidence(kb_with_entry, "PT-DB-001")) == 1

    def test_deduplicates_same_session_id(self, kb_with_entry):
        from holmes.kb.store import load_evidence
        ev = {"session_id": "s1", "contributor": "alice", "date": "2026-01-01T00:00:00+00:00"}
        append_evidence(kb_with_entry, "PT-DB-001", ev)
        result = append_evidence(kb_with_entry, "PT-DB-001", ev)
        assert result is False
        assert len(load_evidence(kb_with_entry, "PT-DB-001")) == 1

    def test_promotes_maturity_to_verified(self, kb_with_entry):
        ev = {"session_id": "s1", "contributor": "alice", "date": "2026-01-01T00:00:00+00:00"}
        append_evidence(kb_with_entry, "PT-DB-001", ev)
        import frontmatter
        post = frontmatter.load(str(kb_with_entry / "pitfall" / "database" / "PT-DB-001.md"))
        assert post.metadata["maturity"] == "verified"

    def test_promotes_to_proven_with_2_sessions_2_contributors(self, kb_with_entry):
        import frontmatter as fm
        # Set maturity to verified first
        path = kb_with_entry / "pitfall" / "database" / "PT-DB-001.md"
        post = fm.load(str(path))
        post.metadata["maturity"] = "verified"
        path.write_text(fm.dumps(post), encoding="utf-8")

        ev1 = {"session_id": "s1", "contributor": "alice", "date": "2026-01-01T00:00:00+00:00"}
        ev2 = {"session_id": "s2", "contributor": "bob", "date": "2026-02-01T00:00:00+00:00"}
        append_evidence(kb_with_entry, "PT-DB-001", ev1)
        append_evidence(kb_with_entry, "PT-DB-001", ev2)
        post = fm.load(str(path))
        assert post.metadata["maturity"] == "proven"

    def test_contributor_captured_in_sidecar_record(self, kb_with_entry):
        # append_evidence writes contributor to the sidecar JSON record.
        # The frontmatter contributors list is NOT updated here (would cause git conflicts);
        # callers that need the list updated should call add_contributor() explicitly.
        from holmes.kb.store import load_evidence
        ev = {"session_id": "s1", "contributor": "alice", "date": "2026-01-01T00:00:00+00:00"}
        append_evidence(kb_with_entry, "PT-DB-001", ev)
        evidence = load_evidence(kb_with_entry, "PT-DB-001")
        assert any(e.get("contributor") == "alice" for e in evidence)

    def test_returns_false_for_nonexistent_entry(self, tmp_path):
        ev = {"session_id": "s1", "contributor": "alice", "date": "2026-01-01"}
        result = append_evidence(tmp_path, "PT-NONEXISTENT", ev)
        assert result is False


# ---------------------------------------------------------------------------
# add_contributor
# ---------------------------------------------------------------------------

class TestAddContributor:

    @pytest.fixture
    def kb_with_entry(self, tmp_path):
        path = tmp_path / "pitfall" / "database" / "PT-DB-001.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_ENTRY_CONTENT, encoding="utf-8")
        return tmp_path

    def test_adds_contributor(self, kb_with_entry):
        add_contributor(kb_with_entry, "PT-DB-001", "alice")
        import frontmatter
        post = frontmatter.load(str(kb_with_entry / "pitfall" / "database" / "PT-DB-001.md"))
        assert "alice" in post.metadata.get("contributors", [])

    def test_no_duplicate_contributor(self, kb_with_entry):
        add_contributor(kb_with_entry, "PT-DB-001", "alice")
        add_contributor(kb_with_entry, "PT-DB-001", "alice")
        import frontmatter
        post = frontmatter.load(str(kb_with_entry / "pitfall" / "database" / "PT-DB-001.md"))
        contribs = post.metadata.get("contributors", [])
        assert contribs.count("alice") == 1


# ---------------------------------------------------------------------------
# resolve_maturity_conflict
# ---------------------------------------------------------------------------

class TestResolveMaturityConflict:

    def test_keeps_lower_when_local_lower(self):
        lower, contradiction = resolve_maturity_conflict("draft", "proven")
        assert lower == "draft"
        assert contradiction is True

    def test_keeps_lower_when_incoming_lower(self):
        lower, contradiction = resolve_maturity_conflict("proven", "verified")
        assert lower == "verified"
        assert contradiction is True

    def test_equal_maturity_keeps_local(self):
        lower, contradiction = resolve_maturity_conflict("verified", "verified")
        assert lower == "verified"
        assert contradiction is True

    def test_contradiction_always_true(self):
        _, contradiction = resolve_maturity_conflict("draft", "draft")
        assert contradiction is True


# ---------------------------------------------------------------------------
# T021-T022: read_entry() case-insensitive ID lookup
# ---------------------------------------------------------------------------


class TestReadEntryCaseInsensitive:

    def _seed(self, kb_root: Path) -> None:
        target = kb_root / "pitfall" / "database" / "PT-DB-001.md"
        write_entry(target, _SAMPLE_PITFALL)

    def test_lowercase_id_matches_uppercase_entry(self, kb_root: Path):
        """T021: querying with all-lowercase returns the entry whose ID is uppercase."""
        self._seed(kb_root)
        assert read_entry(kb_root, "pt-db-001") is not None

    def test_uppercase_id_still_works(self, kb_root: Path):
        """T021: original uppercase query still works."""
        self._seed(kb_root)
        assert read_entry(kb_root, "PT-DB-001") is not None

    def test_mixed_case_id_matches(self, kb_root: Path):
        """T021: mixed-case query returns the entry."""
        self._seed(kb_root)
        assert read_entry(kb_root, "Pt-Db-001") is not None

    def test_nonexistent_id_still_returns_none(self, kb_root: Path):
        """T022: non-existent ID (any case) returns None."""
        self._seed(kb_root)
        assert read_entry(kb_root, "pt-db-999") is None
        assert read_entry(kb_root, "PT-DB-999") is None


# ---------------------------------------------------------------------------
# TestNumericTagSearch — T003/T004/T005
# ---------------------------------------------------------------------------


class TestNumericTagSearch:
    """US1: list --query must not crash when tags contain integers."""

    _ENTRY_NUMERIC_TAGS = """\
---
id: PT-DB-100
type: pitfall
title: Redis Numeric Tag Entry
maturity: draft
category: database
tags: [502, redis, timeout]
created_at: "2026-01-01T00:00:00+00:00"
updated_at: "2026-01-01T00:00:00+00:00"
---

## Symptoms
Test entry with numeric tag.

## Root Cause
Test.

## Resolution
Test.
"""

    @pytest.fixture
    def kb_with_numeric_entry(self, tmp_path: Path) -> Path:
        (tmp_path / "pitfall" / "database").mkdir(parents=True)
        (tmp_path / "contributions" / "pending").mkdir(parents=True)
        path = tmp_path / "pitfall" / "database" / "PT-DB-100.md"
        path.write_text(self._ENTRY_NUMERIC_TAGS, encoding="utf-8")
        return tmp_path

    def test_list_query_does_not_crash_with_numeric_tags(self, kb_with_numeric_entry):
        """T003: list_entries with query does not raise AttributeError on integer tags."""
        results = list_entries(kb_with_numeric_entry, query="redis")
        assert isinstance(results, list)

    def test_list_query_returns_entry_matching_string_tag(self, kb_with_numeric_entry):
        """T004: string tag 'redis' is matched correctly alongside numeric tags."""
        results = list_entries(kb_with_numeric_entry, query="redis")
        ids = [e.id for e in results]
        assert "PT-DB-100" in ids

    def test_list_query_matches_numeric_tag_as_string(self, kb_with_numeric_entry):
        """T004: numeric tag 502 is searchable as string '502'."""
        results = list_entries(kb_with_numeric_entry, query="502")
        ids = [e.id for e in results]
        assert "PT-DB-100" in ids

    def test_list_query_mixed_tags_string_still_matches(self, kb_with_numeric_entry):
        """T005: mixed int+str tags — 'timeout' (string) tag still participates in matching."""
        results = list_entries(kb_with_numeric_entry, query="timeout")
        ids = [e.id for e in results]
        assert "PT-DB-100" in ids


# ---------------------------------------------------------------------------
# T006 / T027 / T028: include_pending support
# ---------------------------------------------------------------------------

_SAMPLE_PENDING = """\
---
id: pending-test
type: pitfall
title: Pending Test Entry
maturity: pending
category: database
tags: [redis]
created_at: "2026-01-01"
updated_at: "2026-01-01"
---

## Symptoms
Test symptoms.
"""


class TestIncludePending:
    """T006/T027/T028: list_entries include_pending and append_evidence to pending."""

    def _seed_pending(self, kb_root: Path) -> Path:
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        p = pending_dir / "pending-test.md"
        p.write_text(_SAMPLE_PENDING, encoding="utf-8")
        return p

    def test_list_entries_include_pending_false_by_default(self, kb_root: Path):
        """T027: pending entry not returned when include_pending not set."""
        self._seed_pending(kb_root)
        results = list_entries(kb_root)
        ids = [e.id for e in results]
        assert "pending-test" not in ids

    def test_list_entries_include_pending_true(self, kb_root: Path):
        """T028: pending entry returned when include_pending=True."""
        # Also add an official entry so we verify both are returned.
        write_entry(kb_root / "pitfall" / "database" / "PT-DB-001.md", _SAMPLE_PITFALL)
        self._seed_pending(kb_root)
        results = list_entries(kb_root, include_pending=True)
        ids = [e.id for e in results]
        assert "PT-DB-001" in ids
        assert "pending-test" in ids

    def test_append_evidence_to_pending_entry(self, kb_root: Path):
        """T006: append_evidence can write a sidecar for a pending entry."""
        self._seed_pending(kb_root)
        record = {"session_id": "test-session", "contributor": "tester", "date": "2026-01-01"}
        result = append_evidence(kb_root, "pending-test", record)
        assert result is True
        sidecar = kb_root / "contributions" / "evidence" / "pending-test" / "test-session.json"
        assert sidecar.exists()
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert data["contributor"] == "tester"
