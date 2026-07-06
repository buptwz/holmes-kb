"""Agent 2 harness — orchestrates the KB entry generation agent loop.

Responsibilities:
  - 6-tool whitelist enforcement (Read, Grep, read_dag, write_entry, read_entry, finalize)
  - Dynamic maxTurns = 50 × process_count (cap 1000)
  - Checkpoint recovery: scan _pending/ for already-written entries and skip them
  - Batch sub-agent mode when process_count > 30 (each batch of 10 nodes)
  - HolmesLogger span recording: agent2.node[<id>] / agent2.root / lint
  - retry_nodes: limit generation to specified node IDs
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from holmes.kb.agent.dag.id_gen import generate_entry_ids
from holmes.kb.agent.dag.prompt2 import AGENT2_NODE_PROMPT, AGENT2_SYSTEM_PROMPT
from holmes.kb.agent.dag.report2 import print_agent2_report
from holmes.kb.agent.dag.tools2 import TOOLS2_DEFINITIONS, TOOLS2_HANDLERS
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.agent.report import ImportReport
from holmes.kb.progress import NullReporter, ProgressReporter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {"Read", "Grep", "read_dag", "write_entry", "read_entry", "finalize"}
)

MAX_TURNS_PER_NODE: int = 50  # multiplier for maxTurns
MAX_TURNS_ABSOLUTE: int = 1000
MAX_RETRIES_PER_ENTRY: int = 3  # max write_entry retries before skipping


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MaxTurnsExceededError(RuntimeError):
    """Raised when Agent 2 exceeds its maxTurns budget."""


# ---------------------------------------------------------------------------
# EntryBrief
# ---------------------------------------------------------------------------


@dataclass
class EntryBrief:
    """Compact summary of a written entry for context injection."""

    entry_id: str       # e.g. "gpu-init-failure-N2-001"
    node_id: str        # e.g. "N2"
    title: str          # e.g. "固件修复排查步骤"
    step_count: int     # number of numbered steps in body
    has_children: bool  # True if child_entry_ids present


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
        reporter: Optional[ProgressReporter] = None,
    ) -> None:
        self.kb_root = kb_root
        self.cfg = cfg
        self.provider = provider
        self.source_hash = source_hash
        self.source_file = source_file
        self.no_interactive = no_interactive
        self.dry_run = dry_run
        self.verbose = verbose
        self.reporter = reporter or NullReporter()

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
        logger.info(
            "Agent2: starting — %d process nodes, %d already written",
            len(effective_nodes), len(written_node_ids),
        )
        self.reporter.start(
            f"Agent2: 开始生成 KB 条目 — {len(effective_nodes)} 个 process 节点"
        )

        # Per-node isolated context mode (unified path for all sizes).
        self._run_per_node_mode(
            process_nodes=effective_nodes,
            written_node_ids=written_node_ids,
            source_text=source_text,
            ctx=ctx,
            report=report,
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

        elapsed = time.monotonic() - t_start
        n_written = len(ctx["written_entries"])
        n_failed = len(failed_entries)
        self.reporter.done(
            f"Agent2: 完成 — {n_written} 个条目已生成"
            + (f"，{n_failed} 个失败" if n_failed else "")
            + f"（{elapsed:.0f}s）"
        )
        logger.info(
            "Agent2: done — %d entries written, %d failed (%.1fs)",
            n_written, n_failed, elapsed,
        )
        self._log(
            "agent2.done", "INFO", "done",
            duration_ms=int(elapsed * 1000),
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
            written_entries=ctx.get("written_entries", []),
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
        system_prompt: Optional[str] = None,
    ) -> None:
        """Standard LLM tool-use loop.

        Args:
            messages: Initial messages list.
            ctx: Shared execution context.
            max_turns: Maximum number of turns before raising MaxTurnsExceededError.
            system_prompt: System prompt override; defaults to AGENT2_SYSTEM_PROMPT.
        """
        if system_prompt is None:
            system_prompt = AGENT2_SYSTEM_PROMPT
        turn_count = 0

        while True:
            if turn_count >= max_turns:
                raise MaxTurnsExceededError(
                    f"Agent 2 exceeded maxTurns={max_turns} after {turn_count} turns"
                )

            t_turn = time.monotonic()
            _stop, tool_calls, messages, _usage = self.provider.complete(
                messages=messages,
                system=system_prompt,
                model=self.cfg.model,
                max_tokens=8192,
                tools=TOOLS2_DEFINITIONS,
            )
            turn_count += 1
            turn_elapsed = time.monotonic() - t_turn
            tool_names = [tc.name for tc in tool_calls] if tool_calls else ["(stop)"]
            tools_str = ", ".join(tool_names)
            logger.info(
                "Agent2: turn %d/%d [%s] (%.1fs)",
                turn_count, max_turns, tools_str, turn_elapsed,
            )
            self.reporter.info(
                f"Agent2 turn {turn_count}/{max_turns} [{tools_str}] ({turn_elapsed:.1f}s)"
            )

            if _stop or not tool_calls:
                break

            results: list[tuple[str, str]] = []
            for tc in tool_calls:
                result = self._execute_tool(tc.name, tc.input, ctx)
                results.append((tc.id, json.dumps(
                    result, ensure_ascii=False,
                    default=lambda o: o.isoformat() if isinstance(o, (date, datetime)) else str(o),
                )))

            messages = self.provider.append_tool_results(messages, results)

            if ctx.get("_terminate"):
                break

    # ------------------------------------------------------------------
    # Internal: per-node mode (replaces single-loop for all cases)
    # ------------------------------------------------------------------

    def _run_per_node_mode(
        self,
        process_nodes: list[dict],
        written_node_ids: set[str],
        source_text: str,
        ctx: dict[str, Any],
        report: ImportReport,
    ) -> None:
        """Per-node isolated context mode — replaces both single-loop and batch modes.

        Each process node is generated in an independent short conversation (~2K tokens),
        with briefs of already-written entries injected for semantic continuity.
        The pitfall root is generated last with full source text.
        """
        source_lines = source_text.splitlines()
        briefs: list[dict] = []
        write_lock = threading.Lock()

        # --- Phase 1: Process nodes (topological layers: leaves first) ---
        layers = self._topological_layers(process_nodes)
        total_to_run = sum(
            1 for layer in layers for n in layer if n["id"] not in written_node_ids
        )
        self._node_done_count = 0
        self._node_total = total_to_run
        logger.info(
            "Agent2: %d layers, %d total process nodes",
            len(layers), sum(len(l) for l in layers),
        )

        for layer_idx, layer in enumerate(layers):
            nodes_to_run = [n for n in layer if n["id"] not in written_node_ids]
            if not nodes_to_run:
                continue

            node_ids = [n["id"] for n in nodes_to_run]
            logger.info(
                "Agent2: layer %d/%d — %d nodes %s",
                layer_idx + 1, len(layers), len(nodes_to_run), node_ids,
            )

            if len(nodes_to_run) == 1:
                # Single node — run directly without thread overhead.
                self._generate_single_node(
                    nodes_to_run[0], source_lines, briefs, ctx, report, write_lock,
                )
            else:
                # US-2: parallel execution for same-layer nodes.
                max_workers = min(3, len(nodes_to_run))
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {
                        pool.submit(
                            self._generate_single_node,
                            node, source_lines, list(briefs), ctx, report, write_lock,
                        ): node
                        for node in nodes_to_run
                    }
                    for future in as_completed(futures):
                        exc = future.exception()
                        if exc:
                            node = futures[future]
                            report.warnings.append(
                                f"Node {node['id']} failed: {exc}"
                            )

            # Collect briefs after each layer completes.
            for node in nodes_to_run:
                node_id = node["id"]
                entry_id = self.entry_ids.get(node_id, "")
                brief = self._collect_brief(ctx, node_id, entry_id)
                if brief and brief not in briefs:
                    briefs.append(brief)

        # --- Phase 2: Pitfall root ---
        root_entry_id = self.entry_ids.get("root", "")
        if root_entry_id and "root" not in written_node_ids:
            self.reporter.start("Agent2: 生成 pitfall 根条目...")
            logger.info("Agent2: generating pitfall root → %s", root_entry_id)
            report.phase_traces.append("Agent2: generating pitfall root")
            ctx["_terminate"] = False
            root_messages = self._build_root_messages(
                source_text=source_text,
                briefs=briefs,
            )
            try:
                self._run_loop(root_messages, ctx, 15, system_prompt=AGENT2_NODE_PROMPT)
            except MaxTurnsExceededError:
                report.warnings.append("Pitfall root exceeded max turns")

        # --- Phase 3: Consistency review (optional, best-effort) ---
        self.reporter.start(f"Agent2: 一致性检查（{len(briefs)} 个条目）...")
        logger.info("Agent2: consistency review (%d entries)", len(briefs))
        if len(briefs) >= 2:
            ctx["_terminate"] = False
            review_messages = self._build_review_messages(briefs)
            try:
                self._run_loop(review_messages, ctx, 10, system_prompt=AGENT2_SYSTEM_PROMPT)
            except MaxTurnsExceededError:
                pass  # review is best-effort

    def _generate_single_node(
        self,
        node: dict,
        source_lines: list[str],
        briefs: list[dict],
        ctx: dict[str, Any],
        report: ImportReport,
        write_lock: threading.Lock,
    ) -> None:
        """Generate a single process node entry (thread-safe).

        Each call creates its own isolated ctx copy for LLM loop state,
        sharing only written_entries (guarded by write_lock).
        """
        node_id = node["id"]
        entry_id = self.entry_ids.get(node_id, "")
        t0 = time.monotonic()
        with write_lock:
            idx = self._node_done_count + 1
        self.reporter.step(idx, self._node_total, f"生成 {node_id} → {entry_id}")
        logger.info("Agent2: generating %s → %s", node_id, entry_id)
        report.phase_traces.append(f"Agent2: generating {node_id} → {entry_id}")

        node_messages = self._build_node_messages(
            node=node,
            source_lines=source_lines,
            briefs=briefs,
        )

        # Thread-local ctx copy — share written_entries list via lock.
        local_ctx = dict(ctx)
        local_ctx["_terminate"] = False
        local_ctx["_auto_terminate_on_write"] = True  # US-1

        try:
            self._run_loop(node_messages, local_ctx, 15, system_prompt=AGENT2_NODE_PROMPT)
        except MaxTurnsExceededError:
            report.warnings.append(
                f"Node {node_id} exceeded 15 turns — skipping to next node"
            )

        elapsed = time.monotonic() - t0
        logger.info("Agent2: %s done (%.1fs)", node_id, elapsed)

        # Merge written entries back to shared ctx under lock.
        with write_lock:
            for entry in local_ctx.get("written_entries", []):
                if entry not in ctx["written_entries"]:
                    ctx["written_entries"].append(entry)
            for fail in local_ctx.get("failed_entries", []):
                if fail not in ctx["failed_entries"]:
                    ctx["failed_entries"].append(fail)
            self._node_done_count += 1
            self.reporter.step(self._node_done_count, self._node_total, f"✓ {node_id}（{elapsed:.1f}s）")

    def _topological_reverse(self, process_nodes: list[dict]) -> list[dict]:
        """Return process nodes ordered so children come before parents (leaves first).

        Uses Kahn's algorithm on reversed edges: treats "node has children" as
        in-degree for topological ordering.
        """
        node_map = {n["id"]: n for n in process_nodes}
        process_ids = set(node_map.keys())

        # Build children sets (only within process_nodes)
        children_of: dict[str, set[str]] = {nid: set() for nid in process_ids}
        parent_of: dict[str, str] = {}

        for node in process_nodes:
            nid = node["id"]
            for edge in node.get("children", []):
                target = edge.get("target", "")
                if target in process_ids:
                    children_of[nid].add(target)
                    parent_of[target] = nid

        # child_count[nid] = number of children this node has in the process subgraph
        child_count = {nid: len(children) for nid, children in children_of.items()}

        # Start from leaf nodes (child_count == 0)
        queue: deque[str] = deque(
            nid for nid in process_ids if child_count[nid] == 0
        )
        result: list[dict] = []
        processed: set[str] = set()

        while queue:
            nid = queue.popleft()
            if nid in processed:
                continue
            processed.add(nid)
            result.append(node_map[nid])
            # Decrement parent's child_count; enqueue if all children processed
            parent_id = parent_of.get(nid)
            if parent_id and parent_id in child_count:
                child_count[parent_id] -= 1
                if child_count[parent_id] == 0 and parent_id not in processed:
                    queue.append(parent_id)

        # Append any remaining disconnected nodes
        for node in process_nodes:
            if node["id"] not in processed:
                result.append(node)

        return result

    def _topological_layers(self, process_nodes: list[dict]) -> list[list[dict]]:
        """Return process nodes grouped into layers for parallel execution.

        Layer 0 = leaf nodes (no children in process subgraph).
        Layer 1 = nodes whose children are all in layer 0.
        And so on. Nodes in the same layer are independent and can run in parallel.
        """
        node_map = {n["id"]: n for n in process_nodes}
        process_ids = set(node_map.keys())

        # Build children sets (only within process_nodes).
        children_of: dict[str, set[str]] = {nid: set() for nid in process_ids}
        # A node may have multiple parents (diamond DAGs).
        parents_of: dict[str, set[str]] = {nid: set() for nid in process_ids}

        for node in process_nodes:
            nid = node["id"]
            for edge in node.get("children", []):
                target = edge.get("target", "")
                if target in process_ids:
                    children_of[nid].add(target)
                    parents_of[target].add(nid)

        child_count = {nid: len(children) for nid, children in children_of.items()}
        layers: list[list[dict]] = []
        processed: set[str] = set()

        while len(processed) < len(process_ids):
            # Current layer: nodes whose unprocessed children count is 0.
            layer = [
                node_map[nid] for nid in process_ids
                if nid not in processed and child_count[nid] == 0
            ]
            if not layer:
                # Remaining nodes have cycles; add them all.
                layer = [node_map[nid] for nid in process_ids if nid not in processed]
                layers.append(layer)
                break
            layers.append(layer)
            for node in layer:
                nid = node["id"]
                processed.add(nid)
                # Decrement child_count for ALL parents of this node.
                for pid in parents_of.get(nid, set()):
                    if pid in child_count:
                        child_count[pid] -= 1

        return layers

    def _format_dag_overview(self) -> str:
        """Generate a compact text overview of the DAG from self.dag_json."""
        nodes = self.dag_json.get("nodes", [])
        title = self.dag_json.get("title", "")
        lines = [f"DAG: {title}" if title else "DAG:"]
        for node in nodes:
            nid = node.get("id", "?")
            desc = node.get("description", "")
            complexity = node.get("complexity", "")
            entry_id = self.entry_ids.get(nid, "")
            children = node.get("children", [])
            child_targets = ", ".join(c.get("target", "") for c in children if c.get("target"))
            child_info = f" → [{child_targets}]" if child_targets else ""
            lines.append(
                f"  {nid} ({complexity}){child_info}: {desc}"
                + (f"  [entry_id: {entry_id}]" if entry_id else "")
            )
        return "\n".join(lines)

    def _collect_brief(
        self, ctx: dict[str, Any], node_id: str, entry_id: str
    ) -> Optional[dict]:
        """Extract a brief summary from the most recently written entry matching entry_id."""
        for entry in reversed(ctx.get("written_entries", [])):
            if entry.get("entry_id") == entry_id:
                fm = entry.get("frontmatter", {})
                body = entry.get("body", "")
                step_count = len(re.findall(r"^\d+\.\s+", body, re.MULTILINE))
                return {
                    "node_id": node_id,
                    "entry_id": entry_id,
                    "title": str(fm.get("title", entry_id)),
                    "step_count": step_count,
                    "has_children": bool(fm.get("child_entry_ids")),
                }
        return None

    def _build_node_messages(
        self,
        node: dict,
        source_lines: list[str],
        briefs: list[dict],
    ) -> list[Any]:
        """Build isolated context for a single process node."""

        # ① DAG 概览
        dag_overview = self._format_dag_overview()

        # ② Entry ID 映射
        entry_ids_table = "\n".join(
            f"  {nid}: {eid}" for nid, eid in self.entry_ids.items()
        )

        # ③ 已写 entries brief
        brief_text = "\n".join(
            f"  - {b['node_id']} → {b['entry_id']}: \"{b['title']}\"（{b['step_count']}步）"
            for b in briefs
        ) or "  (尚无已生成的 entries)"

        # ④ 源文档段落（line_range 切片 + 上下文扩展）
        lr = node.get("line_range")
        if lr and len(lr) == 2:
            start, end = int(lr[0]), int(lr[1])
            # Context buffer: 10 lines before (may contain setup/context),
            # 10 lines after (may contain follow-up/notes)
            safe_start = max(0, start - 10)
            safe_end = min(len(source_lines), end + 10)
            segment = "\n".join(source_lines[safe_start:safe_end])
            source_info = (
                f"源文档段落（行 {safe_start + 1}-{safe_end}，"
                f"核心范围 {start + 1}-{end}）：\n{segment}"
            )
        else:
            heading = node.get("section_heading", "") or node.get("description", "")
            source_info = (
                f"请用 Grep(\"{heading}\", \"{self.source_file}\") 定位节点内容，"
                f"然后用 Read 提取该 section 内容。"
            )

        # ④b 父节点源文档段落（提供上下文连续性）
        parent_nid = node.get("parent_id", "root")
        if parent_nid != "root":
            parent_node = next(
                (n for n in self.dag_json.get("nodes", []) if n["id"] == parent_nid),
                None,
            )
            if parent_node:
                plr = parent_node.get("line_range")
                if plr and len(plr) == 2:
                    ps, pe = int(plr[0]), int(plr[1])
                    ps = max(0, ps)
                    pe = min(len(source_lines), pe)
                    parent_segment = "\n".join(source_lines[ps:pe])
                    source_info += (
                        f"\n\n父节点（{parent_nid}）源文档段落（行 {ps + 1}-{pe}，"
                        f"仅供上下文参考）：\n{parent_segment}"
                    )

        # ⑤ 节点任务指令
        node_id = node["id"]
        entry_id = self.entry_ids.get(node_id, "")
        children_info = ""
        children_ids = node.get("children", [])
        if children_ids:
            lines = []
            for c in children_ids:
                target = c.get("target", "")
                cond = c.get("condition", "")
                c_eid = self.entry_ids.get(target, target)
                # US-1: pre-embed child title from briefs to eliminate read_entry calls
                c_title = next(
                    (b["title"] for b in briefs if b["node_id"] == target), ""
                )
                title_hint = f" \"{c_title}\"" if c_title else ""
                lines.append(f"    {cond} → {target} ({c_eid}{title_hint})")
            children_info = "  子节点跳转：\n" + "\n".join(lines)

        parent_eid = self.entry_ids.get(str(parent_nid), "null")

        task = (
            f"请为以下节点生成 process entry：\n"
            f"  node_id: {node_id}\n"
            f"  entry_id: {entry_id}\n"
            f"  description: {node.get('description', '')}\n"
            f"  node_type: {node.get('node_type', '')}\n"
            f"  parent_id: {parent_eid}\n"
            f"{children_info}\n\n"
            f"source_hash: {self.source_hash}\n"
            f"source_file: {self.source_file}\n"
        )

        content = (
            f"DAG 概览：\n{dag_overview}\n\n"
            f"entry_ids 表：\n{entry_ids_table}\n\n"
            f"已生成 entries：\n{brief_text}\n\n"
            f"{source_info}\n\n"
            f"{task}\n"
            f"子节点 title 已在上方跳转信息中提供，无需调用 read_entry。\n"
            f"调用 write_entry 写入后即可结束，无需调用 finalize()。"
        )
        return [{"role": "user", "content": content}]

    def _build_root_messages(
        self,
        source_text: str,
        briefs: list[dict],
    ) -> list[Any]:
        """Build context for pitfall root generation (all process entries already written)."""
        dag_overview = self._format_dag_overview()

        entry_ids_table = "\n".join(
            f"  {nid}: {eid}" for nid, eid in self.entry_ids.items()
        )

        brief_text = "\n".join(
            f"  - {b['node_id']} → {b['entry_id']}: \"{b['title']}\"（{b['step_count']}步）"
            for b in briefs
        ) or "  (尚无已生成的 process entries)"

        root_entry_id = self.entry_ids.get("root", "")

        # Determine direct children of the pitfall root.
        # Strategy: find topological entry points (nodes not targeted by any other node),
        # then BFS-expand any entry point that has no process entry of its own,
        # collecting the first descendant layer that does have entries.
        all_nodes = self.dag_json.get("nodes", [])
        all_node_ids: set[str] = {n["id"] for n in all_nodes}
        node_map: dict[str, dict] = {n["id"]: n for n in all_nodes}
        targeted: set[str] = set()
        for node in all_nodes:
            for edge in node.get("children", []):
                t = edge.get("target", "")
                if t in all_node_ids:
                    targeted.add(t)
        entry_points = [n["id"] for n in all_nodes if n["id"] not in targeted]
        direct_child_entry_ids: list[str] = []
        seen: set[str] = set()

        def _collect(nid: str) -> None:
            if nid in seen:
                return
            seen.add(nid)
            if nid in self.entry_ids:
                direct_child_entry_ids.append(self.entry_ids[nid])
            else:
                for edge in node_map.get(nid, {}).get("children", []):
                    _collect(edge.get("target", ""))

        for ep in entry_points:
            _collect(ep)
        child_ids_yaml = (
            "\n".join(f"  - {eid}" for eid in direct_child_entry_ids)
            if direct_child_entry_ids
            else "  # (no direct children found)"
        )

        content = (
            f"DAG 概览：\n{dag_overview}\n\n"
            f"entry_ids 表：\n{entry_ids_table}\n\n"
            f"已生成 process entries：\n{brief_text}\n\n"
            f"源文档全文（用于提取 Symptoms/Root Cause）：\n{source_text}\n\n"
            f"请生成 pitfall root entry（node_type=pitfall_root）：\n"
            f"  entry_id: {root_entry_id}\n"
            f"  node_type: pitfall_root\n"
            f"  source_hash: {self.source_hash}\n"
            f"  source_file: {self.source_file}\n\n"
            f"⚠ frontmatter 必须包含以下两个字段，缺一报错：\n"
            f"  1. pitfall_structure: tree   （固定值，不得省略）\n"
            f"  2. child_entry_ids:          （直接子节点列表，已由系统提供）\n"
            f"{child_ids_yaml}\n\n"
            f"先调用 read_entry(child_id) 获取每个子节点的真实 title，再写 root。\n"
            f"生成完成后调用 finalize()。"
        )
        return [{"role": "user", "content": content}]

    def _build_review_messages(self, briefs: list[dict]) -> list[Any]:
        """Build context for consistency review phase."""
        brief_text = "\n".join(
            f"  - {b['node_id']} → {b['entry_id']}: \"{b['title']}\"（{b['step_count']}步）"
            for b in briefs
        )

        entry_ids_table = "\n".join(
            f"  {nid}: {eid}" for nid, eid in self.entry_ids.items()
        )

        content = (
            f"entry_ids 表：\n{entry_ids_table}\n\n"
            f"已生成的所有 entries：\n{brief_text}\n\n"
            f"请随机抽查 3-5 个 entry，用 read_entry(entry_id) 读取，检查：\n"
            f"1. 术语一致性（如相同概念在不同 entry 中使用相同词汇）\n"
            f"2. 交叉引用准确性（parent_id 和 child_entry_ids 与实际内容匹配）\n"
            f"3. 链接格式正确性（[标题](entry-id) 格式）\n\n"
            f"如有问题，调用 write_entry(entry_id, corrected_content) 覆盖修正。\n"
            f"检查完成后调用 finalize()。"
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

        # Track write_entry failures with retry guidance.
        if name == "write_entry" and result.get("success"):
            eid = tool_input.get("entry_id", "")
            self.reporter.info(f"  write_entry ✓ {eid}")
        if name == "write_entry" and "error" in result:
            entry_id = tool_input.get("entry_id", "?")
            self.reporter.warn(f"write_entry 失败 [{entry_id}]: {result['error'][:60]}")
            retry_counts: dict = ctx.setdefault("_retry_counts", {})
            count = retry_counts.get(entry_id, 0) + 1
            retry_counts[entry_id] = count

            if count >= MAX_RETRIES_PER_ENTRY:
                # Max retries reached — record as failed and auto-terminate
                ctx.setdefault("failed_entries", []).append(
                    (entry_id, f"Failed after {count} attempts: {result['error']}")
                )
                ctx["_terminate"] = True
                result["error"] += (
                    f"\n\n⚠ 已重试 {count} 次，仍然失败。跳过此节点。"
                )
            else:
                # Enrich error with correction guidance
                source_hint = ""
                if count >= 2:
                    # On 2nd+ retry, re-attach source text for the node's line_range
                    source_text = ctx.get("source_text", "")
                    if source_text:
                        # Try to extract the relevant segment for this entry
                        node_segment = self._get_node_source_segment(
                            entry_id, source_text.splitlines()
                        )
                        if node_segment:
                            source_hint = (
                                f"\n\n以下是该节点对应的源文档原文，请严格对照：\n{node_segment}"
                            )
                        else:
                            source_hint = (
                                "\n\n提示：请重新检查源文档内容，确保命令和参数完全来自原文。"
                            )
                result["error"] += (
                    f"\n\n请修正以上问题后重新调用 write_entry。"
                    f"（第 {count}/{MAX_RETRIES_PER_ENTRY} 次重试）"
                    f"{source_hint}"
                )

        # Log per-node span + US-1 auto-terminate.
        if name == "write_entry" and result.get("success"):
            entry_id = tool_input.get("entry_id", "")
            if entry_id == self.entry_ids.get("root"):
                self._log("agent2.root", "INFO", "ok")
            else:
                self._log(f"agent2.node[{entry_id}]", "INFO", "ok")
            # US-1: auto-terminate after successful write in per-node mode
            if ctx.get("_auto_terminate_on_write"):
                ctx["_terminate"] = True

        if name == "finalize" and result.get("success"):
            self._log(
                "lint", "INFO",
                "ok" if result.get("lint_failed", 0) == 0 else "warning",
                lint_passed=result.get("lint_passed", 0),
                lint_failed=result.get("lint_failed", 0),
            )

        return result

    def _get_node_source_segment(
        self, entry_id: str, source_lines: list[str]
    ) -> str:
        """Extract source text for a node by entry_id → node_id → line_range."""
        # Reverse lookup: entry_id → node_id
        node_id = None
        for nid, eid in self.entry_ids.items():
            if eid == entry_id:
                node_id = nid
                break
        if not node_id:
            return ""
        # Find node in DAG
        node = next(
            (n for n in self.dag_json.get("nodes", []) if n["id"] == node_id),
            None,
        )
        if not node:
            return ""
        lr = node.get("line_range")
        if not lr or len(lr) != 2:
            return ""
        start, end = max(0, int(lr[0])), min(len(source_lines), int(lr[1]))
        return "\n".join(source_lines[start:end])

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
    reporter: Optional["ProgressReporter"] = None,
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
        reporter=reporter,
    )

    return harness.run(source_text=source_text, retry_nodes=retry_nodes)
