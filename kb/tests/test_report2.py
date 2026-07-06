"""Tests for holmes.kb.agent.dag.report2 — T021."""

from __future__ import annotations

from holmes.kb.agent.dag.lint import LintResult
from holmes.kb.agent.dag.report2 import print_agent2_report
from holmes.kb.agent.report import ImportReport


def _capture(capsys, *args, **kwargs):
    print_agent2_report(*args, **kwargs)
    return capsys.readouterr().out


def _base_report(created=None):
    r = ImportReport()
    r.created = created or []
    return r


# ---------------------------------------------------------------------------
# Basic output structure
# ---------------------------------------------------------------------------


def test_print_agent2_report_header(capsys):
    report = _base_report(["entry1"])
    out = _capture(
        capsys, report, dag_title="硬件初始化失败", root_ids=["root-001"], source_file="doc.md"
    )
    assert "Import 完成" in out
    assert "doc.md" in out
    assert "━" in out


def test_print_agent2_report_dag_title(capsys):
    report = _base_report()
    out = _capture(
        capsys, report, dag_title="硬件初始化失败", root_ids=["root-001"]
    )
    assert "硬件初始化失败" in out
    assert "root-001" in out


def test_print_agent2_report_success_count(capsys):
    report = _base_report(created=["title1", "title2", "title3"])
    out = _capture(capsys, report, dag_title="DAG", root_ids=["root-001"])
    assert "3" in out
    assert "生成成功" in out


def test_print_agent2_report_next_steps_always_shown(capsys):
    report = _base_report()
    out = _capture(capsys, report, dag_title="DAG", root_ids=[])
    assert "下一步" in out
    assert "holmes pending" in out


def test_print_agent2_report_approve_root_shown(capsys):
    report = _base_report()
    out = _capture(capsys, report, dag_title="DAG", root_ids=["root-abc-001"])
    assert "holmes approve root-abc-001" in out


# ---------------------------------------------------------------------------
# Failed entries
# ---------------------------------------------------------------------------


def test_print_agent2_report_failed_entries(capsys):
    report = _base_report()
    failed = [("N3", "missing required field 'title'"), ("N4", "missing section '## Steps'")]
    out = _capture(capsys, report, dag_title="DAG", root_ids=[], failed_entries=failed)
    assert "格式校验失败" in out
    assert "N3" in out
    assert "N4" in out
    assert "--retry-entry" in out


def test_print_agent2_report_no_failed_entries(capsys):
    report = _base_report(created=["t1"])
    out = _capture(capsys, report, dag_title="DAG", root_ids=["root-001"])
    assert "格式校验失败" not in out


# ---------------------------------------------------------------------------
# Lint results
# ---------------------------------------------------------------------------


def test_print_agent2_report_lint_warnings(capsys):
    report = _base_report(created=["t1"])
    lint = [
        LintResult(rule="parent_id_consistency", passed=False, message="proc-001 → parent missing"),
        LintResult(rule="pitfall_has_root", passed=True),
    ]
    out = _capture(capsys, report, dag_title="DAG", root_ids=["root-001"], lint_results=lint)
    assert "Lint 警告" in out
    assert "parent_id_consistency" in out
    assert "proc-001" in out


def test_print_agent2_report_no_lint_warnings_when_all_pass(capsys):
    report = _base_report(created=["t1"])
    lint = [
        LintResult(rule="parent_id_consistency", passed=True),
        LintResult(rule="pitfall_has_root", passed=True),
    ]
    out = _capture(capsys, report, dag_title="DAG", root_ids=["root-001"], lint_results=lint)
    assert "Lint 警告" not in out


# ---------------------------------------------------------------------------
# Errors and auto_decisions
# ---------------------------------------------------------------------------


def test_print_agent2_report_errors(capsys):
    report = _base_report()
    report.errors.append("Agent2: maxTurns exceeded")
    out = _capture(capsys, report, dag_title="DAG", root_ids=[])
    assert "错误" in out
    assert "maxTurns" in out


def test_print_agent2_report_auto_decisions(capsys):
    report = _base_report()
    report.auto_decisions.append("DAG 未经用户确认")
    out = _capture(capsys, report, dag_title="DAG", root_ids=[])
    assert "自动决策" in out
    assert "DAG 未经用户确认" in out


def test_print_agent2_report_source_file_in_header(capsys):
    report = _base_report()
    out = _capture(
        capsys, report, dag_title="my-dag", root_ids=[], source_file="subdir/my-doc.md"
    )
    assert "subdir/my-doc.md" in out


# ---------------------------------------------------------------------------
# Per-entry detail display (B2)
# ---------------------------------------------------------------------------


def test_print_agent2_report_written_entries_detail(capsys):
    """written_entries shows per-entry id, type, title, category."""
    report = _base_report(created=["GPU Init Failure", "Check Firmware"])
    written = [
        {
            "entry_id": "gpu-init-root-001",
            "frontmatter": {"type": "pitfall", "title": "GPU Init Failure", "category": "hardware/gpu"},
            "content": "## Symptoms\n...\n## Root Cause\n...\n## Resolution\n...",
            "path": "_pending/pitfall/hardware/gpu/gpu-init-root-001.md",
        },
        {
            "entry_id": "gpu-check-fw-001",
            "frontmatter": {"type": "process", "title": "Check Firmware", "category": "hardware/gpu"},
            "content": "## Steps\n1. Run `fwinfo`\n2. Compare versions\n3. Flash if needed\n",
            "path": "_pending/process/hardware/gpu/gpu-check-fw-001.md",
        },
    ]
    out = _capture(
        capsys, report, dag_title="GPU", root_ids=["gpu-init-root-001"],
        written_entries=written,
    )
    assert "[pitfall]" in out
    assert "gpu-init-root-001" in out
    assert "GPU Init Failure" in out
    assert "hardware/gpu" in out
    assert "[process]" in out
    assert "gpu-check-fw-001" in out
    assert "3 steps" in out


def test_print_agent2_report_no_written_entries_still_works(capsys):
    """Report works when written_entries is empty or None."""
    report = _base_report(created=["t1"])
    out = _capture(capsys, report, dag_title="DAG", root_ids=["root-001"])
    assert "生成成功" in out
