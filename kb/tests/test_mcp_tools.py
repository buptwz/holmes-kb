"""Tests for MCP tool handlers (Feature 031: MCP KB Channel)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from holmes.mcp.tools import (
    _is_entry_id,
    _is_text_file,
    handle_kb_list,
    handle_kb_overview,
    handle_kb_read,
    handle_kb_search,
    handle_kb_submit,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    return tmp_path


def _make_entry(
    kb_root: Path,
    entry_id: str = "PT-DB-001",
    title: str = "Test Entry",
    skill_refs: Optional[list[str]] = None,
) -> Path:
    entry_dir = kb_root / "pitfall" / "database"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    skill_refs_line = ""
    if skill_refs:
        refs_yaml = ", ".join(f'"{s}"' for s in skill_refs)
        skill_refs_line = f"skill_refs: [{refs_yaml}]"
    content = (
        f"---\n"
        f"id: {entry_id}\n"
        f"type: pitfall\n"
        f"title: {title}\n"
        f"maturity: draft\n"
        f"category: database\n"
        f"tags: [redis, memory]\n"
        f'created_at: "2024-01-01T00:00:00+00:00"\n'
        f'updated_at: "2024-01-01T00:00:00+00:00"\n'
    )
    if skill_refs_line:
        content += skill_refs_line + "\n"
    content += (
        "---\n\n"
        "## Symptoms\n"
        "High memory usage.\n\n"
        "## Root Cause\n"
        "Redis OOM condition.\n\n"
        "## Resolution\n"
        "Flush unused keys.\n"
    )
    entry_path.write_text(content, encoding="utf-8")
    return entry_path


def _make_skill(kb_root: Path, name: str, description: str = "A test skill") -> Path:
    skill_dir = kb_root / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n"
        "## Overview\nSkill instructions here.\n\n"
        "## Steps\n1. Run the check script.\n",
        encoding="utf-8",
    )
    return skill_dir


# ---------------------------------------------------------------------------
# Phase 2: Foundational helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_is_entry_id_valid(self):
        assert _is_entry_id("PT-DB-001")
        assert _is_entry_id("MD-SVC-003")
        assert _is_entry_id("GL-APP-099")

    def test_is_entry_id_invalid(self):
        assert not _is_entry_id("redis-oom-recovery")
        assert not _is_entry_id("pt-db-001")  # lowercase
        assert not _is_entry_id("PTDB001")  # no hyphens
        assert not _is_entry_id("")

    def test_is_text_file_valid(self, tmp_path: Path):
        for ext in [".sh", ".py", ".md", ".yaml", ".json", ".sql"]:
            f = tmp_path / f"file{ext}"
            f.touch()
            assert _is_text_file(f), f"Expected {ext} to be text"

    def test_is_text_file_binary(self, tmp_path: Path):
        for ext in [".png", ".jpg", ".pdf", ".zip", ".exe"]:
            f = tmp_path / f"file{ext}"
            f.touch()
            assert not _is_text_file(f), f"Expected {ext} to be binary"


# ---------------------------------------------------------------------------
# Phase 3: handle_kb_overview
# ---------------------------------------------------------------------------


class TestKbOverview:
    def test_overview_basic_fields(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_overview(kb_root)
        assert "entries" in result
        assert "categories" in result
        assert "top_tags" in result
        assert "skill_count" in result
        assert "session_id" in result
        assert "hint" in result

    def test_overview_skill_count_zero(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_overview(kb_root)
        assert result["skill_count"] == 0

    def test_overview_skill_count_with_skills(self, kb_root: Path):
        _make_entry(kb_root)
        _make_skill(kb_root, "redis-oom-recovery")
        _make_skill(kb_root, "nginx-reload")
        result = handle_kb_overview(kb_root)
        assert result["skill_count"] == 2

    def test_overview_session_id_is_string(self, kb_root: Path):
        result = handle_kb_overview(kb_root)
        assert isinstance(result["session_id"], str)
        assert len(result["session_id"]) > 0

    def test_overview_session_id_unique_per_call(self, kb_root: Path):
        r1 = handle_kb_overview(kb_root)
        r2 = handle_kb_overview(kb_root)
        assert r1["session_id"] != r2["session_id"]

    def test_overview_entry_counts(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001")
        _make_entry(kb_root, "PT-DB-002")
        result = handle_kb_overview(kb_root)
        assert result["entries"].get("pitfall", 0) == 2


# ---------------------------------------------------------------------------
# Phase 3: handle_kb_list with type="skill"
# ---------------------------------------------------------------------------


class TestKbListSkill:
    def test_list_skill_empty(self, kb_root: Path):
        result = handle_kb_list(kb_root, type="skill")
        assert result["entries"] == []
        assert result["total"] == 0

    def test_list_skill_returns_skills(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery", "Fix Redis OOM issues")
        _make_skill(kb_root, "nginx-reload", "Safely reload Nginx")
        result = handle_kb_list(kb_root, type="skill")
        assert result["total"] == 2
        ids = [e["id"] for e in result["entries"]]
        assert "redis-oom-recovery" in ids
        assert "nginx-reload" in ids

    def test_list_skill_entry_structure(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery", "Fix Redis OOM issues")
        result = handle_kb_list(kb_root, type="skill")
        entry = result["entries"][0]
        assert "id" in entry
        assert "description" in entry
        assert entry["description"] == "Fix Redis OOM issues"

    def test_list_skill_hint_present(self, kb_root: Path):
        result = handle_kb_list(kb_root, type="skill")
        assert "hint" in result

    def test_list_entry_includes_hint(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_list(kb_root)
        assert "hint" in result


# ---------------------------------------------------------------------------
# Phase 3: handle_kb_read — unified addressing
# ---------------------------------------------------------------------------


class TestKbReadRouting:
    def test_read_entry_by_id(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001")
        result = handle_kb_read(kb_root, "PT-DB-001")
        assert result.get("error") is None
        assert result["id"] == "PT-DB-001"
        assert result["type"] == "pitfall"

    def test_read_entry_includes_skill_refs_empty(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001")
        result = handle_kb_read(kb_root, "PT-DB-001")
        assert "skill_refs" in result
        assert result["skill_refs"] == []

    def test_read_entry_includes_skill_refs_populated(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        _make_entry(kb_root, "PT-DB-001", skill_refs=["redis-oom-recovery"])
        result = handle_kb_read(kb_root, "PT-DB-001")
        assert result["skill_refs"] == ["redis-oom-recovery"]

    def test_read_entry_hint_when_skill_refs(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        _make_entry(kb_root, "PT-DB-001", skill_refs=["redis-oom-recovery"])
        result = handle_kb_read(kb_root, "PT-DB-001")
        assert "hint" in result

    def test_read_entry_not_found(self, kb_root: Path):
        result = handle_kb_read(kb_root, "PT-DB-999")
        assert "error" in result

    def test_read_entry_with_path_returns_error(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001")
        result = handle_kb_read(kb_root, "PT-DB-001", path="some/file.sh")
        assert "error" in result

    def test_read_skill_by_name(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery", "Fix Redis OOM")
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        assert result.get("error") is None
        assert result["id"] == "redis-oom-recovery"
        assert result["type"] == "skill"
        assert result["description"] == "Fix Redis OOM"

    def test_read_skill_includes_linked_entries(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        _make_entry(kb_root, "PT-DB-001", skill_refs=["redis-oom-recovery"])
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        assert "linked_entries" in result
        assert "PT-DB-001" in result["linked_entries"]

    def test_read_skill_linked_entries_empty_when_none(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        assert result["linked_entries"] == []

    def test_read_skill_includes_files_list(self, kb_root: Path):
        skill_dir = _make_skill(kb_root, "redis-oom-recovery")
        # Add a script file
        scripts = skill_dir / "scripts"
        scripts.mkdir()
        (scripts / "check.sh").write_text("#!/bin/bash\necho ok", encoding="utf-8")
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        assert "files" in result
        assert "scripts/check.sh" in result["files"]

    def test_read_skill_files_excludes_binary(self, kb_root: Path):
        skill_dir = _make_skill(kb_root, "redis-oom-recovery")
        (skill_dir / "image.png").write_bytes(b"\x89PNG")
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        files = result.get("files", [])
        assert not any("image.png" in f for f in files)

    def test_read_skill_files_excludes_skill_md(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        files = result.get("files", [])
        assert "SKILL.md" not in files

    def test_read_skill_not_found(self, kb_root: Path):
        result = handle_kb_read(kb_root, "nonexistent-skill")
        assert "error" in result

    def test_read_skill_content_excludes_frontmatter(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        content = result.get("content", "")
        assert "---" not in content or content.startswith("##")


# ---------------------------------------------------------------------------
# Phase 3: handle_kb_read — skill subfile access
# ---------------------------------------------------------------------------


class TestKbReadSkillSubfile:
    def test_read_subfile_content(self, kb_root: Path):
        skill_dir = _make_skill(kb_root, "redis-oom-recovery")
        scripts = skill_dir / "scripts"
        scripts.mkdir()
        script_content = "#!/bin/bash\nredis-cli info memory"
        (scripts / "check.sh").write_text(script_content, encoding="utf-8")
        result = handle_kb_read(kb_root, "redis-oom-recovery", path="scripts/check.sh")
        assert result.get("error") is None
        assert result["id"] == "redis-oom-recovery"
        assert result["path"] == "scripts/check.sh"
        assert result["content"] == script_content

    def test_read_subfile_not_found(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        result = handle_kb_read(kb_root, "redis-oom-recovery", path="nonexistent.sh")
        assert "error" in result

    def test_read_subfile_binary_rejected(self, kb_root: Path):
        skill_dir = _make_skill(kb_root, "redis-oom-recovery")
        (skill_dir / "image.png").write_bytes(b"\x89PNG")
        result = handle_kb_read(kb_root, "redis-oom-recovery", path="image.png")
        assert "error" in result

    def test_read_subfile_path_traversal_rejected(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        result = handle_kb_read(kb_root, "redis-oom-recovery", path="../../etc/passwd")
        assert "error" in result

    def test_read_subfile_for_unknown_skill_returns_error(self, kb_root: Path):
        result = handle_kb_read(kb_root, "nonexistent-skill", path="check.sh")
        assert "error" in result


# ---------------------------------------------------------------------------
# Phase 4: handle_kb_search
# ---------------------------------------------------------------------------


class TestKbSearch:
    def test_search_returns_results(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001", title="Redis OOM Fix")
        result = handle_kb_search(kb_root, query="redis")
        assert "items" in result
        assert "total" in result
        assert "hint" in result

    def test_search_finds_matching_entry(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001", title="Redis Memory OOM")
        result = handle_kb_search(kb_root, query="redis memory")
        ids = [item["id"] for item in result["items"]]
        assert "PT-DB-001" in ids

    def test_search_no_results_returns_empty(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001", title="Postgres deadlock")
        result = handle_kb_search(kb_root, query="kubernetes networking")
        assert result["items"] == []
        assert result["total"] == 0

    def test_search_item_structure(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001", title="Redis OOM")
        result = handle_kb_search(kb_root, query="redis")
        if result["items"]:
            item = result["items"][0]
            assert "id" in item
            assert "title" in item
            assert "type" in item
            assert "maturity" in item
            assert "score" in item
            assert "brief" in item

    def test_search_type_filter(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001", title="Redis OOM pitfall")
        result = handle_kb_search(kb_root, query="redis", type="pitfall")
        for item in result["items"]:
            assert item["type"] == "pitfall"

    def test_search_limit_respected(self, kb_root: Path):
        for i in range(5):
            _make_entry(kb_root, f"PT-DB-00{i + 1}", title=f"Redis entry {i}")
        result = handle_kb_search(kb_root, query="redis", limit=2)
        assert len(result["items"]) <= 2


# ---------------------------------------------------------------------------
# Phase D: handle_kb_submit → import_document pipeline
# ---------------------------------------------------------------------------


_GOOD_CONTENT = (
    "We observed Redis OOM errors in production. The service was running out of memory "
    "because the maxmemory policy was not set. After setting maxmemory-policy to allkeys-lru "
    "and maxmemory to 2gb, the issue was resolved. Run: redis-cli config set maxmemory-policy allkeys-lru"
)

_SHORT_CONTENT = "too short"


class TestKbSubmitPipeline:
    """Phase D: kb_submit goes through import_document() pipeline."""

    def _mock_import_result(self, pending_id: str = "pending-20260613-abcd1234"):
        from holmes.kb.importer import ImportResult
        return ImportResult(
            pending_id=pending_id,
            kb_type="pitfall",
            title="Redis OOM Recovery",
            category="cache",
            dry_run=False,
            content_preview="## Symptoms\nRedis OOM...",
        )

    def test_submit_success(self, kb_root: Path):
        """Successful submit returns id, status=pending, message."""
        from unittest.mock import AsyncMock, patch

        mock_result = self._mock_import_result()
        with patch(
            "holmes.kb.importer.import_document",
            new=AsyncMock(return_value=mock_result),
        ):
            result = handle_kb_submit(
                kb_root, content=_GOOD_CONTENT, session_id="sess-001"
            )

        assert result["status"] == "pending"
        assert result["id"] == mock_result.pending_id
        assert "message" in result
        assert mock_result.pending_id in result["message"]

    def test_submit_content_too_short_returns_error(self, kb_root: Path):
        """ContentTooShortError returns error status."""
        from holmes.kb.importer import ContentTooShortError

        from unittest.mock import AsyncMock, patch

        with patch(
            "holmes.kb.importer.import_document",
            new=AsyncMock(side_effect=ContentTooShortError("too short")),
        ):
            result = handle_kb_submit(
                kb_root, content=_SHORT_CONTENT, session_id="sess-001"
            )

        assert result["status"] == "rejected"
        assert "error" in result

    def test_submit_duplicate_returns_existing_id(self, kb_root: Path):
        """DuplicatePendingError returns status=duplicate with existing_id."""
        from holmes.kb.importer import DuplicatePendingError
        from unittest.mock import AsyncMock, patch

        _make_entry(kb_root, "PT-DB-001", title="Redis OOM Recovery")

        with patch(
            "holmes.kb.importer.import_document",
            new=AsyncMock(side_effect=DuplicatePendingError("PT-DB-001")),
        ):
            result = handle_kb_submit(
                kb_root, content=_GOOD_CONTENT, session_id="sess-001"
            )

        assert result["status"] == "duplicate"
        assert result["existing_id"] == "PT-DB-001"
        assert "hint" in result
        assert "kb_confirm" in result["hint"]

    def test_submit_writes_evidence_on_success(self, kb_root: Path):
        """Evidence sidecar is written for the pending entry on success."""
        from unittest.mock import AsyncMock, patch
        from holmes.kb.store import EVIDENCE_SIDECAR_DIR

        pending_id = "pending-test-001"
        # Create the pending entry file so append_evidence can find it
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / f"{pending_id}.md").write_text(
            f"---\nid: {pending_id}\ntype: pitfall\ntitle: Test\nmaturity: draft\n"
            "category: ~\ntags: []\ncreated_at: \"2024-01-01T00:00:00+00:00\"\n"
            "updated_at: \"2024-01-01T00:00:00+00:00\"\n---\n\n## Symptoms\ntest\n",
            encoding="utf-8",
        )

        mock_result = self._mock_import_result(pending_id)
        with patch(
            "holmes.kb.importer.import_document",
            new=AsyncMock(return_value=mock_result),
        ):
            handle_kb_submit(
                kb_root, content=_GOOD_CONTENT, session_id="sess-evidence"
            )

        evidence_dir = kb_root / EVIDENCE_SIDECAR_DIR / pending_id
        assert evidence_dir.is_dir(), "Evidence sidecar directory should be created"
        json_files = list(evidence_dir.glob("*.json"))
        assert json_files, "Evidence JSON file should be written"

    def test_submit_temp_file_cleaned_up_on_success(self, kb_root: Path):
        """Temp file is removed after successful import."""
        import glob as globmod
        import tempfile
        from unittest.mock import AsyncMock, patch

        mock_result = self._mock_import_result()
        tmp_names: list[str] = []
        orig_named_temp = tempfile.NamedTemporaryFile

        def capturing_temp(*args, **kwargs):
            t = orig_named_temp(*args, **kwargs)
            tmp_names.append(t.name)
            return t

        with (
            patch("tempfile.NamedTemporaryFile", side_effect=capturing_temp),
            patch(
                "holmes.kb.importer.import_document",
                new=AsyncMock(return_value=mock_result),
            ),
        ):
            handle_kb_submit(kb_root, content=_GOOD_CONTENT, session_id="sess-cleanup")

        for name in tmp_names:
            assert not Path(name).exists(), f"Temp file {name} should be deleted"

    def test_submit_temp_file_cleaned_up_on_error(self, kb_root: Path):
        """Temp file is removed even when import_document raises."""
        import tempfile
        from unittest.mock import AsyncMock, patch

        tmp_names: list[str] = []
        orig_named_temp = tempfile.NamedTemporaryFile

        def capturing_temp(*args, **kwargs):
            t = orig_named_temp(*args, **kwargs)
            tmp_names.append(t.name)
            return t

        with (
            patch("tempfile.NamedTemporaryFile", side_effect=capturing_temp),
            patch(
                "holmes.kb.importer.import_document",
                new=AsyncMock(side_effect=RuntimeError("LLM down")),
            ),
        ):
            result = handle_kb_submit(
                kb_root, content=_GOOD_CONTENT, session_id="sess-err-cleanup"
            )

        assert result["status"] == "rejected"
        for name in tmp_names:
            assert not Path(name).exists(), f"Temp file {name} should be deleted even on error"
