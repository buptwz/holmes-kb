"""Integration tests — full KB lifecycle chain (mock LLM).

Tests the end-to-end flow:
  holmes setup → holmes kb search → holmes import → holmes kb confirm
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from holmes.cli import cli
from holmes.config import HolmesConfig, save_config


_MOCK_LLM_CONTENT = """\
---
id: ""
type: pitfall
title: Redis Connection Pool Exhausted
maturity: draft
category: database
tags: [redis, connection-pool]
created_at: ""
updated_at: ""
---

## Symptoms
Connection timeouts under peak load.

## Root Cause
Connection pool is too small for the workload.

## Resolution
Increase `maxclients` in redis.conf and restart.
"""


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    (kb / "pitfall" / "database").mkdir(parents=True)
    (kb / "contributions" / "pending").mkdir(parents=True)
    (kb / "model").mkdir()
    (kb / "guideline").mkdir()
    (kb / "process").mkdir()
    (kb / "decision").mkdir()
    return kb


@pytest.fixture
def holmes_home(tmp_path: Path, kb_root: Path) -> Path:
    home = tmp_path / "holmes_home"
    home.mkdir()
    cfg = HolmesConfig(
        kb_path=str(kb_root),
        model="mock-model",
        api_key="test-key",
        api_base_url="http://localhost",
    )
    save_config(cfg, holmes_home=home)
    return home


def _mock_openai() -> MagicMock:
    mock = MagicMock()
    choice = MagicMock()
    choice.message.content = _MOCK_LLM_CONTENT
    response = MagicMock()
    response.choices = [choice]
    mock.chat.completions.create = AsyncMock(return_value=response)
    return mock


def test_setup_command(tmp_path: Path, kb_root: Path):
    """holmes setup writes config.json and settings.json."""
    holmes_home = tmp_path / "holmes_cfg"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "setup",
        "--kb-path", str(kb_root),
        "--model", "gpt-4o",
        "--api-key", "test-key",
        "--api-base-url", "http://localhost",
    ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)
    assert result.exit_code == 0
    assert (holmes_home / "config.json").exists()
    assert (holmes_home / "settings.json").exists()
    settings = json.loads((holmes_home / "settings.json").read_text())
    assert settings["env"]["HOLMES_KB_PATH"] == str(kb_root)


def test_kb_search_empty_kb(kb_root: Path, holmes_home: Path):
    """holmes kb search returns no results on empty KB."""
    runner = CliRunner()
    result = runner.invoke(cli, [
        "kb", "--kb-path", str(kb_root), "search", "Redis", "--json",
    ], catch_exceptions=False)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data == []


def test_import_and_confirm_flow(tmp_path: Path, kb_root: Path, holmes_home: Path):
    """Full flow: import document → pending → confirm → official KB."""
    doc = tmp_path / "incident.md"
    doc.write_text(
        "Redis connection timeouts observed during peak hours. "
        "Root cause was connection pool exhaustion. "
        "Resolved by increasing maxclients in redis.conf.",
        encoding="utf-8",
    )

    runner = CliRunner()

    # Import document (mock LLM).
    mock_client = _mock_openai()
    with patch("holmes.kb.importer.openai.AsyncOpenAI", return_value=mock_client):
        result = runner.invoke(cli, [
            "--kb-path", str(kb_root),
            "import", str(doc),
        ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)
    assert result.exit_code == 0
    assert "Saved" in result.output
    pending_id = [
        line.split()[-1]
        for line in result.output.splitlines()
        if "Saved" in line
    ][0]

    # Verify pending entry exists.
    pending_dir = kb_root / "contributions" / "pending"
    pending_files = list(pending_dir.glob("*.md"))
    assert len(pending_files) == 1

    # Confirm the pending entry (simulate all gates passing with y\n response).
    result = runner.invoke(cli, [
        "kb", "--kb-path", str(kb_root), "confirm", pending_id,
    ], input="y\ny\n", catch_exceptions=False)
    assert result.exit_code == 0
    assert "confirmed" in result.output.lower()

    # Verify entry is now in official KB.
    from holmes.kb.store import list_entries
    entries = list_entries(kb_root)
    assert len(entries) == 1
    assert entries[0].type == "pitfall"
    assert entries[0].category == "database"

    # Search should now find it.
    result = runner.invoke(cli, [
        "kb", "--kb-path", str(kb_root), "search", "Redis", "--json",
    ], catch_exceptions=False)
    data = json.loads(result.output)
    assert len(data) >= 1
    assert any("Redis" in r.get("title", "") for r in data)


# ---------------------------------------------------------------------------
# Governance: write-pending with title duplicate check
# ---------------------------------------------------------------------------

_PITFALL_CONTENT = """\
---
type: pitfall
title: MySQL deadlock on concurrent inserts
category: database
tags: [mysql, deadlock]
maturity: draft
created_at: "2026-01-01T00:00:00+00:00"
updated_at: "2026-01-01T00:00:00+00:00"
---

## Symptoms
App hangs under high write concurrency.

## Root Cause
Two transactions acquiring row locks in different order.

## Resolution
Use SELECT ... FOR UPDATE in consistent order.
"""

_VERIFIED_ENTRY = """\
---
id: PT-DB-001
type: pitfall
title: Redis connection timeout under load
maturity: verified
category: database
tags: [redis]
created_at: "2025-01-01T00:00:00+00:00"
updated_at: "2025-01-01T00:00:00+00:00"
---

## Symptoms
Timeout.

## Root Cause
Pool size.

## Resolution
Increase pool.
"""


class TestWritePendingDuplicateCheck:

    def _seed_verified(self, kb_root):
        path = kb_root / "pitfall" / "database" / "PT-DB-001.md"
        path.write_text(_VERIFIED_ENTRY, encoding="utf-8")

    def test_write_pending_new_title_succeeds(self, kb_root):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "write-pending",
            "--content", _PITFALL_CONTENT,
        ], catch_exceptions=False)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "pending_id" in data

    def test_write_pending_duplicate_title_rejected(self, kb_root):
        self._seed_verified(kb_root)
        dup_content = _PITFALL_CONTENT.replace(
            "MySQL deadlock on concurrent inserts",
            "Redis connection timeout under load",
        )
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "write-pending",
            "--content", dup_content,
        ], catch_exceptions=False)
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "error" in data
        assert "PT-DB-001" in data["error"]

    def test_write_pending_with_corrects_bypasses_title_check(self, kb_root):
        self._seed_verified(kb_root)
        corrects_content = _VERIFIED_ENTRY
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "write-pending",
            "--content", corrects_content,
            "--corrects", "PT-DB-001",
        ], catch_exceptions=False)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "pending_id" in data

    def test_write_pending_with_invalid_corrects_fails(self, kb_root):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "write-pending",
            "--content", _PITFALL_CONTENT,
            "--corrects", "PT-NONEXISTENT-999",
        ], catch_exceptions=False)
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Evidence-driven maturity: confirm appends first EvidenceRecord
# ---------------------------------------------------------------------------

class TestConfirmAppendsEvidence:

    def test_confirm_appends_first_evidence(self, kb_root):
        from holmes.kb.pending import write_pending
        from holmes.kb.store import list_entries, load_evidence, read_entry
        import frontmatter

        pending_id = write_pending(kb_root, _PITFALL_CONTENT)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pending_id,
            "--contributor", "maintainer-alice",
        ], input="y\ny\n", catch_exceptions=False)
        assert result.exit_code == 0

        entries = list_entries(kb_root)
        assert len(entries) == 1
        evidence = load_evidence(kb_root, entries[0].id)
        assert len(evidence) == 1
        assert evidence[0]["contributor"] == "maintainer-alice"
        content = read_entry(kb_root, entries[0].id)
        post = frontmatter.loads(content)
        assert post.metadata.get("maturity") == "verified"

    def test_confirm_adds_contributor_to_contributors_list(self, kb_root):
        from holmes.kb.pending import write_pending
        from holmes.kb.store import list_entries, read_entry
        import frontmatter

        pending_id = write_pending(kb_root, _PITFALL_CONTENT)
        runner = CliRunner()
        runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pending_id,
            "--contributor", "bob",
        ], input="y\ny\n", catch_exceptions=False)

        entries = list_entries(kb_root)
        content = read_entry(kb_root, entries[0].id)
        post = frontmatter.loads(content)
        assert "bob" in (post.metadata.get("contributors") or [])


# ---------------------------------------------------------------------------
# Correction workflow: write-pending --corrects → confirm saves snapshot
# ---------------------------------------------------------------------------

class TestCorrectionWorkflow:

    def _seed_verified(self, kb_root):
        path = kb_root / "pitfall" / "database" / "PT-DB-001.md"
        path.write_text(_VERIFIED_ENTRY, encoding="utf-8")

    def test_confirm_correction_saves_snapshot(self, kb_root):
        self._seed_verified(kb_root)
        from holmes.kb.pending import write_pending
        from holmes.kb.history import HISTORY_DIR

        corrects_content = _VERIFIED_ENTRY + "\nUpdated content here.\n"
        pending_id = write_pending(kb_root, corrects_content, corrects="PT-DB-001")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pending_id,
        ], input="y\ny\n", catch_exceptions=False)
        assert result.exit_code == 0
        assert "Correction applied" in result.output
        assert "PT-DB-001" in result.output

        snapshots = list((kb_root / HISTORY_DIR).glob("PT-DB-001-*.md"))
        assert len(snapshots) == 1

    def test_confirm_correction_preserves_evidence(self, kb_root):
        import frontmatter
        # Seed a verified entry with existing evidence.
        original = _VERIFIED_ENTRY.replace(
            "---\n",
            "---\nevidence:\n- session_id: 'old-session'\n  contributor: 'alice'\n  date: '2025-01-01T00:00:00+00:00'\n",
            1,
        )
        path = kb_root / "pitfall" / "database" / "PT-DB-001.md"
        path.write_text(original, encoding="utf-8")

        from holmes.kb.pending import write_pending
        pending_id = write_pending(kb_root, _VERIFIED_ENTRY, corrects="PT-DB-001")
        runner = CliRunner()
        runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pending_id,
        ], input="y\ny\n", catch_exceptions=False)

        post = frontmatter.load(str(path))
        evidence = post.metadata.get("evidence") or []
        assert len(evidence) == 1
        assert evidence[0]["session_id"] == "old-session"

    def test_reject_correction_leaves_original_unchanged(self, kb_root):
        self._seed_verified(kb_root)
        from holmes.kb.pending import write_pending

        pending_id = write_pending(kb_root, _VERIFIED_ENTRY, corrects="PT-DB-001")
        runner = CliRunner()
        runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "reject", pending_id,
        ], catch_exceptions=False)

        original = (kb_root / "pitfall" / "database" / "PT-DB-001.md").read_text()
        assert "Pool size." in original


# ---------------------------------------------------------------------------
# update-refs: evidence array + maturity promotion
# ---------------------------------------------------------------------------

class TestUpdateRefs:

    def _seed_verified_entry(self, kb_root, entry_id="PT-DB-001"):
        import frontmatter
        content = _VERIFIED_ENTRY.replace("PT-DB-001", entry_id)
        path = kb_root / "pitfall" / "database" / f"{entry_id}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def test_update_refs_appends_evidence(self, kb_root):
        import frontmatter
        self._seed_verified_entry(kb_root)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "update-refs",
            "--ids", "PT-DB-001",
            "--session-id", "session-abc123",
            "--contributor", "wangzhi",
        ], catch_exceptions=False)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "PT-DB-001" in data["updated"]

        from holmes.kb.store import load_evidence
        evidence = load_evidence(kb_root, "PT-DB-001")
        assert len(evidence) == 1
        assert evidence[0]["session_id"] == "session-abc123"

    def test_update_refs_deduplicates_same_session(self, kb_root):
        self._seed_verified_entry(kb_root)
        runner = CliRunner()
        for _ in range(2):
            runner.invoke(cli, [
                "kb", "--kb-path", str(kb_root), "update-refs",
                "--ids", "PT-DB-001",
                "--session-id", "session-abc123",
                "--contributor", "wangzhi",
            ], catch_exceptions=False)

        from holmes.kb.store import load_evidence
        evidence = load_evidence(kb_root, "PT-DB-001")
        assert len(evidence) == 1

    def test_update_refs_promotes_to_proven(self, kb_root):
        self._seed_verified_entry(kb_root)
        runner = CliRunner()
        for i, contributor in enumerate(["alice", "bob"]):
            runner.invoke(cli, [
                "kb", "--kb-path", str(kb_root), "update-refs",
                "--ids", "PT-DB-001",
                "--session-id", f"session-{i:04d}",
                "--contributor", contributor,
            ], catch_exceptions=False)

        import frontmatter
        content = (kb_root / "pitfall" / "database" / "PT-DB-001.md").read_text()
        post = frontmatter.loads(content)
        assert post.metadata.get("maturity") == "proven"

    def test_update_refs_not_found_reported(self, kb_root):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "update-refs",
            "--ids", "PT-NONEXISTENT",
            "--session-id", "s1",
            "--contributor", "alice",
        ], catch_exceptions=False)
        data = json.loads(result.output)
        assert "PT-NONEXISTENT" in data["not_found"]
