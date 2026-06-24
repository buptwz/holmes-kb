"""Entry ID pre-generation for Agent 2.

Assigns deterministic KB entry IDs to all DAG nodes before Agent 2 starts,
so that parent_id / child_entry_ids can be filled in during generation.

ID formats:
  process node:  {source-name-slug}-{node-id}-{import-seq}
  pitfall root:  {source-name-slug}-root-{import-seq}

The import-seq is a zero-padded 3-digit counter that is stable across retries
(idempotent): if .dag.json already contains an `entry_ids` field, the function
returns immediately without reassigning IDs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from holmes.kb.atomic import atomic_write


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_entry_ids(dag_json_path: Path) -> dict[str, str]:
    """Pre-generate and persist entry IDs for all DAG nodes.

    If ``entry_ids`` already exists in the .dag.json file, returns the
    existing mapping without modification (idempotent on retry).

    Args:
        dag_json_path: Absolute path to the ``.dag.json`` file produced by Agent 1.

    Returns:
        Mapping of ``{node_id: entry_id}`` with the special key ``"root"``
        holding the pitfall root entry ID.

    Raises:
        FileNotFoundError: If dag_json_path does not exist.
        ValueError: If the file cannot be parsed as valid JSON.
    """
    data = _load_dag_json(dag_json_path)

    # Idempotency: return existing IDs unchanged if already assigned.
    if data.get("entry_ids"):
        return dict(data["entry_ids"])

    # Determine import sequence number.
    state_dir = dag_json_path.parent
    import_seq = get_or_create_import_seq(state_dir, dag_json_path)

    # Build slug from source_file stem or dag title.
    source_file: str = data.get("source_file", "")
    title: str = data.get("title", "unknown")
    slug = _make_slug(source_file or title)

    # Assign IDs.
    entry_ids: dict[str, str] = {}
    nodes = data.get("nodes", [])
    for node in nodes:
        node_id: str = node.get("id", "")
        complexity: str = node.get("complexity", "simple")
        if complexity == "process" and node_id:
            entry_ids[node_id] = f"{slug}-{node_id}-{import_seq}"

    # Pitfall root ID.
    entry_ids["root"] = f"{slug}-root-{import_seq}"

    # Persist to .dag.json.
    data["entry_ids"] = entry_ids
    data["import_seq"] = import_seq
    try:
        atomic_write(dag_json_path, json.dumps(data, ensure_ascii=False, indent=2))
    except OSError as exc:
        raise OSError(f"id_gen: failed to write {dag_json_path}: {exc}") from exc

    return entry_ids


def get_or_create_import_seq(
    state_dir: Path,
    current_dag_path: Optional[Path] = None,
) -> str:
    """Return the next available import sequence number as a zero-padded string.

    Scans all ``.dag.json`` files in *state_dir* for existing ``import_seq``
    values and returns the next one.  If *current_dag_path* already has an
    ``import_seq`` it is reused (idempotency).

    Args:
        state_dir: Directory containing ``*.dag.json`` files
                   (typically ``<kb_root>/_import-state/``).
        current_dag_path: Path of the dag.json currently being processed;
                          its existing seq (if any) takes priority.

    Returns:
        Zero-padded 3-character string, e.g. ``"001"``, ``"002"``.
    """
    # Check if current file already has a seq.
    if current_dag_path is not None and current_dag_path.exists():
        try:
            data = json.loads(current_dag_path.read_text(encoding="utf-8"))
            if data.get("import_seq"):
                return str(data["import_seq"])
        except (json.JSONDecodeError, OSError):
            pass

    max_seq = 0
    if state_dir.exists():
        for p in state_dir.glob("*.dag.json"):
            if current_dag_path is not None and p == current_dag_path:
                continue
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                seq_str = d.get("import_seq", "")
                if seq_str:
                    try:
                        max_seq = max(max_seq, int(seq_str))
                    except ValueError:
                        pass
            except (json.JSONDecodeError, OSError):
                continue

    return f"{max_seq + 1:03d}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_dag_json(path: Path) -> dict:
    """Load and parse a .dag.json file."""
    if not path.exists():
        raise FileNotFoundError(f"id_gen: .dag.json not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"id_gen: invalid JSON in {path}: {exc}") from exc


def _make_slug(text: str) -> str:
    """Convert a file stem or title to a kebab-case ASCII slug.

    Examples:
        "hardware-init-failure.md" -> "hardware-init-failure"
        "GPU 初始化失败 — 固件修复" -> "gpu"
    """
    # Use file stem if it looks like a filename.
    stem = Path(text).stem if "." in text else text

    # Remove non-ASCII and replace spaces / underscores / punctuation with hyphens.
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", stem)
    slug = slug.strip("-").lower()

    # Limit length to avoid overly long IDs.
    if not slug:
        slug = "doc"
    return slug[:40]
