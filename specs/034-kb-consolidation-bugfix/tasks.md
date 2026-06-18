# Tasks: KB 包整合与 Bug 修复

**Feature**: 034-kb-consolidation-bugfix | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

**Prerequisites**: plan.md ✓ | spec.md ✓ | research.md ✓ | data-model.md ✓

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: User story label (US1–US4)

---

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: `merge_pending_entry()` 是 US1 中 `kb_merge` 命令迁移的前置依赖，必须先完成

**⚠️ CRITICAL**: US1 的 cli.py 迁移必须等本 Phase 完成后才能进行 `kb_merge` 部分

- [x] T001 Add `merge_pending_entry(kb_root: Path, content: str) -> dict` function implementing the 5-scenario merge logic (pure_add / evidence_append / maturity_upgrade / maturity_conflict / content_contradiction) using new package APIs (`read_entry`, `write_entry`, `write_conflict_entry`, `rebuild_index_files`) in `kb/holmes/kb/merger.py`

**Checkpoint**: `merge_pending_entry` 可被 CLI 调用后方可进入 US1

---

## Phase 2: US1 — 包整合（Priority: P1）🎯 MVP

**Goal**: `pip install -e .` 后 `holmes import` 直接可用，无需额外 PYTHONPATH

**Independent Test**: `pip install -e . && python -c "from holmes.kb.agent.runner import ImportAgentRunner"` 无报错；`holmes kb list` 和 `holmes kb confirm` 行为不变

### Implementation for US1

- [x] T002 [US1] Add `"holmes-kb @ file:///./kb"` to dependencies list in `holmes/pyproject.toml`
- [x] T003 [US1] Replace old `holmes.kb.*` import block in `holmes/holmes/cli.py` with new imports: `from holmes.kb.linter import lint, LintReport`; `from holmes.kb.pending import get_pending, list_pending, delete_pending, append_log`; `from holmes.kb.store import read_entry, list_entries, write_entry, rebuild_index_files`; `from holmes.kb.validator import validate_schema, check_duplicate, generate_id`; `from holmes.kb.merger import merge_pending_entry`; `from holmes.kb.conflict import list_conflicts, resolve_conflict`
- [x] T004 [US1] Update `kb_pending_show` in `holmes/holmes/cli.py`: `get_pending()` now returns `Optional[str]`; replace `path, post = result` + `frontmatter.dumps(post)` with direct `click.echo(content)`
- [x] T005 [US1] Update `kb_confirm` in `holmes/holmes/cli.py`: (a) parse content string with `frontmatter.loads(content)` to access metadata; (b) replace `validate_entry()` with `validate_schema(content, kb_root)` — check `result.errors`; (c) replace duplicate check with `check_duplicate(kb_root, content)` — check `dup_result.similar_entries`; (d) replace `_next_sequential_id` with `generate_id(kb_root, kb_type, category)` from `holmes.kb.validator`; (e) update frontmatter id field and serialize with `frontmatter.dumps(post)`; (f) construct `entry_path = kb_root / kb_type / category / f"{new_id}.md"` (pitfall with category) or `kb_root / kb_type / f"{new_id}.md"` (others); (g) call `write_entry(entry_path, new_content)`; (h) replace `path.unlink()` with `delete_pending(kb_root, pending_id)`; (i) replace `rebuild_index()` with `rebuild_index_files(kb_root)`; (j) replace `_append_log()` with `append_log()`; (k) remove inline `from holmes.kb.store import KnowledgeEntry, write_entry`
- [x] T006 [US1] Update `kb_reject` in `holmes/holmes/cli.py`: replace `reject_pending(kb_root, pending_id, reason)` with `delete_pending(kb_root, pending_id)` (no reason param); keep ok/error output
- [x] T007 [US1] Update `kb_merge` in `holmes/holmes/cli.py`: replace `merge_entry(kb_root, content)` with `merge_pending_entry(kb_root, content)`; remove inline `import frontmatter` and `frontmatter.dumps(post)` — use `get_pending(kb_root, pending_id)` which now returns string directly
- [x] T008 [US1] Update `kb_resolve` in `holmes/holmes/cli.py`: `resolve_conflict(Path(cfg.kb_path), conflict_id)` signature is compatible; verify no changes needed or adjust if `kept` param required
- [x] T009 [US1] Update `kb_lint` in `holmes/holmes/cli.py`: change dict-key access to attribute access — `results["total_entries"]` → `report.total_entries`; `results["pending_count"]` → `report.pending_count`; `results["conflict_count"]` → `report.conflict_count`; `results["warnings"]` → `report.warnings`; `results["errors"]` → `report.errors`; `results["fixes_applied"]` → `report.fixes_applied`
- [x] T010 [US1] Update `kb_rebuild_index` in `holmes/holmes/cli.py`: replace `rebuild_index(Path(cfg.kb_path))` with `rebuild_index_files(Path(cfg.kb_path))` (returns None); replace `index['total_entries']` count with `len(list_entries(Path(cfg.kb_path)))`
- [x] T011 [US1] Update `kb_show` in `holmes/holmes/cli.py`: replace `get_entry(Path(cfg.kb_path), entry_id)` with `read_entry(Path(cfg.kb_path), entry_id)` (returns `Optional[str]`); replace `entry.to_frontmatter_str()` with `click.echo(content)` directly; check `if content is None` for not-found case
- [x] T012 [US1] Delete entire `holmes/holmes/kb/` directory (removes: `__init__.py`, `conflict.py`, `importer.py`, `index_builder.py`, `linter.py`, `merger.py`, `pending.py`, `store.py`, `validator.py`)
- [x] T013 [US1] Run `pip install -e .` then `pytest kb/tests/ -x` to confirm all tests still pass after package consolidation; fix any import errors

**Checkpoint**: `holmes import <file>` and all `holmes kb *` commands work without PYTHONPATH

---

## Phase 3: US2 — 死代码清理（Priority: P2）

**Goal**: 代码库中不再存在 IPC 相关死代码

**Independent Test**: `ls holmes/holmes/agent_server.py` 返回文件不存在；`holmes tui` 命令返回 "command not found" 或有明确提示

### Implementation for US2

- [x] T014 [P] [US2] Delete `holmes/holmes/agent_server.py`
- [x] T015 [P] [US2] Delete `holmes/holmes/agent/ipc_server.py`
- [x] T016 [P] [US2] Delete `holmes/holmes/agent/tools/kb_read.py` and `holmes/holmes/agent/tools/kb_write.py`
- [x] T017 [US2] Update `holmes/holmes/agent/tools/__init__.py` — remove any `import` statements referencing `kb_read` or `kb_write`
- [x] T018 [US2] Remove `holmes tui` and `holmes agent start` command implementations from `holmes/holmes/cli.py`; update module-level docstring to remove lines `holmes tui — start TUI` and `holmes agent start — start agent IPC server`

**Checkpoint**: Dead files gone; `holmes --help` no longer lists `tui` or `agent` commands

---

## Phase 4: US3 — Skill 名称可读（Priority: P3）

**Goal**: 自动生成的 skill 名称从条目 title 派生，不再包含 pending 时间戳

**Independent Test**: `holmes import <test_file>` 后 `holmes kb list --type skill` 输出的 skill 名称不含 `pending` 前缀

### Implementation for US3

- [x] T019 [P] [US3] Update `_make_slug()` static method in `kb/holmes/kb/agent/skill_advisor.py`: change signature to `_make_slug(entry_id: str, title: str = "") -> str`; when title is non-empty, apply: `slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")`; then `slug = re.sub(r"-{2,}", "-", slug)[:40]`; return slug if `len(slug) >= 3` else fall through to entry_id logic
- [x] T020 [US3] Update `advise()` Form A path in `kb/holmes/kb/agent/skill_advisor.py` (line ~161): change `slug = self._make_slug(entry_id)` to `slug = self._make_slug(entry_id, title=description)`; after computing suggested_name, add dedup loop: check if `(kb_root / "skills" / suggested_name).is_dir()`; if so, try `suggested_name + "-2"`, `"-3"` etc. until name is free
- [x] T021 [US3] Add unit test in `kb/tests/test_skill_advisor.py` (or create it): test that `_make_slug("pending-20260617-xxx", title="Redis Connection Pool Exhausted")` returns `"redis-connection-pool-exhausted"` (not a pending timestamp); test empty title falls back to entry_id logic; test dedup appends `-2`

**Checkpoint**: Import a document → generated skill name is readable (title-derived, not timestamp)

---

## Phase 5: US4 — Extractor type-section 约束（Priority: P4）

**Goal**: 导入后生成的 KB 条目 type 与 body sections 始终匹配 schema 要求

**Independent Test**: Import a document containing a `decision`-type knowledge point; verify the generated entry uses `## Context` and `## Decision` sections, not `## Symptoms` / `## Resolution`

### Implementation for US4

- [x] T022 [P] [US4] Update `EXTRACTOR_SYSTEM_PROMPT` in `kb/holmes/kb/agent/phases/extractor.py`: after line 70 (`"For pitfall entries: Symptoms, Root Cause, and Resolution sections are mandatory."`), insert TYPE-SECTION MAPPING block listing all 5 type→section mappings and CRITICAL rules prohibiting cross-type sections (e.g., decision must NOT have ## Resolution)
- [x] T023 [P] [US4] Add type-section consistency check in `kb/holmes/kb/agent/phases/normalizer.py`: add `_TYPE_FORBIDDEN_SECTIONS` dict; in `normalize()` method, after extracting type from frontmatter, scan body sections (using `re.findall(r"^## (.+)", body, re.MULTILINE)`); for `decision` type with `## Resolution` found → rename to `## Decision`; for other forbidden sections → append warning to report but do not auto-modify
- [x] T024 [US4] Add unit test in `kb/tests/test_normalizer.py` (or create it): test that `decision` type entry with `## Resolution` section gets it renamed to `## Decision` after normalize(); test that `pitfall` type with correct sections passes without warnings

**Checkpoint**: decision entries no longer use pitfall section structure

---

## Phase 6: Polish & Verification

**Purpose**: 全面验证 + 收尾

- [x] T025 Run `pytest kb/tests/ -v` and confirm total passing tests ≥ 733 baseline; record final count (741 passing)
- [x] T026 [P] Run end-to-end CLI smoke test: `holmes kb list`, `holmes kb pending`, `holmes kb lint`, `holmes kb rebuild-index` all return valid output without errors
- [x] T027 [P] Run `pip install -e . && holmes import <any_existing_test_file>` and verify it completes without ImportError or PYTHONPATH requirement

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Foundational)**: No dependencies — start immediately
- **Phase 2 (US1)**: Depends on Phase 1 (T001 must complete before T007 kb_merge update)
- **Phase 3 (US2)**: Independent of Phase 2 — can run in parallel with US1 after Phase 1
- **Phase 4 (US3)**: Independent — can run in parallel with US1/US2
- **Phase 5 (US4)**: Independent — can run in parallel with US1/US2/US3
- **Phase 6 (Polish)**: Depends on all Phase 2–5 tasks complete

### Critical Path

```
T001 (merge_pending_entry)
  → T002-T012 (US1 migration, sequential — all in cli.py)
    → T013 (pytest verification)
      → T025-T027 (final validation)
```

### Parallel Opportunities

US2, US3, US4 can all proceed independently after Phase 1:

```bash
# After T001 completes:
# Thread A: T002 → T003 → T004 → T005 → T006 → T007 → T008 → T009 → T010 → T011 → T012 → T013 (US1)
# Thread B: T014 → T015 → T016 → T017 → T018 (US2)
# Thread C: T019 → T020 → T021 (US3)
# Thread D: T022 → T023 → T024 (US4)
# All threads done → T025, T026, T027
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: T001 (merge_pending_entry)
2. Complete Phase 2: T002–T013 (package consolidation)
3. **STOP and VALIDATE**: `pip install -e .` + `holmes import` + `holmes kb list` work
4. Deploy/demo if ready

### Incremental Delivery

1. Phase 1 → Phase 2 (US1) → Validate → foundation for all commands works
2. Add Phase 3 (US2) → dead code gone, codebase cleaner
3. Add Phase 4 (US3) → skill naming improved
4. Add Phase 5 (US4) → extractor type consistency improved
5. Phase 6 → full verification

---

## Task Summary

| Phase | Story | Tasks | Notes |
|-------|-------|-------|-------|
| Phase 1: Foundational | — | T001 | Blocking prerequisite |
| Phase 2: Package consolidation | US1 | T002–T013 | Sequential (all cli.py) |
| Phase 3: Dead code cleanup | US2 | T014–T018 | Mostly parallel file deletions |
| Phase 4: Skill naming Bug-4 | US3 | T019–T021 | Independent |
| Phase 5: Type-section Bug-5 | US4 | T022–T024 | Independent |
| Phase 6: Polish | — | T025–T027 | After all stories |
| **Total** | | **27** | |
