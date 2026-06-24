"""Agent 1 harness — orchestrates the DAG extraction agent loop.

Responsibilities:
  - 5-tool whitelist enforcement (Read, Grep, write_dag, read_dag, output_dag)
  - maxTurns=300 enforcement
  - Crash recovery: write session.json every 20 turns
  - --resume: load session.json and continue loop
  - Post-loop interactive menu [1/2/3] (or --no-interactive auto-select [2])
  - HolmesLogger span recording: agent1.read / agent1.draft / agent1.review[N]
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import click

from holmes.kb.atomic import atomic_write
from holmes.kb.agent.dag.prompt1 import AGENT1_SYSTEM_PROMPT
from holmes.kb.agent.dag.schema import Complexity
from holmes.kb.agent.dag.tools1 import TOOLS1_DEFINITIONS, TOOLS1_HANDLERS
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.agent.report import ImportReport


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def _make_json_safe(obj: Any) -> Any:
    """Recursively convert non-JSON-serializable objects (e.g. ToolCall dataclasses)."""
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_json_safe(v) for v in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {f: _make_json_safe(getattr(obj, f)) for f in obj.__dataclass_fields__}
    return obj


_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {"Read", "Grep", "write_dag", "read_dag", "output_dag"}
)

MAX_TURNS: int = 300
SNAPSHOT_INTERVAL: int = 20


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class MaxTurnsExceededError(RuntimeError):
    """Raised when Agent 1 exceeds maxTurns=300."""


class SessionLoadError(IOError):
    """Raised when session.json cannot be loaded on --resume."""


# ---------------------------------------------------------------------------
# Agent1Harness
# ---------------------------------------------------------------------------


class Agent1Harness:
    """Orchestrates Agent 1: the DAG extraction LLM tool-use loop.

    Args:
        kb_root: KB repository root directory.
        cfg: HolmesConfig with provider, model, api_key, api_base_url.
        provider: Pre-created LLMProvider instance.
        source_hash: 16-char SHA-256 prefix of the source document.
        source_file: Optional relative path to the source document.
        no_interactive: If True, skip all user prompts (auto-select [2]).
        dry_run: If True, skip all file writes.
        skip_edit: If True, skip the [1/2/3] editing menu after completion.
        verbose: If True, print per-turn progress.
    """

    def __init__(
        self,
        kb_root: Path,
        cfg: Any,
        provider: LLMProvider,
        source_hash: str,
        source_file: str = "",
        no_interactive: bool = False,
        dry_run: bool = False,
        skip_edit: bool = False,
        verbose: bool = False,
    ) -> None:
        self.kb_root = kb_root
        self.cfg = cfg
        self.provider = provider
        self.source_hash = source_hash
        self.source_file = source_file
        self.no_interactive = no_interactive
        self.dry_run = dry_run
        self.skip_edit = skip_edit
        self.verbose = verbose

        self.state_dir = kb_root / "_import-state"
        self._dag_graph: Optional[Any] = None  # set by tool_output_dag on success

        # Logger (optional — guarded by try/except ImportError)
        self._logger: Optional[Any] = None
        self._trace_id: str = ""
        self._init_logger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        source_text: str,
        resume: bool = False,
    ) -> ImportReport:
        """Run Agent 1 for the given source document.

        Args:
            source_text: Full, untruncated source document text.
            resume: If True, load session.json and continue from snapshot.

        Returns:
            ImportReport with phase_traces, warnings, errors, auto_decisions.
        """
        report = ImportReport()

        # Build tool execution context
        ctx: dict[str, Any] = {
            "state_dir": self.state_dir,
            "source_hash": self.source_hash,
            "source_file": self.source_file,
            "source_text": source_text,
            "kb_root": self.kb_root,
            "dry_run": self.dry_run,
        }

        # Load or build initial messages
        if resume:
            try:
                messages, start_turn = self._load_session()
                report.phase_traces.append(
                    f"Agent1: resumed from session.json (turn {start_turn})"
                )
            except SessionLoadError as exc:
                report.errors.append(f"Agent1 resume failed: {exc}")
                return report
        else:
            messages = self._build_initial_messages(source_text)
            start_turn = 0

        # Log agent1.read span start
        t_start = time.monotonic()
        self._log("agent1.read", "INFO", "start")

        # Run the loop
        try:
            final_turn, total_in_tok, total_out_tok = self._run_loop(messages, start_turn, ctx)
        except MaxTurnsExceededError:
            report.errors.append(
                f"Agent1: maxTurns={MAX_TURNS} exceeded — import aborted. "
                f"Run 'holmes import --resume' to continue from last snapshot."
            )
            return report

        # Populate report
        dag_graph = ctx.get("_dag_graph")
        if dag_graph is not None:
            self._dag_graph = dag_graph
            process_count = sum(
                1 for n in dag_graph.nodes if n.complexity == Complexity.process
            )
            total_count = len(dag_graph.nodes)
            report.phase_traces.append(
                f"Agent1: {total_count} 个节点，{process_count} 个 process 节点提取完成"
            )
            self._log(
                "agent1.done",
                "INFO",
                "done",
                duration_ms=int((time.monotonic() - t_start) * 1000),
                llm_calls=final_turn - start_turn,
                tokens=total_in_tok + total_out_tok,
                input_tokens=total_in_tok,
                output_tokens=total_out_tok,
                nodes=total_count,
                process_nodes=process_count,
            )
        else:
            report.warnings.append("Agent1: output_dag was not called — DAG extraction incomplete")

        # Post-loop: interactive menu
        if not self.dry_run and dag_graph is not None:
            self._show_menu(report)

        return report

    # ------------------------------------------------------------------
    # Internal: agent loop
    # ------------------------------------------------------------------

    def _run_loop(
        self,
        messages: list[Any],
        start_turn: int,
        ctx: dict[str, Any],
    ) -> int:
        """Run the LLM tool-use loop until output_dag succeeds or maxTurns hit.

        Returns:
            Final turn count.

        Raises:
            MaxTurnsExceededError: If turn count reaches MAX_TURNS.
        """
        turn_count = start_turn
        phase = "read"   # read → draft → review
        review_round = 0
        total_input_tokens = 0
        total_output_tokens = 0
        phase_start: dict[str, float] = {"read": time.monotonic()}
        phase_llm_calls: dict[str, int] = {"read": 0}

        while True:
            if turn_count >= MAX_TURNS:
                raise MaxTurnsExceededError(
                    f"Agent 1 exceeded maxTurns={MAX_TURNS} after {turn_count} turns"
                )

            stop, tool_calls, messages, usage = self.provider.complete(
                messages=messages,
                system=AGENT1_SYSTEM_PROMPT,
                model=self.cfg.model,
                max_tokens=8192,
                tools=TOOLS1_DEFINITIONS,
            )

            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)
            turn_count += 1

            if stop or not tool_calls:
                break

            # Crash recovery snapshot every SNAPSHOT_INTERVAL turns
            if turn_count % SNAPSHOT_INTERVAL == 0 and not self.dry_run:
                self._save_session(messages, turn_count)

            # Execute tool calls
            results: list[tuple[str, str]] = []
            terminate = False
            for tc in tool_calls:
                # Phase tracking based on tool name
                if tc.name == "write_dag":
                    if phase == "read":
                        # First write_dag — close read span, open draft
                        read_duration = int((time.monotonic() - phase_start["read"]) * 1000)
                        self._log(
                            "agent1.read", "INFO", "end",
                            duration_ms=read_duration,
                            llm_calls=phase_llm_calls.get("read", 0),
                            tokens=total_input_tokens + total_output_tokens,
                        )
                        phase = "draft"
                        phase_start["draft"] = time.monotonic()
                        phase_llm_calls["draft"] = 0
                        self._log("agent1.draft", "INFO", "start")
                    else:
                        # Subsequent write_dag — review round
                        review_round += 1
                        phase_key = f"review[{review_round}]"
                        phase_start[phase_key] = time.monotonic()
                        phase_llm_calls[phase_key] = 0
                        self._log(
                            f"agent1.review[{review_round}]",
                            "INFO",
                            "start",
                            turn=turn_count,
                        )
                    phase_llm_calls[phase] = phase_llm_calls.get(phase, 0)

                result = self._execute_tool(tc.name, tc.input, ctx)

                if result.get("_terminate"):
                    terminate = True

                results.append((tc.id, json.dumps(result)))

            messages = self.provider.append_tool_results(messages, results)

            if terminate:
                break

        return turn_count, total_input_tokens, total_output_tokens

    def _execute_tool(
        self,
        name: str,
        tool_input: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool call with whitelist enforcement.

        Non-whitelisted tools return {"error": "tool not allowed: <name>"}.
        """
        if name not in _ALLOWED_TOOLS:
            return {"error": f"tool not allowed: {name}"}

        handler = TOOLS1_HANDLERS.get(name)
        if handler is None:
            return {"error": f"tool not found: {name}"}

        try:
            result = handler(ctx, tool_input)
        except Exception as exc:  # noqa: BLE001
            result = {"error": f"{name}: unexpected error: {exc}"}

        return result

    # ------------------------------------------------------------------
    # Initial messages
    # ------------------------------------------------------------------

    def _build_initial_messages(self, source_text: str) -> list[Any]:
        """Build the initial user message with source document context."""
        source_ref = self.source_file or "source_document.md"
        user_content = (
            f"请提取以下故障排查文档的排查树结构。\n\n"
            f"source_hash: {self.source_hash}\n"
            f"source_file: {source_ref}\n\n"
            f"---\n\n"
            f"文档内容如下（使用 Read 或 Grep 工具时，path 参数填写 '{source_ref}'）：\n\n"
            f"{source_text}"
        )
        return [{"role": "user", "content": user_content}]

    # ------------------------------------------------------------------
    # Session persistence (crash recovery)
    # ------------------------------------------------------------------

    def _save_session(self, messages: list[Any], turn_count: int) -> None:
        """Write crash recovery snapshot to _import-state/<hash>.session.json."""
        session_path = self.state_dir / f"{self.source_hash}.session.json"
        try:
            data = {
                "source_hash": self.source_hash,
                "turn_count": turn_count,
                "source_file": self.source_file,
                "messages": _make_json_safe(messages),
            }
            atomic_write(session_path, json.dumps(data, ensure_ascii=False))
        except OSError:
            pass  # snapshot failure is non-fatal

    def _load_session(self) -> tuple[list[Any], int]:
        """Load crash recovery snapshot from session.json.

        Returns:
            (messages, turn_count) from the snapshot.

        Raises:
            SessionLoadError: If session.json doesn't exist or is invalid.
        """
        session_path = self.state_dir / f"{self.source_hash}.session.json"
        if not session_path.exists():
            raise SessionLoadError(
                f"Session snapshot not found: {session_path}. "
                f"Cannot resume without a prior snapshot."
            )
        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
            messages = data["messages"]
            turn_count = int(data.get("turn_count", 0))
            return messages, turn_count
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise SessionLoadError(
                f"Session snapshot corrupted: {session_path}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Post-loop interactive menu
    # ------------------------------------------------------------------

    def _show_menu(self, report: ImportReport) -> None:
        """Display the [1/2/3] post-extraction menu.

        --no-interactive or --skip-edit automatically selects option [2].
        """
        dag_md_path = self.state_dir / f"{self.source_hash}.dag.md"
        dag_graph = self._dag_graph
        node_count = len(dag_graph.nodes) if dag_graph else 0
        process_count = (
            sum(1 for n in dag_graph.nodes if n.complexity == Complexity.process)
            if dag_graph
            else 0
        )

        print(
            f"\nDAG 已提取（{node_count} 个节点，{process_count} 个 process 节点）。"
            f"\n已保存到 {dag_md_path.relative_to(self.kb_root)}"
        )

        if self.no_interactive or self.skip_edit:
            # Auto-select [2]
            print("\n[自动] 已选择 [2] 跳过编辑，直接继续。")
            report.auto_decisions.append("DAG 未经用户确认")
            self._handle_option_proceed(report)
            return

        print(
            "\n选择：\n"
            "  [1] 现在编辑（打开编辑器，完成后按 Enter 继续）\n"
            "  [2] 不需要编辑，直接生成\n"
            "  [3] 稍后处理（退出后运行 holmes import --resume）"
        )

        try:
            choice = click.prompt("选择 [1/2/3]", default="2").strip()
        except click.exceptions.Abort:
            choice = "3"

        if choice == "1":
            self._handle_option_edit(dag_md_path, report)
        elif choice == "3":
            self._handle_option_defer(dag_md_path)
        else:
            self._handle_option_proceed(report)

    def _handle_option_edit(self, dag_md_path: Path, report: ImportReport) -> None:
        """Open the .dag.md in editor and wait."""
        editor = os.environ.get("EDITOR", os.environ.get("VISUAL", ""))
        if editor:
            try:
                subprocess.run([editor, str(dag_md_path)], check=False)
            except (OSError, FileNotFoundError):
                pass
        else:
            print(f"\n编辑文件：{dag_md_path}\n编辑完成后按 Enter 继续...")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass

        print("\n编辑完成，继续处理…")
        self._handle_option_proceed(report)

    def _handle_option_proceed(self, report: ImportReport) -> None:
        """Option [2]: proceed to Step 2.5 (stub — filled by future modules)."""
        # Step 2.5 (parse + normalize) is implemented by a future module.
        # This is intentionally a placeholder.
        report.phase_traces.append("Agent1: 用户选择继续（Step 2.5 待实现）")

    def _handle_option_defer(self, dag_md_path: Path) -> None:
        """Option [3]: exit, state preserved for --resume."""
        rel_path = dag_md_path.relative_to(self.kb_root)
        print(
            f"\n状态已保存到 {rel_path}\n"
            f"稍后运行以下命令继续：\n"
            f"  holmes import --resume"
        )
        raise SystemExit(0)

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
# --resume multi-state selection
# ---------------------------------------------------------------------------


def find_pending_sessions(kb_root: Path) -> list[dict[str, Any]]:
    """Scan _import-state/ and return all pending session.json files.

    Returns:
        List of dicts with keys: source_hash, source_file, turn_count, path.
        Sorted by modification time (newest first).
    """
    state_dir = kb_root / "_import-state"
    if not state_dir.exists():
        return []

    sessions = []
    for session_file in sorted(
        state_dir.glob("*.session.json"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
            # Only include sessions where output_dag hasn't completed (no .dag.json)
            source_hash = data.get("source_hash", session_file.stem.replace(".session", ""))
            dag_json = state_dir / f"{source_hash}.dag.json"
            sessions.append({
                "source_hash": source_hash,
                "source_file": data.get("source_file", ""),
                "turn_count": int(data.get("turn_count", 0)),
                "path": str(session_file),
                "completed": dag_json.exists(),
            })
        except (json.JSONDecodeError, OSError):
            continue

    return sessions


def prompt_session_selection(sessions: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Prompt user to select a pending session when multiple exist.

    Returns:
        Selected session dict, or None if user cancels.
    """
    if not sessions:
        return None

    if len(sessions) == 1:
        return sessions[0]

    print(f"\n找到 {len(sessions)} 个待处理的 import：")
    for i, s in enumerate(sessions, 1):
        source_label = s["source_file"] or s["source_hash"][:8]
        status = "（已提取）" if s["completed"] else f"（turn {s['turn_count']}）"
        print(f"  [{i}] {source_label} {status}")

    try:
        raw = click.prompt("选择", default="1").strip()
        idx = int(raw) - 1
        if 0 <= idx < len(sessions):
            return sessions[idx]
    except (ValueError, click.exceptions.Abort):
        pass

    return None
