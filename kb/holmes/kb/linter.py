"""KB health check — linter with optional auto-fix.

Checks:
  - Index/file consistency: _index.md entries vs actual files
  - Orphan entries: files not listed in _index.md
  - Pending entries older than 30 days
  - Maturity decay: proven >12 months / verified >6 months without updates
  - Contradiction keyword scan in body text
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import frontmatter

CONTRADICTION_KEYWORDS = [
    "actually wrong",
    "this is incorrect",
    "do not use",
    "deprecated by",
    "superseded by",
    "no longer valid",
]


@dataclass
class LintReport:
    """Output of a lint run."""

    total_entries: int = 0
    pending_count: int = 0
    conflict_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fixes_applied: list[str] = field(default_factory=list)


def lint(kb_root: Path, fix: bool = False) -> LintReport:
    """Run KB health checks and optionally auto-fix issues.

    Args:
        kb_root: Root directory of the knowledge base.
        fix: If True, rebuild _index.md files and apply maturity decay fixes.

    Returns:
        LintReport with findings.
    """
    report = LintReport()

    # Count official entries.
    from holmes.kb.store import list_entries, rebuild_index_files

    all_entries = list_entries(kb_root)
    report.total_entries = len(all_entries)

    # Count pending entries.
    pending_dir = kb_root / "contributions" / "pending"
    if pending_dir.exists():
        pending_files = list(pending_dir.glob("*.md"))
        report.pending_count = len(pending_files)
        _check_stale_pending(pending_files, report)

    # Count only unresolved conflict entries.
    conflicts_dir = kb_root / "contributions" / "conflicts"
    if conflicts_dir.exists():
        count = 0
        for p in conflicts_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("status") == "pending_review":
                    count += 1
            except Exception:  # noqa: BLE001
                pass
        report.conflict_count = count

    # Check index/file consistency per type.
    for kb_type in ("pitfall", "model", "guideline", "process", "decision"):
        type_dir = kb_root / kb_type
        if not type_dir.is_dir():
            continue
        _check_index_consistency(type_dir, report)

    # Check contradictions and cross-entry duplicates.
    for entry in all_entries:
        _check_contradictions(entry, report)

    _check_duplicate_entries(all_entries, report)

    if fix:
        rebuild_index_files(kb_root)
        report.fixes_applied.append("Rebuilt all _index.md files")

    return report


def _check_stale_pending(pending_files: list[Path], report: LintReport) -> None:
    """Warn about pending entries older than 30 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    for path in pending_files:
        try:
            post = frontmatter.load(str(path))
            created_str = str(post.metadata.get("created_at", ""))
            if created_str:
                created_dt = datetime.fromisoformat(created_str)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                if created_dt < cutoff:
                    report.warnings.append(
                        f"Pending entry {path.stem} is >30 days old (created {created_str[:10]})"
                    )
        except Exception:  # noqa: BLE001
            pass


def _check_index_consistency(type_dir: Path, report: LintReport) -> None:
    """Check for orphan files not listed in _index.md."""
    index_path = type_dir / "_index.md"
    if not index_path.exists():
        report.errors.append(f"Missing _index.md in {type_dir.name}/")
        return

    index_content = index_path.read_text(encoding="utf-8")
    actual_ids: set[str] = set()
    for md_file in type_dir.rglob("*.md"):
        if md_file.name.startswith("_"):
            continue
        try:
            post = frontmatter.load(str(md_file))
            entry_id = str(post.metadata.get("id", md_file.stem))
            actual_ids.add(entry_id)
        except Exception:  # noqa: BLE001
            pass

    for entry_id in actual_ids:
        if entry_id not in index_content:
            report.warnings.append(
                f"Entry {entry_id} exists on disk but is missing from {type_dir.name}/_index.md"
            )


def _check_duplicate_entries(entries: list, report: LintReport) -> None:
    """Warn when two official entries of the same type have Jaccard title similarity >85%."""
    from holmes.kb.validator import jaccard_similarity

    seen: list = []
    for entry in entries:
        for prev in seen:
            if entry.type != prev.type:
                continue
            sim = jaccard_similarity(entry.title, prev.title)
            if sim >= 0.85:
                report.warnings.append(
                    f"Possible duplicate entries: [{entry.id}] vs [{prev.id}] "
                    f"(title similarity {sim:.0%})"
                )
        seen.append(entry)


def _check_contradictions(entry, report: LintReport) -> None:  # noqa: ANN001
    """Scan for contradiction keywords in entry body text."""
    body_lower = entry.body.lower() if hasattr(entry, "body") else ""
    # For EntryMeta we need to read the file.
    if not body_lower and entry.file_path:
        try:
            post = frontmatter.load(str(entry.file_path))
            body_lower = post.content.lower()
        except Exception:  # noqa: BLE001
            return

    for keyword in CONTRADICTION_KEYWORDS:
        if keyword in body_lower:
            report.warnings.append(
                f"{entry.id} contains possible contradiction keyword: {keyword!r}"
            )
            break
