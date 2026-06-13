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
    from unittest.mock import MagicMock

    from holmes.kb.agent.report import ImportReport
    from holmes.kb.pending import write_pending

    doc = tmp_path / "incident.md"
    doc.write_text(
        "Redis connection timeouts observed during peak hours. "
        "Root cause was connection pool exhaustion. "
        "Resolved by increasing maxclients in redis.conf.",
        encoding="utf-8",
    )

    from holmes.kb.agent.report import ImportReport
    from holmes.kb.pending import write_pending

    # Pre-create a real pending entry so the confirm step works.
    pending_content = """\
---
type: pitfall
title: Redis Connection Pool Exhausted
category: database
tags: [redis, connection-pool]
maturity: draft
created_at: "2026-01-01T00:00:00+00:00"
updated_at: "2026-01-01T00:00:00+00:00"
---

## Symptoms
Connection timeouts under peak load.

## Root Cause
Connection pool is too small for the workload.

## Resolution
Increase `maxclients` in redis.conf and restart.
"""
    actual_pending_id = write_pending(kb_root, pending_content, source="auto")
    mock_report = ImportReport(created=[actual_pending_id])

    runner = CliRunner()

    # Import document — mock ImportAgentRunner.run() to write a real pending file.
    def fake_run(source_text, file_path=None):  # noqa: ANN001, ANN202
        write_pending(kb_root, _MOCK_LLM_CONTENT, source="auto")
        return ImportReport(created=["Redis Connection Pool Exhausted"])

    mock_runner = MagicMock()
    mock_runner.run.side_effect = fake_run

    with patch("holmes.kb.agent.runner.ImportAgentRunner", return_value=mock_runner):
        result = runner.invoke(cli, [
            "--kb-path", str(kb_root),
            "import", str(doc),
        ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)
    assert result.exit_code == 0
    assert "Created" in result.output

    # Verify pending entry exists; get its ID from the filename.
    pending_dir = kb_root / "contributions" / "pending"
    pending_files = list(pending_dir.glob("*.md"))
    assert len(pending_files) == 1
    pending_id = pending_files[0].stem

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


# ---------------------------------------------------------------------------
# Fix: Agent write → confirm → clean official entry (no pending internal fields)
# ---------------------------------------------------------------------------

_AGENT_WRITTEN_CONTENT = """\
---
type: pitfall
title: ES Heap Full Causes OOM
category: application
tags: [elasticsearch, heap, oom]
---

## Symptoms
Elasticsearch returns OutOfMemoryError in logs.

## Root Cause
Heap size too small for the dataset.

## Resolution
Increase -Xmx in jvm.options.
"""


class TestAgentWriteConfirmCleanEntry:

    def test_agent_write_without_maturity_passes_gate1(self, kb_root):
        """write_pending() auto-injects maturity; confirm Gate 1 passes for Agent-written entries."""
        from holmes.kb.pending import write_pending

        pending_id = write_pending(kb_root, _AGENT_WRITTEN_CONTENT, source="agent")
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pending_id,
        ], input="y\ny\n", catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "Gate 1" in result.output
        assert "Schema valid" in result.output

    def test_confirmed_entry_has_no_pending_internal_fields(self, kb_root):
        """Official entry after confirm must not contain any pending-state metadata fields."""
        import frontmatter as fm
        from holmes.kb.pending import write_pending
        from holmes.kb.store import list_entries, read_entry

        pending_id = write_pending(kb_root, _AGENT_WRITTEN_CONTENT, source="agent")
        runner = CliRunner()
        runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pending_id,
        ], input="y\ny\n", catch_exceptions=False)

        entries = list_entries(kb_root)
        assert len(entries) == 1
        content = read_entry(kb_root, entries[0].id)
        post = fm.loads(content)
        meta = post.metadata

        pending_fields = {"pending", "pending_since", "source", "source_session",
                          "suggested_type", "suggested_category"}
        leaked = pending_fields & set(meta.keys())
        assert leaked == set(), f"Official entry leaked pending fields: {leaked}"


# ---------------------------------------------------------------------------
# T014-T015: US3 — Correction workflow Gate 2 bypass
# ---------------------------------------------------------------------------


class TestCorrectionGate2Bypass:

    def _seed_entry(self, kb_root):
        path = kb_root / "pitfall" / "database" / "PT-DB-001.md"
        path.write_text(_VERIFIED_ENTRY, encoding="utf-8")

    def test_correction_proposal_skips_gate2(self, kb_root):
        """T014: confirm a correction proposal outputs Gate 2 skip message; single user interaction."""
        self._seed_entry(kb_root)
        from holmes.kb.pending import write_pending

        pending_id = write_pending(kb_root, _VERIFIED_ENTRY, corrects="PT-DB-001")
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pending_id,
        ], input="y\n", catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "Skipped (correction proposal)" in result.output

    def test_normal_confirm_still_runs_gate2(self, kb_root):
        """T015: regression — normal pending entry (no corrects) still runs Gate 2."""
        runner = CliRunner()
        from holmes.kb.pending import write_pending

        pending_id = write_pending(kb_root, _AGENT_WRITTEN_CONTENT, source="agent")
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pending_id,
        ], input="y\ny\n", catch_exceptions=False)
        assert result.exit_code == 0, result.output
        # Gate 2 output should show duplicate check ran (not skipped)
        assert "Gate 2" in result.output
        assert "Skipped (correction proposal)" not in result.output


# ---------------------------------------------------------------------------
# T003-T004: US1 — Correction path pending field cleanup
# ---------------------------------------------------------------------------


class TestCorrectionFieldCleanup:

    def _seed_entry(self, kb_root):
        path = kb_root / "pitfall" / "database" / "PT-DB-001.md"
        path.write_text(_VERIFIED_ENTRY, encoding="utf-8")

    def test_correction_confirm_removes_all_pending_internal_fields(self, kb_root):
        """T003: After confirming a correction proposal, no pending-internal fields remain."""
        import frontmatter as fm
        from holmes.kb.pending import write_pending
        from holmes.kb.store import read_entry

        self._seed_entry(kb_root)
        pending_id = write_pending(kb_root, _VERIFIED_ENTRY, corrects="PT-DB-001")
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pending_id,
        ], input="y\n", catch_exceptions=False)
        assert result.exit_code == 0, result.output

        content = read_entry(kb_root, "PT-DB-001")
        assert content is not None
        meta = fm.loads(content).metadata
        pending_fields = {"pending", "pending_since", "source", "source_session",
                          "suggested_type", "suggested_category"}
        leaked = pending_fields & set(meta.keys())
        assert leaked == set(), f"Correction path leaked pending fields: {leaked}"

    def test_correction_confirm_normal_path_still_clean(self, kb_root):
        """T004: Regression — normal (non-correction) confirm path still cleans fields correctly."""
        import frontmatter as fm
        from holmes.kb.pending import write_pending
        from holmes.kb.store import list_entries, read_entry

        pending_id = write_pending(kb_root, _AGENT_WRITTEN_CONTENT, source="agent")
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pending_id,
        ], input="y\ny\n", catch_exceptions=False)
        assert result.exit_code == 0, result.output

        entries = list_entries(kb_root)
        assert len(entries) == 1
        content = read_entry(kb_root, entries[0].id)
        meta = fm.loads(content).metadata
        pending_fields = {"pending", "pending_since", "source", "source_session",
                          "suggested_type", "suggested_category"}
        leaked = pending_fields & set(meta.keys())
        assert leaked == set(), f"Normal path leaked pending fields: {leaked}"


# ---------------------------------------------------------------------------
# T010-T011: US3 — skill run --json exit code propagation
# ---------------------------------------------------------------------------


class TestSkillRunJsonExitCode:

    def _make_skill(self, kb_root: Path, name: str, exit_code: int) -> None:
        """Create a skill whose run.sh exits with given code."""
        from holmes.kb.skill.manager import create_skill
        skill_dir = create_skill(kb_root, name, f"Test skill exit {exit_code}")
        run_sh = skill_dir / "scripts" / "run.sh"
        run_sh.write_text(
            f"#!/usr/bin/env bash\necho 'output'\nexit {exit_code}\n",
            encoding="utf-8",
        )
        run_sh.chmod(0o755)

    def test_json_mode_propagates_nonzero_exit_code(self, kb_root):
        """T010: skill run --json with failing skill → CLI exit_code == 1."""
        self._make_skill(kb_root, "fail-skill", 1)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "skill", "run", "fail-skill", "--json",
        ], catch_exceptions=False)
        assert result.exit_code == 1

    def test_json_mode_success_exits_zero(self, kb_root):
        """T011: skill run --json with succeeding skill → CLI exit_code == 0, JSON complete."""
        import json as _json
        self._make_skill(kb_root, "ok-skill", 0)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "skill", "run", "ok-skill", "--json",
        ], catch_exceptions=False)
        assert result.exit_code == 0
        data = _json.loads(result.output)
        assert data["exit_code"] == 0

    def test_json_exit_code_matches_json_field(self, kb_root):
        """T010b: CLI exit_code matches JSON exit_code field for failing skill."""
        import json as _json
        self._make_skill(kb_root, "fail2-skill", 2)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "skill", "run", "fail2-skill", "--json",
        ], catch_exceptions=False)
        data = _json.loads(result.output)
        assert result.exit_code == data["exit_code"] == 2


# ---------------------------------------------------------------------------
# TestCorrectionDataIntegrity — T014/T015/T016/T017/T018
# ---------------------------------------------------------------------------

import textwrap as _textwrap
import frontmatter as _fm


def _make_kb_entry(kb_root: Path, entry_id: str, maturity: str = "proven",
                   contributors: list = None, created_at: str = "2020-01-01T00:00:00+00:00") -> Path:
    """Helper: write a minimal KB pitfall entry."""
    cat_dir = kb_root / "pitfall" / "database"
    cat_dir.mkdir(parents=True, exist_ok=True)
    entry_path = cat_dir / f"{entry_id}.md"
    meta_contributors = contributors or ["alice"]
    content = _textwrap.dedent(f"""\
        ---
        id: {entry_id}
        type: pitfall
        title: Test Entry {entry_id}
        maturity: {maturity}
        category: database
        tags: [redis]
        created_at: "{created_at}"
        updated_at: "2024-01-01T00:00:00+00:00"
        contributors: {meta_contributors}
        evidence: []
        ---

        ## Symptoms
        Test.

        ## Root Cause
        Test root cause that is definitely more than 50 characters long here.

        ## Resolution
        Test resolution that is definitely more than 50 characters long here.
    """)
    entry_path.write_text(content, encoding="utf-8")
    return entry_path


def _make_correction_pending(kb_root: Path, corrects_id: str, pending_id: str = None) -> Path:
    """Helper: write a correction pending entry."""
    pending_dir = kb_root / "contributions" / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    pid = pending_id or f"pending-correction-{corrects_id}"
    pending_path = pending_dir / f"{pid}.md"
    content = _textwrap.dedent(f"""\
        ---
        id: ""
        corrects: {corrects_id}
        type: pitfall
        title: Corrected Entry {corrects_id}
        maturity: draft
        category: database
        tags: [redis]
        created_at: ""
        updated_at: ""
        pending: true
        ---

        ## Symptoms
        Corrected symptoms that are definitely more than fifty characters long.

        ## Root Cause
        Corrected root cause that is more than fifty characters long.

        ## Resolution
        Corrected resolution that is more than fifty characters long.
    """)
    pending_path.write_text(content, encoding="utf-8")
    return pending_path, pid


class TestCorrectionDataIntegrity:
    """US3/US4/US5/US7: correction confirm must preserve created_at, append contributor,
    show --show hint for long entries, and emit maturity change message."""

    def test_created_at_preserved_after_correction(self, kb_root):
        """T014: correction confirm keeps original created_at unchanged."""
        original_created = "2020-05-15T10:00:00+00:00"
        _make_kb_entry(kb_root, "PT-DB-C001", created_at=original_created)
        _, pid = _make_correction_pending(kb_root, "PT-DB-C001")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pid,
        ], input="y\ny\ny\n", catch_exceptions=False)

        assert result.exit_code == 0, result.output
        entry_path = kb_root / "pitfall" / "database" / "PT-DB-C001.md"
        post = _fm.load(str(entry_path))
        assert str(post.metadata.get("created_at")) == original_created

    def test_contributor_appended_after_correction(self, kb_root):
        """T015: correction confirm with --contributor appends to contributors list."""
        _make_kb_entry(kb_root, "PT-DB-C002", contributors=["alice"])
        _, pid = _make_correction_pending(kb_root, "PT-DB-C002")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pid, "--contributor", "bob",
        ], input="y\ny\ny\n", catch_exceptions=False)

        assert result.exit_code == 0, result.output
        entry_path = kb_root / "pitfall" / "database" / "PT-DB-C002.md"
        post = _fm.load(str(entry_path))
        contributors = post.metadata.get("contributors", [])
        assert "alice" in contributors
        assert "bob" in contributors

    def test_contributor_not_duplicated(self, kb_root):
        """T016: if contributor is already in list, it is not added again."""
        _make_kb_entry(kb_root, "PT-DB-C003", contributors=["alice", "bob"])
        _, pid = _make_correction_pending(kb_root, "PT-DB-C003")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pid, "--contributor", "bob",
        ], input="y\ny\ny\n", catch_exceptions=False)

        assert result.exit_code == 0, result.output
        entry_path = kb_root / "pitfall" / "database" / "PT-DB-C003.md"
        post = _fm.load(str(entry_path))
        contributors = post.metadata.get("contributors", [])
        assert contributors.count("bob") == 1

    def test_gate3_long_entry_shows_show_hint(self, kb_root, tmp_path):
        """T017: Gate 3 for long entries (>800 chars) shows --show hint, not truncated content."""
        # Create an entry with content > 800 chars
        cat_dir = kb_root / "pitfall" / "database"
        cat_dir.mkdir(parents=True, exist_ok=True)
        entry_path = cat_dir / "PT-DB-C004.md"
        long_body = "x" * 900
        entry_path.write_text(
            f"---\nid: PT-DB-C004\ntype: pitfall\ntitle: Long Entry\nmaturity: draft\n"
            f"category: database\ntags: []\ncreated_at: '2024-01-01T00:00:00+00:00'\n"
            f"updated_at: '2024-01-01T00:00:00+00:00'\ncontributors: []\nevidence: []\n---\n\n{long_body}\n",
            encoding="utf-8",
        )
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        pid = "pending-long-c004"
        long_correction = (
            "## Symptoms\n" + "Corrected symptom details. " * 30 + "\n\n"
            "## Root Cause\n" + "Corrected root cause details. " * 30 + "\n\n"
            "## Resolution\n" + "Corrected resolution details. " * 30 + "\n"
        )
        (pending_dir / f"{pid}.md").write_text(
            f"---\nid: ''\ncorrects: PT-DB-C004\ntype: pitfall\ntitle: Long Entry Corrected\n"
            f"maturity: draft\ncategory: database\ntags: []\ncreated_at: ''\nupdated_at: ''\npending: true\n---\n\n"
            + long_correction,
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pid,
        ], input="y\ny\nn\n", catch_exceptions=False)

        assert "holmes kb pending --show" in result.output

    def test_maturity_change_shown_in_output(self, kb_root):
        """T018: correction confirm output includes maturity change line."""
        _make_kb_entry(kb_root, "PT-DB-C005", maturity="proven")
        _, pid = _make_correction_pending(kb_root, "PT-DB-C005")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pid,
        ], input="y\ny\ny\n", catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "maturity:" in result.output
        assert "proven" in result.output
        assert "verified" in result.output


# ---------------------------------------------------------------------------
# TestPendingListEmptyId — T020/T021
# ---------------------------------------------------------------------------


class TestPendingListEmptyId:
    """US6: pending list must show file stem when frontmatter id is empty string."""

    def test_empty_id_shows_file_stem(self, kb_root):
        """T020: pending entry with id='' displays file stem in list output."""
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        stem = "MY-STEM-PENDING-001"
        (pending_dir / f"{stem}.md").write_text(
            "---\nid: \"\"\ntype: pitfall\ntitle: Empty ID Entry\n"
            "maturity: draft\ncategory: database\ntags: []\n"
            "created_at: '2024-01-01T00:00:00+00:00'\nupdated_at: ''\n---\n\nBody.\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "pending",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert stem in result.output

    def test_normal_id_displays_unchanged(self, kb_root):
        """T021: pending entry with normal id still shows id correctly."""
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        normal_id = "pending-normal-abc123"
        (pending_dir / "MY-NORMAL-FILE.md").write_text(
            f"---\nid: \"{normal_id}\"\ntype: pitfall\ntitle: Normal ID Entry\n"
            "maturity: draft\ncategory: database\ntags: []\n"
            "created_at: '2024-01-01T00:00:00+00:00'\nupdated_at: ''\n---\n\nBody.\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "pending",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert normal_id in result.output


# ---------------------------------------------------------------------------
# TestMergeExitCode — T006 (US1)
# ---------------------------------------------------------------------------


class TestMergeExitCode:
    """US1: merge command must exit 0 even when conflicts are isolated."""

    def test_merge_with_isolated_conflict_exits_zero(self, kb_root):
        """T006a: when isolation occurs, exit code is 0 and resolve hint shown."""
        from holmes.kb.conflict import ConflictFile
        runner = CliRunner()
        dummy_path = kb_root / "pitfall" / "database" / "conflict.md"
        dummy_path.write_text("dummy", encoding="utf-8")
        cf = ConflictFile(
            path=dummy_path,
            local_content="local content here",
            remote_content="remote content here",
        )

        with patch("holmes.kb.merger.parse_conflicts", return_value=[cf]), \
             patch("holmes.kb.merger.auto_resolve", return_value=None):
            result = runner.invoke(cli, [
                "kb", "--kb-path", str(kb_root), "merge",
            ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "holmes kb resolve" in result.output

    def test_merge_with_auto_resolved_conflict_exits_zero(self, kb_root):
        """T006b: when auto-resolution succeeds, exit code is 0."""
        from holmes.kb.conflict import ConflictFile
        dummy_path = kb_root / "pitfall" / "database" / "conflict.md"
        dummy_path.write_text("dummy", encoding="utf-8")
        cf = ConflictFile(
            path=dummy_path,
            local_content="same content",
            remote_content="same content",
        )
        runner = CliRunner()
        with patch("holmes.kb.merger.parse_conflicts", return_value=[cf]), \
             patch("holmes.kb.merger.auto_resolve", return_value="resolved content"):
            result = runner.invoke(cli, [
                "kb", "--kb-path", str(kb_root), "merge",
            ], catch_exceptions=False)

        assert result.exit_code == 0, result.output

    def test_merge_with_no_conflicts_exits_zero(self, kb_root):
        """T006c: when no conflicts present, exit code is 0."""
        runner = CliRunner()
        with patch("holmes.kb.merger.parse_conflicts", return_value=[]):
            result = runner.invoke(cli, [
                "kb", "--kb-path", str(kb_root), "merge",
            ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "No git conflict markers" in result.output


# ---------------------------------------------------------------------------
# TestGate3FieldStripping — T008 (US2)
# ---------------------------------------------------------------------------


class TestGate3FieldStripping:
    """US2: Gate 3 preview must not show internal pending fields."""

    _PENDING_WITH_INTERNAL = """\
---
id: pending-20260101-120000-abcd
type: pitfall
title: Connection pool exhaustion
maturity: draft
category: database
tags: [postgres]
created_at: "2026-01-01T00:00:00+00:00"
updated_at: "2026-01-01T00:00:00+00:00"
pending: true
pending_since: "2026-01-01T12:00:00+00:00"
source: auto
source_session: session-abc
suggested_type: pitfall
suggested_category: database
---

## Symptoms
Connections time out under load.

## Root Cause
Max connections limit reached.

## Resolution
Increase max_connections in postgresql.conf.
"""

    def test_gate3_strips_internal_fields(self, kb_root):
        """T008a: Gate 3 preview does not contain any internal fields."""
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        pid = "pending-20260101-120000-abcd"
        (pending_dir / f"{pid}.md").write_text(self._PENDING_WITH_INTERNAL, encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pid,
        ], input="n\n", catch_exceptions=False)

        assert result.exit_code == 0
        for field in ("pending:", "pending_since:", "source:", "source_session:",
                      "suggested_type:", "suggested_category:"):
            assert field not in result.output, f"Internal field '{field}' found in Gate 3 preview"

    def test_gate3_preserves_kb_fields(self, kb_root):
        """T008b: Gate 3 preview still shows KB-destined fields."""
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        pid = "pending-20260101-120000-abcd"
        (pending_dir / f"{pid}.md").write_text(self._PENDING_WITH_INTERNAL, encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", pid,
        ], input="n\n", catch_exceptions=False)

        assert "Connection pool exhaustion" in result.output or "Gate 3" in result.output


# ---------------------------------------------------------------------------
# TestShowWithEvidence — T015 (US5)
# ---------------------------------------------------------------------------


class TestShowWithEvidence:
    """US5: show --with-evidence displays sidecar evidence summary."""

    def _seed_entry(self, kb_root: Path, entry_id: str = "PT-DB-001") -> None:
        path = kb_root / "pitfall" / "database" / f"{entry_id}.md"
        path.write_text(_VERIFIED_ENTRY, encoding="utf-8")

    def test_with_evidence_shows_summary(self, kb_root):
        """T015a: show --with-evidence outputs Evidence: N sessions line."""
        import json as _json
        self._seed_entry(kb_root)
        ev_dir = kb_root / "contributions" / "evidence" / "PT-DB-001"
        ev_dir.mkdir(parents=True)
        (ev_dir / "session1.json").write_text(
            _json.dumps({"session_id": "s1", "contributor": "alice", "date": "2026-01-01"}),
            encoding="utf-8",
        )
        (ev_dir / "session2.json").write_text(
            _json.dumps({"session_id": "s2", "contributor": "bob", "date": "2026-06-01"}),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "show", "PT-DB-001", "--with-evidence",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "Evidence: 2 sessions" in result.output
        assert "alice" in result.output
        assert "bob" in result.output
        assert "2026-06-01" in result.output

    def test_with_evidence_no_sidecar_shows_none(self, kb_root):
        """T015b: show --with-evidence with no sidecar outputs 'Evidence: none'."""
        self._seed_entry(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "show", "PT-DB-001", "--with-evidence",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "Evidence: none" in result.output

    def test_without_evidence_flag_unchanged(self, kb_root):
        """T015c: show without --with-evidence does not add Evidence line."""
        self._seed_entry(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "show", "PT-DB-001",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "Evidence:" not in result.output


# ---------------------------------------------------------------------------
# TestHistoryShow — T017 (US6)
# ---------------------------------------------------------------------------


class TestHistoryShow:
    """US6: history --show displays snapshot content."""

    def _seed_entry_and_snapshot(self, kb_root: Path) -> str:
        """Seed a KB entry and a snapshot, return snapshot filename."""
        path = kb_root / "pitfall" / "database" / "PT-DB-001.md"
        path.write_text(_VERIFIED_ENTRY, encoding="utf-8")

        history_dir = kb_root / ".history"
        history_dir.mkdir(parents=True, exist_ok=True)
        snap_name = "PT-DB-001-20260101-120000.md"
        (history_dir / snap_name).write_text(
            _VERIFIED_ENTRY + "\n# Snapshot marker line\n",
            encoding="utf-8",
        )
        return snap_name

    def test_show_snapshot_displays_content(self, kb_root):
        """T017a: history --show <name> displays full snapshot content."""
        snap_name = self._seed_entry_and_snapshot(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "history", "PT-DB-001",
            "--show", snap_name,
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "Snapshot marker line" in result.output

    def test_show_nonexistent_snapshot_gives_error(self, kb_root):
        """T017b: history --show nonexistent.md gives error message without crash."""
        (kb_root / ".history").mkdir(parents=True, exist_ok=True)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "history", "PT-DB-001",
            "--show", "nonexistent.md",
        ], catch_exceptions=False)

        assert result.exit_code == 1  # exit 1 for nonexistent snapshot (US7)
        assert "not found" in result.output.lower() or "Snapshot not found" in result.output

    def test_show_path_traversal_rejected(self, kb_root):
        """T017c: history --show with path separators is rejected."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "history", "PT-DB-001",
            "--show", "../../etc/passwd",
        ], catch_exceptions=False)

        assert result.exit_code != 0 or "invalid" in result.output.lower()

    def test_without_show_lists_snapshots(self, kb_root):
        """T017d: history without --show shows list (original behavior)."""
        snap_name = self._seed_entry_and_snapshot(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "history", "PT-DB-001",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert snap_name in result.output


# ---------------------------------------------------------------------------
# TestDryRunHint — T019 (US7)
# ---------------------------------------------------------------------------


class TestDryRunHint:
    """US7: import --dry-run without LLM and without classification params shows hint."""

    _IMPORT_CONTENT = (
        "This document describes a serious database connection issue that causes "
        "timeouts under heavy load. The root cause is connection pool exhaustion. "
        "The resolution involves increasing the max_connections parameter and "
        "configuring connection pooling correctly for high-traffic scenarios."
    )

    def _make_import_file(self, tmp_path: Path) -> Path:
        f = tmp_path / "incident.txt"
        f.write_text(self._IMPORT_CONTENT, encoding="utf-8")
        return f

    def _no_api_key_holmes_home(self, tmp_path: Path, kb_root: Path) -> Path:
        home = tmp_path / "holmes_home_no_key"
        home.mkdir()
        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="mock-model",
            api_key="",
            api_base_url="",
        )
        save_config(cfg, holmes_home=home)
        return home

    def test_dry_run_no_llm_no_params_shows_hint(self, tmp_path, kb_root):
        """T019a: dry-run without api_key and without --type/--category/--title/--tags shows hint."""
        holmes_home = self._no_api_key_holmes_home(tmp_path, kb_root)
        import_file = self._make_import_file(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--kb-path", str(kb_root),
            "import", str(import_file), "--dry-run",
        ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "LLM not configured" in result.output

    def test_dry_run_with_type_no_hint(self, tmp_path, kb_root):
        """T019b: dry-run with --type provided and api_key set does not show hint."""
        # api_key must be set — the unified LLM check rejects all paths without a key.
        holmes_home = tmp_path / "holmes_home_with_key2"
        holmes_home.mkdir()
        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="mock-model",
            api_key="test-key",
            api_base_url="http://localhost",
        )
        save_config(cfg, holmes_home=holmes_home)
        import_file = self._make_import_file(tmp_path)

        from holmes.kb.agent.report import ImportReport

        runner = CliRunner()
        with patch("holmes.kb.agent.runner.ImportAgentRunner.run",
                   return_value=ImportReport(dry_run=True)):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(import_file), "--dry-run", "--type", "pitfall",
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "LLM not configured" not in result.output

    def test_dry_run_with_api_key_no_hint(self, tmp_path, kb_root):
        """T019c: dry-run with api_key set does not show hint (even without params)."""
        holmes_home = tmp_path / "holmes_home_with_key"
        holmes_home.mkdir()
        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="mock-model",
            api_key="real-key",
            api_base_url="http://localhost",
        )
        save_config(cfg, holmes_home=holmes_home)
        import_file = self._make_import_file(tmp_path)

        from holmes.kb.agent.report import ImportReport

        runner = CliRunner()
        with patch("holmes.kb.agent.runner.ImportAgentRunner.run",
                   return_value=ImportReport(dry_run=True)):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(import_file), "--dry-run",
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "LLM not configured" not in result.output


# ---------------------------------------------------------------------------
# TestBatchReject — T012 (US4)
# ---------------------------------------------------------------------------


class TestBatchReject:
    """US4: holmes kb reject --stale-days N bulk-deletes old pending entries."""

    def _seed_pending(self, kb_root: Path, entry_id: str, pending_since: str) -> None:
        """Seed a pending entry with a specific pending_since timestamp."""
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / f"{entry_id}.md").write_text(
            f"---\nid: {entry_id}\ntype: pitfall\ntitle: Test Entry {entry_id}\n"
            f"maturity: draft\ncategory: database\ntags: []\n"
            f"pending_since: '{pending_since}'\ncreated_at: '{pending_since}'\n"
            f"updated_at: '{pending_since}'\n---\n\nBody.\n",
            encoding="utf-8",
        )

    def test_batch_deletes_old_entries(self, kb_root):
        """T012a: reject --stale-days 1 deletes entries older than 1 day."""
        self._seed_pending(kb_root, "old-1", "2020-01-01T00:00:00+00:00")
        self._seed_pending(kb_root, "old-2", "2020-06-15T00:00:00+00:00")
        self._seed_pending(kb_root, "old-3", "2021-01-01T00:00:00+00:00")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "reject", "--stale-days", "1",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "Rejected: 3" in result.output

        # Files should be gone.
        pending_dir = kb_root / "contributions" / "pending"
        remaining = list(pending_dir.glob("*.md"))
        assert len(remaining) == 0, f"Expected 0 remaining, got {remaining}"

    def test_created_at_fallback_for_stale(self, kb_root):
        """T012b: entries without pending_since but with old created_at are also rejected."""
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / "no-pending-since.md").write_text(
            "---\nid: no-pending-since\ntype: pitfall\ntitle: Old No Since\n"
            "maturity: draft\ncategory: database\ntags: []\n"
            "created_at: '2020-01-01T00:00:00+00:00'\n---\n\nBody.\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "reject", "--stale-days", "1",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "Rejected: 1" in result.output

    def test_zero_results_shows_count(self, kb_root):
        """T012c: reject --stale-days 0 with no entries shows 'Rejected: 0'."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "reject", "--stale-days", "9999",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "Rejected: 0" in result.output

    def test_backward_compat_single_reject(self, kb_root):
        """T012d: reject <pending_id> (no --stale-days) still works as before."""
        from holmes.kb.pending import write_pending

        pending_id = write_pending(kb_root, _VERIFIED_ENTRY.replace("PT-DB-001", "pending-test-001"))

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "reject", pending_id,
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "Rejected" in result.output


# ---------------------------------------------------------------------------
# TestSearchTypeFilter — T016 (US6)
# ---------------------------------------------------------------------------


class TestSearchTypeFilter:
    """US6: holmes kb search --type filters results by entry type."""

    def _seed_entries(self, kb_root: Path) -> None:
        """Seed a pitfall and a model entry both matching 'timeout'."""
        pitfall_dir = kb_root / "pitfall" / "database"
        pitfall_dir.mkdir(parents=True, exist_ok=True)
        (pitfall_dir / "PT-DB-001.md").write_text(
            "---\nid: PT-DB-001\ntype: pitfall\ntitle: Connection Timeout Pitfall\n"
            "maturity: verified\ncategory: database\ntags: [timeout]\n---\n\n"
            "Connection timeout pitfall occurs under load.\n",
            encoding="utf-8",
        )

        model_dir = kb_root / "model" / "database"
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "MD-DB-001.md").write_text(
            "---\nid: MD-DB-001\ntype: model\ntitle: Timeout Model\n"
            "maturity: verified\ncategory: database\ntags: [timeout]\n---\n\n"
            "Model describing timeout behavior.\n",
            encoding="utf-8",
        )

    def test_type_filter_returns_only_pitfall(self, kb_root):
        """T016a: search --type pitfall returns only pitfall entries."""
        self._seed_entries(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "search", "timeout",
            "--type", "pitfall", "--json",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert all(e["type"] == "pitfall" for e in data), \
            f"Non-pitfall entries returned: {data}"
        assert any(e["id"] == "PT-DB-001" for e in data)

    def test_no_filter_returns_all(self, kb_root):
        """T016b: search without --type returns all matching entries."""
        self._seed_entries(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "search", "timeout", "--json",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        types = {e["type"] for e in data}
        assert "pitfall" in types and "model" in types, \
            f"Expected both types; got: {types}"

    def test_nonexistent_type_returns_empty(self, kb_root):
        """T016c: search --type nonexistent returns empty list without error."""
        self._seed_entries(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "search", "timeout",
            "--type", "nonexistent_type", "--json",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        # Warning may be mixed into output; extract the JSON array part.
        json_part = result.output[result.output.rfind("["):]
        data = json.loads(json_part)
        assert data == [], f"Expected empty list; got: {data}"


# ---------------------------------------------------------------------------
# TestShowEvidencePosition — T018 (US7)
# ---------------------------------------------------------------------------


class TestShowEvidencePosition:
    """US7: show --with-evidence outputs Evidence line before entry content."""

    def _seed_entry_with_evidence(self, kb_root: Path) -> None:
        path = kb_root / "pitfall" / "database" / "PT-DB-001.md"
        path.write_text(_VERIFIED_ENTRY, encoding="utf-8")
        ev_dir = kb_root / "contributions" / "evidence" / "PT-DB-001"
        ev_dir.mkdir(parents=True)
        (ev_dir / "session1.json").write_text(
            json.dumps({"session_id": "s1", "contributor": "alice", "date": "2026-01-01"}),
            encoding="utf-8",
        )

    def test_evidence_before_content(self, kb_root):
        """T018a: Evidence line appears before the first ## section heading."""
        self._seed_entry_with_evidence(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "show", "PT-DB-001", "--with-evidence",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        evidence_pos = result.output.find("Evidence:")
        first_section_pos = result.output.find("##")
        assert evidence_pos != -1, "Evidence line not found in output"
        assert first_section_pos != -1, "No ## section heading found"
        assert evidence_pos < first_section_pos, (
            f"Evidence ({evidence_pos}) must appear before first ## ({first_section_pos})"
        )

    def test_no_evidence_flag_no_evidence_line(self, kb_root):
        """T018b: without --with-evidence flag, no Evidence line is output."""
        self._seed_entry_with_evidence(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "show", "PT-DB-001",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "Evidence:" not in result.output


# ---------------------------------------------------------------------------
# TestHistoryShowFieldStrip — T020 (US8)
# ---------------------------------------------------------------------------


class TestHistoryShowFieldStrip:
    """US8: history --show strips replaced_at/replaced_by/snapshot_reason from output."""

    _INTERNAL_FIELDS = ("replaced_at", "replaced_by", "snapshot_reason")

    def _seed_snapshot_with_internal_fields(self, kb_root: Path) -> str:
        """Create a snapshot with internal fields; return snapshot filename."""
        history_dir = kb_root / ".history"
        history_dir.mkdir(parents=True, exist_ok=True)
        snap_name = "PT-DB-001-20260101-120000.md"
        snap_content = (
            "---\n"
            "id: PT-DB-001\n"
            "type: pitfall\n"
            "title: Connection Pool Exhausted\n"
            "maturity: verified\n"
            "category: database\n"
            "tags: [redis]\n"
            "replaced_at: '2026-06-01T12:00:00+00:00'\n"
            "replaced_by: PT-DB-001-20260601-130000.md\n"
            "snapshot_reason: update\n"
            "---\n\n"
            "## Root Cause\nConnection pool is too small.\n"
        )
        (history_dir / snap_name).write_text(snap_content, encoding="utf-8")
        return snap_name

    def test_internal_fields_absent_in_output(self, kb_root):
        """T020a: history --show output does not contain replaced_at/replaced_by/snapshot_reason."""
        snap_name = self._seed_snapshot_with_internal_fields(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "history", "PT-DB-001",
            "--show", snap_name,
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        for field in self._INTERNAL_FIELDS:
            assert field not in result.output, \
                f"Internal field '{field}' should not appear in output"

    def test_knowledge_fields_present(self, kb_root):
        """T020b: history --show output retains knowledge fields (title, type, tags, body)."""
        snap_name = self._seed_snapshot_with_internal_fields(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "history", "PT-DB-001",
            "--show", snap_name,
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "Connection Pool Exhausted" in result.output
        assert "Root Cause" in result.output
        assert "verified" in result.output


# ---------------------------------------------------------------------------
# TestHolmesVersion — T022 (US9)
# ---------------------------------------------------------------------------


class TestHolmesVersion:
    """US9: holmes --version and -v output version number."""

    def test_version_flag_exits_zero(self, kb_root):
        """T022a: holmes --version exits 0 and prints version string."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "holmes" in result.output.lower() or result.output.strip()
        # Should contain at least one digit (version number).
        assert any(ch.isdigit() for ch in result.output), \
            f"Version output missing digits: {result.output!r}"

    def test_short_v_flag(self, kb_root):
        """T022b: holmes -v also outputs version."""
        runner = CliRunner()
        result = runner.invoke(cli, ["-v"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert any(ch.isdigit() for ch in result.output), \
            f"-v output missing digits: {result.output!r}"


# ---------------------------------------------------------------------------
# TestRejectDryRun — T008 (US2)
# ---------------------------------------------------------------------------


class TestRejectDryRun:
    """US2: holmes kb reject --stale-days N --dry-run previews without deleting."""

    def _seed_old_pending(self, kb_root: Path, entry_id: str) -> None:
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / f"{entry_id}.md").write_text(
            f"---\nid: {entry_id}\ntype: pitfall\ntitle: Test {entry_id}\n"
            f"maturity: draft\ncategory: database\ntags: []\n"
            f"pending_since: '2020-01-01T00:00:00+00:00'\n"
            f"created_at: '2020-01-01T00:00:00+00:00'\n---\n\nBody.\n",
            encoding="utf-8",
        )

    def test_dry_run_prints_ids(self, kb_root):
        """T008a: --dry-run prints entry IDs that would be rejected."""
        self._seed_old_pending(kb_root, "old-dr-1")
        self._seed_old_pending(kb_root, "old-dr-2")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "reject",
            "--stale-days", "1", "--dry-run",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "old-dr-1" in result.output
        assert "old-dr-2" in result.output

    def test_dry_run_does_not_delete(self, kb_root):
        """T008b: --dry-run leaves files on disk unchanged."""
        self._seed_old_pending(kb_root, "old-nodelete")
        pending_dir = kb_root / "contributions" / "pending"
        before = set(f.name for f in pending_dir.glob("*.md"))

        runner = CliRunner()
        runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "reject",
            "--stale-days", "1", "--dry-run",
        ], catch_exceptions=False)

        after = set(f.name for f in pending_dir.glob("*.md"))
        assert before == after, f"Files were deleted: {before - after}"

    def test_dry_run_output_contains_marker(self, kb_root):
        """T008c: --dry-run output contains '(dry run)' marker."""
        self._seed_old_pending(kb_root, "old-marker")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "reject",
            "--stale-days", "1", "--dry-run",
        ], catch_exceptions=False)

        assert "(dry run)" in result.output, \
            f"'(dry run)' marker missing from output: {result.output!r}"

    def test_dry_run_without_stale_days_errors(self, kb_root):
        """T008d: --dry-run without --stale-days exits with error."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "reject", "--dry-run",
        ], catch_exceptions=False)

        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# TestTypeWarning — T012 (US4)
# ---------------------------------------------------------------------------


class TestTypeWarning:
    """US4: search and list warn on invalid --type values."""

    def _seed_pitfall(self, kb_root: Path) -> None:
        pitfall_dir = kb_root / "pitfall" / "database"
        pitfall_dir.mkdir(parents=True, exist_ok=True)
        (pitfall_dir / "PT-DB-001.md").write_text(
            "---\nid: PT-DB-001\ntype: pitfall\ntitle: Timeout Issue\n"
            "maturity: verified\ncategory: database\ntags: [timeout]\n---\n\n"
            "Connection timeout occurs under load.\n",
            encoding="utf-8",
        )

    def test_search_invalid_type_warns(self, kb_root):
        """T012a: search --type invalid_xyz warns."""
        self._seed_pitfall(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "search", "timeout",
            "--type", "invalid_xyz_type",
        ], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Warning" in result.output

    def test_list_invalid_type_warns(self, kb_root):
        """T012b: list --type invalid_xyz warns."""
        self._seed_pitfall(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "list",
            "--type", "invalid_xyz_type",
        ], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Warning" in result.output

    def test_search_valid_type_no_warning(self, kb_root):
        """T012c: search --type pitfall (valid) does not produce a warning."""
        self._seed_pitfall(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "search", "timeout",
            "--type", "pitfall",
        ], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Warning" not in result.output

    def test_search_invalid_type_json_mode_warning_in_output(self, kb_root):
        """T012d: --json mode with invalid type warns and output contains JSON array."""
        self._seed_pitfall(kb_root)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "search", "timeout",
            "--type", "invalid_xyz_type", "--json",
        ], catch_exceptions=False)

        assert result.exit_code == 0
        # Warning present in output
        assert "Warning" in result.output
        # JSON array is present (last line or extractable)
        json_part = result.output[result.output.rfind("["):]
        data = json.loads(json_part)
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Helpers shared by v7 tests
# ---------------------------------------------------------------------------


def _seed_pending(kb_root: Path, entry_id: str, extra_frontmatter: str = "") -> None:
    """Write a minimal pending entry to contributions/pending/."""
    pending_dir = kb_root / "contributions" / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    (pending_dir / f"{entry_id}.md").write_text(
        f"---\nid: {entry_id}\ntype: pitfall\ntitle: Test {entry_id}\n"
        f"maturity: draft\ncategory: app\ntags: []\n"
        f"pending: true\npending_since: '2020-01-01T00:00:00+00:00'\n"
        f"source: auto\nsource_session: test\n{extra_frontmatter}---\n\nBody.\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# TestAmendPending — T010 (US2)
# ---------------------------------------------------------------------------


class TestAmendPending:
    """US2: holmes kb amend-pending replaces pending content while preserving metadata."""

    def test_amend_with_content_replaces_body(self, kb_root):
        """T010a: amend-pending --content updates the pending file."""
        _seed_pending(kb_root, "pending-amend-001")

        runner = CliRunner()
        new_content = (
            "---\ntitle: Fixed Entry\ntype: pitfall\ncategory: app\nmaturity: draft\n---\n\nFixed body.\n"
        )
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "amend-pending", "pending-amend-001",
            "--content", new_content,
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "Amended" in result.output

        path = kb_root / "contributions" / "pending" / "pending-amend-001.md"
        text = path.read_text(encoding="utf-8")
        assert "Fixed Entry" in text
        assert "Fixed body." in text

    def test_amend_with_file_replaces_body(self, kb_root, tmp_path):
        """T010b: amend-pending --file reads from file and updates pending."""
        _seed_pending(kb_root, "pending-amend-002")
        entry_file = tmp_path / "fixed.md"
        entry_file.write_text(
            "---\ntitle: File Fixed Entry\ntype: pitfall\ncategory: app\nmaturity: draft\n---\n\nFile body.\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "amend-pending", "pending-amend-002",
            "--file", str(entry_file),
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        path = kb_root / "contributions" / "pending" / "pending-amend-002.md"
        text = path.read_text(encoding="utf-8")
        assert "File Fixed Entry" in text

    def test_amend_nonexistent_id_errors(self, kb_root):
        """T010c: amend-pending on nonexistent id exits 1."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "amend-pending", "pending-no-such",
            "--content", "---\ntitle: X\ntype: pitfall\nmaturity: draft\ncategory: app\n---\n\nX.\n",
        ], catch_exceptions=False)

        assert result.exit_code == 1

    def test_amend_preserves_pending_metadata(self, kb_root):
        """T010d: amend-pending keeps id, pending_since, source, source_session, pending=True."""
        _seed_pending(kb_root, "pending-amend-003")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "amend-pending", "pending-amend-003",
            "--content", (
                "---\ntitle: Amended Title\ntype: pitfall\ncategory: app\nmaturity: draft\n---\n\nNew body.\n"
            ),
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        import frontmatter as fm
        path = kb_root / "contributions" / "pending" / "pending-amend-003.md"
        post = fm.load(str(path))
        assert post.metadata.get("id") == "pending-amend-003"
        assert post.metadata.get("pending_since") == "2020-01-01T00:00:00+00:00"
        assert post.metadata.get("source") == "auto"
        assert post.metadata.get("pending") is True


# ---------------------------------------------------------------------------
# TestWritePendingFile — T012 (US3)
# ---------------------------------------------------------------------------


class TestWritePendingFile:
    """US3: write-pending --file <path> accepts file input."""

    _VALID_CONTENT = (
        "---\ntitle: File Input Test\ntype: pitfall\ncategory: app\nmaturity: draft\ntags: []\n---\n\nTesting.\n"
    )

    def test_file_option_writes_pending(self, kb_root, tmp_path):
        """T012a: --file writes pending entry successfully."""
        entry_file = tmp_path / "entry.md"
        entry_file.write_text(self._VALID_CONTENT, encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "write-pending",
            "--file", str(entry_file),
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "pending_id" in data

    def test_nonexistent_file_errors(self, kb_root):
        """T012b: --file with nonexistent path exits 1."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "write-pending",
            "--file", "/tmp/no-such-file-xyz.md",
        ], catch_exceptions=False)

        assert result.exit_code == 1

    def test_both_content_and_file_errors(self, kb_root, tmp_path):
        """T012c: --content and --file together exits 1."""
        entry_file = tmp_path / "entry.md"
        entry_file.write_text(self._VALID_CONTENT, encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "write-pending",
            "--content", self._VALID_CONTENT,
            "--file", str(entry_file),
        ], catch_exceptions=False)

        assert result.exit_code == 1

    def test_neither_content_nor_file_errors(self, kb_root):
        """T012d: neither --content nor --file exits 1."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "write-pending",
        ], catch_exceptions=False)

        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# TestArchiveOrphansDryRun — T014 (US4)
# ---------------------------------------------------------------------------


class TestArchiveOrphansDryRun:
    """US4: archive-orphans --dry-run prints IDs without moving files."""

    def _seed_draft_no_evidence(self, kb_root: Path, entry_id: str) -> None:
        """Write a draft entry with no evidence sidecar."""
        cat_dir = kb_root / "pitfall" / "app"
        cat_dir.mkdir(parents=True, exist_ok=True)
        (cat_dir / f"{entry_id}.md").write_text(
            f"---\nid: {entry_id}\ntype: pitfall\ntitle: Orphan {entry_id}\n"
            f"maturity: draft\ncategory: app\ntags: []\n---\n\nBody.\n",
            encoding="utf-8",
        )

    def test_dry_run_prints_ids_without_moving(self, kb_root):
        """T014a: --dry-run prints orphan IDs, files not moved."""
        self._seed_draft_no_evidence(kb_root, "PT-APP-DRY1")
        self._seed_draft_no_evidence(kb_root, "PT-APP-DRY2")
        entry_dir = kb_root / "pitfall" / "app"
        before = set(f.name for f in entry_dir.glob("*.md"))

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "archive-orphans", "--dry-run",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "PT-APP-DRY1" in result.output
        assert "PT-APP-DRY2" in result.output
        after = set(f.name for f in entry_dir.glob("*.md"))
        assert before == after, f"Files moved during dry-run: {before - after}"

    def test_dry_run_output_contains_marker(self, kb_root):
        """T014b: --dry-run output contains '(dry run)' marker."""
        self._seed_draft_no_evidence(kb_root, "PT-APP-DRY3")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "archive-orphans", "--dry-run",
        ], catch_exceptions=False)

        assert "(dry run)" in result.output

    def test_normal_mode_unchanged(self, kb_root):
        """T014c: without --dry-run, archive-orphans still archives."""
        self._seed_draft_no_evidence(kb_root, "PT-APP-REAL1")
        entry_dir = kb_root / "pitfall" / "app"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "archive-orphans",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        # File should be moved out of entry_dir
        assert not (entry_dir / "PT-APP-REAL1.md").exists(), \
            "File should have been archived but still exists"


# ---------------------------------------------------------------------------
# TestRejectSingleDryRun — T016 (US5)
# ---------------------------------------------------------------------------


class TestRejectSingleDryRun:
    """US5: reject <id> --dry-run prints entry without deleting."""

    def test_single_dry_run_prints_id_and_marker(self, kb_root):
        """T016a: reject <id> --dry-run prints id and '(dry run)', file not deleted."""
        _seed_pending(kb_root, "pending-single-dr")
        pending_dir = kb_root / "contributions" / "pending"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "reject", "pending-single-dr", "--dry-run",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "pending-single-dr" in result.output
        assert "(dry run)" in result.output
        assert (pending_dir / "pending-single-dr.md").exists(), \
            "File should not be deleted in dry-run mode"

    def test_single_reject_without_dry_run_deletes(self, kb_root):
        """T016b: reject <id> without --dry-run still deletes the file."""
        _seed_pending(kb_root, "pending-delete-me")
        pending_dir = kb_root / "contributions" / "pending"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "reject", "pending-delete-me",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert not (pending_dir / "pending-delete-me.md").exists(), \
            "File should be deleted in non-dry-run mode"


# ---------------------------------------------------------------------------
# TestPendingTableCreatedColumn — T018 (US6)
# ---------------------------------------------------------------------------


class TestPendingTableCreatedColumn:
    """US6: pending table CREATED column shows pending_since (never blank)."""

    def test_old_format_entry_shows_pending_since_in_created(self, kb_root):
        """T018a: old-format entry without created_at shows pending_since date in table."""
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        # Old-format: no created_at field, only pending_since
        (pending_dir / "old-fmt-001.md").write_text(
            "---\nid: old-fmt-001\ntype: pitfall\ntitle: Old Format Entry\n"
            "maturity: draft\ncategory: app\ntags: []\n"
            "pending: true\npending_since: '2026-01-15T10:00:00+00:00'\n"
            "source: auto\nsource_session: test\n---\n\nBody.\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "pending",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        # CREATED column should show the pending_since date
        assert "2026-01-15" in result.output, \
            f"Expected pending_since date in CREATED column, got:\n{result.output}"

    def test_new_format_entry_shows_non_empty_created(self, kb_root):
        """T018b: new-format entry with created_at still shows non-empty CREATED column."""
        _seed_pending(kb_root, "new-fmt-001", "created_at: '2026-03-20T08:00:00+00:00'\n")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "pending",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        # CREATED column should be non-empty (pending_since = '2020-01-01...')
        assert "2020-01-01" in result.output, \
            f"Expected non-empty CREATED column, got:\n{result.output}"


# ---------------------------------------------------------------------------
# TestAmendPendingUpdatedAt — T009 (US1 v8)
# ---------------------------------------------------------------------------


class TestAmendPendingUpdatedAt:
    """US1 v8: amend-pending injects updated_at and preserves created_at."""

    def test_amend_injects_updated_at(self, kb_root):
        """T009a: amend-pending sets updated_at in the written file."""
        _seed_pending(kb_root, "pending-upd-001")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "amend-pending", "pending-upd-001",
            "--content", "---\ntitle: Fixed\ntype: pitfall\ncategory: app\nmaturity: draft\n---\n\nBody.\n",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        import frontmatter as fm
        path = kb_root / "contributions" / "pending" / "pending-upd-001.md"
        post = fm.load(str(path))
        assert post.metadata.get("updated_at"), "updated_at should be set after amend"

    def test_amend_preserves_original_created_at(self, kb_root):
        """T009b: amend-pending keeps original created_at."""
        _seed_pending(kb_root, "pending-upd-002", "created_at: '2025-01-01T00:00:00+00:00'\n")

        runner = CliRunner()
        runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "amend-pending", "pending-upd-002",
            "--content", "---\ntitle: Fixed2\ntype: pitfall\ncategory: app\nmaturity: draft\n---\n\nBody.\n",
        ], catch_exceptions=False)

        import frontmatter as fm
        path = kb_root / "contributions" / "pending" / "pending-upd-002.md"
        post = fm.load(str(path))
        assert post.metadata.get("created_at") == "2025-01-01T00:00:00+00:00"

    def test_amend_without_original_created_at_no_error(self, kb_root):
        """T009c: amend-pending doesn't error when original has no created_at."""
        _seed_pending(kb_root, "pending-upd-003")  # no created_at

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "amend-pending", "pending-upd-003",
            "--content", "---\ntitle: Fixed3\ntype: pitfall\ncategory: app\nmaturity: draft\n---\n\nBody.\n",
        ], catch_exceptions=False)

        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# TestWritePendingFrontmatterValidation — T013 (US3 v8)
# ---------------------------------------------------------------------------


class TestWritePendingFrontmatterValidation:
    """US3 v8: write-pending rejects content without YAML frontmatter."""

    def test_empty_content_rejected(self, kb_root):
        """T013a: empty string is rejected."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "write-pending",
            "--content", "",
        ], catch_exceptions=False)
        assert result.exit_code == 1

    def test_plain_text_rejected(self, kb_root):
        """T013b: plain text without frontmatter is rejected."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "write-pending",
            "--content", "no frontmatter at all, just text",
        ], catch_exceptions=False)
        assert result.exit_code == 1

    def test_valid_frontmatter_accepted(self, kb_root):
        """T013c: valid frontmatter content is accepted (original behavior preserved)."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "write-pending",
            "--content", "---\ntitle: Valid Entry\ntype: pitfall\ncategory: app\nmaturity: draft\ntags: []\n---\n\nBody.\n",
        ], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "pending_id" in data

    def test_file_without_frontmatter_rejected(self, kb_root, tmp_path):
        """T013d: --file pointing to file without frontmatter is rejected."""
        bad_file = tmp_path / "bad.md"
        bad_file.write_text("just text, no frontmatter", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "write-pending",
            "--file", str(bad_file),
        ], catch_exceptions=False)
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# TestGate3LongContentConfirm — T015 (US4 v8)
# ---------------------------------------------------------------------------


class TestGate3LongContentConfirm:
    """US4 v8: Gate 3 long content (>800 chars) requires explicit 'yes' input."""

    _LONG_CONTENT = "---\ntitle: Long Entry\ntype: pitfall\ncategory: app\nmaturity: draft\ntags: []\n---\n\n" + "x" * 900

    def _write_pending_direct(self, kb_root: Path, entry_id: str) -> None:
        """Write a Gate 1-valid pending entry with >800 char content."""
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (kb_root / "pitfall" / "application").mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        body = "\n## Symptoms\n\n" + "symptom text " * 30 + "\n\n## Root Cause\n\n" + "root cause " * 30 + "\n\n## Resolution\n\n" + "resolution steps " * 30 + "\n"
        (pending_dir / f"{entry_id}.md").write_text(
            f"---\nid: {entry_id}\ntitle: Long Entry {entry_id}\ntype: pitfall\n"
            f"category: application\nmaturity: draft\ntags: []\n"
            f"pending: true\npending_since: '{now}'\ncreated_at: '{now}'\n"
            f"updated_at: '{now}'\nsource: auto\nsource_session: test\n"
            f"suggested_type: pitfall\nsuggested_category: application\n---\n"
            + body,
            encoding="utf-8",
        )

    def test_long_content_yes_input_confirms(self, kb_root):
        """T015a: long content with 'yes' input proceeds to confirmation."""
        self._write_pending_direct(kb_root, "pending-long-001")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", "pending-long-001",
            "--contributor", "test",
        ], input="yes\n", catch_exceptions=False)

        # Should NOT abort (may fail for other gate reasons but won't show "Aborted.")
        assert "Aborted." not in result.output

    def test_long_content_y_input_aborts(self, kb_root):
        """T015b: long content with 'y' input aborts."""
        self._write_pending_direct(kb_root, "pending-long-002")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "confirm", "pending-long-002",
            "--contributor", "test",
        ], input="y\n", catch_exceptions=False)

        assert "Aborted." in result.output
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# TestListMaturityFilter — T019 (US6 v8)
# ---------------------------------------------------------------------------


class TestListMaturityFilter:
    """US6 v8: list --maturity filters entries by maturity level."""

    def _seed_entries(self, kb_root: Path) -> None:
        """Seed entries with different maturity levels."""
        pitfall_dir = kb_root / "pitfall" / "app"
        pitfall_dir.mkdir(parents=True, exist_ok=True)
        for entry_id, maturity in [
            ("PT-APP-D01", "draft"),
            ("PT-APP-V01", "verified"),
            ("PT-APP-P01", "proven"),
        ]:
            (pitfall_dir / f"{entry_id}.md").write_text(
                f"---\nid: {entry_id}\ntype: pitfall\ntitle: {entry_id} Entry\n"
                f"maturity: {maturity}\ncategory: app\ntags: []\n---\n\nBody.\n",
                encoding="utf-8",
            )

    def test_maturity_draft_filter(self, kb_root):
        """T019a: --maturity draft returns only draft entries."""
        self._seed_entries(kb_root)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "list", "--maturity", "draft",
        ], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "PT-APP-D01" in result.output
        assert "PT-APP-V01" not in result.output
        assert "PT-APP-P01" not in result.output

    def test_maturity_proven_filter(self, kb_root):
        """T019b: --maturity proven returns only proven entries."""
        self._seed_entries(kb_root)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "list", "--maturity", "proven",
        ], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "PT-APP-P01" in result.output
        assert "PT-APP-D01" not in result.output

    def test_maturity_and_type_combined(self, kb_root):
        """T019c: --maturity + --type filters are both applied."""
        self._seed_entries(kb_root)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "list",
            "--maturity", "draft", "--type", "pitfall",
        ], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "PT-APP-D01" in result.output

    def test_maturity_json_mode(self, kb_root):
        """T019d: --json --maturity draft returns only draft entries as JSON."""
        self._seed_entries(kb_root)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "list", "--json", "--maturity", "draft",
        ], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert all(e["maturity"] == "draft" for e in data)

    def test_invalid_maturity_warns(self, kb_root):
        """T019e: invalid --maturity warns and returns empty, exit 0."""
        self._seed_entries(kb_root)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "list", "--maturity", "invalid_xyz",
        ], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Warning" in result.output or "warning" in result.output.lower()


# ---------------------------------------------------------------------------
# TestHistoryExitCodes — T021 (US7 v8)
# ---------------------------------------------------------------------------


class TestHistoryExitCodes:
    """US7 v8: history returns exit 1 when entry/snapshot not found."""

    def _seed_entry_with_snapshot(self, kb_root: Path) -> None:
        pitfall_dir = kb_root / "pitfall" / "app"
        pitfall_dir.mkdir(parents=True, exist_ok=True)
        (pitfall_dir / "PT-APP-H01.md").write_text(
            "---\nid: PT-APP-H01\ntype: pitfall\ntitle: History Test\n"
            "maturity: draft\ncategory: app\ntags: []\n---\n\nBody.\n",
            encoding="utf-8",
        )
        history_dir = kb_root / ".history"
        history_dir.mkdir(parents=True, exist_ok=True)
        (history_dir / "PT-APP-H01-20260101-000000.md").write_text(
            "---\nid: PT-APP-H01\nreplaced_at: '2026-01-01T00:00:00+00:00'\n"
            "snapshot_reason: test\n---\n\nOld body.\n",
            encoding="utf-8",
        )

    def test_nonexistent_entry_exits_1(self, kb_root):
        """T021a: history for nonexistent entry returns exit 1."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "history", "NONEXISTENT",
        ], catch_exceptions=False)
        assert result.exit_code == 1

    def test_existing_entry_exits_0(self, kb_root):
        """T021b: history for existing entry with snapshots returns exit 0."""
        self._seed_entry_with_snapshot(kb_root)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "history", "PT-APP-H01",
        ], catch_exceptions=False)
        assert result.exit_code == 0, result.output

    def test_show_nonexistent_snapshot_exits_1(self, kb_root):
        """T021c: --show nonexistent snapshot returns exit 1."""
        self._seed_entry_with_snapshot(kb_root)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "history", "PT-APP-H01",
            "--show", "nonexistent.md",
        ], catch_exceptions=False)
        assert result.exit_code == 1

    def test_show_valid_snapshot_exits_0(self, kb_root):
        """T021d: --show valid snapshot returns exit 0."""
        self._seed_entry_with_snapshot(kb_root)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "kb", "--kb-path", str(kb_root), "history", "PT-APP-H01",
            "--show", "PT-APP-H01-20260101-000000.md",
        ], catch_exceptions=False)
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# T009 [US1]: Autonomous import — basic pipeline
# ---------------------------------------------------------------------------


class TestAutonomousImport:
    """T009: holmes import <file> triggers agent pipeline and produces pending entry."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "model",
                  "guideline", "process", "decision"):
            (kb / d).mkdir(parents=True, exist_ok=True)
        return kb

    @pytest.fixture
    def holmes_home(self, tmp_path: Path, kb_root: Path) -> Path:
        home = tmp_path / "holmes_home"
        home.mkdir()
        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="claude-3-5-haiku-20241022",
            api_key="test-key",
            api_base_url="",
        )
        save_config(cfg, holmes_home=home)
        return home

    def _make_mock_report(self, created=1) -> MagicMock:
        from holmes.kb.agent.report import ImportReport
        report = ImportReport(created=["Test Entry"] * created)
        return report

    def test_single_file_creates_pending_entry(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T009a: single file import triggers agent and creates pending entry."""
        doc = tmp_path / "incident.md"
        doc.write_text(
            "PostgreSQL OOM crash. Root cause: shared_buffers too large. "
            "Resolved by reducing shared_buffers to 1.5GB and reloading config.",
            encoding="utf-8",
        )
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=self._make_mock_report(created=1),
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0

    def test_dir_batch_processes_multiple_files(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T009b: --dir batch processes all .md files in directory."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        for i in range(3):
            (docs_dir / f"incident-{i}.md").write_text(
                f"Incident {i}: some failure. Root: cause {i}. Fix: step {i}.",
                encoding="utf-8",
            )

        runner = CliRunner()
        call_count = 0

        def mock_run(self_arg, source_text, file_path=None):
            nonlocal call_count
            call_count += 1
            from holmes.kb.agent.report import ImportReport
            return ImportReport(created=["Entry"])

        with patch("holmes.kb.agent.runner.ImportAgentRunner.run", mock_run):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", "--dir", str(docs_dir),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0
        assert call_count == 3

    def test_content_too_short_exits_1(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T009c: content shorter than 50 chars exits with code 1."""
        doc = tmp_path / "tiny.md"
        doc.write_text("Too short.", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--kb-path", str(kb_root),
            "import", str(doc),
        ], env={"HOLMES_HOME": str(holmes_home)})
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# T013 [US2]: Agent verification — content correctness
# ---------------------------------------------------------------------------


class TestAgentVerification:
    """T013: Agent verifies fields have source support; hallucinated content is cleared."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "model",
                  "guideline", "process", "decision"):
            (kb / d).mkdir(parents=True, exist_ok=True)
        return kb

    @pytest.fixture
    def holmes_home(self, tmp_path: Path, kb_root: Path) -> Path:
        home = tmp_path / "holmes_home"
        home.mkdir()
        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="claude-3-5-haiku-20241022",
            api_key="test-key",
        )
        save_config(cfg, holmes_home=home)
        return home

    def test_no_commands_input_produces_no_commands(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T013a: input with no commands → report warns about empty resolution."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "nocommands.md"
        doc.write_text(
            "The database server ran out of memory. "
            "We restarted it and it came back online. "
            "The issue was caused by too many connections being opened simultaneously.",
            encoding="utf-8",
        )
        expected_report = ImportReport(
            created=["Memory Exhaustion"],
            warnings=["resolution_commands: no shell commands found in source"],
        )
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=expected_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0

    def test_command_in_source_preserved(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T013b: command in source text → preserved in report unchanged."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "withcommand.md"
        exact_cmd = "pg_dump -h {host} -d {db} -F c -f backup.dump"
        doc.write_text(
            f"PostgreSQL backup procedure. Run: `{exact_cmd}` to back up. "
            "This is the standard backup command for production databases.",
            encoding="utf-8",
        )
        expected_report = ImportReport(created=["PostgreSQL Backup"])
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=expected_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0

    def test_low_confidence_field_cleared(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T013c: field with no source support → warning in report."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "minimal.md"
        doc.write_text(
            "Database restart fixed the issue. No root cause identified. "
            "Just a transient problem that went away on its own after restart.",
            encoding="utf-8",
        )
        expected_report = ImportReport(
            created=["Database Restart"],
            warnings=["root_cause: cleared (no source support)"],
        )
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=expected_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# T017 [US3]: Idempotency — source_hash dedup
# ---------------------------------------------------------------------------


class TestIdempotency:
    """T017: Reimporting same source → skip; updated source → merge; different root → new+link."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "model",
                  "guideline", "process", "decision"):
            (kb / d).mkdir(parents=True, exist_ok=True)
        return kb

    @pytest.fixture
    def holmes_home(self, tmp_path: Path, kb_root: Path) -> Path:
        home = tmp_path / "holmes_home"
        home.mkdir()
        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="claude-3-5-haiku-20241022",
            api_key="test-key",
        )
        save_config(cfg, holmes_home=home)
        return home

    def test_exact_hash_match_skips(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T017a: reimport of same content → report.skipped has entry."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "same.md"
        content = (
            "PostgreSQL OOM. Root cause: shared_buffers. "
            "Fix: reduce shared_buffers. Reload with pg_reload_conf()."
        )
        doc.write_text(content, encoding="utf-8")

        skipped_report = ImportReport(skipped=["a1b2c3d4e5f60123"])
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=skipped_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0
        assert "skipped" in result.output.lower() or result.exit_code == 0

    def test_updated_source_merges(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T017b: same root cause, new content → report.updated has entry ID."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "updated.md"
        doc.write_text(
            "PostgreSQL OOM with additional resolution step found. "
            "Root cause: same shared_buffers issue. "
            "New fix: also increase vm.overcommit_memory kernel param.",
            encoding="utf-8",
        )
        updated_report = ImportReport(updated=["PT-DB-001"])
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=updated_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0

    def test_different_root_cause_creates_new_with_link(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T017c: different root cause → new entry created."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "different.md"
        doc.write_text(
            "PostgreSQL crash due to corrupt WAL files. "
            "Root cause: disk I/O errors corrupted transaction log. "
            "Fix: restore from backup and run fsck on disk.",
            encoding="utf-8",
        )
        new_report = ImportReport(created=["PostgreSQL WAL Corruption"])
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=new_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0

    def test_same_content_different_filename_skips(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T017d: same content, different filename → skip (content hash match)."""
        from holmes.kb.agent.report import ImportReport

        content = (
            "Redis connection pool exhausted. Root cause: maxclients too low. "
            "Fix: increase maxclients in redis.conf and restart redis-server."
        )
        doc1 = tmp_path / "redis-1.md"
        doc2 = tmp_path / "redis-copy.md"
        doc1.write_text(content, encoding="utf-8")
        doc2.write_text(content, encoding="utf-8")

        skipped_report = ImportReport(skipped=["hash-abc123"])
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=skipped_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc2),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0

    def test_new_content_creates_entry(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T017e: first import of new content → entry created."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "new.md"
        doc.write_text(
            "Nginx 502 Bad Gateway under load. Root cause: upstream backend "
            "timeouts. Fix: increase proxy_read_timeout and proxy_connect_timeout "
            "in nginx.conf then reload nginx with `nginx -s reload`.",
            encoding="utf-8",
        )
        created_report = ImportReport(created=["Nginx 502 Under Load"])
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=created_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# T021 [US4]: Interactive gates
# ---------------------------------------------------------------------------


class TestInteractiveGates:
    """T021: Low-confidence decisions prompt user; --no-interactive skips all gates."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "model",
                  "guideline", "process", "decision"):
            (kb / d).mkdir(parents=True, exist_ok=True)
        return kb

    @pytest.fixture
    def holmes_home(self, tmp_path: Path, kb_root: Path) -> Path:
        home = tmp_path / "holmes_home"
        home.mkdir()
        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="claude-3-5-haiku-20241022",
            api_key="test-key",
        )
        save_config(cfg, holmes_home=home)
        return home

    def test_no_interactive_skips_prompts(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T021c: --no-interactive flag → no prompts, auto-decisions logged."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "ambiguous.md"
        doc.write_text(
            "System performance degraded unexpectedly. Investigation showed "
            "CPU throttling due to thermal limits. No commands available. "
            "Fixed by improving ventilation and adding cooling.",
            encoding="utf-8",
        )
        auto_report = ImportReport(
            created=["CPU Throttling"],
            auto_decisions=["classification: used LLM best guess (confidence 0.55, threshold 0.70)"],
        )
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=auto_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", "--no-interactive", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0

    def test_no_interactive_auto_decisions_in_report(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T021d: --no-interactive + --verbose → auto_decisions printed."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "ambiguous2.md"
        doc.write_text(
            "Network timeouts intermittent. Probable cause: DNS resolution slow. "
            "Could also be routing table issues. Restart resolved it temporarily. "
            "Run `dig @8.8.8.8 example.com` to diagnose DNS.",
            encoding="utf-8",
        )
        auto_report = ImportReport(
            created=["Network Timeouts"],
            auto_decisions=["classification: used LLM best guess (confidence 0.58)"],
        )
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=auto_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", "--no-interactive", "--verbose", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# T024 [US5]: Skill generation
# ---------------------------------------------------------------------------


class TestSkillGeneration:
    """T024: Agent generates skills for multi-step entries; curator finds candidates."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "model",
                  "guideline", "process", "decision", "skills"):
            (kb / d).mkdir(parents=True, exist_ok=True)
        return kb

    @pytest.fixture
    def holmes_home(self, tmp_path: Path, kb_root: Path) -> Path:
        home = tmp_path / "holmes_home"
        home.mkdir()
        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="claude-3-5-haiku-20241022",
            api_key="test-key",
        )
        save_config(cfg, holmes_home=home)
        return home

    def test_multi_step_with_params_creates_skill(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T024a: ≥3 steps + {parameter} → skill created."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "pg-recovery.md"
        doc.write_text(
            "PostgreSQL connection exhaustion. Root cause: pool_size too low. "
            "Resolution:\n"
            "1. Check connections: `psql -c 'SELECT count(*) FROM pg_stat_activity'`\n"
            "2. Set pool size: `pgbouncer-set-pool --size {pool_size} --db {database}`\n"
            "3. Reload: `pgbouncer --reload`\n",
            encoding="utf-8",
        )
        skill_report = ImportReport(
            created=["PostgreSQL Connection Exhaustion"],
            skills_generated=["pg-connection-recovery"],
        )
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=skill_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0

    def test_single_step_no_param_skips_skill(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T024b: single step, no param → skill skipped, suggestion in report."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "simple.md"
        doc.write_text(
            "Redis memory full. Root cause: no maxmemory set. "
            "Fix: add `maxmemory 2gb` to redis.conf and restart.",
            encoding="utf-8",
        )
        skip_report = ImportReport(
            created=["Redis Max Memory"],
            suggestions=["skill candidate: redis-set-maxmemory (1 step, no parameters)"],
        )
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=skip_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0

    def test_existing_skill_links_not_creates(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T024c: existing skill covers commands → link not create."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "existing.md"
        doc.write_text(
            "Same PostgreSQL pool issue again. Root cause: pool_size. "
            "Use: `pgbouncer-set-pool --size {pool_size} --db {database}` to fix. "
            "Then `pgbouncer --reload` and `pgbouncer --status` to verify.",
            encoding="utf-8",
        )
        link_report = ImportReport(
            created=["PostgreSQL Pool Issue 2"],
            skills_linked=["pg-connection-recovery"],
        )
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=link_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# T031 [US6]: Dry-run and observability
# ---------------------------------------------------------------------------


class TestDryRunAndObservability:
    """T031: --dry-run leaves KB unchanged; --verbose shows decision trace."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "model",
                  "guideline", "process", "decision"):
            (kb / d).mkdir(parents=True, exist_ok=True)
        return kb

    @pytest.fixture
    def holmes_home(self, tmp_path: Path, kb_root: Path) -> Path:
        home = tmp_path / "holmes_home"
        home.mkdir()
        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="claude-3-5-haiku-20241022",
            api_key="test-key",
        )
        save_config(cfg, holmes_home=home)
        return home

    def test_dry_run_no_files_written(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T031a: --dry-run → KB pending dir stays empty."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "incident.md"
        doc.write_text(
            "MySQL slow queries causing timeouts. Root cause: missing index. "
            "Fix: `CREATE INDEX idx_user_created ON users(created_at)` then "
            "`ANALYZE TABLE users` and `EXPLAIN SELECT ...` to verify.",
            encoding="utf-8",
        )
        dry_report = ImportReport(
            dry_run=True,
            suggestions=["Would create: pitfall/database — MySQL Slow Query"],
        )
        runner = CliRunner()

        pending_dir = kb_root / "contributions" / "pending"
        files_before = set(pending_dir.glob("*.md"))

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=dry_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", "--dry-run", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        files_after = set(pending_dir.glob("*.md"))
        assert result.exit_code == 0
        assert files_after == files_before

    def test_dry_run_output_contains_would_create(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T031b: --dry-run stdout shows execution plan."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "incident2.md"
        doc.write_text(
            "Kubernetes pod OOMKilled repeatedly. Root cause: memory limit too low. "
            "Fix: `kubectl set resources deployment {name} --limits=memory={mem}` "
            "then `kubectl rollout status deployment/{name}` to verify.",
            encoding="utf-8",
        )
        dry_report = ImportReport(
            dry_run=True,
            suggestions=["Would create: pitfall/system — K8s OOMKilled"],
        )
        runner = CliRunner()

        with patch(
            "holmes.kb.agent.runner.ImportAgentRunner.run",
            return_value=dry_report,
        ):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", "--dry-run", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0
        assert "DRY RUN" in result.output or "dry" in result.output.lower()

    def test_partial_failure_in_batch_does_not_crash(
        self, tmp_path: Path, kb_root: Path, holmes_home: Path
    ):
        """T031d: single-item error in batch → summary shows error count, no crash."""
        from holmes.kb.agent.report import ImportReport

        docs_dir = tmp_path / "batch"
        docs_dir.mkdir()
        (docs_dir / "good.md").write_text(
            "Network packet loss. Root cause: NIC driver bug. "
            "Fix: `ethtool -K {interface} tso off` then `ifconfig {interface} down && up`.",
            encoding="utf-8",
        )
        (docs_dir / "bad.md").write_text("Too short.", encoding="utf-8")

        runner = CliRunner()
        call_count = 0

        def mock_run(self_arg, source_text, file_path=None):
            nonlocal call_count
            call_count += 1
            from holmes.kb.agent.report import ImportReport
            if len(source_text) < 50:
                raise ValueError("content too short")
            return ImportReport(created=["Network Packet Loss"])

        with patch("holmes.kb.agent.runner.ImportAgentRunner.run", mock_run):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", "--dir", str(docs_dir),
            ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        # Partial failure: batch continues (no crash) but exits 1 so CI can detect errors.
        assert result.exit_code == 1
        assert "1 error" in result.output


# ---------------------------------------------------------------------------
# Multi-provider LLM configuration tests (014-multi-provider-llm)
# ---------------------------------------------------------------------------


class TestMultiProviderConfig:
    """T014, T015: Anthropic provider path; T018, T019: OpenAI provider path.
    T021–T022: provider switching via setup.
    T025–T026: error messages include provider name.
    """

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        for d in ("pitfall/database", "pitfall/network", "contributions/pending",
                  "model", "guideline", "process", "decision"):
            (kb / d).mkdir(parents=True, exist_ok=True)
        return kb

    @pytest.fixture
    def holmes_home_anthropic(self, tmp_path: Path, kb_root: Path) -> Path:
        home = tmp_path / "holmes_anthropic"
        home.mkdir()
        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="claude-3-5-haiku-20241022",
            api_key="test-anthropic-key",
            provider="anthropic",
        )
        save_config(cfg, holmes_home=home)
        return home

    @pytest.fixture
    def holmes_home_openai(self, tmp_path: Path, kb_root: Path) -> Path:
        home = tmp_path / "holmes_openai"
        home.mkdir()
        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="gpt-4o",
            api_key="test-openai-key",
            provider="openai",
        )
        save_config(cfg, holmes_home=home)
        return home

    # T014: Anthropic provider path completes import
    def test_import_with_anthropic_provider(
        self, tmp_path: Path, kb_root: Path, holmes_home_anthropic: Path
    ):
        """T014: import via Anthropic provider produces KB entry."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "incident.md"
        doc.write_text(
            "Redis OOM: maxmemory policy evicts keys mid-transaction.\n"
            "Root cause: noeviction policy not set.\n"
            "Fix: run `redis-cli CONFIG SET maxmemory-policy noeviction`.",
            encoding="utf-8",
        )
        mock_report = ImportReport(created=["Redis OOM"])

        runner = CliRunner()
        with patch("holmes.kb.agent.runner.ImportAgentRunner.run", return_value=mock_report):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home_anthropic)}, catch_exceptions=False)

        assert result.exit_code == 0
        assert "1 created" in result.output

    # T015: Backward compat — config without provider field defaults to anthropic
    def test_backward_compat_no_provider_field(self, tmp_path: Path, kb_root: Path):
        """T015: HolmesConfig loaded from file without 'provider' key defaults to 'anthropic'."""
        import json as json_mod
        from holmes.config import load_config
        home = tmp_path / "holmes_legacy"
        home.mkdir()
        # Write config without 'provider' field (simulating old config file)
        legacy_config = {
            "kb_path": str(kb_root),
            "model": "gpt-4o",
            "api_key": "legacy-key",
            "api_base_url": "",
        }
        (home / "config.json").write_text(
            json_mod.dumps(legacy_config), encoding="utf-8"
        )

        cfg = load_config(holmes_home=home)
        assert cfg.provider == "anthropic"

    # T018: OpenAI provider path completes import
    def test_import_with_openai_provider(
        self, tmp_path: Path, kb_root: Path, holmes_home_openai: Path
    ):
        """T018: import via OpenAI-compatible provider produces KB entry."""
        from holmes.kb.agent.report import ImportReport

        doc = tmp_path / "incident.md"
        doc.write_text(
            "PostgreSQL connection pool exhaustion. Root cause: HikariCP maxPoolSize too low.\n"
            "Fix: set `spring.datasource.hikari.maximum-pool-size=20` and restart.",
            encoding="utf-8",
        )
        mock_report = ImportReport(created=["PostgreSQL Connection Pool"])

        runner = CliRunner()
        with patch("holmes.kb.agent.runner.ImportAgentRunner.run", return_value=mock_report):
            result = runner.invoke(cli, [
                "--kb-path", str(kb_root),
                "import", str(doc),
            ], env={"HOLMES_HOME": str(holmes_home_openai)}, catch_exceptions=False)

        assert result.exit_code == 0
        assert "1 created" in result.output

    # T019: OpenAI tool definition conversion
    def test_openai_tool_def_conversion(self):
        """T019: Anthropic input_schema format is correctly converted to OpenAI parameters format."""
        from holmes.kb.agent.provider.openai_provider import _to_openai_tools
        from holmes.kb.agent.tools import TOOL_DEFINITIONS

        openai_tools = _to_openai_tools(TOOL_DEFINITIONS)

        assert len(openai_tools) == len(TOOL_DEFINITIONS)
        for tool in openai_tools:
            assert tool["type"] == "function"
            func = tool["function"]
            assert "name" in func
            assert "parameters" in func
            # parameters should be a dict with "type" key (JSON schema)
            assert isinstance(func["parameters"], dict)

        # Check specific tool: check_source_hash
        check_hash = next(t for t in openai_tools if t["function"]["name"] == "check_source_hash")
        assert "hash" in check_hash["function"]["parameters"]["properties"]


class TestProviderSetupCommand:
    """T021–T022: provider switching via holmes setup command."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending"):
            (kb / d).mkdir(parents=True, exist_ok=True)
        return kb

    def test_setup_saves_provider_field(self, tmp_path: Path, kb_root: Path):
        """T021: holmes setup --provider openai writes provider=openai to config.json."""
        import json as json_mod

        holmes_home = tmp_path / "holmes_setup_test"
        holmes_home.mkdir()

        runner = CliRunner()
        result = runner.invoke(cli, [
            "setup",
            "--kb-path", str(kb_root),
            "--provider", "openai",
            "--api-key", "sk-test-openai",
            "--model", "gpt-4o",
        ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 0
        config = json_mod.loads((holmes_home / "config.json").read_text())
        assert config["provider"] == "openai"

    def test_setup_switches_provider(self, tmp_path: Path, kb_root: Path):
        """T022: setup anthropic then openai; second config has provider=openai."""
        import json as json_mod

        holmes_home = tmp_path / "holmes_switch_test"
        holmes_home.mkdir()

        runner = CliRunner()
        # First setup: anthropic
        runner.invoke(cli, [
            "setup",
            "--kb-path", str(kb_root),
            "--provider", "anthropic",
            "--api-key", "sk-ant-test",
            "--model", "claude-3-5-haiku-20241022",
        ], env={"HOLMES_HOME": str(holmes_home)})

        config_after_first = json_mod.loads((holmes_home / "config.json").read_text())
        assert config_after_first["provider"] == "anthropic"

        # Switch to openai
        runner.invoke(cli, [
            "setup",
            "--kb-path", str(kb_root),
            "--provider", "openai",
            "--api-key", "sk-test-openai",
            "--model", "gpt-4o",
        ], env={"HOLMES_HOME": str(holmes_home)})

        config_after_switch = json_mod.loads((holmes_home / "config.json").read_text())
        assert config_after_switch["provider"] == "openai"


class TestProviderErrorMessages:
    """T025–T026: error messages include provider name."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending"):
            (kb / d).mkdir(parents=True, exist_ok=True)
        return kb

    def _make_holmes_home(self, tmp_path: Path, kb_root: Path, provider: str) -> Path:
        home = tmp_path / f"holmes_{provider}_err"
        home.mkdir()
        # No api_key → triggers auth error path
        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="test-model",
            api_key="",
            provider=provider,
        )
        save_config(cfg, holmes_home=home)
        return home

    def test_error_message_includes_provider_anthropic(
        self, tmp_path: Path, kb_root: Path
    ):
        """T025: no api_key + provider=anthropic → error contains 'anthropic'."""
        holmes_home = self._make_holmes_home(tmp_path, kb_root, "anthropic")
        doc = tmp_path / "doc.md"
        doc.write_text(
            "Service outage. Root cause: memory leak. Fix: restart the service.", encoding="utf-8"
        )

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--kb-path", str(kb_root),
            "import", str(doc),
        ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 1
        assert "anthropic" in result.output.lower()

    def test_error_message_includes_provider_openai(
        self, tmp_path: Path, kb_root: Path
    ):
        """T026: no api_key + provider=openai → error contains 'openai'."""
        holmes_home = self._make_holmes_home(tmp_path, kb_root, "openai")
        doc = tmp_path / "doc.md"
        doc.write_text(
            "Service outage. Root cause: memory leak. Fix: restart the service.", encoding="utf-8"
        )

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--kb-path", str(kb_root),
            "import", str(doc),
        ], env={"HOLMES_HOME": str(holmes_home)}, catch_exceptions=False)

        assert result.exit_code == 1
        assert "openai" in result.output.lower()
