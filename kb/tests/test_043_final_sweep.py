"""Tests for the final one-pass product sweep (spec 043):

- T048: programmatic category-prefix derivation
- schema required fields enforced inside the feedback loop (category retry)
- stdin / inline-text import forms
- source_file stored as relative path (not bare basename)
- pipeline git commit stages only contributions/ (never the user's unrelated files)
- kb_read not-found returns a navigation hint
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import frontmatter
import pytest
from click.testing import CliRunner

from holmes.cli import cli
from holmes.config import HolmesConfig
from holmes.kb.agent.pipeline import ImportPipeline, _compute_source_file
from holmes.kb.validator import _derive_cat_prefix
from holmes.mcp.tools import handle_kb_read


# ---------------------------------------------------------------------------
# T048 — category prefix derivation
# ---------------------------------------------------------------------------


class TestDeriveCatPrefix:
    @pytest.mark.parametrize("category,expected", [
        ("serdes/pll", "SP"),
        ("pcie/link-training", "PLT"),
        ("bmc-firmware-upgrade", "BFU"),
        ("memory", "MEM"),
        ("hardware", "HAR"),
        ("x", "GEN"),           # too short to be useful
        ("", "GEN"),
    ])
    def test_derivation(self, category: str, expected: str) -> None:
        assert _derive_cat_prefix(category) == expected

    def test_mapped_categories_still_win(self) -> None:
        from holmes.kb.validator import PITFALL_CAT_PREFIXES
        assert PITFALL_CAT_PREFIXES["database"] == "DB"

    def test_generate_id_uses_derived_prefix(self, tmp_path: Path) -> None:
        from holmes.kb.validator import generate_id
        new_id = generate_id(tmp_path, "pitfall", "serdes/pll")
        assert new_id.startswith("PT-SP-"), new_id


# ---------------------------------------------------------------------------
# Schema required fields inside the feedback loop
# ---------------------------------------------------------------------------


class _PipelineMockProvider:
    """Scripted for pipeline LLM calls (classifier → summarizer → generator...)."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    def complete(self, messages, system, model, max_tokens, tools=None):  # noqa: ANN001
        item = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return True, [], list(messages) + [{"role": "assistant", "content": str(item)}], {}

    def simple_complete(self, messages, system="", max_tokens=512):  # noqa: ANN001
        item = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return str(item)

    def append_tool_results(self, messages, results):  # noqa: ANN001
        return messages


_CLASSIFIER_PITFALL = (
    '{"doc_type":"incident","suggested_type":"pitfall","language":"zh",'
    '"is_multi_topic":false,"topic_boundaries":[],"branch_count":1,"reason":"incident"}'
)
_SUMMARIZER_OK = (
    '{"brief":"x","key_facts":["f1","f2"],"commands":[],"symptoms":["s1","s2"],'
    '"resolution_branches":[],"outline":[{"section":"Symptoms","description":"s"}],'
    '"steps":[],"decision_tree":""}'
)


class TestSchemaInFeedbackLoop:
    def test_missing_category_triggers_retry_not_death(self, tmp_path: Path) -> None:
        """A draft missing `category` used to die at the write-time schema gate
        with no retry; now it must be caught inside the feedback loop and the
        retried draft must succeed."""
        draft_missing_category = (
            "---\ntype: pitfall\ntitle: 测试\ntags: [a,b]\n---\n\n"
            "## Symptoms\ns1 s2\n\n## Root Cause\nr\n\n## Resolution\n1. step\n"
        )
        draft_fixed = (
            "---\ntype: pitfall\ntitle: 测试\ncategory: hardware\ntags: [a,b]\n---\n\n"
            "## Symptoms\ns1 s2\n\n## Root Cause\nr\n\n## Resolution\n1. step\n"
        )
        provider = _PipelineMockProvider([
            _CLASSIFIER_PITFALL, _SUMMARIZER_OK, draft_missing_category, draft_fixed,
        ])
        pipeline = ImportPipeline(
            kb_root=tmp_path, cfg=HolmesConfig(model="test"),
            no_interactive=True, _provider=provider,
        )
        report = pipeline.run("排障文档内容 " * 20, file_path=None)
        assert not report.errors, f"pipeline errors: {report.errors}"
        assert provider.calls == 4  # retry happened (initial draft + 1 retry)
        pending = list((tmp_path / "contributions" / "pending").glob("*.md"))
        assert pending, "no pending entry produced"


# ---------------------------------------------------------------------------
# stdin / inline-text import
# ---------------------------------------------------------------------------


class TestImportInputForms:
    def test_missing_file_clean_error(self) -> None:
        result = CliRunner().invoke(cli, ["import", "/nonexistent/x.md"])
        assert result.exit_code == 1
        assert "file not found" in result.output
        assert "Traceback" not in result.output

    def test_stdin_too_short_rejected_cleanly(self) -> None:
        result = CliRunner().invoke(cli, ["import", "-"], input="short")
        assert result.exit_code == 1
        assert "too short" in result.output.lower()
        assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# source_file relative path
# ---------------------------------------------------------------------------


class TestSourceFilePath:
    def test_relative_to_cwd(self, monkeypatch, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        target = tmp_path / "docs" / "a.md"
        target.write_text("x", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert _compute_source_file(target) == "docs/a.md"

    def test_outside_cwd_falls_back_to_absolute(self, tmp_path: Path) -> None:
        target = tmp_path / "b.md"
        target.write_text("x", encoding="utf-8")
        result = _compute_source_file(target)
        assert result.endswith("b.md") and "/" in result

    def test_none_is_empty(self) -> None:
        assert _compute_source_file(None) == ""


# ---------------------------------------------------------------------------
# git commit stages only contributions/
# ---------------------------------------------------------------------------


class TestGitTargetedAdd:
    def test_unrelated_files_not_committed(self, tmp_path: Path) -> None:
        kb = tmp_path / "kb"
        kb.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=kb, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=kb, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=kb, check=True)
        (kb / "README.md").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=kb, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=kb, capture_output=True, check=True)
        # User's unrelated uncommitted work:
        (kb / "my-notes.txt").write_text("do not commit me", encoding="utf-8")

        provider = _PipelineMockProvider([
            _CLASSIFIER_PITFALL, _SUMMARIZER_OK,
            "---\ntype: pitfall\ntitle: 测试\ncategory: hardware\ntags: [a,b]\n---\n\n"
            "## Symptoms\ns1 s2\n\n## Root Cause\nr\n\n## Resolution\n1. step\n",
        ])
        pipeline = ImportPipeline(
            kb_root=kb, cfg=HolmesConfig(model="test"),
            no_interactive=True, _provider=provider,
        )
        report = pipeline.run("排障文档内容 " * 20, file_path=None)
        assert not report.errors

        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=kb,
            capture_output=True, text=True, check=True,
        ).stdout
        assert "my-notes.txt" in status, "unrelated file must remain uncommitted"
        assert "?? my-notes.txt" in status


# ---------------------------------------------------------------------------
# kb_read not-found hint
# ---------------------------------------------------------------------------


class TestReadNotFoundHint:
    def test_hint_present(self, tmp_path: Path) -> None:
        result = handle_kb_read(tmp_path, "PT-NOPE-000")
        assert "error" in result
        assert "kb_browse" in result.get("hint", "")
