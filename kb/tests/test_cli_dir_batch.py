"""Tests for --dir concurrent batch import + single git commit (US5)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from click.testing import CliRunner

from holmes.cli import cli
from holmes.config import HolmesConfig
from holmes.kb.agent.report import ImportReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_DOC = textwrap.dedent("""\
    # OOM Killer

    When the system runs out of memory the OOM killer terminates processes.

    ## Root Cause

    Insufficient memory available for new allocations.

    ## Resolution

    Increase available memory or reduce process footprint.
""" * 5)  # repeat to exceed 50 chars


def _make_success_report(n: int = 1) -> ImportReport:
    r = ImportReport(dry_run=False)
    for i in range(n):
        r.created.append(f"PT-DB-{i:03d}")
    return r


def _make_dir_with_files(tmp_path: Path, count: int = 3) -> Path:
    d = tmp_path / "docs"
    d.mkdir()
    for i in range(count):
        (d / f"doc{i}.md").write_text(_MINIMAL_DOC, encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# Test: all files are processed
# ---------------------------------------------------------------------------

def test_dir_batch_all_files_processed(tmp_path: Path) -> None:
    """All files in --dir must be submitted to runner.run()."""
    docs_dir = _make_dir_with_files(tmp_path, count=3)
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()

    run_count = 0

    def _fake_run(source_text, file_path=None):
        nonlocal run_count
        run_count += 1
        return _make_success_report(1)

    with patch("holmes.cli.load_config") as mock_cfg, \
         patch("holmes.kb.agent.runner.ImportAgentRunner.run", side_effect=_fake_run), \
         patch("holmes.kb.agent.runner.ImportAgentRunner._git_commit", return_value=True):

        mock_cfg.return_value = HolmesConfig(
            kb_path=str(kb_dir), api_key="test", dir_concurrency=4
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_dir), "import", "--dir", str(docs_dir), "--no-interactive"])

    assert run_count == 3, f"Expected 3 files processed, got {run_count}"


# ---------------------------------------------------------------------------
# Test: single git commit (not one per file)
# ---------------------------------------------------------------------------

def test_dir_batch_single_git_commit(tmp_path: Path) -> None:
    """--dir must produce exactly one git commit, not one per file."""
    docs_dir = _make_dir_with_files(tmp_path, count=4)
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()

    commit_calls = []

    def _fake_commit(msg):
        commit_calls.append(msg)
        return True

    def _fake_run(source_text, file_path=None):
        return _make_success_report(1)

    with patch("holmes.cli.load_config") as mock_cfg, \
         patch("holmes.kb.agent.runner.ImportAgentRunner.run", side_effect=_fake_run), \
         patch("holmes.kb.agent.runner.ImportAgentRunner._git_commit", side_effect=_fake_commit):

        mock_cfg.return_value = HolmesConfig(
            kb_path=str(kb_dir), api_key="test", dir_concurrency=4
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_dir), "import", "--dir", str(docs_dir), "--no-interactive"])

    assert len(commit_calls) == 1, (
        f"Expected exactly 1 git commit, got {len(commit_calls)}: {commit_calls}"
    )
    assert "--dir:" in commit_calls[0], f"Commit message should mention --dir: {commit_calls[0]}"


# ---------------------------------------------------------------------------
# Test: failed file does not abort remaining files
# ---------------------------------------------------------------------------

def test_dir_batch_failed_file_does_not_abort(tmp_path: Path) -> None:
    """A failed file must not prevent other files from being processed."""
    docs_dir = _make_dir_with_files(tmp_path, count=3)
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()

    files_run = []

    def _fake_run(source_text, file_path=None):
        files_run.append(str(file_path))
        if file_path and "doc0" in file_path.name:
            raise RuntimeError("Simulated API failure for doc0")
        return _make_success_report(1)

    with patch("holmes.cli.load_config") as mock_cfg, \
         patch("holmes.kb.agent.runner.ImportAgentRunner.run", side_effect=_fake_run), \
         patch("holmes.kb.agent.runner.ImportAgentRunner._git_commit", return_value=True):

        mock_cfg.return_value = HolmesConfig(
            kb_path=str(kb_dir), api_key="test", dir_concurrency=4
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_dir), "import", "--dir", str(docs_dir), "--no-interactive"])

    assert len(files_run) == 3, f"All 3 files should have been attempted, got {len(files_run)}"
    assert result.exit_code == 0, f"Should not exit 1 when only 1 of 3 files failed: {result.output}"


# ---------------------------------------------------------------------------
# Test: --dir-concurrency=1 works (serial fallback)
# ---------------------------------------------------------------------------

def test_dir_concurrency_one_works(tmp_path: Path) -> None:
    """--dir-concurrency 1 must behave identically to serial processing."""
    docs_dir = _make_dir_with_files(tmp_path, count=2)
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()

    run_count = 0

    def _fake_run(source_text, file_path=None):
        nonlocal run_count
        run_count += 1
        return _make_success_report(1)

    with patch("holmes.cli.load_config") as mock_cfg, \
         patch("holmes.kb.agent.runner.ImportAgentRunner.run", side_effect=_fake_run), \
         patch("holmes.kb.agent.runner.ImportAgentRunner._git_commit", return_value=True):

        mock_cfg.return_value = HolmesConfig(
            kb_path=str(kb_dir), api_key="test", dir_concurrency=1
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_dir), "import", "--dir", str(docs_dir),
             "--dir-concurrency", "1", "--no-interactive"],
        )

    assert run_count == 2


# ---------------------------------------------------------------------------
# Test: skip_git_commit is passed to each file's runner
# ---------------------------------------------------------------------------

def test_dir_batch_skip_git_commit_per_file(tmp_path: Path) -> None:
    """Each per-file runner must have skip_git_commit=True."""
    docs_dir = _make_dir_with_files(tmp_path, count=2)
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()

    skip_flags = []

    original_init = __import__(
        "holmes.kb.agent.runner", fromlist=["ImportAgentRunner"]
    ).ImportAgentRunner.__init__

    def _capturing_init(self, *args, **kwargs):
        skip_flags.append(kwargs.get("skip_git_commit", False))
        original_init(self, *args, **kwargs)

    def _fake_run(source_text, file_path=None):
        return _make_success_report(1)

    with patch("holmes.cli.load_config") as mock_cfg, \
         patch("holmes.kb.agent.runner.ImportAgentRunner.__init__", _capturing_init), \
         patch("holmes.kb.agent.runner.ImportAgentRunner.run", side_effect=_fake_run), \
         patch("holmes.kb.agent.runner.ImportAgentRunner._git_commit", return_value=True):

        mock_cfg.return_value = HolmesConfig(
            kb_path=str(kb_dir), api_key="test", dir_concurrency=4
        )

        runner = CliRunner()
        runner.invoke(cli, ["--kb-path", str(kb_dir), "import", "--dir", str(docs_dir), "--no-interactive"])

    # Per-file runners should have skip_git_commit=True; the final commit runner may have False.
    # At least 2 runners (one per file) should have skip_git_commit=True.
    skip_true_count = sum(1 for f in skip_flags if f)
    assert skip_true_count >= 2, (
        f"Expected at least 2 runners with skip_git_commit=True, got flags: {skip_flags}"
    )


# ---------------------------------------------------------------------------
# T9: --dir with nonexistent directory exits 1
# ---------------------------------------------------------------------------

def test_dir_nonexistent_directory_exits_1(tmp_path: Path) -> None:
    """T9: --dir pointing to a nonexistent path must exit with code 1."""
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    nonexistent = tmp_path / "does_not_exist"

    with patch("holmes.cli.load_config") as mock_cfg:
        mock_cfg.return_value = HolmesConfig(kb_path=str(kb_dir), api_key="test")
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_dir), "import", "--dir", str(nonexistent)],
        )

    assert result.exit_code == 1, (
        f"Expected exit 1 for nonexistent dir, got {result.exit_code}. Output: {result.output}"
    )


# ---------------------------------------------------------------------------
# T10: --dir with directory containing no .md/.txt/.rst files exits 1
# ---------------------------------------------------------------------------

def test_dir_no_matching_files_exits_1(tmp_path: Path) -> None:
    """T10: --dir on a dir with no .md/.txt/.rst files must exit with code 1."""
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    # Only non-matching files.
    (docs_dir / "notes.pdf").write_text("pdf content", encoding="utf-8")
    (docs_dir / "data.json").write_text("{}", encoding="utf-8")

    with patch("holmes.cli.load_config") as mock_cfg:
        mock_cfg.return_value = HolmesConfig(kb_path=str(kb_dir), api_key="test")
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_dir), "import", "--dir", str(docs_dir)],
        )

    assert result.exit_code == 1, (
        f"Expected exit 1 for no matching files, got {result.exit_code}. Output: {result.output}"
    )


# ---------------------------------------------------------------------------
# T11: files with < 50 chars are skipped (not counted as failures), exit 0
# ---------------------------------------------------------------------------

def test_dir_short_content_is_skipped_not_failed(tmp_path: Path) -> None:
    """T11: files with < 50 chars must be silently skipped, not counted as failures.

    The short-content guard returns None (skip) before calling runner.run(),
    so failed_files stays 0 and exit code must be 0.
    """
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    # Short file — will be skipped.
    (docs_dir / "short.md").write_text("Too short.", encoding="utf-8")
    # Valid file — will succeed.
    (docs_dir / "good.md").write_text(_MINIMAL_DOC, encoding="utf-8")

    def _fake_run(source_text, file_path=None):
        return _make_success_report(1)

    with patch("holmes.cli.load_config") as mock_cfg, \
         patch("holmes.kb.agent.runner.ImportAgentRunner.run", side_effect=_fake_run), \
         patch("holmes.kb.agent.runner.ImportAgentRunner._git_commit", return_value=True):

        mock_cfg.return_value = HolmesConfig(
            kb_path=str(kb_dir), api_key="test", dir_concurrency=1
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_dir), "import", "--dir", str(docs_dir),
             "--no-interactive"],
        )

    # Short file is a skip, not a failure — exit code must be 0.
    assert result.exit_code == 0, (
        f"Short content must be skipped (not failed). exit={result.exit_code}, "
        f"output={result.output}"
    )
    # Output should indicate "skipped" for the short file.
    assert "skipped" in result.output.lower() or "warn" in result.output.lower(), (
        f"Expected skip/warn message for short file. output={result.output}"
    )


# ---------------------------------------------------------------------------
# T12: all files fail → exit 1
# ---------------------------------------------------------------------------

def test_dir_all_files_fail_exits_1(tmp_path: Path) -> None:
    """T12: when every file raises an exception, exit code must be 1."""
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    docs_dir = _make_dir_with_files(tmp_path, count=3)

    def _always_fail(source_text, file_path=None):
        raise RuntimeError("Simulated total failure")

    with patch("holmes.cli.load_config") as mock_cfg, \
         patch("holmes.kb.agent.runner.ImportAgentRunner.run",
               side_effect=_always_fail), \
         patch("holmes.kb.agent.runner.ImportAgentRunner._git_commit",
               return_value=True):

        mock_cfg.return_value = HolmesConfig(
            kb_path=str(kb_dir), api_key="test", dir_concurrency=4
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_dir), "import", "--dir", str(docs_dir),
             "--no-interactive"],
        )

    assert result.exit_code == 1, (
        f"Expected exit 1 when all files fail, got {result.exit_code}. "
        f"output={result.output}"
    )
