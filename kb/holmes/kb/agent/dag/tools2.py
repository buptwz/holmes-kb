"""Agent 2 domain-specific tools: read_dag, write_entry, read_entry, finalize.

Also re-exports Read and Grep from tools1.py to complete the 6-tool whitelist.

Tool context dict (ctx) keys used by these functions:
    state_dir (Path): kb_root / "_import-state/"
    source_hash (str): 16-char SHA-256 prefix
    source_file (str): relative path of source document
    source_text (str): full untruncated source document
    kb_root (Path): KB root directory
    dry_run (bool): if True, write_entry skips the actual file write
    dag_json (dict): parsed .dag.json including entry_ids
    entry_ids (dict): node_id → entry_id mapping
    pending_root (Path): kb_root / "_pending"
    written_entries (list): [{entry_id, frontmatter, path}] for lint/report
    failed_entries (list): [(node_id, reason)] for report
    _terminate (bool): set True by finalize()
    lint_results (list[LintResult]): populated by finalize()
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import frontmatter as _fm

from holmes.kb.atomic import atomic_write
from holmes.kb.agent.dag.lint import run_lint
from holmes.kb.agent.dag.tools1 import tool_read, tool_grep


# ---------------------------------------------------------------------------
# Required frontmatter fields per entry type
# ---------------------------------------------------------------------------

_PITFALL_REQUIRED_FIELDS = frozenset({
    "title", "description", "type", "category", "pitfall_structure",
    "kb_status", "source_file", "source_hash", "import_trace_id",
    "child_entry_ids", "maturity", "decay_status", "next_decay_check",
    "contributors", "tags",
})

_PROCESS_REQUIRED_FIELDS = frozenset({
    "title", "description", "type", "category", "kb_status",
    "source_file", "source_hash", "import_trace_id", "parent_id",
    "maturity", "decay_status", "next_decay_check", "contributors", "tags",
})

_PITFALL_REQUIRED_SECTIONS = ("## Symptoms", "## Root Cause", "## Resolution")
_PROCESS_REQUIRED_SECTIONS = ("## Steps",)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def tool_read_dag2(ctx: dict[str, Any], tool_input: dict[str, Any]) -> dict[str, Any]:
    """Read the .dag.json including entry_ids and import_seq.

    No input parameters required.

    Returns:
        title, nodes, entry_ids, import_seq, source_file
    """
    dag_json: dict = ctx.get("dag_json", {})
    if not dag_json:
        state_dir: Path = ctx["state_dir"]
        source_hash: str = ctx["source_hash"]
        dag_json_path = state_dir / f"{source_hash}.dag.json"
        if not dag_json_path.exists():
            return {"error": "read_dag: .dag.json not found — ensure Agent 1 completed successfully"}
        import json
        try:
            dag_json = json.loads(dag_json_path.read_text(encoding="utf-8"))
            ctx["dag_json"] = dag_json
            ctx["entry_ids"] = dag_json.get("entry_ids", {})
        except (json.JSONDecodeError, OSError) as exc:
            return {"error": f"read_dag: failed to read .dag.json: {exc}"}

    return {
        "title": dag_json.get("title", ""),
        "source_file": dag_json.get("source_file", ""),
        "import_seq": dag_json.get("import_seq", ""),
        "entry_ids": dag_json.get("entry_ids", {}),
        "nodes": dag_json.get("nodes", []),
    }


def tool_read_entry(ctx: dict[str, Any], tool_input: dict[str, Any]) -> dict[str, Any]:
    """Read back an already-written entry.

    Input:
        entry_id (str): The entry ID to look up.

    Returns:
        title, content, frontmatter dict — or error if not found.
    """
    entry_id = tool_input.get("entry_id", "").strip()
    if not entry_id:
        return {"error": "read_entry: entry_id must not be empty"}

    pending_root: Path = ctx.get("pending_root", ctx["kb_root"] / "_pending")

    # Search all subdirectories of _pending for <entry_id>.md
    target_name = f"{entry_id}.md"
    for candidate in pending_root.rglob(target_name):
        try:
            content = candidate.read_text(encoding="utf-8")
            post = _fm.loads(content)
            return {
                "title": str(post.metadata.get("title", "")),
                "content": content,
                "frontmatter": dict(post.metadata),
            }
        except (OSError, Exception) as exc:  # noqa: BLE001
            return {"error": f"read_entry: failed to read {candidate}: {exc}"}

    # Also check in-memory written_entries (dry_run or same-turn writes)
    for written in ctx.get("written_entries", []):
        if written.get("entry_id") == entry_id:
            fm = written.get("frontmatter", {})
            return {
                "title": str(fm.get("title", "")),
                "content": written.get("content", ""),
                "frontmatter": fm,
            }

    return {"error": f"read_entry: entry not found: {entry_id}"}


def tool_write_entry(ctx: dict[str, Any], tool_input: dict[str, Any]) -> dict[str, Any]:
    """Write a KB entry to _pending/<type>/<category>/<entry_id>.md.

    Built-in format validation runs before any file write.  Validation failure
    returns an error dict (no exception) so the agent can correct and retry.

    Input:
        entry_id (str): The entry ID (used as filename stem).
        content (str): Complete Markdown content with YAML frontmatter.

    Returns on success:
        success=True, path (relative string), optional warning.
    Returns on validation error:
        error (str) — agent must fix and retry.
    """
    entry_id = tool_input.get("entry_id", "").strip()
    content = tool_input.get("content", "")

    if not entry_id:
        return {"error": "write_entry: entry_id must not be empty"}
    if not content.strip():
        return {"error": "write_entry: content must not be empty"}

    # Parse frontmatter.
    try:
        post = _fm.loads(content)
        fm = dict(post.metadata)
        body = post.content or ""
    except Exception as exc:  # noqa: BLE001
        return {"error": f"write_entry: cannot parse frontmatter: {exc}"}

    entry_type = fm.get("type", "")
    category = fm.get("category", "general")

    # --- Validate ---
    error = _validate_entry(entry_id, fm, body, entry_type, ctx)
    if error:
        return {"error": error}

    # Build write path.
    pending_root: Path = ctx.get("pending_root", ctx["kb_root"] / "_pending")
    write_dir = pending_root / entry_type / category
    write_path = write_dir / f"{entry_id}.md"
    rel_path = str(write_path.relative_to(ctx["kb_root"])) if ctx["kb_root"] in write_path.parents else str(write_path)

    # Check for match_failed warning.
    warning = ""
    if fm.get("content_source") in ("description_match_failed", "match_failed"):
        warning = f"content_source: {fm.get('content_source')}"

    if not ctx.get("dry_run"):
        try:
            write_dir.mkdir(parents=True, exist_ok=True)
            atomic_write(write_path, content)
        except OSError as exc:
            return {"error": f"write_entry: write failed: {exc}"}

    # Record in context for lint and report.
    written_entries: list = ctx.setdefault("written_entries", [])
    written_entries.append({
        "entry_id": entry_id,
        "frontmatter": fm,
        "content": content,
        "path": rel_path,
    })

    # Content quality warnings (non-blocking — entry is still written).
    content_warnings: list[str] = []
    if entry_type == "process" and "## Steps" in body:
        steps_section = body.split("## Steps", 1)[1] if "## Steps" in body else ""
        # Check: steps with [api] or [remote] should have code blocks or backtick commands.
        api_remote_steps = re.findall(
            r"\*\*\[(api|remote)\]\*\*(.+?)(?=\n\d+\.\s|\n##|\Z)",
            steps_section, re.DOTALL,
        )
        for tag, step_body in api_remote_steps:
            if "`" not in step_body and "```" not in step_body:
                content_warnings.append(
                    f"[{tag}] step missing executable command (no code block found)"
                )
        # Check: steps should have behavior tags.
        step_lines = re.findall(r"^\d+\.\s+(.+)", steps_section, re.MULTILINE)
        for step_line in step_lines:
            if not re.search(r"\*\*\[(api|remote|physical|observe|decide)\]\*\*", step_line):
                content_warnings.append(
                    f"Step missing behavior tag: {step_line[:60]}..."
                )

    result: dict[str, Any] = {"success": True, "path": rel_path}
    if warning:
        result["warning"] = warning
    if content_warnings:
        result["content_warnings"] = content_warnings
    return result


def tool_finalize(ctx: dict[str, Any], tool_input: dict[str, Any]) -> dict[str, Any]:
    """Finalize Agent 2: run lint rules and signal loop termination.

    No input parameters required.

    Side effects:
        - Sets ctx["_terminate"] = True
        - Sets ctx["lint_results"] with 7 LintResult objects

    Returns:
        _terminate=True, success=True, lint_passed, lint_failed, lint_errors list.
    """
    lint_results = run_lint(ctx)
    ctx["lint_results"] = lint_results
    ctx["_terminate"] = True

    passed = sum(1 for r in lint_results if r.passed)
    failed_rules = [r for r in lint_results if not r.passed]

    return {
        "_terminate": True,
        "success": True,
        "lint_passed": passed,
        "lint_failed": len(failed_rules),
        "lint_errors": [f"{r.rule}: {r.message}" for r in failed_rules],
    }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_entry(
    entry_id: str,
    fm: dict,
    body: str,
    entry_type: str,
    ctx: dict[str, Any],
) -> str:
    """Validate a KB entry's frontmatter and body.

    Returns:
        Error string if validation fails, empty string if OK.
    """
    entry_ids: dict[str, str] = ctx.get("entry_ids", {})
    all_entry_ids: set[str] = set(entry_ids.values())

    if entry_type == "pitfall":
        return _validate_pitfall(entry_id, fm, body, all_entry_ids)
    elif entry_type == "process":
        return _validate_process(entry_id, fm, body, all_entry_ids)
    else:
        return (
            f"write_entry: unknown entry type '{entry_type}'. "
            "Must be 'pitfall' or 'process'."
        )


def _validate_pitfall(
    entry_id: str,
    fm: dict,
    body: str,
    all_entry_ids: set[str],
) -> str:
    # Required fields.
    for field in _PITFALL_REQUIRED_FIELDS:
        val = fm.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            return f"write_entry: pitfall entry missing required field '{field}'"

    # Required sections.
    for section in _PITFALL_REQUIRED_SECTIONS:
        if section not in body:
            return f"write_entry: pitfall entry missing required section '{section}'"

    # child_entry_ids items must be in entry_ids table.
    children = fm.get("child_entry_ids") or []
    if all_entry_ids:  # only check if table is populated
        for child_ref in children:
            child_id = _strip_yaml_comment(str(child_ref))
            if child_id and child_id not in all_entry_ids:
                return (
                    f"write_entry: child_entry_id '{child_id}' not in DAG entry_ids table"
                )

    return ""


def _validate_process(
    entry_id: str,
    fm: dict,
    body: str,
    all_entry_ids: set[str],
) -> str:
    # Required fields.
    for field in _PROCESS_REQUIRED_FIELDS:
        val = fm.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            return f"write_entry: process entry missing required field '{field}'"

    # Required section.
    for section in _PROCESS_REQUIRED_SECTIONS:
        if section not in body:
            return f"write_entry: process entry missing required section '{section}'"

    # parent_id must be in entry_ids table.
    parent_id = fm.get("parent_id")
    if parent_id and all_entry_ids and parent_id not in all_entry_ids:
        # Strip comment if present.
        parent_clean = _strip_yaml_comment(str(parent_id))
        if parent_clean and parent_clean not in all_entry_ids:
            return (
                f"write_entry: parent_id '{parent_clean}' not in DAG entry_ids table"
            )

    # child_entry_ids (optional for process).
    children = fm.get("child_entry_ids") or []
    if all_entry_ids:
        for child_ref in children:
            child_id = _strip_yaml_comment(str(child_ref))
            if child_id and child_id not in all_entry_ids:
                return (
                    f"write_entry: child_entry_id '{child_id}' not in DAG entry_ids table"
                )

    return ""


def _strip_yaml_comment(value: str) -> str:
    """Strip inline YAML comment: ``"id   # title"`` → ``"id"``."""
    idx = value.find("#")
    if idx >= 0:
        value = value[:idx]
    return value.strip()


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic input_schema format)
# ---------------------------------------------------------------------------

TOOLS2_DEFINITIONS: list[dict] = [
    {
        "name": "Read",
        "description": (
            "Read lines from a file. Use the source document path or 'source' "
            "as a shortcut. Returns line content with start/end line numbers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "offset": {"type": "integer", "description": "Start line (0-based, default 0)"},
                "limit": {"type": "integer", "description": "Max lines to return (default 100)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "Grep",
        "description": (
            "Search for a regex pattern in a file. Returns matching lines with context. "
            "Use source document path or 'source' for the source document."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python regex pattern"},
                "path": {"type": "string", "description": "File path to search"},
                "context_lines": {
                    "type": "integer",
                    "description": "Lines of context around each match (default 2)",
                },
            },
            "required": ["pattern", "path"],
        },
    },
    {
        "name": "read_dag",
        "description": (
            "Read the .dag.json including full node list, entry_ids table, and import_seq. "
            "Call this first in Phase 1 Study to understand the tree structure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "write_entry",
        "description": (
            "Write a KB entry to _pending/<type>/<category>/<entry_id>.md. "
            "Built-in format validation runs first — if it fails, an error is returned "
            "and NO file is written. Correct the content and retry. "
            "entry_id MUST come from the entry_ids table returned by read_dag()."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "string",
                    "description": "Entry ID from the DAG entry_ids table",
                },
                "content": {
                    "type": "string",
                    "description": "Complete Markdown content with YAML frontmatter",
                },
            },
            "required": ["entry_id", "content"],
        },
    },
    {
        "name": "read_entry",
        "description": (
            "Read back an already-written entry from _pending/. "
            "Use this to get a child entry's real title before writing a parent entry, "
            "so that child_entry_ids annotations and route links are accurate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "string",
                    "description": "Entry ID to look up",
                },
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "finalize",
        "description": (
            "Finalize Agent 2: run 7 lint rules and terminate the loop. "
            "Call this ONLY after writing ALL entries (process entries + pitfall root). "
            "Returns lint results. Loop exits after this call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

# Handler map: name → function
TOOLS2_HANDLERS: dict[str, Any] = {
    "Read": tool_read,
    "Grep": tool_grep,
    "read_dag": tool_read_dag2,
    "write_entry": tool_write_entry,
    "read_entry": tool_read_entry,
    "finalize": tool_finalize,
}
