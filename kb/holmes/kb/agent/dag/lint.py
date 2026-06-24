"""Lint rules for Agent 2 KB entry generation.

Runs 7 structural integrity checks against the set of entries generated in a
single import run.  Called by the ``finalize()`` tool after all entries are
written to ``_pending/<type>/<category>/``.

Lint failures are non-blocking: all entries already written remain in
``_pending/``, but failures are recorded in ``ImportReport.errors`` and
displayed in the ImportReport.

Rules
-----
1. parent_id_consistency      — process entry parent_id exists in written set
2. child_entry_ids_consistency — all child_entry_ids items exist in written set
3. tree_completeness           — every process DAG node has an entry; no orphans
4. no_cycle                    — child_entry_ids graph is acyclic
5. pitfall_has_root            — at least one pitfall root (no parent_id) exists
6. source_file_consistent      — all entries share same source_file and source_hash
7. evidence_fields_present     — maturity/decay_status/next_decay_check/contributors present
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class LintResult:
    """Result of a single lint rule check.

    Attributes:
        rule: Rule identifier string (e.g. ``"parent_id_consistency"``).
        passed: True if the rule passed.
        message: Human-readable detail when the rule fails; empty when passed.
    """

    rule: str
    passed: bool
    message: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_lint(ctx: dict[str, Any]) -> list[LintResult]:
    """Run all 7 lint rules against entries written in this import run.

    Args:
        ctx: Agent 2 tool context dict.  Must contain:
            - ``written_entries``: list of ``{"entry_id": str, "frontmatter": dict}``
            - ``dag_json``: parsed .dag.json dict (used for tree_completeness)

    Returns:
        List of ``LintResult`` (one per rule, in definition order).
    """
    written: list[dict] = ctx.get("written_entries", [])
    dag_json: dict = ctx.get("dag_json", {})

    # Build lookup structures.
    entry_by_id: dict[str, dict] = {}
    for e in written:
        eid = e.get("entry_id", "")
        if eid:
            entry_by_id[eid] = e

    fm_by_id: dict[str, dict] = {
        eid: e.get("frontmatter", {}) for eid, e in entry_by_id.items()
    }

    results: list[LintResult] = [
        _rule_parent_id_consistency(fm_by_id),
        _rule_child_entry_ids_consistency(fm_by_id),
        _rule_tree_completeness(fm_by_id, dag_json, ctx),
        _rule_no_cycle(fm_by_id),
        _rule_pitfall_has_root(fm_by_id),
        _rule_source_file_consistent(fm_by_id),
        _rule_evidence_fields_present(fm_by_id),
    ]
    return results


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------


def _rule_parent_id_consistency(fm_by_id: dict[str, dict]) -> LintResult:
    """All process entries' parent_id must refer to an existing written entry."""
    rule = "parent_id_consistency"
    bad: list[str] = []
    for eid, fm in fm_by_id.items():
        parent = fm.get("parent_id")
        if parent and parent not in fm_by_id:
            bad.append(f"{eid} → parent_id={parent} (not found)")
    if bad:
        return LintResult(rule=rule, passed=False, message="; ".join(bad))
    return LintResult(rule=rule, passed=True)


def _rule_child_entry_ids_consistency(fm_by_id: dict[str, dict]) -> LintResult:
    """All child_entry_ids in every entry must refer to existing written entries."""
    rule = "child_entry_ids_consistency"
    bad: list[str] = []
    for eid, fm in fm_by_id.items():
        children = fm.get("child_entry_ids") or []
        for child_ref in children:
            # Strip inline YAML comments: "id   # title" → "id"
            child_id = _strip_yaml_comment(str(child_ref))
            if child_id and child_id not in fm_by_id:
                bad.append(f"{eid} → child={child_id} (not found)")
    if bad:
        return LintResult(rule=rule, passed=False, message="; ".join(bad))
    return LintResult(rule=rule, passed=True)


def _rule_tree_completeness(
    fm_by_id: dict[str, dict],
    dag_json: dict,
    ctx: dict[str, Any],
) -> LintResult:
    """Every process DAG node has a corresponding written entry; no orphaned entries."""
    rule = "tree_completeness"

    # Build set of process node IDs from DAG.
    entry_ids_table: dict[str, str] = dag_json.get("entry_ids", {})
    expected_entry_ids: set[str] = set()
    for node_id, eid in entry_ids_table.items():
        if node_id != "root":
            expected_entry_ids.add(eid)
    # Include root.
    root_eid = entry_ids_table.get("root", "")
    if root_eid:
        expected_entry_ids.add(root_eid)

    missing = expected_entry_ids - set(fm_by_id.keys())
    orphans = set(fm_by_id.keys()) - expected_entry_ids

    msgs: list[str] = []
    if missing:
        msgs.append(f"DAG nodes missing entries: {', '.join(sorted(missing))}")
    if orphans:
        msgs.append(f"Orphaned entries (not in DAG): {', '.join(sorted(orphans))}")

    if msgs:
        return LintResult(rule=rule, passed=False, message="; ".join(msgs))
    return LintResult(rule=rule, passed=True)


def _rule_no_cycle(fm_by_id: dict[str, dict]) -> LintResult:
    """child_entry_ids must not form a cycle."""
    rule = "no_cycle"

    # Build adjacency.
    adj: dict[str, list[str]] = {}
    for eid, fm in fm_by_id.items():
        children = [
            _strip_yaml_comment(str(c))
            for c in (fm.get("child_entry_ids") or [])
            if c
        ]
        adj[eid] = [c for c in children if c in fm_by_id]

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {eid: WHITE for eid in fm_by_id}

    def dfs(node: str) -> str:
        color[node] = GRAY
        for child in adj.get(node, []):
            if color.get(child, WHITE) == GRAY:
                return f"{node} → {child}"
            if color.get(child, WHITE) == WHITE:
                result = dfs(child)
                if result:
                    return f"{node} → {result}"
        color[node] = BLACK
        return ""

    for eid in list(fm_by_id):
        if color[eid] == WHITE:
            cycle = dfs(eid)
            if cycle:
                return LintResult(rule=rule, passed=False, message=f"Cycle: {cycle}")

    return LintResult(rule=rule, passed=True)


def _rule_pitfall_has_root(fm_by_id: dict[str, dict]) -> LintResult:
    """At least one entry has type=pitfall and no parent_id (the root)."""
    rule = "pitfall_has_root"
    roots = [
        eid
        for eid, fm in fm_by_id.items()
        if fm.get("type") == "pitfall" and not fm.get("parent_id")
    ]
    if not roots:
        return LintResult(
            rule=rule,
            passed=False,
            message="No pitfall root entry found (type=pitfall with no parent_id)",
        )
    return LintResult(rule=rule, passed=True)


def _rule_source_file_consistent(fm_by_id: dict[str, dict]) -> LintResult:
    """All entries share the same source_file and source_hash."""
    rule = "source_file_consistent"
    source_files: set[str] = set()
    source_hashes: set[str] = set()
    for fm in fm_by_id.values():
        sf = fm.get("source_file", "")
        sh = fm.get("source_hash", "")
        if sf:
            source_files.add(sf)
        if sh:
            source_hashes.add(sh)

    msgs: list[str] = []
    if len(source_files) > 1:
        msgs.append(f"Multiple source_file values: {source_files}")
    if len(source_hashes) > 1:
        msgs.append(f"Multiple source_hash values: {source_hashes}")

    if msgs:
        return LintResult(rule=rule, passed=False, message="; ".join(msgs))
    return LintResult(rule=rule, passed=True)


def _rule_evidence_fields_present(fm_by_id: dict[str, dict]) -> LintResult:
    """maturity, decay_status, next_decay_check, contributors must be present in all entries."""
    rule = "evidence_fields_present"
    required = ("maturity", "decay_status", "next_decay_check", "contributors")
    bad: list[str] = []
    for eid, fm in fm_by_id.items():
        missing = [f for f in required if not fm.get(f)]
        if missing:
            bad.append(f"{eid}: missing {missing}")
    if bad:
        return LintResult(rule=rule, passed=False, message="; ".join(bad))
    return LintResult(rule=rule, passed=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_yaml_comment(value: str) -> str:
    """Strip inline YAML comment from a string value.

    ``"hardware-init-N3-001   # 固件修复"`` → ``"hardware-init-N3-001"``
    """
    idx = value.find("#")
    if idx >= 0:
        value = value[:idx]
    return value.strip()
