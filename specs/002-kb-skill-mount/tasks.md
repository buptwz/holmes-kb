# Tasks: KB Skill Mounting

**Input**: Design documents from `specs/002-kb-skill-mount/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to
- Exact file paths included in all descriptions

---

## Phase 1: Setup

**Purpose**: 创建新模块目录结构，为所有 User Story 提供骨架

- [X] T001 Create Python skill module directory `kb/holmes/kb/skill/` with `__init__.py`, `manager.py`, `runner.py`, `template.py` (empty stubs) in `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/`
- ~~T002~~ ~~[P] Create TypeScript tool stub `KbReadSkill.ts`~~ — **废弃**：Agent 改用原生文件工具，不再需要自定义 KB 工具
- ~~T003~~ ~~[P] Create TypeScript tool stub `KbRunSkill.ts`~~ — **废弃**：同上

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 所有 User Story 依赖的共享基础，必须先完成

**⚠️ CRITICAL**: US1-US4 的实现均依赖此阶段

- [X] T004 Implement `parse_skill_md(path)` in `manager.py` — parse SKILL.md frontmatter using `python-frontmatter`, return dict with name/description/version/platforms/timeout/params/prerequisites. Reference: `/home/wangzhi/project/hermes-agent/agent/skill_utils.py` `parse_frontmatter()` at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/manager.py`
- [X] T005 [P] Implement `validate_skill_name(name)` in `manager.py` — enforce `[a-z0-9-]` pattern, 3-64 chars, raise `ValueError` on invalid at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/manager.py`
- [X] T006 [P] Implement `get_skill_dir(kb_root, name)` and `skill_exists(kb_root, name)` helpers in `manager.py` at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/manager.py`
- [X] T007 Extend `validate_entry()` in `schema.py` — add `skill_refs` as optional list[str] field, skip validation if absent, validate each name matches `[a-z0-9-]` if present at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/schema.py`
- [X] T008 [P] Implement `generate_skill_template(name, description, platform)` in `template.py` — return SKILL.md string with YAML frontmatter and placeholder body sections. Reference: `/home/wangzhi/project/hermes-agent/skills/apple/imessage/SKILL.md` at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/template.py`
- [X] T009 [P] Implement `generate_run_sh_template(description)` in `template.py` — return bash script template with `$SKILL_PARAM_*` env var convention at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/template.py`
- ~~T010~~ ~~Register `KbReadSkill` and `KbRunSkill` in `index.ts`~~ — **废弃**：KB 工具全部移除

**Checkpoint**: Foundation ready — US1-US4 implementation can now begin

---

## Phase 3: User Story 1 — Skill 库创建与挂载 (Priority: P1) 🎯 MVP

**Goal**: 维护者能通过 CLI 创建 Skill 文件夹并挂载到 KB 条目

**Independent Test**: 运行 `holmes kb skill create check-redis --desc "..."` 后 `skills/check-redis/SKILL.md` 存在；`holmes kb skill link PT-DB-001 check-redis` 后 PT-DB-001.md frontmatter 含 `skill_refs: [check-redis]`；`holmes kb show PT-DB-001` 输出含 skill 信息

### Implementation

- [X] T011 [US1] Implement `create_skill(kb_root, name, description, platforms)` in `manager.py` — create `skills/<name>/` dir, write SKILL.md from template, create `scripts/run.sh` from template, raise if already exists at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/manager.py`
- [X] T012 [US1] Implement `link_skill(kb_root, entry_id, skill_name)` in `manager.py` — read entry via `store.read_entry`, parse frontmatter, append to `skill_refs` list (deduplicate), write back; raise if entry or skill not found at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/manager.py`
- [X] T013 [P] [US1] Implement `unlink_skill(kb_root, entry_id, skill_name)` in `manager.py` — remove skill_name from entry `skill_refs`, idempotent at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/manager.py`
- [X] T014 [US1] Add `skill` Click group and `skill create` subcommand to `cli.py` — options: `--desc` (required), `--platform` (default `linux,macos`); calls `manager.create_skill()`; output per contracts/cli-commands.md at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/cli.py`
- [X] T015 [US1] Add `skill link` subcommand to `cli.py` — args: entry_id, skill_name; calls `manager.link_skill()`; error messages per contracts/cli-commands.md at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/cli.py`
- [X] T016 [P] [US1] Add `skill unlink` subcommand to `cli.py` — calls `manager.unlink_skill()`; idempotent exit 0 at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/cli.py`
- [X] T017 [US1] Extend `kb_show` command in `cli.py` — after printing entry content, check `skill_refs` in frontmatter; if present, print "Skills: <name> [可执行] @ skills/<name>/" for each ref; warn if skill dir missing at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/cli.py`

**Checkpoint**: `holmes kb skill create/link/unlink` + `holmes kb show` with skill info all working

---

## Phase 4: User Story 2 — Agent 排查时读取并执行 Skill (Priority: P2)

**Goal**: Agent 能直接读取 KB 文件找到相关条目，发现 skill_refs 后读取 SKILL.md，提议并执行诊断脚本

**Independent Test**: `holmes-agent -p "redis连接超时"` 时，agent 用 Grep/Read 工具在 KB 目录找到 PT-DB-001.md，读取其中 `skill_refs: [check-redis]`，再 Read `skills/check-redis/SKILL.md`，提议并执行 `bash skills/check-redis/scripts/run.sh`

### Implementation

- [X] T018 [US2] Implement `run_skill(kb_root, name, params, timeout_override)` in `runner.py` — check prerequisites, inject `SKILL_PARAM_*` env vars, execute `bash scripts/run.sh` via `subprocess.run(timeout=N, capture_output=True)`, truncate stdout to 10KB, return `SkillExecution` dataclass; log cmd/params/exit_code/duration at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/runner.py`
- [X] T019 [P] [US2] Add `skill read` subcommand to `cli.py` — arg: skill_name, flag: `--json`; calls `manager.parse_skill_md`, checks `scripts/run.sh` exists; output per contracts/cli-commands.md at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/cli.py`
- [X] T020 [P] [US2] Add `skill run` subcommand to `cli.py` — arg: skill_name, option: `--param key=value` (multiple), `--timeout`, `--json`; calls `runner.run_skill()`; JSON output per contracts/cli-commands.md at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/cli.py`
- ~~T021~~ ~~Implement KbReadSkill.ts~~ — **废弃**：不再有自定义 KB 工具
- ~~T022~~ ~~Implement KbRunSkill.ts~~ — **废弃**：同上
- [X] T021-NEW [US2] Remove all custom KB tools from agent: delete `src/tools/kb/` directory and remove all KB tool imports/registrations from `src/tools.ts` at `/home/wangzhi/project/claude-code/`
- [X] T022-NEW [US2] Update `~/.holmes/CLAUDE.md` — 重写为文件访问规范：描述 KB 目录结构（`$HOLMES_KB_PATH/<type>/<category>/<ID>.md`）、Skill 位置（`skills/<name>/SKILL.md` + `scripts/run.sh`）、用 Grep 搜索、用 Read 读条目、用 Bash 执行 skill（需确认）；移除所有 Kb* 工具引用
- [X] T023-NEW [P] [US2] Update `~/holmes-kb/CLAUDE.md` — 与 T022-NEW 内容保持一致
- [X] T024-NEW [US2] Rebuild holmes-agent binary: `cd /home/wangzhi/project/claude-code && bun run build`
- ~~T025~~ — 合并至 T023-NEW
- ~~T026~~ ~~Update settings.json permissions for skill tools~~ — **废弃**：不再需要 KB 工具权限

**Checkpoint**: Agent 排查 Redis 问题时用 Grep/Read 工具找到 PT-DB-001.md，读取 skill_refs，用 Read 读 SKILL.md，用 Bash 执行 run.sh，输出结果

---

## Phase 5: User Story 3 — Agent 沉淀时自动生成 Skill (Priority: P2)

**Goal**: Agent 排查成功后沉淀经验时，自动识别 Resolution 中的可执行命令并提议生成 Skill

**Independent Test**: 模拟 `KbExtractAndSave` 调用，传入含命令行的 Resolution，agent 输出中出现 skill 候选列表；用户确认后 `skills/<name>/` 被创建，pending 条目 frontmatter 含 `skill_refs`

### Implementation

- [X] T027 [US3] Implement `detect_commands(resolution_text)` in `manager.py` — apply `CMD_PATTERN` regex from research.md (matches `$ cmd`, `` `backtick` ``, known CLI tools); return list of `(line, suggested_name)` tuples at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/manager.py`
- [X] T028 [US3] Implement `auto_create_skill(kb_root, name, command, description)` in `manager.py` — generate SKILL.md with command in description + auto-detect params from `{placeholder}` pattern; write `scripts/run.sh` with `bash -c "$CMD"` body at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/manager.py`
- ~~T029~~ ~~Extend KbExtractAndSave.ts~~ — **废弃**：KbExtractAndSave 等 KB 工具全部移除；skill 自动生成提示改由 CLAUDE.md 中的工作流指南引导模型在沉淀时主动调用 `holmes kb skill detect-commands` via Bash
- [X] T030 [US3] Add `skill detect-commands` hidden subcommand to `cli.py` — option: `--content TEXT`, `--json`; calls `manager.detect_commands()`; returns JSON array of `{line, suggested_name}` for agent use at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/cli.py`
- [X] T031 [US3] Add `skill auto-create` subcommand to `cli.py` — options: `--name`, `--cmd`, `--desc`; calls `manager.auto_create_skill()`; used by agent after user confirms candidate at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/cli.py`
- ~~T032~~ — **废弃**：KbExtractAndSave 移除，不需要额外 rebuild（已合并至 T024-NEW）

**Checkpoint**: 沉淀含 `redis-cli info | grep connected_clients` 的排查，agent 提议生成 skill，确认后 `skills/check-redis-connections/` 创建完成

---

## Phase 6: User Story 4 — CLI 管理 Skill 库 (Priority: P3)

**Goal**: 维护者能通过 `holmes kb skill list` 浏览 Skill 库，独立运行 skill 验证有效性

**Independent Test**: `holmes kb skill list` 列出所有 skill + 被引用条目数；`holmes kb skill run check-redis` 独立执行并打印输出

### Implementation

- [X] T033 [P] [US4] Implement `list_skills(kb_root, entry_id=None)` in `manager.py` — scan `skills/*/SKILL.md`, parse names/descriptions; if entry_id given, return only that entry's skill_refs; compute linked_entries by scanning all entries' frontmatter at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/manager.py`
- [X] T034 [US4] Add `skill list [entry-id]` subcommand to `cli.py` — table output (NAME / DESCRIPTION / REFS) and `--json` mode per contracts/cli-commands.md at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/cli.py`
- [X] T035 [P] [US4] Implement prerequisite check in `runner.py` — before `subprocess.run`, iterate `prerequisites.commands`, check each with `shutil.which()`; raise `PrerequisiteError` if missing at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/runner.py`

**Checkpoint**: All 4 user stories independently functional

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T036 [P] Add structured logging to `runner.py` — log at INFO level: `skill_run skill=<name> params=<keys> exit_code=<N> duration_ms=<N> truncated=<bool>` at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/skill/runner.py`
- [X] T037 [P] Add dangling skill_refs warning in `kb_show` — when `skill_refs` entry has no matching `skills/<name>/` dir, print `Warning: skill '<name>' not found in skills/` at `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/cli.py`
- [X] T038 [P] Write pytest unit tests for `manager.py` (create/link/unlink/list/detect_commands) in `/home/wangzhi/project/projectTmp/holmes/holmes/kb/tests/test_skill_manager.py`
- [X] T039 [P] Write pytest unit tests for `runner.py` (run_skill timeout, truncation, prereq check) in `/home/wangzhi/project/projectTmp/holmes/holmes/kb/tests/test_skill_runner.py`
- [X] T040 Run end-to-end integration: 用 `holmes-agent --print` 提问 Redis 排查场景，验证 agent 用 Grep/Read/Bash 自动浏览 KB、找到 skill_refs、读取 SKILL.md、执行 run.sh；沉淀时确认 `holmes kb skill detect-commands` 被正确建议

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — can start immediately after Foundational
- **US2 (Phase 4)**: Depends on Phase 2 + US1 (needs `skill read`/`skill run` CLI from US1)
- **US3 (Phase 5)**: Depends on Phase 2 + US1 (needs skill create mechanism)
- **US4 (Phase 6)**: Depends on Phase 2 only (list/run are independent capabilities)
- **Polish (Phase 7)**: Depends on all desired stories complete

### User Story Dependencies

- **US1 (P1)**: Unblocked after Foundational ← **Start here (MVP)**
- **US2 (P2)**: Requires US1 CLI (`skill read`, `skill run`) to exist
- **US3 (P2)**: Requires US1 `create_skill()` function to exist
- **US4 (P3)**: Requires Foundational only; `list_skills()` independent of US2/US3

### Parallel Opportunities

- T005, T006, T008, T009 (Phase 2): All parallel, different files
- T013, T016 (Phase 3): Parallel within US1
- T019, T020, T023-NEW (Phase 4): Parallel where marked
- T033, T035 (Phase 6): Parallel
- T036–T039 (Phase 7): All parallel

---

## Parallel Example: User Story 1

```
# After T011 (create_skill) and T012 (link_skill) done:
Parallel: T013 (unlink_skill impl) + T014 (skill create CLI)

# After T014, T015 done:
Parallel: T016 (skill unlink CLI) + T017 (extend kb show)
```

---

## Implementation Strategy

### MVP (User Story 1 Only)

1. Phase 1: Setup stubs
2. Phase 2: Foundational (parse_skill_md, templates, schema extension)
3. Phase 3: US1 complete — `create`, `link`, `unlink`, `kb show` with skills
4. **STOP & VALIDATE**: 手动跑 quickstart.md 场景 1
5. Proceed to US2

### Full Incremental Delivery

1. Setup + Foundational → 骨架就绪
2. US1 → Skill 创建挂载 ✓（对 agent 有用但不能执行）
3. US2 → Agent 能读取并执行 Skill ✓（核心价值交付）
4. US3 → 沉淀时自动生成 ✓（Skill 库自然增长）
5. US4 → 完整 CLI 管理界面 ✓
6. Polish → 日志、测试、错误处理完善
