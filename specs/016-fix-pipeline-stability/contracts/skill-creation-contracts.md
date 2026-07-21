# Contracts: Skill Creation with Commands (D-6)

## Contract: `create_skill(kb_root, name, description, ..., commands=None)`

**New parameter**: `commands: list[str] | None = None`

**Pre-conditions**:
- `commands` is a list of shell command strings (may be empty or None)
- All other pre-conditions unchanged from existing `create_skill` contract

**Post-conditions**:
- If `commands` is non-empty: `scripts/run.sh` contains each command from the list, one per line
- If `commands` is None or empty: `scripts/run.sh` uses the existing placeholder template (backward compatible)
- Script header (shebang, set -euo pipefail) is always present regardless of `commands`
- `SKILL.md` is always created (unchanged behavior)

---

## Contract: `create_skill_for_entry` tool input schema

**New optional field**: `resolution_commands: list[str]`

**Behavior**:
- When present and non-empty, passed to `create_skill()` as `commands`
- When absent or empty, `create_skill()` uses the placeholder template

---

## Contract: `_run_skill_and_curation` in `runner.py`

**Invariant** (D-6 fix):
- When calling `create_skill_for_entry` with `recommendation == RECOMMENDED`, MUST include `resolution_commands` extracted via `detect_commands(resolution_text)` in the tool input
- Empty `detect_commands` result is acceptable (falls back to placeholder template)
