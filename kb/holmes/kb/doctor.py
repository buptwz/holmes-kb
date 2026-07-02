"""Holmes KB Doctor — comprehensive self-diagnostic with optional auto-fix.

Checks configuration, directory structure, entry integrity, index consistency,
search health, skill validation, evidence/maturity correctness, and git state.

Usage via CLI::

    holmes doctor           # read-only diagnosis
    holmes doctor --fix     # apply safe auto-fixes
    holmes doctor --verbose # show per-entry details
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import frontmatter

from holmes.config import HolmesConfig, _holmes_home, load_config


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class CheckItem:
    """A single diagnostic finding."""

    category: str
    level: str  # "ok", "fixed", "warn", "error"
    message: str


@dataclass
class DoctorReport:
    """Aggregated results of a doctor run."""

    items: list[CheckItem] = field(default_factory=list)
    fix_count: int = 0
    warn_count: int = 0
    error_count: int = 0
    elapsed_ms: int = 0

    def ok(self, cat: str, msg: str) -> None:
        self.items.append(CheckItem(cat, "ok", msg))

    def fixed(self, cat: str, msg: str) -> None:
        self.items.append(CheckItem(cat, "fixed", msg))
        self.fix_count += 1

    def warn(self, cat: str, msg: str) -> None:
        self.items.append(CheckItem(cat, "warn", msg))
        self.warn_count += 1

    def error(self, cat: str, msg: str) -> None:
        self.items.append(CheckItem(cat, "error", msg))
        self.error_count += 1


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_doctor(
    kb_root: Optional[Path] = None,
    fix: bool = False,
    verbose: bool = False,
    check_api: bool = False,
) -> DoctorReport:
    """Run all diagnostic checks.

    Args:
        kb_root: KB root directory. Resolved from config if None.
        fix: If True, apply safe auto-fixes.
        verbose: If True, include per-entry detail items.
        check_api: If True, test LLM API connectivity.

    Returns:
        DoctorReport with all findings.
    """
    t0 = time.monotonic()
    report = DoctorReport()

    # --- 1. Configuration ---
    cfg = _check_config(report)

    # --- 2. KB root resolution ---
    if kb_root is None:
        if cfg and cfg.kb_path:
            kb_root = Path(cfg.kb_path)
        else:
            report.error("config", "kb_path not configured. Run: holmes setup --kb-path <path>")
            report.elapsed_ms = int((time.monotonic() - t0) * 1000)
            return report

    if not kb_root.is_dir():
        report.error("config", f"KB directory does not exist: {kb_root}")
        report.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return report

    if not os.access(kb_root, os.W_OK):
        report.error("config", f"KB directory is not writable: {kb_root}")
    else:
        report.ok("config", f"KB path: {kb_root}")

    # --- 3. Directory structure ---
    _check_directories(kb_root, fix, report)

    # --- 4. .gitignore ---
    _check_gitignore(kb_root, fix, report)

    # --- 5. Entry integrity ---
    all_entries = _check_entries(kb_root, fix, verbose, report)

    # --- 6. Index consistency ---
    _check_index(kb_root, fix, report, expected_count=len(all_entries))

    # --- 7. Orphaned temp files ---
    _check_tmp_files(kb_root, fix, report)

    # --- 8. Pending entries ---
    _check_pending(kb_root, verbose, report)

    # --- 9. Trash state ---
    _check_trash(kb_root, all_entries, report)

    # --- 10. Evidence & maturity ---
    _check_evidence_maturity(kb_root, all_entries, fix, verbose, report)

    # --- 11. Skills ---
    _check_skills(kb_root, all_entries, fix, verbose, report)

    # --- 12. Search health ---
    _check_search(kb_root, report)

    # --- 13. LLM provider ---
    _check_llm(cfg, check_api, report)

    # --- 14. Git state ---
    _check_git(kb_root, report)

    # --- 15. Contributions structure ---
    _check_contributions(kb_root, fix, report)

    report.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return report


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

CAT_CONFIG = "config"
CAT_DIR = "directory"
CAT_ENTRY = "entry"
CAT_INDEX = "index"
CAT_PENDING = "pending"
CAT_TRASH = "trash"
CAT_EVIDENCE = "evidence"
CAT_SKILL = "skill"
CAT_SEARCH = "search"
CAT_LLM = "llm"
CAT_GIT = "git"
CAT_CONTRIB = "contributions"
CAT_CLEANUP = "cleanup"


def _check_config(report: DoctorReport) -> Optional[HolmesConfig]:
    """Check config file existence and required fields."""
    home = _holmes_home()
    config_path = home / "config.json"

    if not config_path.exists():
        report.error(CAT_CONFIG, f"Config file missing: {config_path}. Run: holmes setup")
        return None

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.error(CAT_CONFIG, f"Config file is invalid JSON: {e}")
        return None

    cfg = HolmesConfig.from_dict(data)

    if not cfg.kb_path:
        report.error(CAT_CONFIG, "kb_path not set in config")
    if not cfg.api_key and not cfg.api_base_url:
        report.warn(CAT_CONFIG, "No LLM credentials (api_key / api_base_url). Import pipeline won't work.")
    if not cfg.model:
        report.warn(CAT_CONFIG, "model not set in config")
    else:
        report.ok(CAT_CONFIG, f"Model: {cfg.model} (provider: {cfg.provider})")
    if not cfg.username:
        report.warn(CAT_CONFIG, "username not set (recommended for contribution tracking)")

    return cfg


_REQUIRED_DIRS = [
    "pitfall", "model", "guideline", "process", "decision",
    "_drafts", "_pending", "_trash", ".history",
    "skills",
    "contributions", "contributions/evidence", "contributions/pending",
    "contributions/archive", "contributions/conflicts",
]


def _check_directories(kb_root: Path, fix: bool, report: DoctorReport) -> None:
    """Check required KB subdirectories exist."""
    missing = []
    for d in _REQUIRED_DIRS:
        p = kb_root / d
        if not p.is_dir():
            missing.append(d)
            if fix:
                p.mkdir(parents=True, exist_ok=True)

    if missing:
        if fix:
            report.fixed(CAT_DIR, f"Created missing directories: {', '.join(missing)}")
        else:
            report.warn(CAT_DIR, f"Missing directories (--fix to create): {', '.join(missing)}")
    else:
        report.ok(CAT_DIR, f"All {len(_REQUIRED_DIRS)} required directories present")


def _check_gitignore(kb_root: Path, fix: bool, report: DoctorReport) -> None:
    """Check .gitignore includes generated files."""
    gitignore = kb_root / ".gitignore"
    required_entries = ["index.json"]

    if not gitignore.exists():
        if fix:
            gitignore.write_text("\n".join(required_entries) + "\n", encoding="utf-8")
            report.fixed(CAT_DIR, ".gitignore created with: " + ", ".join(required_entries))
        else:
            report.warn(CAT_DIR, ".gitignore missing (--fix to create)")
        return

    content = gitignore.read_text(encoding="utf-8")
    lines = content.splitlines()
    missing = [e for e in required_entries if e not in lines]

    if missing:
        if fix:
            new = content.rstrip("\n") + "\n" + "\n".join(missing) + "\n"
            gitignore.write_text(new, encoding="utf-8")
            report.fixed(CAT_DIR, f".gitignore updated: added {', '.join(missing)}")
        else:
            report.warn(CAT_DIR, f".gitignore missing entries: {', '.join(missing)} (--fix to add)")
    else:
        report.ok(CAT_DIR, ".gitignore OK")


def _check_entries(
    kb_root: Path, fix: bool, verbose: bool, report: DoctorReport
) -> list:
    """Validate all active KB entries. Returns list of EntryMeta."""
    from holmes.kb.schema import (
        REQUIRED_FRONTMATTER_FIELDS,
        TYPE_REQUIRED_SECTIONS,
        VALID_MATURITY,
        VALID_PITFALL_CATEGORIES,
        VALID_TYPES,
    )
    from holmes.kb.store import list_entries

    entries = list_entries(kb_root)
    if not entries:
        report.warn(CAT_ENTRY, "No entries found in KB")
        return entries

    error_count = 0
    warn_count = 0
    ids_seen: dict[str, str] = {}  # id_lower -> file_path

    for entry in entries:
        fp = Path(entry.file_path) if entry.file_path else None
        if not fp or not fp.is_file():
            report.error(CAT_ENTRY, f"{entry.id}: file missing — {entry.file_path}")
            error_count += 1
            continue

        try:
            post = frontmatter.load(str(fp))
        except Exception as e:
            report.error(CAT_ENTRY, f"{entry.id}: YAML parse error — {e}")
            error_count += 1
            continue

        meta = post.metadata
        entry_errors: list[str] = []
        entry_fixed = False

        # Auto-fix missing timestamps from file mtime
        if fix:
            mtime = datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc)
            mtime_iso = mtime.isoformat()
            if "created_at" not in meta:
                meta["created_at"] = mtime_iso
                entry_fixed = True
            if "updated_at" not in meta:
                meta["updated_at"] = mtime_iso
                entry_fixed = True
            # Fix maturity case/missing
            mat = meta.get("maturity", "")
            if not mat or str(mat) not in VALID_MATURITY:
                meta["maturity"] = "draft"
                entry_fixed = True
            # Fix missing tags
            if "tags" not in meta:
                meta["tags"] = []
                entry_fixed = True

        # Required fields
        for f in REQUIRED_FRONTMATTER_FIELDS:
            if f not in meta:
                entry_errors.append(f"missing field '{f}'")

        # Type validity
        kb_type = str(meta.get("type", ""))
        if kb_type and kb_type not in VALID_TYPES:
            entry_errors.append(f"invalid type '{kb_type}'")

        # Maturity validity
        maturity = str(meta.get("maturity", ""))
        if maturity and maturity not in VALID_MATURITY:
            entry_errors.append(f"invalid maturity '{maturity}'")

        # Pitfall category
        if kb_type == "pitfall":
            cat = str(meta.get("category", ""))
            if cat and cat not in VALID_PITFALL_CATEGORIES:
                entry_errors.append(f"invalid pitfall category '{cat}'")

        # Tags must be list
        tags = meta.get("tags")
        if tags is not None and not isinstance(tags, list):
            if fix:
                meta["tags"] = []
                from holmes.kb.atomic import atomic_write
                atomic_write(fp, frontmatter.dumps(post))
                report.fixed(CAT_ENTRY, f"{entry.id}: converted tags to list")
            else:
                entry_errors.append("tags is not a list")

        # Required body sections (content quality — warn, not error)
        if kb_type in TYPE_REQUIRED_SECTIONS:
            body_lower = post.content.lower()
            missing_sections = [
                s for s in TYPE_REQUIRED_SECTIONS[kb_type]
                if s.lower() not in body_lower
            ]
            if missing_sections:
                warn_count += 1
                if verbose:
                    report.warn(CAT_ENTRY,
                                f"{entry.id}: missing sections: {', '.join(missing_sections)}")

        # ID uniqueness
        id_lower = entry.id.lower()
        if id_lower in ids_seen:
            entry_errors.append(f"duplicate ID (also in {ids_seen[id_lower]})")
        else:
            ids_seen[id_lower] = str(fp)

        # Child references
        children = meta.get("child_entry_ids")
        if isinstance(children, list):
            for cid in children:
                if str(cid).lower() not in ids_seen and not _entry_exists(kb_root, str(cid)):
                    warn_count += 1
                    if verbose:
                        report.warn(CAT_ENTRY, f"{entry.id}: child '{cid}' not found")

        # Write back fixes
        if entry_fixed:
            from holmes.kb.atomic import atomic_write
            atomic_write(fp, frontmatter.dumps(post))
            report.fixed(CAT_ENTRY, f"{entry.id}: filled missing frontmatter fields")

        if entry_errors:
            error_count += 1
            if verbose:
                for e in entry_errors:
                    report.error(CAT_ENTRY, f"{entry.id}: {e}")

    if error_count:
        report.error(CAT_ENTRY, f"{error_count}/{len(entries)} entries have errors" +
                     (" (use --verbose for details)" if not verbose else ""))
    else:
        report.ok(CAT_ENTRY, f"All {len(entries)} entries valid")

    if warn_count and not verbose:
        report.warn(CAT_ENTRY, f"{warn_count} cross-reference warnings (use --verbose)")

    return entries


def _entry_exists(kb_root: Path, entry_id: str) -> bool:
    """Quick check if an entry exists (without full find_entry overhead)."""
    from holmes.kb.store import find_entry
    return find_entry(kb_root, entry_id) is not None


def _check_index(
    kb_root: Path, fix: bool, report: DoctorReport, expected_count: int
) -> None:
    """Check index.json and _index.md consistency."""
    index_file = kb_root / "index.json"

    needs_rebuild = False
    if not index_file.is_file():
        needs_rebuild = True
        report.warn(CAT_INDEX, "index.json missing")
    else:
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            indexed = len(data.get("entries", []))
            if indexed != expected_count:
                needs_rebuild = True
                report.warn(CAT_INDEX,
                            f"index.json has {indexed} entries but {expected_count} on disk")
            else:
                report.ok(CAT_INDEX, f"index.json: {indexed} entries, synced")
        except (json.JSONDecodeError, KeyError) as e:
            needs_rebuild = True
            report.warn(CAT_INDEX, f"index.json corrupted: {e}")

    # Check _index.md per type
    missing_index_md = []
    for kb_type in ("pitfall", "model", "guideline", "process", "decision"):
        type_dir = kb_root / kb_type
        if type_dir.is_dir() and not (type_dir / "_index.md").is_file():
            missing_index_md.append(kb_type)
            needs_rebuild = True

    if missing_index_md:
        report.warn(CAT_INDEX, f"Missing _index.md in: {', '.join(missing_index_md)}")

    if needs_rebuild:
        if fix:
            from holmes.kb.store import rebuild_index_files
            rebuild_index_files(kb_root)
            report.fixed(CAT_INDEX, "Rebuilt index.json and _index.md files")
        else:
            report.warn(CAT_INDEX, "Index out of sync (--fix to rebuild)")


def _check_tmp_files(kb_root: Path, fix: bool, report: DoctorReport) -> None:
    """Find and clean orphaned .tmp files from crashed atomic writes."""
    tmp_files = list(kb_root.rglob("*.tmp"))
    if not tmp_files:
        return

    if fix:
        for f in tmp_files:
            f.unlink(missing_ok=True)
        report.fixed(CAT_CLEANUP, f"Deleted {len(tmp_files)} orphaned .tmp files")
    else:
        report.warn(CAT_CLEANUP,
                    f"Found {len(tmp_files)} orphaned .tmp files (--fix to delete)")


def _check_pending(kb_root: Path, verbose: bool, report: DoctorReport) -> None:
    """Check pending entries health."""
    pending_dirs = [kb_root / "_pending", kb_root / "contributions" / "pending"]
    total = 0
    stale = 0
    errors = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    for pdir in pending_dirs:
        if not pdir.is_dir():
            continue
        for md in pdir.rglob("*.md"):
            if md.name.startswith("_"):
                continue
            total += 1
            try:
                post = frontmatter.load(str(md))
                created = str(post.metadata.get("created_at", ""))
                if created:
                    dt = datetime.fromisoformat(created)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        stale += 1
                        days = (datetime.now(timezone.utc) - dt).days
                        if verbose:
                            report.warn(CAT_PENDING,
                                        f"{post.metadata.get('id', md.stem)}: "
                                        f"pending {days} days")
            except Exception:
                errors += 1
                if verbose:
                    report.error(CAT_PENDING, f"Cannot parse: {md.name}")

    if total == 0:
        report.ok(CAT_PENDING, "No pending entries")
    else:
        msg = f"{total} pending entries"
        if stale:
            msg += f" ({stale} stale >30 days — consider approve/reject)"
        if errors:
            msg += f" ({errors} parse errors)"
        level = "warn" if stale or errors else "ok"
        getattr(report, level)(CAT_PENDING, msg)


def _check_trash(kb_root: Path, active_entries: list, report: DoctorReport) -> None:
    """Check trash for conflicts with active entries."""
    trash_dir = kb_root / "_trash"
    if not trash_dir.is_dir():
        return

    trash_files = list(trash_dir.rglob("*.md"))
    if not trash_files:
        report.ok(CAT_TRASH, "Trash is empty")
        return

    active_ids = {e.id.lower() for e in active_entries}
    conflicts = 0
    for md in trash_files:
        try:
            post = frontmatter.load(str(md))
            tid = str(post.metadata.get("id", "")).lower()
            if tid and tid in active_ids:
                conflicts += 1
        except Exception:
            pass

    msg = f"{len(trash_files)} trashed entries"
    if conflicts:
        report.warn(CAT_TRASH, f"{msg} ({conflicts} also exist as active — stale trash copies)")
    else:
        report.ok(CAT_TRASH, msg)


def _check_evidence_maturity(
    kb_root: Path, entries: list, fix: bool, verbose: bool, report: DoctorReport
) -> None:
    """Verify maturity matches evidence; detect stale maturity."""
    from holmes.kb.store import derive_maturity, load_evidence

    mismatches = 0
    stale_count = 0
    now = datetime.now(timezone.utc)

    for entry in entries:
        fp = Path(entry.file_path) if entry.file_path else None
        if not fp or not fp.is_file():
            continue

        try:
            post = frontmatter.load(str(fp))
        except Exception:
            continue

        fm_evidence = post.metadata.get("evidence", [])
        evidence = load_evidence(kb_root, entry.id, fm_evidence if isinstance(fm_evidence, list) else None)
        derived = derive_maturity(evidence)
        current = str(post.metadata.get("maturity", "draft"))

        # Check maturity vs evidence
        from holmes.kb.store import MATURITY_ORDER
        if MATURITY_ORDER.get(derived, 0) > MATURITY_ORDER.get(current, 0):
            mismatches += 1
            if fix:
                from holmes.kb.atomic import atomic_write
                post.metadata["maturity"] = derived
                atomic_write(fp, frontmatter.dumps(post))
                report.fixed(CAT_EVIDENCE,
                             f"{entry.id}: upgraded maturity {current} → {derived}")
            elif verbose:
                report.warn(CAT_EVIDENCE,
                            f"{entry.id}: maturity is '{current}' but evidence supports '{derived}'")

        # Check staleness
        if evidence:
            dates = []
            for rec in evidence:
                d = rec.get("date", "")
                if d:
                    try:
                        dt = datetime.fromisoformat(d)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        dates.append(dt)
                    except ValueError:
                        pass
            if dates:
                latest = max(dates)
                if latest.tzinfo is None:
                    latest = latest.replace(tzinfo=timezone.utc)
                age_months = (now - latest).days / 30
                if current == "proven" and age_months > 12:
                    stale_count += 1
                    if verbose:
                        report.warn(CAT_EVIDENCE,
                                    f"{entry.id}: proven but last evidence {age_months:.0f} months ago")
                elif current == "verified" and age_months > 6:
                    stale_count += 1
                    if verbose:
                        report.warn(CAT_EVIDENCE,
                                    f"{entry.id}: verified but last evidence {age_months:.0f} months ago")

    if mismatches:
        if not fix:
            report.warn(CAT_EVIDENCE,
                        f"{mismatches} entries have maturity below evidence level"
                        + (" (--fix to upgrade)" if not verbose else ""))
    if stale_count:
        report.warn(CAT_EVIDENCE,
                    f"{stale_count} entries may need decay (run: holmes decay)"
                    + (" — use --verbose for list" if not verbose else ""))

    total_evidence = sum(1 for e in entries if _has_evidence(kb_root, e))
    if not mismatches and not stale_count:
        report.ok(CAT_EVIDENCE,
                  f"Maturity OK ({total_evidence}/{len(entries)} entries have evidence)")


def _has_evidence(kb_root: Path, entry) -> bool:
    """Quick check if an entry has any evidence."""
    sidecar = kb_root / "contributions" / "evidence" / entry.id
    if sidecar.is_dir() and any(sidecar.glob("*.json")):
        return True
    return False


_SKILL_ALLOWED_KEYS = frozenset(
    {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
)


def _fix_skill_legacy_keys(skill_md: Path) -> None:
    """Remove non-standard frontmatter keys from a SKILL.md file."""
    post = frontmatter.load(str(skill_md))
    to_remove = [k for k in post.metadata if k not in _SKILL_ALLOWED_KEYS]
    for k in to_remove:
        del post.metadata[k]
    from holmes.kb.atomic import atomic_write
    atomic_write(skill_md, frontmatter.dumps(post))


def _check_skills(
    kb_root: Path, entries: list, fix: bool, verbose: bool, report: DoctorReport
) -> None:
    """Validate all skills in skills/ directory."""
    import shutil

    skills_dir = kb_root / "skills"
    if not skills_dir.is_dir():
        return

    skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir()]
    if not skill_dirs:
        report.ok(CAT_SKILL, "No skills defined")
        return

    # --- Phase 1: Detect and optionally remove template-junk skills ---
    _TEMPLATE_MARKERS = (
        "No parameters defined",
        "bash scripts/run.sh",
        "Example usage:",
        "Describe when an agent should use this skill",
        "First step: describe what to do",
    )
    junk_skills: list[str] = []
    for sd in list(skill_dirs):
        skill_md = sd / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            body = skill_md.read_text(encoding="utf-8")
            if any(marker in body for marker in _TEMPLATE_MARKERS):
                junk_skills.append(sd.name)
        except Exception:  # noqa: BLE001
            pass

    if junk_skills:
        if fix:
            for name in junk_skills:
                shutil.rmtree(skills_dir / name, ignore_errors=True)
            report.fixed(CAT_SKILL,
                         f"Removed {len(junk_skills)} template-placeholder skills")
            # Refresh skill_dirs after cleanup
            skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir()]
        else:
            report.warn(CAT_SKILL,
                        f"{len(junk_skills)} skills have template-placeholder content "
                        "(run --fix to remove)")

    # --- Phase 2: Clean up orphaned scripts/ directories ---
    scripts_cleaned = 0
    for sd in skill_dirs:
        scripts_dir = sd / "scripts"
        if scripts_dir.is_dir():
            if fix:
                shutil.rmtree(scripts_dir, ignore_errors=True)
                scripts_cleaned += 1
            elif verbose:
                report.warn(CAT_SKILL,
                            f"Skill '{sd.name}' has legacy scripts/ directory")
    if fix and scripts_cleaned:
        report.fixed(CAT_SKILL,
                     f"Removed scripts/ from {scripts_cleaned} skills")
    elif not fix and scripts_cleaned == 0:
        # Count without verbose
        legacy_scripts = sum(1 for sd in skill_dirs if (sd / "scripts").is_dir())
        if legacy_scripts:
            report.warn(CAT_SKILL,
                        f"{legacy_scripts} skills have legacy scripts/ directory "
                        "(run --fix to remove)")

    # --- Phase 3: Validate remaining skills ---
    errors = 0
    error_reasons: dict[str, list[str]] = {}  # reason -> [skill_names]
    for sd in skill_dirs:
        skill_md = sd / "SKILL.md"
        if not skill_md.exists():
            error_reasons.setdefault("missing SKILL.md", []).append(sd.name)
            errors += 1
            continue

        try:
            from holmes.kb.skill.manager import validate_skill_md
            valid, msg = validate_skill_md(skill_md)
            if not valid and fix and "Unexpected key" in msg:
                # Strip legacy frontmatter keys
                _fix_skill_legacy_keys(skill_md)
                # Re-validate after fix
                valid2, msg2 = validate_skill_md(skill_md)
                if valid2:
                    report.fixed(CAT_SKILL, f"Skill '{sd.name}': stripped legacy keys")
                else:
                    error_reasons.setdefault(msg2, []).append(sd.name)
                    errors += 1
            elif not valid:
                error_reasons.setdefault(msg, []).append(sd.name)
                errors += 1
            elif verbose:
                report.ok(CAT_SKILL, f"Skill '{sd.name}' valid")
        except Exception as e:
            error_reasons.setdefault(str(e), []).append(sd.name)
            errors += 1

    # --- Phase 4: Check & fix dangling skill_refs ---
    skill_names = {d.name for d in skill_dirs}
    dangling = 0
    dangling_fixed = 0
    for entry in entries:
        fp = Path(entry.file_path) if entry.file_path else None
        if not fp or not fp.is_file():
            continue
        try:
            post = frontmatter.load(str(fp))
            refs = post.metadata.get("skill_refs", [])
            if not isinstance(refs, list):
                continue
            stale = [str(r) for r in refs if str(r) not in skill_names]
            if not stale:
                continue
            dangling += len(stale)
            if fix:
                cleaned = [str(r) for r in refs if str(r) in skill_names]
                if cleaned:
                    post.metadata["skill_refs"] = cleaned
                else:
                    post.metadata.pop("skill_refs", None)
                fp.write_text(frontmatter.dumps(post), encoding="utf-8")
                dangling_fixed += len(stale)
            elif verbose:
                for ref in stale:
                    report.warn(CAT_SKILL,
                                f"{entry.id}: skill_ref '{ref}' not found")
        except Exception:  # noqa: BLE001
            pass

    if fix and dangling_fixed:
        report.fixed(CAT_SKILL, f"Removed {dangling_fixed} dangling skill_refs")

    if errors:
        report.error(CAT_SKILL, f"{errors}/{len(skill_dirs)} skills have errors:")
        for reason, names in error_reasons.items():
            if len(names) <= 3 or verbose:
                report.error(CAT_SKILL, f"  {reason}: {', '.join(names)}")
            else:
                report.error(CAT_SKILL, f"  {reason}: {', '.join(names[:3])} ... +{len(names)-3} more")
    else:
        report.ok(CAT_SKILL, f"All {len(skill_dirs)} skills valid")

    if dangling and not fix and not verbose:
        report.warn(CAT_SKILL, f"{dangling} dangling skill_refs (use --verbose)")


def _check_search(kb_root: Path, report: DoctorReport) -> None:
    """Verify BM25 index can be built."""
    try:
        from holmes.kb.search import BM25Backend
        backend = BM25Backend(kb_root)
        backend.invalidate()
        # Trigger index build with a dummy search
        results = backend.search("test", limit=1)
        report.ok(CAT_SEARCH, "BM25 search index builds successfully")
    except Exception as e:
        report.error(CAT_SEARCH, f"BM25 index build failed: {e}")


def _check_llm(
    cfg: Optional[HolmesConfig], check_api: bool, report: DoctorReport
) -> None:
    """Check LLM provider configuration and optional connectivity."""
    if not cfg:
        report.warn(CAT_LLM, "Config not loaded — cannot check LLM")
        return

    if not cfg.api_key and not cfg.api_base_url:
        report.warn(CAT_LLM, "No API credentials configured (import pipeline won't work)")
        return

    # Fast path: just validate config fields without importing heavy SDK
    if not check_api:
        report.ok(CAT_LLM, f"Credentials configured (provider: {cfg.provider}, model: {cfg.model})")
        return

    # Full check: instantiate provider and test connectivity
    try:
        from holmes.kb.agent.provider import create_provider
        provider = create_provider(cfg)
    except Exception as e:
        report.error(CAT_LLM, f"Cannot create LLM provider: {e}")
        return

    try:
        resp = provider.simple_complete("Reply with OK.", max_tokens=10)
        if resp and resp.strip():
            report.ok(CAT_LLM, f"API connectivity: OK ({cfg.provider}/{cfg.model})")
        else:
            report.warn(CAT_LLM, "API returned empty response")
    except Exception as e:
        report.error(CAT_LLM, f"API connectivity test failed: {e}")


def _check_git(kb_root: Path, report: DoctorReport) -> None:
    """Check git state of KB directory."""
    git_dir = kb_root / ".git"
    if not git_dir.exists():
        report.warn(CAT_GIT, "KB is not a git repository (recommended for collaboration)")
        return

    # Check for merge conflict markers
    conflict_files = []
    for md in kb_root.rglob("*.md"):
        if md.name.startswith("_") and md.name == "_index.md":
            continue
        # Skip large dirs
        rel = md.relative_to(kb_root)
        parts = rel.parts
        if parts and parts[0] in (".git", ".history", "node_modules"):
            continue
        try:
            text = md.read_text(encoding="utf-8")
            if "<<<<<<" in text and "======" in text:
                conflict_files.append(str(rel))
        except Exception:
            pass

    if conflict_files:
        report.error(CAT_GIT,
                     f"Merge conflict markers in {len(conflict_files)} files: "
                     + ", ".join(conflict_files[:5]))
    else:
        report.ok(CAT_GIT, "No merge conflict markers")


def _check_contributions(kb_root: Path, fix: bool, report: DoctorReport) -> None:
    """Check contributions directory structure and log."""
    log_file = kb_root / "contributions" / "log.md"
    if not log_file.exists():
        if fix:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text("# KB Operations Log\n", encoding="utf-8")
            report.fixed(CAT_CONTRIB, "Created contributions/log.md")
        else:
            report.warn(CAT_CONTRIB, "contributions/log.md missing (--fix to create)")
    else:
        report.ok(CAT_CONTRIB, "contributions/log.md exists")

    # Check evidence sidecar integrity
    evidence_dir = kb_root / "contributions" / "evidence"
    if not evidence_dir.is_dir():
        return

    corrupt = 0
    total = 0
    for json_file in evidence_dir.rglob("*.json"):
        total += 1
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "session_id" not in data:
                corrupt += 1
        except Exception:
            corrupt += 1

    if total == 0:
        return

    if corrupt:
        report.warn(CAT_CONTRIB, f"{corrupt}/{total} evidence sidecar files are malformed")
    else:
        report.ok(CAT_CONTRIB, f"All {total} evidence sidecars valid")
