"""Unit tests for holmes.kb.logger: HolmesLogger and derive_trace_id."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from holmes.kb.logger import HolmesLogger, derive_trace_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    return date.today().isoformat()


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _read_log_lines(path: Path) -> list[str]:
    return [line for line in path.read_text("utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Phase 3 / US1: write_span format tests
# ---------------------------------------------------------------------------


class TestWriteSpanJsonl:
    """T005 — write_span writes correct JSON Lines records."""

    def test_required_fields_present(self, tmp_path: Path) -> None:
        logger = HolmesLogger(tmp_path)
        logger.write_span("t1", "agent1.draft", "INFO", "write_dag", nodes=8, duration_ms=42100)

        jsonl = tmp_path / f"{_today()}.jsonl"
        assert jsonl.exists(), ".jsonl file must be created"
        records = _read_jsonl(jsonl)
        assert len(records) == 1
        r = records[0]
        assert r["ts"]
        assert r["trace"] == "t1"
        assert r["span"] == "agent1.draft"
        assert r["level"] == "INFO"
        assert r["msg"] == "write_dag"

    def test_extra_fields_in_jsonl(self, tmp_path: Path) -> None:
        logger = HolmesLogger(tmp_path)
        logger.write_span("t1", "agent1.draft", "INFO", "write_dag", nodes=8, duration_ms=42100)

        records = _read_jsonl(tmp_path / f"{_today()}.jsonl")
        assert records[0]["nodes"] == 8
        assert records[0]["duration_ms"] == 42100

    def test_multiple_spans_appended(self, tmp_path: Path) -> None:
        logger = HolmesLogger(tmp_path)
        logger.write_span("t1", "agent1.read", "INFO", "start")
        logger.write_span("t1", "agent1.draft", "INFO", "write_dag")

        records = _read_jsonl(tmp_path / f"{_today()}.jsonl")
        assert len(records) == 2
        assert records[0]["span"] == "agent1.read"
        assert records[1]["span"] == "agent1.draft"


class TestWriteSpanLog:
    """T006 — write_span writes correct human-readable .log lines."""

    def test_log_file_format(self, tmp_path: Path) -> None:
        logger = HolmesLogger(tmp_path)
        logger.write_span("t1", "agent1.draft", "INFO", "write_dag", nodes=8)

        lines = _read_log_lines(tmp_path / f"{_today()}.log")
        assert len(lines) == 1
        line = lines[0]
        # Must contain the required fragments in order
        assert "t1" in line
        assert "agent1.draft" in line
        assert "write_dag" in line
        assert "nodes=8" in line
        # Level must be left-padded to 5 chars: "[INFO ]"
        assert "[INFO ]" in line

    def test_log_level_warn_padded(self, tmp_path: Path) -> None:
        logger = HolmesLogger(tmp_path)
        logger.write_span("t1", "lint", "WARN", "mismatch")

        line = _read_log_lines(tmp_path / f"{_today()}.log")[0]
        assert "[WARN ]" in line

    def test_log_level_error_padded(self, tmp_path: Path) -> None:
        logger = HolmesLogger(tmp_path)
        logger.write_span("t1", "import.start", "ERROR", "config.username not set")

        line = _read_log_lines(tmp_path / f"{_today()}.log")[0]
        assert "[ERROR]" in line


class TestWriteSpanNoTrailingSpace:
    """T007 — .log line has no trailing space when there are no extra fields."""

    def test_no_trailing_space_when_no_extra(self, tmp_path: Path) -> None:
        logger = HolmesLogger(tmp_path)
        logger.write_span("t1", "lint", "INFO", "ok")

        line = _read_log_lines(tmp_path / f"{_today()}.log")[0]
        assert not line.endswith(" "), f"log line must not end with space, got: {line!r}"

    def test_no_trailing_space_with_extra(self, tmp_path: Path) -> None:
        logger = HolmesLogger(tmp_path)
        logger.write_span("t1", "lint", "INFO", "ok", nodes=3)

        line = _read_log_lines(tmp_path / f"{_today()}.log")[0]
        # With extra, line ends with extra value — not a space
        assert not line.endswith(" ")


# ---------------------------------------------------------------------------
# Phase 4 / US2: ERROR level
# ---------------------------------------------------------------------------


class TestWriteSpanErrorLevel:
    """T009 — ERROR level is correctly stored in .jsonl."""

    def test_error_level_in_jsonl(self, tmp_path: Path) -> None:
        logger = HolmesLogger(tmp_path)
        logger.write_span("t1", "import.start", "ERROR", "config.username not set")

        records = _read_jsonl(tmp_path / f"{_today()}.jsonl")
        assert records[0]["level"] == "ERROR"
        assert "username" in records[0]["msg"]


# ---------------------------------------------------------------------------
# Phase 6 / US4: verbose mode
# ---------------------------------------------------------------------------


class TestVerbosePrintsToStdout:
    """T015 — verbose=True causes write_span to print to stdout."""

    def test_verbose_prints(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        logger = HolmesLogger(tmp_path, verbose=True)
        logger.write_span("t1", "agent1.draft", "INFO", "write_dag", nodes=8)

        captured = capsys.readouterr()
        assert "t1" in captured.out
        assert "agent1.draft" in captured.out
        assert "write_dag" in captured.out

    def test_non_verbose_no_stdout(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        logger = HolmesLogger(tmp_path, verbose=False)
        logger.write_span("t1", "agent1.draft", "INFO", "write_dag")

        captured = capsys.readouterr()
        assert captured.out == ""


# ---------------------------------------------------------------------------
# Phase 7 / US5: rotate()
# ---------------------------------------------------------------------------


class TestRotate:
    """T017, T018 — rotate() deletes files older than 30 days, preserves recent ones."""

    def _create_log_pair(self, log_dir: Path, stem: str) -> tuple[Path, Path]:
        """Create a .log and .jsonl file pair with the given stem."""
        log = log_dir / f"{stem}.log"
        jsonl = log_dir / f"{stem}.jsonl"
        log.write_text("dummy log\n", encoding="utf-8")
        jsonl.write_text('{"ts":"x"}\n', encoding="utf-8")
        return log, jsonl

    def test_old_files_deleted(self, tmp_path: Path) -> None:
        """T017 — files 31 days old are deleted by rotate()."""
        old_stem = (date.today() - timedelta(days=31)).isoformat()
        old_log, old_jsonl = self._create_log_pair(tmp_path, old_stem)

        today_stem = date.today().isoformat()
        today_log, today_jsonl = self._create_log_pair(tmp_path, today_stem)

        HolmesLogger(tmp_path).rotate()

        assert not old_log.exists(), "old .log must be deleted"
        assert not old_jsonl.exists(), "old .jsonl must be deleted"
        assert today_log.exists(), "today's .log must be kept"
        assert today_jsonl.exists(), "today's .jsonl must be kept"

    def test_exactly_30_days_kept(self, tmp_path: Path) -> None:
        """Boundary: exactly 30 days ago is NOT deleted (cutoff is strictly <)."""
        stem_30 = (date.today() - timedelta(days=30)).isoformat()
        log_30, jsonl_30 = self._create_log_pair(tmp_path, stem_30)

        HolmesLogger(tmp_path).rotate()

        assert log_30.exists(), "30-day-old .log must be kept"
        assert jsonl_30.exists(), "30-day-old .jsonl must be kept"

    def test_non_date_files_skipped(self, tmp_path: Path) -> None:
        """T018 — non-date-format filenames are skipped silently."""
        readme = tmp_path / "README.txt"
        readme.write_text("hello\n", encoding="utf-8")

        HolmesLogger(tmp_path).rotate()

        assert readme.exists(), "README.txt must not be deleted"

    def test_non_date_log_files_skipped(self, tmp_path: Path) -> None:
        """Files named foo.log or foo.jsonl with non-date stems are preserved."""
        foo_log = tmp_path / "foo.log"
        foo_log.write_text("bar\n", encoding="utf-8")

        HolmesLogger(tmp_path).rotate()

        assert foo_log.exists()


# ---------------------------------------------------------------------------
# Phase 8 / Polish: logger creates log_dir if missing
# ---------------------------------------------------------------------------


class TestLoggerCreatesDir:
    """T020 — HolmesLogger creates log_dir automatically."""

    def test_creates_missing_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "logs"
        assert not nested.exists()

        HolmesLogger(nested)

        assert nested.exists(), "HolmesLogger must create the log_dir"


# ---------------------------------------------------------------------------
# Phase 4 / US2: username check CLI integration
# ---------------------------------------------------------------------------


class TestUsernameCheckCli:
    """C2 — holmes import exits 1 and prints guidance when username not set."""

    def test_import_exits_when_username_missing(self, tmp_path: Path, monkeypatch) -> None:
        from click.testing import CliRunner
        from holmes.cli import cli
        from holmes.config import HolmesConfig, save_config

        monkeypatch.setenv("HOLMES_HOME", str(tmp_path))

        kb_root = tmp_path / "kb"
        kb_root.mkdir()

        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="mock-model",
            api_key="test-key",
            api_base_url="http://localhost",
            username="",  # explicitly empty
        )
        save_config(cfg, holmes_home=tmp_path)

        doc = tmp_path / "doc.md"
        doc.write_text("A" * 100, encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["import", str(doc)])

        assert result.exit_code == 1
        combined = (result.output or "") + (result.stderr_bytes.decode() if result.stderr_bytes else "")
        assert "username" in combined.lower()
        assert "holmes config set username" in combined

    def test_import_proceeds_when_username_set(self, tmp_path: Path, monkeypatch) -> None:
        from unittest.mock import patch
        from click.testing import CliRunner
        from holmes.cli import cli
        from holmes.config import HolmesConfig, save_config
        from holmes.kb.agent.report import ImportReport

        monkeypatch.setenv("HOLMES_HOME", str(tmp_path))

        kb_root = tmp_path / "kb"
        kb_root.mkdir()

        cfg = HolmesConfig(
            kb_path=str(kb_root),
            model="mock-model",
            api_key="test-key",
            api_base_url="http://localhost",
            username="testuser",
        )
        save_config(cfg, holmes_home=tmp_path)

        doc = tmp_path / "doc.md"
        doc.write_text("A" * 100, encoding="utf-8")

        runner = CliRunner()
        with patch("holmes.kb.agent.runner.ImportAgentRunner.run",
                   return_value=ImportReport()):
            result = runner.invoke(cli, ["import", str(doc)])

        # Should not exit with 1 due to username check
        assert result.exit_code != 1 or "username" not in (result.output or "").lower()


# ---------------------------------------------------------------------------
# Phase 5 / US3: log list CLI classification
# ---------------------------------------------------------------------------


class TestLogListClassification:
    """T011 — holmes log list correctly classifies import/draft/session traces."""

    def test_trace_types_classified(self, tmp_path: Path, monkeypatch) -> None:
        from click.testing import CliRunner
        from holmes.cli import cli

        # Redirect logs to tmp_path
        monkeypatch.setenv("HOLMES_HOME", str(tmp_path))

        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        jsonl = log_dir / f"{today}.jsonl"

        import json as _json

        records = [
            # import trace
            {"ts": "2026-06-23T10:00:00Z", "trace": "gpu-troubleshooting", "span": "agent1.draft", "level": "INFO", "msg": "write_dag"},
            {"ts": "2026-06-23T10:01:00Z", "trace": "gpu-troubleshooting", "span": "lint", "level": "INFO", "msg": "ok"},
            # draft trace
            {"ts": "2026-06-23T11:00:00Z", "trace": "redis-oom-2026-06-23", "span": "mcp.draft", "level": "INFO", "msg": "saved"},
            # session trace
            {"ts": "2026-06-23T12:00:00Z", "trace": "session-a3f1", "span": "mcp.kb_search", "level": "INFO", "msg": "search"},
        ]
        with jsonl.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(_json.dumps(r) + "\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["log", "list"])
        assert result.exit_code == 0, result.output
        assert "import" in result.output
        assert "draft" in result.output
        assert "session" in result.output


# ---------------------------------------------------------------------------
# derive_trace_id
# ---------------------------------------------------------------------------


class TestDeriveTraceId:
    def test_simple_stem(self) -> None:
        assert derive_trace_id("gpu-troubleshooting.md") == "gpu-troubleshooting"

    def test_with_full_path(self) -> None:
        assert derive_trace_id("/some/path/gpu-troubleshooting.md") == "gpu-troubleshooting"

    def test_with_hash_uses_first_4_chars(self) -> None:
        assert derive_trace_id("gpu-troubleshooting.md", "a3f1b2c3") == "gpu-troubleshooting-a3f1"

    def test_with_short_hash(self) -> None:
        assert derive_trace_id("doc.md", "ab") == "doc-ab"

    def test_empty_hash_ignored(self) -> None:
        assert derive_trace_id("doc.md", "") == "doc"

    def test_no_extension(self) -> None:
        assert derive_trace_id("my-doc") == "my-doc"
