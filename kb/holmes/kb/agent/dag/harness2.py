"""Agent 2 harness — orchestrates the KB entry generation agent loop.

Responsibilities:
  - 6-tool whitelist enforcement (Read, Grep, read_dag, write_entry, read_entry, finalize)
  - Dynamic maxTurns = 50 × process_count (cap 1000)
  - Checkpoint recovery: scan _pending/ for already-written entries and skip them
  - Batch sub-agent mode when process_count > 20 (each batch of 10 nodes)
  - HolmesLogger span recording: agent2.node[<id>] / agent2.root / lint
  - retry_nodes: limit generation to specified node IDs
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from holmes.kb.agent.dag.id_gen import generate_entry_ids
from holmes.kb.agent.dag.prompt2 import AGENT2_SYSTEM_PROMPT
from holmes.kb.agent.dag.report2 import print_agent2_report
from holmes.kb.agent.dag.tools2 import TOOLS2_DEFINITIONS, TOOLS2_HANDLERS
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.agent.report import ImportReport


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {"Read", "Grep", "read_dag", "write_entry", "read_entry", "finalize"}
)

BATCH_SIZE: int = 10          # nodes per sub-agent batch when >20 process nodes
MAX_TURNS_PER_NODE: int = 50  # multiplier for maxTurns
MAX_TURNS_ABSOLUTE: int = 1000


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MaxTurnsExceededError(RuntimeError):
    """Raised when Agent 2 exceeds its maxTurns budget."""


# ---------------------------------------------------------------------------
# Agent2Harness
# ---------------------------------------------------------------------------


class Agent2Harness:
    """Orchestrates Agent 2: the KB entry generation LLM tool-use loop.

    Args:
        kb_root: KB repository root directory.
        cfg: HolmesConfig (model, api_key, api_base_url, username).
        provider: Pre-created LLMProvider instance.
        source_hash: 16-char SHA-256 prefix of source document.
        source_file: Relative path of source document (for display).
        dag_json_path: Absolute path to the ``.dag.json`` produced by Agent 1.
        no_interactive: If True, skip user prompts.
        dry_run: If True, write_entry skips actual file write.
        verbose: If True, print per-turn progress.
    """

    def __init__(
        self,
        kb_root: Path,
        cfg: Any,
        provider: LLMProvider,
        source_hash: str,
        source_file: str = "",
        dag_json_path: Optional[Path] = None,
        no_interactive: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        self.kb_root = kb_root
        self.cfg = cfg
        self.provider = provider
        self.source_hash = source_hash
        self.source_file = source_file
        self.no_interactive = no_interactive
        self.dry_run = dry_run
        self.verbose = verbose

        self.state_dir = kb_root / "_import-state"
        self.pending_root = kb_root / "_pending"

        # Resolve dag_json_path.
        if dag_json_path is None:
            dag_json_path = self.state_dir / f"{source_hash}.dag.json"
        self.dag_json_path = dag_json_path

        # Load dag_json.
        self.dag_json: dict = {}
        self.entry_ids: dict[str, str] = {}
        self._process_node_ids: list[str] = []

        self._logger: Optional[Any] = None
        self._trace_id: str = ""
        self._init_logger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        source_text: str = "",
        retry_nodes: Optional[list[str]] = None,
    ) -> ImportReport:
        """Run Agent 2 for the given DAG.

        Args:
            source_text: Full, untruncated source document text.
            retry_nodes: If set, only regenerate entries for these node IDs.

        Returns:
            ImportReport with phase_traces, created, warnings, errors.
        """
        report = ImportReport()

        # Validate username.
        username = getattr(self.cfg, "username", "")
        if not username:
            report.errors.append(
                "Agent 2: config.username is not set. "
                "Please configure username in ~/.holmes/config.json before importing."
            )
            return report

        # Load .dag.json (with entry_ids, which id_gen already wrote).
        if not self._load_dag_json(report):
            return report

        process_nodes = [
            n for n in self.dag_json.get("nodes", [])
            if n.get("complexity") == "process"
        ]
        process_count = len(process_nodes)
        self._process_node_ids = [n["id"] for n in process_nodes]

        # Dynamic maxTurns.
        max_turns = min(MAX_TURNS_PER_NODE * max(process_count, 1), MAX_TURNS_ABSOLUTE)

        # Determine already-written nodes (crash recovery checkpoint).
        written_node_ids = self._scan_written_node_ids()
        if written_node_ids:
            report.phase_traces.append(
                f"Agent2: found {len(written_node_ids)} already-written entries — skipping"
            )

        # Filter to retry_nodes if specified.
        effective_nodes = process_nodes
        if retry_nodes:
            effective_nodes = [n for n in process_nodes if n["id"] in retry_nodes]
            written_node_ids -= set(retry_nodes)  # force re-gen of retry targets

        # Build shared ctx.
        ctx: dict[str, Any] = {
            "state_dir": self.state_dir,
            "source_hash": self.source_hash,
            "source_file": self.source_file,
            "source_text": source_text,
            "kb_root": self.kb_root,
            "dry_run": self.dry_run,
            "dag_json": self.dag_json,
            "entry_ids": self.entry_ids,
            "pending_root": self.pending_root,
            "username": username,
            "written_entries": [],
            "failed_entries": [],
            "_terminate": False,
            "lint_results": [],
        }

        t_start = time.monotonic()

        # Choose single-loop or batch mode.
        if process_count > 20 and not retry_nodes:
            self._run_batch_mode(
                effective_nodes, written_node_ids, ctx, report, max_turns
            )
        else:
            messages = self._build_initial_messages(written_node_ids, source_text)
            try:
                self._run_loop(messages, ctx, max_turns)
            except MaxTurnsExceededError:
                report.errors.append(
                    f"Agent2: maxTurns={max_turns} exceeded — restart to continue from checkpoint"
                )

        # Collect results.
        root_entry_id = self.entry_ids.get("root", "")
        root_ids = [root_entry_id] if root_entry_id else []
        for entry in ctx["written_entries"]:
            fm = entry.get("frontmatter", {})
            if fm.get("type") == "pitfall" and not fm.get("parent_id"):
                title = str(fm.get("title", entry["entry_id"]))
                if entry["entry_id"] not in report.created:
                    report.created.append(title)
            else:
                title = str(fm.get("title", entry["entry_id"]))
                report.created.append(title)

        # Lint results → report.errors
        for lr in ctx.get("lint_results", []):
            if not lr.passed:
                report.warnings.append(f"lint: {lr.rule}: {lr.message}")

        # Failed entries.
        failed_entries: list[tuple[str, str]] = ctx.get("failed_entries", [])

        self._log(
            "agent2.done", "INFO", "done",
            duration_ms=int((time.monotonic() - t_start) * 1000),
            entries_written=len(ctx["written_entries"]),
            entries_failed=len(failed_entries),
        )

        # Print ImportReport.
        dag_title = self.dag_json.get("title", "")
        print_agent2_report(
            report=report,
            dag_title=dag_title,
            root_ids=root_ids,
            source_file=self.source_file,
            failed_entries=failed_entries,
            lint_results=ctx.get("lint_results", []),
        )

        report.phase_traces.append(
            f"Agent2: {len(ctx['written_entries'])} entries written, "
            f"{len(failed_entries)} format validation failures"
        )
        return report

    # ------------------------------------------------------------------
    # Internal: main loop
    # ------------------------------------------------------------------

    def _run_loop(
        self,
        messages: list[Any],
        ctx: dict[str, Any],
        max_turns: int,
    ) -> None:
        """Standard LLM tool-use loop for ≤20 process nodes (single agent)."""
        turn_count = 0

        while True:
            if turn_count >= max_turns:
                raise MaxTurnsExceededError(
                    f"Agent 2 exceeded maxTurns={max_turns} after {turn_count} turns"
                )

            _stop, tool_calls, messages, _usage = self.provider.complete(
                messages=messages,
                system=AGENT2_SYSTEM_PROMPT,
                model=self.cfg.model,
                max_tokens=8192,
                tools=TOOLS2_DEFINITIONS,
            )
            turn_count += 1

            if _stop or not tool_calls:
                break

            results: list[tuple[str, str]] = []
            for tc in tool_calls:
                result = self._execute_tool(tc.name, tc.input, ctx)
                results.append((tc.id, json.dumps(result, ensure_ascii=False)))

            messages = self.provider.append_tool_results(messages, results)

            if ctx.get("_terminate"):
                break

    # ------------------------------------------------------------------
    # Internal: batch mode (>20 process nodes)
    # ------------------------------------------------------------------

    def _run_batch_mode(
        self,
        process_nodes: list[dict],
        written_node_ids: set[str],
        ctx: dict[str, Any],
        report: ImportReport,
        max_turns_total: int,
    ) -> None:
        """Run Agent 2 in batches of BATCH_SIZE process nodes.

        Each batch gets a fresh messages list (independent context).
        A {id: title} summary table is passed between batches.
        The pitfall root is generated last by a dedicated sub-agent.
        """
        # Filter out already-written nodes.
        pending_nodes = [
            n for n in process_nodes
            if n["id"] not in written_node_ids
        ]

        batches = [
            pending_nodes[i: i + BATCH_SIZE]
            for i in range(0, len(pending_nodes), BATCH_SIZE)
        ]

        title_summary: dict[str, str] = {}  # {entry_id: title}
        max_turns_per_batch = min(MAX_TURNS_PER_NODE * BATCH_SIZE, MAX_TURNS_ABSOLUTE)

        for batch_idx, batch_nodes in enumerate(batches):
            report.phase_traces.append(
                f"Agent2: batch {batch_idx + 1}/{len(batches)} ({len(batch_nodes)} nodes)"
            )
            batch_messages = self._build_batch_messages(
                batch_nodes, title_summary, is_root_batch=False
            )
            try:
                self._run_loop(batch_messages, ctx, max_turns_per_batch)
            except MaxTurnsExceededError:
                report.errors.append(
                    f"Agent2: batch {batch_idx + 1} exceeded maxTurns — "
                    f"restart to continue from checkpoint"
                )
                break

            # Collect titles from newly written entries for next batch.
            for e in ctx["written_entries"]:
                fm = e.get("frontmatter", {})
                title_summary[e["entry_id"]] = str(fm.get("title", e["entry_id"]))

        # Generate pitfall root as final sub-agent.
        root_node_id = self.entry_ids.get("root")
        if root_node_id and root_node_id not in written_node_ids:
            report.phase_traces.append("Agent2: generating pitfall root")
            ctx["_terminate"] = False  # reset for root sub-agent
            root_messages = self._build_batch_messages(
                [], title_summary, is_root_batch=True
            )
            try:
                self._run_loop(root_messages, ctx, max_turns_per_batch)
            except MaxTurnsExceededError:
                report.errors.append(
                    "Agent2: pitfall root generation exceeded maxTurns"
                )

    def _build_batch_messages(
        self,
        batch_nodes: list[dict],
        title_summary: dict[str, str],
        is_root_batch: bool,
    ) -> list[Any]:
        """Build initial messages for a batch sub-agent."""
        entry_ids_table = "\n".join(
            f"  {node_id}: {eid}"
            for node_id, eid in self.entry_ids.items()
        )
        title_table = "\n".join(
            f"  {eid}: {title}" for eid, title in title_summary.items()
        ) or "  (no entries written yet)"

        if is_root_batch:
            task_desc = (
                "任务：生成 pitfall root entry，entry_id 为 entry_ids 表中的 'root' 键。\n"
                "所有 process entries 已生成，通过 read_entry() 获取子节点真实 title 后再写 root。\n"
                "最后调用 finalize()。"
            )
        else:
            node_list = "\n".join(
                f"  {n['id']} — {n.get('description', '')} "
                f"(section_heading: {n.get('section_heading', 'null')})"
                for n in batch_nodes
            )
            task_desc = (
                f"任务：按拓扑逆序生成以下 {len(batch_nodes)} 个 process entries：\n{node_list}\n"
                "生成完本批所有 process entries 后调用 finalize()。"
            )

        content = (
            f"source_hash: {self.source_hash}\n"
            f"source_file: {self.source_file}\n\n"
            f"entry_ids 表：\n{entry_ids_table}\n\n"
            f"已写 entries 标题摘要（供术语一致性参考）：\n{title_table}\n\n"
            f"{task_desc}"
        )
        return [{"role": "user", "content": content}]

    def _build_initial_messages(
        self,
        written_node_ids: set[str],
        source_text: str,
    ) -> list[Any]:
        """Build initial user message for single-loop mode."""
        entry_ids_table = "\n".join(
            f"  {node_id}: {eid}"
            for node_id, eid in self.entry_ids.items()
        )

        skip_info = ""
        if written_node_ids:
            skip_ids = ", ".join(sorted(written_node_ids))
            skip_info = f"\n已生成（跳过）：{skip_ids}\n"

        source_ref = self.source_file or "source_document.md"
        content = (
            f"请根据以下排查树生成 KB entries。\n\n"
            f"source_hash: {self.source_hash}\n"
            f"source_file: {source_ref}\n\n"
            f"entry_ids 表（节点ID → entry_id）：\n{entry_ids_table}\n"
            f"{skip_info}\n"
            f"原始文档内容如下（使用 Read 或 Grep 工具时，path 填写 '{source_ref}'）：\n\n"
            f"{source_text}"
        )
        return [{"role": "user", "content": content}]

    # ------------------------------------------------------------------
    # Internal: tool execution
    # ------------------------------------------------------------------

    def _execute_tool(
        self,
        name: str,
        tool_input: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool call with whitelist enforcement."""
        if name not in _ALLOWED_TOOLS:
            return {"error": f"tool not allowed: {name}"}

        handler = TOOLS2_HANDLERS.get(name)
        if handler is None:
            return {"error": f"tool not found: {name}"}

        try:
            result = handler(ctx, tool_input)
        except Exception as exc:  # noqa: BLE001
            result = {"error": f"{name}: unexpected error: {exc}"}

        # Track write_entry failures for report.
        if name == "write_entry" and "error" in result:
            entry_id = tool_input.get("entry_id", "?")
            ctx.setdefault("failed_entries", []).append(
                (entry_id, result["error"])
            )

        # Log per-node span.
        if name == "write_entry" and result.get("success"):
            entry_id = tool_input.get("entry_id", "")
            if entry_id == self.entry_ids.get("root"):
                self._log("agent2.root", "INFO", "ok")
            else:
                self._log(f"agent2.node[{entry_id}]", "INFO", "ok")

        if name == "finalize" and result.get("success"):
            self._log(
                "lint", "INFO",
                "ok" if result.get("lint_failed", 0) == 0 else "warning",
                lint_passed=result.get("lint_passed", 0),
                lint_failed=result.get("lint_failed", 0),
            )

        return result

    # ------------------------------------------------------------------
    # Internal: checkpoint recovery
    # ------------------------------------------------------------------

    def _scan_written_node_ids(self) -> set[str]:
        """Scan _pending/ for entries already written in this import run.

        Matches files whose name (entry_id stem) maps back to a known DAG
        node via the entry_ids table.

        Returns:
            Set of node IDs whose entries already exist in _pending/.
        """
        import_seq = self.dag_json.get("import_seq", "")
        found: set[str] = set()
        if not self.pending_root.exists() or not import_seq:
            return found

        # Build reverse map: entry_id → node_id.
        reverse: dict[str, str] = {}
        for node_id, eid in self.entry_ids.items():
            reverse[eid] = node_id

        for md_file in self.pending_root.rglob("*.md"):
            eid = md_file.stem
            if eid in reverse:
                node_id = reverse[eid]
                if node_id != "root":
                    found.add(node_id)

        return found

    # ------------------------------------------------------------------
    # Internal: DAG loading
    # ------------------------------------------------------------------

    def _load_dag_json(self, report: ImportReport) -> bool:
        """Load .dag.json into self.dag_json and self.entry_ids.

        Returns:
            True on success, False on error (error appended to report).
        """
        if not self.dag_json_path.exists():
            report.errors.append(
                f"Agent2: .dag.json not found: {self.dag_json_path}. "
                f"Ensure Agent 1 completed successfully."
            )
            return False
        try:
            self.dag_json = json.loads(
                self.dag_json_path.read_text(encoding="utf-8")
            )
            self.entry_ids = self.dag_json.get("entry_ids", {})
            return True
        except (json.JSONDecodeError, OSError) as exc:
            report.errors.append(f"Agent2: failed to load .dag.json: {exc}")
            return False

    # ------------------------------------------------------------------
    # HolmesLogger integration
    # ------------------------------------------------------------------

    def _init_logger(self) -> None:
        """Initialise HolmesLogger if M8 is available."""
        try:
            from holmes.kb.logger import HolmesLogger, derive_trace_id  # type: ignore

            log_dir = Path("~/.holmes/logs").expanduser()
            self._logger = HolmesLogger(log_dir=log_dir, verbose=self.verbose)
            self._trace_id = derive_trace_id(
                self.source_file or "unknown", self.source_hash
            )
        except ImportError:
            pass

    def _log(self, span: str, level: str, msg: str, **extra: Any) -> None:
        """Write a HolmesLogger span (no-op if logger unavailable)."""
        if self._logger is not None:
            try:
                self._logger.write_span(
                    trace_id=self._trace_id,
                    span=span,
                    level=level,
                    msg=msg,
                    **extra,
                )
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_agent2(
    source_text: str,
    file_path: Optional[Path],
    kb_root: Path,
    cfg: Any,
    provider: Any,
    source_hash: str,
    dag_json_path: Optional[Path] = None,
    no_interactive: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
    retry_nodes: Optional[list[str]] = None,
) -> ImportReport:
    """Run Agent 2 KB entry generation for a pitfall document.

    Pre-generates entry IDs (idempotent) then launches Agent2Harness.

    Args:
        source_text: Full, untruncated source document text.
        file_path: Optional source file path.
        kb_root: KB root directory.
        cfg: HolmesConfig.
        provider: Pre-created LLMProvider instance.
        source_hash: 16-char SHA-256 prefix of source document.
        dag_json_path: Path to .dag.json; defaults to _import-state/<hash>.dag.json.
        no_interactive: Skip user prompts.
        dry_run: Skip file writes.
        verbose: Print per-turn progress.
        retry_nodes: If set, only regenerate these node IDs.

    Returns:
        ImportReport.
    """
    state_dir = kb_root / "_import-state"
    if dag_json_path is None:
        dag_json_path = state_dir / f"{source_hash}.dag.json"

    # Pre-generate entry IDs (idempotent — safe to call on retry).
    try:
        generate_entry_ids(dag_json_path)
    except (FileNotFoundError, ValueError, OSError) as exc:
        report = ImportReport()
        report.errors.append(f"Agent2: ID generation failed: {exc}")
        return report

    source_file = ""
    if file_path is not None:
        try:
            source_file = file_path.relative_to(kb_root).as_posix()
        except ValueError:
            source_file = file_path.name

    harness = Agent2Harness(
        kb_root=kb_root,
        cfg=cfg,
        provider=provider,
        source_hash=source_hash,
        source_file=source_file,
        dag_json_path=dag_json_path,
        no_interactive=no_interactive,
        dry_run=dry_run,
        verbose=verbose,
    )

    return harness.run(source_text=source_text, retry_nodes=retry_nodes)
