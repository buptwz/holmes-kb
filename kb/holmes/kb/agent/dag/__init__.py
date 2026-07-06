"""Holmes KB DAG import pipeline — Agent 1 (extraction) and Agent 2 (generation).

Public API:
    run_agent1(...)   — DAG extraction (called by pipeline._run_dag_pipeline())
    run_agent2(...)   — KB entry generation (called after Step 2.5 confirmation)
    Agent1Harness     — harness class
    Agent2Harness     — harness class
    DAGGraph          — the extracted DAG data model
    DAGNode           — individual node
    DAGEdge           — directed edge between nodes
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from holmes.kb.agent.dag.harness1 import Agent1Harness, find_pending_sessions, prompt_session_selection
from holmes.kb.agent.dag.harness2 import Agent2Harness, run_agent2
from holmes.kb.agent.dag.schema import DAGEdge, DAGGraph, DAGNode
from holmes.kb.agent.report import ImportReport
from holmes.kb.importer import compute_source_hash


__all__ = [
    "run_agent1",
    "run_agent2",
    "Agent1Harness",
    "Agent2Harness",
    "DAGGraph",
    "DAGNode",
    "DAGEdge",
    "find_pending_sessions",
    "prompt_session_selection",
]


def run_agent1(
    source_text: str,
    file_path: Optional[Path],
    kb_root: Path,
    cfg: Any,
    provider: Any,
    no_interactive: bool = False,
    dry_run: bool = False,
    resume: bool = False,
    skip_edit: bool = False,
    verbose: bool = False,
    reporter: Optional[Any] = None,
) -> ImportReport:
    """Run Agent 1 DAG extraction for a pitfall document.

    This is the primary entry point called by
    ThreePhaseImportPipeline._run_dag_pipeline().

    Args:
        source_text: Full, untruncated source document text.
        file_path: Optional source file path (for display and Read/Grep routing).
        kb_root: KB repository root directory.
        cfg: HolmesConfig (api_key, model, api_base_url, username).
        provider: Pre-created LLMProvider instance.
        no_interactive: If True, skip all user prompts (auto-select [2]).
        dry_run: If True, skip all file writes.
        resume: If True, load session.json and continue loop.
        skip_edit: If True, skip the [1/2/3] editing menu after completion.
        verbose: If True, print per-turn progress.

    Returns:
        ImportReport with:
          - phase_traces: agent progress messages
          - warnings: non-fatal issues
          - errors: fatal errors (e.g. MaxTurnsExceeded)
          - auto_decisions: "DAG 未经用户确认" when no_interactive=True
    """
    source_hash = compute_source_hash(source_text)
    source_file = ""
    if file_path is not None:
        try:
            source_file = file_path.relative_to(kb_root).as_posix()
        except ValueError:
            source_file = file_path.name

    harness = Agent1Harness(
        kb_root=kb_root,
        cfg=cfg,
        provider=provider,
        source_hash=source_hash,
        source_file=source_file,
        no_interactive=no_interactive,
        dry_run=dry_run,
        skip_edit=skip_edit,
        verbose=verbose,
        reporter=reporter,
    )

    return harness.run(source_text=source_text, resume=resume)
