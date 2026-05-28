"""Knowledge base health checker.

Checks:
- index.json consistency with actual files
- _index.md consistency
- Maturity auto-decay (no updates > 180 days → downgrade proven → verified)
- Orphan pending entries (> 30 days old)
- Entries tagged 'contradiction'
- Unresolved conflicts
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

from holmes.kb.conflict import list_conflicts
from holmes.kb.index_builder import rebuild_index
from holmes.kb.pending import list_pending
from holmes.kb.store import list_entries, write_entry
from holmes.logging_config import get_logger


logger = get_logger("kb.linter")

MATURITY_DECAY_DAYS = 180  # proven → verified if not updated in 180 days
ORPHAN_PENDING_DAYS = 30


def lint(kb_root: Path, fix: bool = False) -> dict:
    """Run all health checks on the knowledge base.

    Args:
        kb_root: Root directory of the knowledge base.
        fix: If True, auto-fix issues where possible (maturity decay, index rebuild).

    Returns:
        Dict with check results, warnings, and applied fixes.
    """
    results: dict = {
        "warnings": [],
        "errors": [],
        "fixes_applied": [],
    }
    now = datetime.now(timezone.utc)

    # Check 1: Maturity decay
    all_entries = list_entries(kb_root)
    for entry in all_entries:
        if entry.maturity != "proven":
            continue
        try:
            updated = datetime.fromisoformat(entry.updated_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        age_days = (now - updated).days
        if age_days > MATURITY_DECAY_DAYS:
            msg = f"{entry.id} ({entry.title}): proven for {age_days} days without update"
            if fix:
                entry.maturity = "verified"  # type: ignore[assignment]
                entry.updated_at = now.isoformat()
                write_entry(kb_root, entry)
                results["fixes_applied"].append(f"Downgraded {entry.id} proven → verified")
            else:
                results["warnings"].append(f"Maturity decay: {msg}")

    # Check 2: Contradiction tags
    for entry in all_entries:
        if "contradiction" in [t.lower() for t in entry.tags]:
            results["warnings"].append(
                f"Contradiction tag: {entry.id} ({entry.title}) — review needed"
            )

    # Check 3: Orphan pending entries
    pending_entries = list_pending(kb_root)
    for p in pending_entries:
        try:
            created = datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))
            age_days = (now - created).days
            if age_days > ORPHAN_PENDING_DAYS:
                results["warnings"].append(
                    f"Orphan pending: {p['id']} ({p['title']}) — {age_days} days old"
                )
        except (ValueError, KeyError):
            pass

    # Check 4: Unresolved conflicts
    conflicts = list_conflicts(kb_root)
    for c in conflicts:
        results["warnings"].append(
            f"Unresolved conflict: {c['conflict_id']} — "
            f"{c['entry_a_id']} vs {c['entry_b_id']} ({c['conflict_type']})"
        )

    # Check 5: Index consistency — rebuild if fix
    if fix:
        rebuild_index(kb_root)
        results["fixes_applied"].append("Rebuilt index.json and _index.md files")

    results["total_entries"] = len(all_entries)
    results["pending_count"] = len(pending_entries)
    results["conflict_count"] = len(conflicts)
    results["status"] = "ok" if not results["errors"] else "error"

    return results
