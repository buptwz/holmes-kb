"""Knowledge base maturity decay — offline batch scan and demotion.

Scans all public KB entries, computes elapsed time since last evidence reference,
and demotes entries whose maturity has gone stale beyond the configured thresholds.

Saves a VersionSnapshot to .history/ for each demoted entry.
Records a system "decayed" evidence sidecar per demotion so the read-time
maturity derivation (derive_maturity) follows the demotion.
Logs all decay events to contributions/log.md.

Usage:
    from holmes.kb.decay import run_decay
    result = run_decay(kb_root, dry_run=False)
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter
import yaml

from holmes.kb.atomic import atomic_write
from holmes.kb.pending import append_log
from holmes.kb.store import (
    EVIDENCE_SIDECAR_DIR,
    entry_lock,
    list_entries,
    load_evidence,
    write_entry,
)

ARCHIVE_DIR = "contributions/archive"

# Default decay thresholds (months).
DEFAULT_PROVEN_MONTHS = 12
DEFAULT_VERIFIED_MONTHS = 6
DEFAULT_DRAFT_MIN_AGE_DAYS = 30   # draft must exist this long before archiving
DEFAULT_DRAFT_STALE_MONTHS = 3    # draft must be unreferenced this long

MATURITY_ORDER: dict[str, int] = {"draft": 0, "verified": 1, "proven": 2}


@dataclass
class DecayChange:
    """Records a single maturity demotion."""

    id: str
    old_maturity: str
    new_maturity: str
    last_evidence_date: Optional[str]   # ISO string of most recent evidence or None
    months_unreferenced: int


@dataclass
class DecayResult:
    """Aggregate result of a decay scan run."""

    scanned: int = 0
    changes: list[DecayChange] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def decayed(self) -> int:
        return len(self.changes)


def _load_decay_config(kb_root: Path) -> dict:
    """Load decay thresholds from kb-config.yml, falling back to defaults."""
    config_path = kb_root / "kb-config.yml"
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            decay_cfg = data.get("decay", {})
            return {
                "proven_months": int(decay_cfg.get("proven_months", DEFAULT_PROVEN_MONTHS)),
                "verified_months": int(decay_cfg.get("verified_months", DEFAULT_VERIFIED_MONTHS)),
                "draft_min_age_days": int(decay_cfg.get("draft_min_age_days", DEFAULT_DRAFT_MIN_AGE_DAYS)),
                "draft_stale_months": int(decay_cfg.get("draft_stale_months", DEFAULT_DRAFT_STALE_MONTHS)),
            }
        except Exception:  # noqa: BLE001
            pass
    return {
        "proven_months": DEFAULT_PROVEN_MONTHS,
        "verified_months": DEFAULT_VERIFIED_MONTHS,
        "draft_min_age_days": DEFAULT_DRAFT_MIN_AGE_DAYS,
        "draft_stale_months": DEFAULT_DRAFT_STALE_MONTHS,
    }


def _get_reference_date(metadata: dict) -> datetime:
    """Compute the most recent reference date for an entry.

    Priority:
    1. max(evidence[*].date) — primary source
    2. last_referenced — legacy field
    3. updated_at — fallback

    Returns datetime.min (UTC) if no date is found.
    """
    evidence = metadata.get("evidence") or []
    if evidence:
        dates: list[datetime] = []
        for rec in evidence:
            date_str = rec.get("date") if isinstance(rec, dict) else None
            if date_str:
                try:
                    dt = datetime.fromisoformat(str(date_str))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    dates.append(dt)
                except ValueError:
                    pass
        if dates:
            return max(dates)

    # Legacy / fallback fields.
    for field_name in ("last_referenced", "updated_at"):
        val = metadata.get(field_name)
        if val:
            try:
                dt = datetime.fromisoformat(str(val))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                pass

    return datetime.min.replace(tzinfo=timezone.utc)


def _months_since(ref_date: datetime) -> int:
    """Return approximate number of whole months since ref_date."""
    now = datetime.now(timezone.utc)
    delta = now - ref_date
    return int(delta.days / 30)


def run_decay(
    kb_root: Path,
    dry_run: bool = False,
    kb_type: Optional[str] = None,
) -> DecayResult:
    """Scan public KB entries and demote any that have exceeded staleness thresholds.

    Args:
        kb_root: Root directory of the knowledge base.
        dry_run: If True, compute changes but do not write them to disk.
        kb_type: If provided, limit scan to entries of this type.

    Returns:
        DecayResult summarising the scan.
    """
    from holmes.kb.history import save_snapshot

    config = _load_decay_config(kb_root)
    proven_threshold = config["proven_months"]
    verified_threshold = config["verified_months"]

    result = DecayResult()
    entries = list_entries(kb_root, kb_type=kb_type)
    result.scanned = len(entries)

    draft_min_age = config["draft_min_age_days"]
    draft_stale = config["draft_stale_months"]

    for entry_meta in entries:
        entry_id = entry_meta.id
        maturity = entry_meta.maturity

        if maturity not in ("proven", "verified", "draft"):
            continue

        entry_path = Path(entry_meta.file_path)
        if not entry_path.exists():
            result.errors.append(f"{entry_id}: file not found at {entry_path}")
            continue

        try:
            post = frontmatter.load(str(entry_path))
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{entry_id}: failed to parse frontmatter: {exc}")
            continue

        # Combine frontmatter evidence with sidecar files for accurate reference date.
        # Decay's own system records (outcome "decayed") are excluded — they are
        # demotion events, not references, and must not reset the staleness clock.
        evidence = [
            r for r in load_evidence(kb_root, entry_id, post.metadata.get("evidence"))
            if r.get("outcome") != "decayed"
        ]
        metadata_with_evidence = {**post.metadata, "evidence": evidence}
        ref_date = _get_reference_date(metadata_with_evidence)
        months_ago = _months_since(ref_date)

        # --- Draft auto-archive: old + stale → move to archive ---
        if maturity == "draft":
            created_at = post.metadata.get("created_at")
            age_days = 0
            if created_at:
                try:
                    dt = datetime.fromisoformat(str(created_at))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age_days = (datetime.now(timezone.utc) - dt).days
                except ValueError:
                    pass
            if age_days >= draft_min_age and months_ago >= draft_stale:
                change = DecayChange(
                    id=entry_id,
                    old_maturity="draft",
                    new_maturity="archived",
                    last_evidence_date=None,
                    months_unreferenced=months_ago,
                )
                result.changes.append(change)
                if not dry_run:
                    try:
                        with entry_lock(kb_root, entry_id):
                            archive_orphan(kb_root, entry_id)
                        append_log(
                            kb_root, action="archived", entry_id=entry_id,
                            summary=f"draft stale {months_ago} months, age {age_days} days",
                        )
                    except Exception as exc:  # noqa: BLE001
                        result.errors.append(f"{entry_id}: archive failed: {exc}")
            continue  # draft: either archived or skipped, no demotion path

        # --- Proven/Verified demotion ---
        new_maturity: Optional[str] = None
        if maturity == "proven" and months_ago > proven_threshold:
            new_maturity = "verified"
        elif maturity == "verified" and months_ago > verified_threshold:
            new_maturity = "draft"

        if new_maturity is None:
            continue

        last_evidence_iso: Optional[str] = None
        if evidence:
            dates = [r.get("date") for r in evidence if isinstance(r, dict) and r.get("date")]
            if dates:
                last_evidence_iso = max(str(d) for d in dates)

        change = DecayChange(
            id=entry_id,
            old_maturity=maturity,
            new_maturity=new_maturity,
            last_evidence_date=last_evidence_iso,
            months_unreferenced=months_ago,
        )
        result.changes.append(change)

        if dry_run:
            continue

        # Apply demotion.
        try:
            with entry_lock(kb_root, entry_id):
                original_content = entry_path.read_text(encoding="utf-8")
                save_snapshot(kb_root, entry_id, original_content, replaced_by="decay", reason="decay")

                now = datetime.now(timezone.utc)
                post.metadata["maturity"] = new_maturity
                post.metadata["updated_at"] = now.isoformat()
                atomic_write(entry_path, frontmatter.dumps(post))

                # Event-sourced demotion: record a system "decayed" evidence
                # sidecar so the read-time derivation (derive_maturity) sees
                # the same demotion and rebuild recalibration cannot bounce
                # the level back up.
                reason = f"{maturity} → {new_maturity}: unreferenced {months_ago} months"
                decay_tag = now.strftime("%Y%m%d")
                record = {
                    "session_id": f"decay-{decay_tag}",
                    "contributor": "system",
                    "outcome": "decayed",
                    "date": now.date().isoformat(),
                    "maturity_after": new_maturity,
                    "reason": reason,
                }
                sidecar_file = kb_root / EVIDENCE_SIDECAR_DIR / entry_id / f"decay-{decay_tag}.json"
                atomic_write(sidecar_file, json.dumps(record, ensure_ascii=False))

            append_log(
                kb_root,
                action="decay",
                entry_id=entry_id,
                summary=reason,
            )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{entry_id}: failed to apply decay: {exc}")

    return result


def archive_orphan(kb_root: Path, entry_id: str) -> Path:
    """Move an orphaned draft entry (no evidence) to contributions/archive/.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: ID of the orphaned draft entry.

    Returns:
        New path of the archived file.

    Raises:
        FileNotFoundError: If the entry cannot be found.
    """
    from holmes.kb.store import rebuild_index_files

    # Find the entry.
    entry_path: Optional[Path] = None
    for meta in list_entries(kb_root):
        if meta.id == entry_id:
            entry_path = Path(meta.file_path)
            break

    if entry_path is None or not entry_path.exists():
        raise FileNotFoundError(f"Entry not found: {entry_id}")

    archive_dir = kb_root / ARCHIVE_DIR
    archive_dir.mkdir(parents=True, exist_ok=True)
    dst = archive_dir / entry_path.name

    shutil.move(str(entry_path), str(dst))
    rebuild_index_files(kb_root)
    append_log(kb_root, action="archived", entry_id=entry_id, summary="orphan draft with no evidence")

    return dst
