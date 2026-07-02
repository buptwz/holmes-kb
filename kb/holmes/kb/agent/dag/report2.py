"""Agent 2 ImportReport terminal display.

Provides ``print_agent2_report()``, which formats and prints the Agent 2
import result in the structured multi-line format defined in the blueprint:

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Import 完成：<source_file>
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  排查树：<dag_title>
    pitfall root: <root_id>

  ✓ 生成成功  N 个 entries
    ...

  ⚠ 格式校验失败  M 个 entries（未写入 pending）
    - <node_id>: <reason>
    重试：holmes import --retry-entry <node_id>

  ⚠ Lint 警告  K 条
    - <rule>: <message>

  下一步：
    审核 pending entries：holmes pending
    approve 并发布：holmes approve <root_id>
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from holmes.kb.agent.dag.lint import LintResult
from holmes.kb.agent.report import ImportReport


_SEP = "━" * 40


def print_agent2_report(
    report: ImportReport,
    dag_title: str,
    root_ids: list[str],
    source_file: str = "",
    failed_entries: list[tuple[str, str]] | None = None,
    lint_results: list[LintResult] | None = None,
) -> None:
    """Print the Agent 2 import report to stdout.

    Args:
        report: ``ImportReport`` populated during the Agent 2 run.
            ``report.created`` contains titles of successfully written entries.
        dag_title: Human-readable DAG title (e.g. "硬件初始化失败").
        root_ids: List of pitfall root entry IDs generated in this run.
        source_file: Relative path to the source document.
        failed_entries: List of ``(node_id, error_reason)`` for entries that
            failed format validation and were not written to pending.
        lint_results: List of ``LintResult`` from the 7 lint rules.
    """
    failed_entries = failed_entries or []
    lint_results = lint_results or []

    lines: list[str] = ["", _SEP]

    # Header
    label = source_file or dag_title
    lines.append(f"Import 完成：{label}")
    lines.append(_SEP)
    lines.append("")

    # Pitfall tree info
    lines.append(f"排查树：{dag_title}")
    for root_id in root_ids:
        lines.append(f"  pitfall root: {root_id}")
    lines.append("")

    # Success count
    success_count = len(report.created)
    pitfall_count = len(root_ids)
    process_count = success_count - pitfall_count
    lines.append(f"✓ 生成成功  {success_count} 个 entries")
    if pitfall_count or process_count:
        parts = []
        if pitfall_count:
            parts.append(f"{pitfall_count} pitfall root")
        if process_count > 0:
            parts.append(f"{process_count} process entries")
        lines.append(f"  {' + '.join(parts)}")
        lines.append("  写入 _pending/<type>/<category>/")
    lines.append("")

    # Format validation failures
    if failed_entries:
        lines.append(f"⚠ 格式校验失败  {len(failed_entries)} 个 entries（未写入 pending）")
        for node_id, reason in failed_entries:
            lines.append(f"  - {node_id}：{reason}")
        lines.append("  重试：")
        for node_id, _ in failed_entries:
            lines.append(f"       holmes import --retry-entry {node_id}")
        lines.append("")

    # Lint results
    lint_failures = [r for r in lint_results if not r.passed]
    lint_warnings_in_report = [
        w for w in report.warnings if w.startswith("lint:")
    ]
    total_lint_issues = len(lint_failures) + len(lint_warnings_in_report)
    if total_lint_issues:
        lines.append(f"⚠ Lint 警告  {total_lint_issues} 条（已写入 pending，但有问题）")
        for r in lint_failures:
            lines.append(f"  - {r.rule}：{r.message}")
        for w in lint_warnings_in_report:
            lines.append(f"  - {w}")
        lines.append("")

    # Errors from report
    if report.errors:
        lines.append(f"⚠ 错误  {len(report.errors)} 条")
        for e in report.errors:
            lines.append(f"  - {e}")
        lines.append("")

    # Auto-decisions in no-interactive mode
    if report.auto_decisions:
        lines.append("  [自动决策]")
        for d in report.auto_decisions:
            lines.append(f"    • {d}")
        lines.append("")

    # Next steps (always shown)
    lines.append("下一步：")
    lines.append("  审核 pending entries：holmes pending")
    if root_ids:
        for root_id in root_ids:
            lines.append(f"  approve 并发布：holmes approve {root_id}")
    else:
        lines.append("  approve 并发布：holmes approve <root-id>")
    lines.append(_SEP)
    lines.append("")

    print("\n".join(lines))
