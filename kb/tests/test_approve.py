"""Tests for M6a — Pending/Approve 基础流程.

Covers:
- approve_entry: move pending → confirmed, kb_status=active
- deprecate_entry: in-place kb_status=deprecated, no file move
- find_entries_by_source_file: scans _pending/ + confirmed
- Three-layer scenario: confirmed + old pending + new pending
- holmes pending: category grouping + legacy compat (CLI)
- holmes approve: basic + conflict detection (CLI)

Pending entries are written in the legacy ``_pending/<type>/<category>/``
layout via the local ``_write_pending`` helper — this keeps coverage of the
read-only compatibility scan retained for one version cycle (spec 043, D8).
The canonical ``contributions/pending/`` writer is ``holmes.kb.pending.write_pending``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import frontmatter
import pytest
from click.testing import CliRunner

from holmes.cli import cli
from holmes.kb.store import (
    approve_entry,
    deprecate_entry,
    find_entries_by_source_file,
    list_entries,
)

# Permanent IDs minted by generate_id (spec 043, D2/T021b): e.g. PT-HW-a3f8c2.
PERMANENT_ID_RE = re.compile(r"[A-Z]{2}-[A-Z]{2,3}-[0-9a-f]{6}")


def _approved_files(kb_root: Path, category: str = "hardware") -> list[Path]:
    """Return the confirmed entry files under pitfall/<category>/ (may be empty)."""
    d = kb_root / "pitfall" / category
    return sorted(d.glob("*.md")) if d.is_dir() else []


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch: pytest.MonkeyPatch):
    """Keep approve CLI tests hermetic: provider creation fails, so the
    semantic dedup gate degrades to skip instead of making real LLM calls."""
    def _raise(cfg):
        raise RuntimeError("no LLM provider in tests")
    monkeypatch.setattr("holmes.kb.agent.provider.factory.create_provider", _raise)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    entry_id: str,
    *,
    kb_type: str = "pitfall",
    category: str = "hardware",
    kb_status: str = "active",
    source_file: str = "",
    source_hash: str = "",
) -> str:
    src_line = f"source_file: {source_file}\n" if source_file else ""
    hash_line = f"source_hash: {source_hash}\n" if source_hash else ""
    return (
        f"---\n"
        f"id: {entry_id}\n"
        f"type: {kb_type}\n"
        f"title: Test Entry {entry_id}\n"
        f"category: {category}\n"
        f"kb_status: {kb_status}\n"
        f"maturity: draft\n"
        f"decay_status: active\n"
        f"created_at: '2026-06-24'\n"
        f"updated_at: '2026-06-24'\n"
        f"{src_line}"
        f"{hash_line}"
        f"---\n\n## Description\nTest entry.\n"
    )


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    """Return a fresh temporary KB root directory."""
    return tmp_path


# ---------------------------------------------------------------------------
# Helpers — legacy-format pending writer
# ---------------------------------------------------------------------------

def _write_pending(kb_root: Path, entry_id: str, content: str, entry_type: str, category: str) -> Path:
    """Write an entry to the legacy ``_pending/<entry_type>/<category>/<entry_id>.md`` path."""
    pending_dir = kb_root / "_pending" / entry_type / category
    pending_dir.mkdir(parents=True, exist_ok=True)
    path = pending_dir / f"{entry_id}.md"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# T005 — approve_entry
# ---------------------------------------------------------------------------

class TestApproveEntry:
    def test_approve_moves_file_to_confirmed(self, kb_root: Path) -> None:
        _write_pending(kb_root, "hw-init-001", _make_entry("hw-init-001", kb_status="pending"), "pitfall", "hardware")
        new_path = approve_entry(kb_root, "hw-init-001")
        # Approved entry lands in <type>/ (pitfall/) under a newly minted
        # permanent ID — the temporary pending ID never becomes official.
        new_id = new_path.stem
        assert PERMANENT_ID_RE.fullmatch(new_id)
        assert new_path == kb_root / "pitfall" / "hardware" / f"{new_id}.md"
        assert new_path.exists()
        post = frontmatter.load(str(new_path))
        assert post.metadata["id"] == new_id
        assert post.metadata["former_id"] == "hw-init-001"

    def test_approve_removes_pending_file(self, kb_root: Path) -> None:
        _write_pending(kb_root, "hw-init-001", _make_entry("hw-init-001", kb_status="pending"), "pitfall", "hardware")
        pending_path = kb_root / "_pending" / "pitfall" / "hardware" / "hw-init-001.md"
        assert pending_path.exists()
        approve_entry(kb_root, "hw-init-001")
        assert not pending_path.exists()

    def test_approve_sets_kb_status_active(self, kb_root: Path) -> None:
        _write_pending(kb_root, "hw-init-001", _make_entry("hw-init-001", kb_status="pending"), "pitfall", "hardware")
        new_path = approve_entry(kb_root, "hw-init-001")
        post = frontmatter.load(str(new_path))
        assert post.metadata["kb_status"] == "active"

    def test_approve_creates_type_dir(self, kb_root: Path) -> None:
        _write_pending(kb_root, "net-001", _make_entry("net-001", kb_status="pending", category="network"), "pitfall", "network")
        assert not (kb_root / "pitfall").exists()
        approve_entry(kb_root, "net-001")
        # type=pitfall → pitfall/network/ directory created
        assert (kb_root / "pitfall" / "network").is_dir()

    def test_approve_nonexistent_raises(self, kb_root: Path) -> None:
        with pytest.raises(FileNotFoundError, match="not found in the pending area"):
            approve_entry(kb_root, "does-not-exist")

    def test_approved_entry_visible_in_list(self, kb_root: Path) -> None:
        _write_pending(kb_root, "hw-init-001", _make_entry("hw-init-001", kb_status="pending"), "pitfall", "hardware")
        new_path = approve_entry(kb_root, "hw-init-001")
        # Entry lands in pitfall/hardware/ (type/category) → list_entries finds it.
        entries = list_entries(kb_root, kb_status="active")
        assert any(e.id == new_path.stem for e in entries)


# ---------------------------------------------------------------------------
# T021b — approve mints a permanent ID (spec 043, D2)
# ---------------------------------------------------------------------------

class TestApprovePermanentId:
    def test_corrects_reference_preserved(self, kb_root: Path) -> None:
        """`corrects` points at another official entry and must survive approve."""
        content = _make_entry("hw-001", kb_status="pending").replace(
            "---\n\n## Description", "corrects: PT-HW-a1b2c3\n---\n\n## Description"
        )
        _write_pending(kb_root, "hw-001", content, "pitfall", "hardware")
        new_path = approve_entry(kb_root, "hw-001")
        post = frontmatter.load(str(new_path))
        assert post.metadata["corrects"] == "PT-HW-a1b2c3"
        assert post.metadata["id"] == new_path.stem
        assert PERMANENT_ID_RE.fullmatch(new_path.stem)

    def test_self_reference_in_body_rewritten(self, kb_root: Path) -> None:
        """Body self-references to the temporary ID are rewritten to the new ID."""
        content = _make_entry("hw-001", kb_status="pending") + (
            "\nSee also hw-001 for the full history.\n"
        )
        _write_pending(kb_root, "hw-001", content, "pitfall", "hardware")
        new_path = approve_entry(kb_root, "hw-001")
        new_id = new_path.stem
        body = new_path.read_text(encoding="utf-8")
        assert f"See also {new_id} for the full history." in body

    def test_evidence_sidecar_dir_migrated(self, kb_root: Path) -> None:
        """contributions/evidence/<old_id>/ moves to <new_id>/ on approve."""
        _write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending"), "pitfall", "hardware")
        old_evidence = kb_root / "contributions" / "evidence" / "hw-001"
        old_evidence.mkdir(parents=True)
        (old_evidence / "sess-1.json").write_text(
            json.dumps({"session_id": "sess-1", "outcome": "referenced"}),
            encoding="utf-8",
        )
        new_path = approve_entry(kb_root, "hw-001")
        new_evidence = kb_root / "contributions" / "evidence" / new_path.stem
        assert not old_evidence.exists(), "old evidence dir must be migrated away"
        record = json.loads((new_evidence / "sess-1.json").read_text(encoding="utf-8"))
        assert record["session_id"] == "sess-1"

    def test_log_records_id_mapping(self, kb_root: Path) -> None:
        """contributions/log.md records the old→new ID mapping."""
        _write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending"), "pitfall", "hardware")
        new_path = approve_entry(kb_root, "hw-001")
        log = (kb_root / "contributions" / "log.md").read_text(encoding="utf-8")
        assert "approve" in log
        assert new_path.stem in log
        assert "former_id=hw-001" in log


# ---------------------------------------------------------------------------
# T006 — deprecate_entry
# ---------------------------------------------------------------------------

class TestDeprecateEntry:
    def _write_confirmed(self, kb_root: Path, entry_id: str, category: str = "hardware") -> Path:
        """Write a confirmed (active) entry directly to pitfall/<category>/<id>.md."""
        content = _make_entry(entry_id, kb_type="pitfall", category=category, kb_status="active")
        path = kb_root / "pitfall" / category / f"{entry_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_deprecate_sets_kb_status(self, kb_root: Path) -> None:
        path = self._write_confirmed(kb_root, "hw-001")
        result = deprecate_entry(kb_root, "hw-001")
        assert result is True
        post = frontmatter.load(str(path))
        assert post.metadata["kb_status"] == "deprecated"

    def test_deprecate_does_not_move_file(self, kb_root: Path) -> None:
        path = self._write_confirmed(kb_root, "hw-001")
        deprecate_entry(kb_root, "hw-001")
        assert path.exists(), "File must not be moved or deleted"

    def test_deprecate_nonexistent_returns_false(self, kb_root: Path) -> None:
        result = deprecate_entry(kb_root, "does-not-exist")
        assert result is False

    def test_deprecate_pending_entry_returns_false(self, kb_root: Path) -> None:
        """deprecate_entry must not modify pending entries."""
        _write_pending(kb_root, "hw-pending-001", _make_entry("hw-pending-001", kb_status="pending"), "pitfall", "hardware")
        # The entry is in _pending/ — deprecate_entry should refuse.
        result = deprecate_entry(kb_root, "hw-pending-001")
        assert result is False


# ---------------------------------------------------------------------------
# T004 — find_entries_by_source_file (with _pending/ coverage)
# ---------------------------------------------------------------------------

class TestFindEntriesBySourceFile:
    def test_finds_new_pending_entry(self, kb_root: Path) -> None:
        content = _make_entry("hw-001", kb_status="pending", source_file="docs/hw.md")
        _write_pending(kb_root, "hw-001", content, "pitfall", "hardware")
        results = find_entries_by_source_file(kb_root, "docs/hw.md")
        assert any(e.id == "hw-001" for e in results)

    def test_finds_confirmed_entry(self, kb_root: Path) -> None:
        content = _make_entry("hw-old-001", kb_status="active", source_file="docs/hw.md")
        path = kb_root / "pitfall" / "hw-old-001.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        results = find_entries_by_source_file(kb_root, "docs/hw.md")
        assert any(e.id == "hw-old-001" for e in results)

    def test_empty_source_file_returns_nothing(self, kb_root: Path) -> None:
        results = find_entries_by_source_file(kb_root, "")
        assert results == []

    def test_no_match_returns_empty(self, kb_root: Path) -> None:
        _write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending", source_file="docs/other.md"), "pitfall", "hardware")
        results = find_entries_by_source_file(kb_root, "docs/hw.md")
        assert results == []


# ---------------------------------------------------------------------------
# Three-layer scenario (US2)
# ---------------------------------------------------------------------------

class TestThreeLayerScenario:
    """
    Scenario: same source_file has three layers:
      - hw-001 (confirmed, active)
      - hw-002 (pending, old import)
      - hw-003 (pending, new import — being approved)

    Approving hw-003 should cancel hw-002 and deprecate hw-001.
    """

    def _setup(self, kb_root: Path) -> None:
        src = "docs/hw-troubleshooting.md"

        # Confirmed active entry (hw-001)
        content_001 = _make_entry("hw-001", kb_status="active", source_file=src)
        path_001 = kb_root / "pitfall" / "hw-001.md"
        path_001.parent.mkdir(parents=True, exist_ok=True)
        path_001.write_text(content_001, encoding="utf-8")

        # Old pending entry (hw-002)
        _write_pending(kb_root, "hw-002", _make_entry("hw-002", kb_status="pending", source_file=src), "pitfall", "hardware")

        # New pending entry (hw-003 — the one being approved)
        _write_pending(kb_root, "hw-003", _make_entry("hw-003", kb_status="pending", source_file=src), "pitfall", "hardware")

    def test_three_layer_approve_via_functions(self, kb_root: Path) -> None:
        self._setup(kb_root)
        src = "docs/hw-troubleshooting.md"

        # Simulate the approve flow for hw-003.
        all_same = find_entries_by_source_file(kb_root, src)
        old_pending = [e for e in all_same if e.kb_status == "pending" and e.id != "hw-003"]
        old_confirmed = [e for e in all_same if e.kb_status == "active"]

        assert len(old_pending) == 1 and old_pending[0].id == "hw-002"
        assert len(old_confirmed) == 1 and old_confirmed[0].id == "hw-001"

        # Approve new entry first.
        new_path = approve_entry(kb_root, "hw-003")

        # Cancel old pending.
        import os
        for e in old_pending:
            os.unlink(e.file_path)

        # Deprecate old confirmed.
        for e in old_confirmed:
            deprecate_entry(kb_root, e.id)

        # Verify state.
        assert not (kb_root / "_pending" / "pitfall" / "hardware" / "hw-002.md").exists(), "hw-002 should be cancelled"
        assert not (kb_root / "_pending" / "pitfall" / "hardware" / "hw-003.md").exists(), "hw-003 pending file removed"
        assert new_path.exists(), "hw-003 approved under a newly minted permanent ID"
        assert PERMANENT_ID_RE.fullmatch(new_path.stem)

        post_001 = frontmatter.load(str(kb_root / "pitfall" / "hw-001.md"))
        assert post_001.metadata["kb_status"] == "deprecated", "hw-001 should be deprecated"

        post_003 = frontmatter.load(str(new_path))
        assert post_003.metadata["kb_status"] == "active", "hw-003 should be active"
        assert post_003.metadata["former_id"] == "hw-003"


# ---------------------------------------------------------------------------
# CLI — holmes pending (US3)
# ---------------------------------------------------------------------------

class TestCliPending:
    def test_no_pending_shows_message(self, kb_root: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_root), "kb", "pending"])
        assert result.exit_code == 0
        assert "No pending entries" in result.output

    def test_new_format_grouped_by_category(self, kb_root: Path) -> None:
        _write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending"), "pitfall", "hardware")
        _write_pending(kb_root, "net-001", _make_entry("net-001", kb_status="pending", category="network"), "pitfall", "network")
        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_root), "kb", "pending"])
        assert result.exit_code == 0
        assert "[hardware]" in result.output
        assert "[network]" in result.output
        assert "hw-001" in result.output
        assert "net-001" in result.output

    def test_json_output_contains_format_field(self, kb_root: Path) -> None:
        _write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending"), "pitfall", "hardware")
        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_root), "kb", "pending", "--json"])
        assert result.exit_code == 0
        import json as _json
        data = _json.loads(result.output)
        assert any(e.get("format") == "new" for e in data)

    def test_show_new_format_entry(self, kb_root: Path) -> None:
        content = _make_entry("hw-001", kb_status="pending")
        _write_pending(kb_root, "hw-001", content, "pitfall", "hardware")
        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_root), "kb", "pending", "--show", "hw-001"])
        assert result.exit_code == 0
        assert "hw-001" in result.output


# ---------------------------------------------------------------------------
# CLI — holmes approve (US1 + US2)
# ---------------------------------------------------------------------------

class TestCliApprove:
    def test_approve_basic_no_conflicts(self, kb_root: Path) -> None:
        _write_pending(kb_root, "hw-init-001", _make_entry("hw-init-001", kb_status="pending"), "pitfall", "hardware")
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_root), "kb", "approve", "hw-init-001", "--no-interactive"],
        )
        assert result.exit_code == 0, result.output
        assert "✓ Approved" in result.output
        approved = _approved_files(kb_root)
        assert len(approved) == 1
        assert PERMANENT_ID_RE.fullmatch(approved[0].stem)
        # Approve output shows the newly minted permanent ID.
        assert approved[0].stem in result.output

    def test_approve_nonexistent_exits_1(self, kb_root: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_root), "kb", "approve", "does-not-exist", "--no-interactive"],
        )
        assert result.exit_code == 1

    def test_approve_with_old_pending_cancelled(self, kb_root: Path) -> None:
        src = "docs/hw.md"
        _write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending", source_file=src), "pitfall", "hardware")
        _write_pending(kb_root, "hw-002", _make_entry("hw-002", kb_status="pending", source_file=src), "pitfall", "hardware")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_root), "kb", "approve", "hw-002", "--no-interactive"],
        )
        assert result.exit_code == 0, result.output
        # hw-001 (old pending) should be cancelled.
        assert not (kb_root / "_pending" / "pitfall" / "hardware" / "hw-001.md").exists()
        # hw-002 should be approved (type=pitfall → pitfall/hardware/) under a new ID.
        approved = _approved_files(kb_root)
        assert len(approved) == 1
        assert PERMANENT_ID_RE.fullmatch(approved[0].stem)

    def test_approve_with_old_confirmed_deprecated(self, kb_root: Path) -> None:
        src = "docs/hw.md"
        # Confirmed active entry.
        content_old = _make_entry("hw-000", kb_status="active", source_file=src)
        path_old = kb_root / "pitfall" / "hw-000.md"
        path_old.parent.mkdir(parents=True, exist_ok=True)
        path_old.write_text(content_old, encoding="utf-8")

        # New pending entry.
        _write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending", source_file=src), "pitfall", "hardware")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_root), "kb", "approve", "hw-001", "--no-interactive"],
        )
        assert result.exit_code == 0, result.output
        # hw-000 should be deprecated.
        post = frontmatter.load(str(path_old))
        assert post.metadata["kb_status"] == "deprecated"
        # hw-001 should be approved (type=pitfall → pitfall/hardware/) under a new ID.
        approved = _approved_files(kb_root)
        assert len(approved) == 1
        assert PERMANENT_ID_RE.fullmatch(approved[0].stem)


# ---------------------------------------------------------------------------
# CLI — holmes approve semantic dedup gate (spec 043, D2/P13)
# ---------------------------------------------------------------------------

class _FakeDedupProvider:
    """LLMProvider stand-in returning a fixed root-cause comparison payload."""

    def __init__(self, payload: dict):
        self._text = json.dumps(payload)
        self.calls = 0

    def simple_complete(self, messages, system: str = "", max_tokens: int = 512) -> str:
        self.calls += 1
        return self._text


class TestCliApproveDedup:
    """Semantic dedup gate in `holmes approve` with a mocked provider."""

    def _seed_active(self, kb_root: Path, entry_id: str = "PT-HW-a1b2c3") -> None:
        content = _make_entry(entry_id, kb_status="active")
        path = kb_root / "pitfall" / "hardware" / f"{entry_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _patch_provider(self, monkeypatch: pytest.MonkeyPatch, provider: _FakeDedupProvider) -> None:
        monkeypatch.setattr(
            "holmes.kb.agent.provider.factory.create_provider", lambda cfg: provider
        )

    def test_dedup_suspect_interactive_cancel(self, kb_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._seed_active(kb_root)
        _write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending"), "pitfall", "hardware")
        self._patch_provider(monkeypatch, _FakeDedupProvider(
            {"same_root_cause": True, "confidence": 0.92, "reason": "same root cause"}
        ))

        runner = CliRunner()
        result = runner.invoke(
            cli, ["--kb-path", str(kb_root), "kb", "approve", "hw-001"], input="n\n",
        )
        assert result.exit_code == 0, result.output
        assert "疑似重複" in result.output
        assert "PT-HW-a1b2c3" in result.output
        assert "same root cause" in result.output
        # Cancelled: pending file remains, nothing approved (only the seed stays).
        assert (kb_root / "_pending" / "pitfall" / "hardware" / "hw-001.md").exists()
        assert len(_approved_files(kb_root)) == 1  # the seeded PT-HW-a1b2c3

    def test_dedup_suspect_interactive_confirm(self, kb_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._seed_active(kb_root)
        _write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending"), "pitfall", "hardware")
        self._patch_provider(monkeypatch, _FakeDedupProvider(
            {"same_root_cause": True, "confidence": 0.92, "reason": "same root cause"}
        ))

        runner = CliRunner()
        # y → dedup gate, y → final confirmation.
        result = runner.invoke(
            cli, ["--kb-path", str(kb_root), "kb", "approve", "hw-001"], input="y\ny\n",
        )
        assert result.exit_code == 0, result.output
        assert "✓ Approved" in result.output
        assert "dedup: merge" in result.output
        approved = [p for p in _approved_files(kb_root) if p.stem != "PT-HW-a1b2c3"]
        assert len(approved) == 1
        assert PERMANENT_ID_RE.fullmatch(approved[0].stem)

    def test_dedup_suspect_no_interactive_continues(self, kb_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._seed_active(kb_root)
        _write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending"), "pitfall", "hardware")
        self._patch_provider(monkeypatch, _FakeDedupProvider(
            {"same_root_cause": False, "confidence": 0.7, "reason": "related topic"}
        ))

        runner = CliRunner()
        result = runner.invoke(
            cli, ["--kb-path", str(kb_root), "kb", "approve", "hw-001", "--no-interactive"],
        )
        assert result.exit_code == 0, result.output
        # Warning printed, result recorded in approve output, entry approved.
        assert "疑似重複" in result.output
        assert "dedup: new_with_link" in result.output
        approved = [p for p in _approved_files(kb_root) if p.stem != "PT-HW-a1b2c3"]
        assert len(approved) == 1
        assert PERMANENT_ID_RE.fullmatch(approved[0].stem)

    def test_dedup_llm_failure_degrades(self, kb_root: Path) -> None:
        """Provider creation fails (autouse fixture) → warn and continue."""
        self._seed_active(kb_root)
        _write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending"), "pitfall", "hardware")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["--kb-path", str(kb_root), "kb", "approve", "hw-001", "--no-interactive"],
        )
        assert result.exit_code == 0, result.output
        assert "無法執行" in result.output
        approved = [p for p in _approved_files(kb_root) if p.stem != "PT-HW-a1b2c3"]
        assert len(approved) == 1
        assert PERMANENT_ID_RE.fullmatch(approved[0].stem)

    def test_dedup_no_candidates_passes(self, kb_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending"), "pitfall", "hardware")
        provider = _FakeDedupProvider({"same_root_cause": True, "confidence": 0.9, "reason": "x"})
        self._patch_provider(monkeypatch, provider)

        runner = CliRunner()
        result = runner.invoke(
            cli, ["--kb-path", str(kb_root), "kb", "approve", "hw-001", "--no-interactive"],
        )
        assert result.exit_code == 0, result.output
        assert "疑似重複" not in result.output
        # No candidates → no LLM call needed.
        assert provider.calls == 0
        approved = [p for p in _approved_files(kb_root) if p.stem != "PT-HW-a1b2c3"]
        assert len(approved) == 1
        assert PERMANENT_ID_RE.fullmatch(approved[0].stem)

    def test_dedup_skip_flag(self, kb_root: Path) -> None:
        """--skip-dedup bypasses the gate entirely (provider never created)."""
        self._seed_active(kb_root)
        _write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending"), "pitfall", "hardware")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_root), "kb", "approve", "hw-001", "--no-interactive", "--skip-dedup"],
        )
        assert result.exit_code == 0, result.output
        assert "已跳過" in result.output
        # Provider creation would have raised (autouse fixture) — it was never called.
        assert "無法執行" not in result.output
        approved = [p for p in _approved_files(kb_root) if p.stem != "PT-HW-a1b2c3"]
        assert len(approved) == 1
        assert PERMANENT_ID_RE.fullmatch(approved[0].stem)
