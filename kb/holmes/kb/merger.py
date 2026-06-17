"""Git conflict detection and 5-scenario intelligent merge.

Scans the KB for files containing git conflict markers and classifies
each conflict into one of five scenarios:

  1. pure_new          — only one side has the file (auto-resolve: keep it)
  2. evidence_append   — same id, only Resolution/Prevention sections differ
  3. maturity_change   — only maturity frontmatter field differs
  4. field_update      — non-content fields differ (tags, category, etc.)
  5. content_contradiction — Root Cause or Resolution text has real conflict
                             (isolate for human review)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import frontmatter

CONFLICT_MARKER_RE = re.compile(r"^<{7} ", re.MULTILINE)
SEPARATOR_RE = re.compile(r"^={7}$", re.MULTILINE)
REMOTE_RE = re.compile(r"^>{7} ", re.MULTILINE)

ConflictScenario = Literal[
    "pure_new",
    "evidence_append",
    "maturity_change",
    "field_update",
    "content_contradiction",
]


@dataclass
class ConflictFile:
    """A KB file that contains git conflict markers."""

    path: Path
    local_content: str
    remote_content: str


def parse_conflicts(kb_root: Path) -> list[ConflictFile]:
    """Scan KB for files with git conflict markers.

    Args:
        kb_root: Root directory of the knowledge base.

    Returns:
        List of ConflictFile objects (one per file with markers).
    """
    results: list[ConflictFile] = []
    for md_file in sorted(kb_root.rglob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        if not CONFLICT_MARKER_RE.search(text):
            continue
        local, remote = _split_conflict(text)
        results.append(ConflictFile(path=md_file, local_content=local, remote_content=remote))
    return results


def _split_conflict(text: str) -> tuple[str, str]:
    """Extract the two sides from a git conflict block.

    Args:
        text: File text containing git conflict markers.

    Returns:
        Tuple (local_content, remote_content).
    """
    # Pattern: <<<<<<< HEAD\n<local>\n=======\n<remote>\n>>>>>>> branch
    lines = text.splitlines(keepends=True)
    local_lines: list[str] = []
    remote_lines: list[str] = []
    in_local = False
    in_remote = False

    for line in lines:
        if line.startswith("<<<<<<<"):
            in_local = True
            continue
        if line.startswith("======="):
            in_local = False
            in_remote = True
            continue
        if line.startswith(">>>>>>>"):
            in_remote = False
            continue
        if in_local:
            local_lines.append(line)
        elif in_remote:
            remote_lines.append(line)
        else:
            # Context outside conflict blocks — append to both.
            local_lines.append(line)
            remote_lines.append(line)

    return "".join(local_lines), "".join(remote_lines)


def classify_conflict(local_content: str, remote_content: str) -> ConflictScenario:
    """Classify a conflict into one of five scenarios.

    Args:
        local_content: The local (HEAD) side content.
        remote_content: The remote (incoming) side content.

    Returns:
        ConflictScenario string.
    """
    if not local_content.strip():
        return "pure_new"
    if not remote_content.strip():
        return "pure_new"

    try:
        local_post = frontmatter.loads(local_content)
        remote_post = frontmatter.loads(remote_content)
    except Exception:  # noqa: BLE001
        return "content_contradiction"

    local_meta = local_post.metadata
    remote_meta = remote_post.metadata

    # Check if only maturity differs.
    if local_meta.get("id") == remote_meta.get("id"):
        meta_diffs = {
            k for k in set(local_meta) | set(remote_meta)
            if local_meta.get(k) != remote_meta.get(k)
        }

        if meta_diffs == {"maturity"}:
            return "maturity_change"

        if meta_diffs and not meta_diffs & {"id", "title"}:
            # Only non-identity fields differ — field_update unless body also differs.
            if local_post.content.strip() == remote_post.content.strip():
                return "field_update"

        # Check for evidence-only differences (Resolution/Prevention sections).
        if _only_evidence_differs(local_post.content, remote_post.content):
            return "evidence_append"

    return "content_contradiction"


def _only_evidence_differs(local_body: str, remote_body: str) -> bool:
    """Return True if only Resolution or Prevention sections differ."""
    evidence_sections = {"## resolution", "## prevention"}

    def strip_evidence(body: str) -> str:
        lines = body.splitlines()
        result: list[str] = []
        skip = False
        for line in lines:
            if line.strip().lower() in evidence_sections:
                skip = True
            elif line.startswith("## ") and line.strip().lower() not in evidence_sections:
                skip = False
            if not skip:
                result.append(line)
        return "\n".join(result)

    return strip_evidence(local_body).strip() == strip_evidence(remote_body).strip()


def auto_resolve(conflict_file: ConflictFile) -> Optional[str]:
    """Attempt to automatically resolve a conflict.

    For pure_new / evidence_append / maturity_change / field_update,
    returns the resolved Markdown string. For content_contradiction, returns None.

    Args:
        conflict_file: ConflictFile with local and remote sides.

    Returns:
        Resolved Markdown string or None.
    """
    scenario = classify_conflict(
        conflict_file.local_content, conflict_file.remote_content
    )

    if scenario == "pure_new":
        content = conflict_file.remote_content or conflict_file.local_content
        return content.strip() + "\n"

    if scenario == "evidence_append":
        return _merge_evidence(conflict_file.local_content, conflict_file.remote_content)

    if scenario == "maturity_change":
        return _merge_maturity(conflict_file.local_content, conflict_file.remote_content)

    if scenario == "field_update":
        # Take the newer version based on updated_at timestamp.
        return _merge_field_update(conflict_file.local_content, conflict_file.remote_content)

    return None  # content_contradiction


def _merge_evidence(local: str, remote: str) -> str:
    """Merge by appending remote Resolution/Prevention content to local."""
    try:
        local_post = frontmatter.loads(local)
        remote_post = frontmatter.loads(remote)
    except Exception:  # noqa: BLE001
        return local

    # Append remote Resolution/Prevention blocks to local body.
    remote_lines = remote_post.content.splitlines()
    extra_lines: list[str] = []
    in_target = False
    for line in remote_lines:
        if line.strip().lower() in {"## resolution", "## prevention"}:
            in_target = True
        elif line.startswith("## ") and line.strip().lower() not in {"## resolution", "## prevention"}:
            in_target = False
        if in_target:
            extra_lines.append(line)

    extra = "\n".join(extra_lines).strip()
    if extra and extra not in local_post.content:
        local_post.content = local_post.content.rstrip() + "\n\n" + extra + "\n"

    return frontmatter.dumps(local_post)


def _merge_maturity(local: str, remote: str) -> str:
    """Resolve maturity conflict.

    - Upgrade (remote > local): take the higher value (e.g. draft → verified).
    - Downgrade dispute (remote < local, e.g. proven vs draft): take the lower
      value and append the 'contradiction' tag for human follow-up.
    - Same value: no change.
    """
    maturity_rank = {"draft": 0, "verified": 1, "proven": 2, "deprecated": -1}
    try:
        local_post = frontmatter.loads(local)
        remote_post = frontmatter.loads(remote)
    except Exception:  # noqa: BLE001
        return local

    local_m = str(local_post.metadata.get("maturity", "draft"))
    remote_m = str(remote_post.metadata.get("maturity", "draft"))
    local_r = maturity_rank.get(local_m, 0)
    remote_r = maturity_rank.get(remote_m, 0)

    if remote_r > local_r:
        # Unambiguous upgrade — take the higher value.
        local_post.metadata["maturity"] = remote_m
    elif remote_r < local_r:
        # Downgrade dispute — take the lower value and flag for review.
        local_post.metadata["maturity"] = remote_m
        tags = list(local_post.metadata.get("tags", []))
        if "contradiction" not in tags:
            tags.append("contradiction")
        local_post.metadata["tags"] = tags
    # else: same rank — no change.

    return frontmatter.dumps(local_post)


def merge_pending_entry(kb_root: Path, pending_content: str) -> dict:
    """Merge a pending KB entry into the knowledge base using 5-scenario logic.

    This function implements the same 5-scenario merge logic as the old
    ``holmes/holmes/kb/merger.py:merge_entry()`` but uses the new package API.

    Args:
        kb_root: Root directory of the knowledge base.
        pending_content: Raw Markdown string with YAML frontmatter.

    Returns:
        Dict with ``scenario``, ``action``, ``entry_id``, and optional ``conflict_id``.
    """
    from datetime import datetime, timezone

    import frontmatter as fm

    from holmes.kb.conflict import ConflictFile, write_conflict_entry
    from holmes.kb.pending import append_log
    from holmes.kb.store import list_entries, read_entry, rebuild_index_files, write_entry

    _MATURITY_ORDER = {"draft": 0, "verified": 1, "proven": 2}

    try:
        post = fm.loads(pending_content)
    except Exception:  # noqa: BLE001
        return {"scenario": "error", "action": "failed", "entry_id": ""}

    entry_id = str(post.metadata.get("id", ""))
    kb_type = str(post.metadata.get("type", "pitfall"))
    category = post.metadata.get("category")
    new_maturity = str(post.metadata.get("maturity", "draft"))

    existing_content = read_entry(kb_root, entry_id) if entry_id else None

    if existing_content is None:
        # Scenario 1: Pure add — entry does not yet exist in the KB.
        if kb_type == "pitfall" and category:
            entry_path = kb_root / kb_type / str(category) / f"{entry_id}.md"
        else:
            entry_path = kb_root / kb_type / f"{entry_id}.md"
        write_entry(entry_path, pending_content)
        rebuild_index_files(kb_root)
        title = str(post.metadata.get("title", entry_id))
        append_log(kb_root, "merged-pure-add", entry_id, title)
        return {"scenario": "pure_add", "action": "written", "entry_id": entry_id}

    # Parse existing entry to compare maturity.
    try:
        existing_post = fm.loads(existing_content)
    except Exception:  # noqa: BLE001
        existing_post = None

    existing_maturity = str(existing_post.metadata.get("maturity", "draft")) if existing_post else "draft"
    existing_title = str(existing_post.metadata.get("title", entry_id)) if existing_post else entry_id

    existing_rank = _MATURITY_ORDER.get(existing_maturity, 0)
    new_rank = _MATURITY_ORDER.get(new_maturity, 0)

    # Find the existing entry's file path via list_entries.
    existing_path: Path | None = None
    for meta in list_entries(kb_root):
        if meta.id.upper() == entry_id.upper():
            existing_path = Path(meta.file_path)
            break

    if existing_path is None:
        # Fallback: should not happen since read_entry found it.
        return {"scenario": "error", "action": "failed", "entry_id": entry_id}

    if new_rank <= existing_rank:
        # Scenario 2: Evidence append — same or lower maturity incoming.
        now_str = datetime.now(timezone.utc).date().isoformat()
        merged_body = (
            (existing_post.content if existing_post else "")
            + f"\n\n---\n\n*Additional evidence (merged {now_str})*\n\n"
            + post.content
        )
        if existing_post:
            existing_post.content = merged_body
            existing_post.metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
            write_entry(existing_path, fm.dumps(existing_post))
        rebuild_index_files(kb_root)
        append_log(kb_root, "merged-evidence-append", entry_id, existing_title)
        return {"scenario": "evidence_append", "action": "appended", "entry_id": entry_id}

    if new_rank > existing_rank:
        # Scenario 3: Maturity upgrade.
        if existing_post:
            existing_post.metadata["maturity"] = new_maturity
            existing_post.metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
            write_entry(existing_path, fm.dumps(existing_post))
        rebuild_index_files(kb_root)
        append_log(kb_root, "merged-maturity-upgrade", entry_id, f"{existing_title} → {new_maturity}")
        return {"scenario": "maturity_upgrade", "action": "upgraded", "entry_id": entry_id}

    # Scenario 4/5: Content contradiction — isolate for human review.
    cf = ConflictFile(path=existing_path, local_content=existing_content, remote_content=pending_content)
    conflict_id = write_conflict_entry(kb_root, cf)
    return {
        "scenario": "content_contradiction",
        "action": "isolated",
        "entry_id": entry_id,
        "conflict_id": conflict_id,
    }


def _merge_field_update(local: str, remote: str) -> str:
    """Resolve field update by taking the version with the newer updated_at."""
    try:
        local_post = frontmatter.loads(local)
        remote_post = frontmatter.loads(remote)
    except Exception:  # noqa: BLE001
        return local

    local_ts = str(local_post.metadata.get("updated_at", ""))
    remote_ts = str(remote_post.metadata.get("updated_at", ""))

    if remote_ts > local_ts:
        return remote
    return local
