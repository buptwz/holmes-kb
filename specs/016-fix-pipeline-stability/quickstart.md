# Quickstart / Test Scenarios: Pipeline Stability Fixes (D-1~D-7)

**Feature**: 016-fix-pipeline-stability
**Date**: 2026-06-08

Each scenario maps to a user story and a specific defect fix. All can be run as unit tests with mocked providers.

---

## T-01: Multi-KP Document — No Silent Drops (D-1)

**Story**: US1 | **Defect**: D-1

**Setup**: Mock Extractor LLM to return a malformed draft for KP-2 (missing closing `---`) and valid drafts for KP-1 and KP-3.

**Assertions**:
- `report.created` contains 2 entries (KP-1 and KP-3)
- `report.errors` or `report.warnings` contains a message mentioning `kp-2`
- Pipeline does NOT raise an exception
- KP-3 is processed normally (processing continued after KP-2 failure)

---

## T-02: Runbook Resolution Commands — Verbatim Copy (D-2)

**Story**: US1/US2 | **Defect**: D-2

**Setup**: Source document has `## Resolution\n\n```bash\nredis-cli DEBUG SLEEP 0\n```\n`.

**Assertions**:
- Extractor draft's `## Resolution` section contains `redis-cli DEBUG SLEEP 0` verbatim
- The draft does NOT contain only "Run the debug command" or similar paraphrase
- (Unit test: provide source with commands, verify `EXTRACTOR_SYSTEM_PROMPT` contains verbatim-copy instruction)

---

## T-03: Single-Incident Document — 1 KP (D-3)

**Story**: US3 | **Defect**: D-3

**Setup**: Source is a single-incident runbook with `## Symptoms`, `## Root Cause`, `## Resolution` sections.

**Assertions**:
- `knowledge_map.knowledge_points` has exactly 1 entry
- The single KP's `section_start` and `section_end` span most of the document
- (Unit test: verify `READER_SYSTEM_PROMPT` contains the one-incident scoping instruction)

---

## T-04: 0-KP Warning (D-4)

**Story**: US4 | **Defect**: D-4

**Setup**: Mock Reader LLM to call no tools and return stop=True (produces 0 KPs).

**Assertions**:
- `report.warnings` is non-empty
- `report.warnings[0]` contains the phrase "No knowledge points identified"
- `report.created` is empty
- Pipeline exits normally (no exception)

---

## T-05: Semantic Dedup — No Duplicate Entry (D-5)

**Story**: US4 | **Defect**: D-5

**Setup**: Mock `compare_root_cause` to return similarity ≥ 0.8 with existing entry `PT-APP-001`. Mock extraction loop LLM to call `compare_root_cause` first (the new prompt step 0 should trigger this).

**Assertions**:
- `report.updated` contains `PT-APP-001` (or the existing entry)
- `report.created` is empty (no new duplicate)
- `compare_root_cause` tool was called at least once during the extraction loop

---

## T-06: Skill run.sh Contains Real Commands (D-6)

**Story**: US2 | **Defect**: D-6

**Setup**: Entry has `## Resolution` with `redis-cli INFO replication\nredis-cli DEBUG SLEEP 0`. Mock `SkillAdvisor` to return RECOMMENDED. Dry_run=False.

**Assertions**:
- `run.sh` file contains `redis-cli INFO replication`
- `run.sh` file contains `redis-cli DEBUG SLEEP 0`
- `run.sh` does NOT contain only `# TODO: Add your diagnostic commands here.`

---

## T-07: Verbose Trace — No Contradictory Field Status (D-7)

**Story**: US5 | **Defect**: D-7

**Setup**: Construct a `DecisionTrace` and simulate two verify_content updates:
1. First call: marks `resolution_commands` as verified (adds to `field_sources`)
2. Second call: marks `resolution_commands` as CLEARED (adds to `unsupported_fields`)

**Assertions**:
- After both updates, `resolution_commands` is in `unsupported_fields` (last write wins)
- `resolution_commands` is NOT in `field_sources`
- `format_verbose()` output contains exactly one trace line for `resolution_commands`, showing `[CLEARED]`

---

## T-08: Full Pipeline Regression — All 546 Tests Pass

**Story**: All | **Defect**: All

**Setup**: Run `python -m pytest -q` from the `kb/` directory.

**Assertions**:
- All 546 tests pass (zero failures)
- No new warnings about deprecated APIs or import errors

---

## Fixture Files Used

| Fixture | Used By |
|---------|---------|
| `tests/fixtures/multi_kp_postmortem.md` | T-01, T-03 |
| `tests/fixtures/redis_runbook_zh.md` | T-02, T-06 |
| `tests/fixtures/large_runbook_15k.md` | T-03 |
