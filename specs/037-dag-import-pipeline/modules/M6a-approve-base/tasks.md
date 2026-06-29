# Tasks: M6a — Pending/Approve 基础流程

**Input**: Design documents from `specs/037-dag-import-pipeline/modules/M6a-approve-base/`

**Branch**: `dev-M6a`

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属 User Story（US1/US2/US3）
- 每个任务含精确文件路径

---

## Phase 1: Setup

**Purpose**: 确认依赖，创建测试骨架

- [x] T001 确认 037-dag-import-pipeline 分支已有 M1/M8 实现（store.py 中 EntryMeta 含 kb_status、HolmesLogger 可用），记录确认结果
- [x] T002 在 `kb/tests/test_approve.py` 创建空测试文件骨架（imports + fixtures + 空 test functions）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 核心存储函数，所有 CLI 命令的基础

**⚠️ CRITICAL**: US1/US2/US3 均依赖本阶段完成

- [x] T003 [P] 在 `kb/holmes/kb/store.py` 新增 `write_pending(kb_root, entry_id, content, category) -> Path`：原子写入 `_pending/<category>/<entry_id>.md`，目录不存在时自动创建
- [x] T004 [P] 在 `kb/holmes/kb/store.py` 新增 `find_entries_by_source_file(kb_root, source_file) -> list[EntryMeta]`：扫描 `_pending/<category>/`、所有 confirmed 类型目录（pitfall/model/guideline/process/decision）、旧格式 `contributions/pending/`，返回 `source_file` 字段匹配的 entries
- [x] T005 在 `kb/holmes/kb/store.py` 新增 `approve_entry(kb_root, entry_id) -> Path`：扫描 `_pending/` 找到 pending 文件，atomic_write 到 `<category>/`（自动创建），更新 `kb_status=active`，删除原 pending 文件
- [x] T006 在 `kb/holmes/kb/store.py` 新增 `deprecate_entry(kb_root, entry_id) -> bool`：扫描所有 confirmed 类型目录找到 entry，in-place 修改 `kb_status=deprecated`（atomic_write 原地），不移动文件，返回是否成功

**Checkpoint**: T003–T006 完成后，所有存储层函数可用

---

## Phase 3: User Story 1 — 写入 Pending 并 Approve (Priority: P1) 🎯 MVP

**Goal**: engineer 可以将 pending entry approve 为 active，`holmes kb list` 立即可见

**Independent Test**: `write_pending` 写入文件 → `approve_entry` 移动文件 → `list_entries(kb_status="active")` 可找到

### 实现

- [x] T007 [US1] 在 `kb/holmes/cli.py` 新增 `holmes kb approve <id>` 命令（Click `@kb.command("approve")`）：基础流程（无冲突检测），读取 pending entry → 调用 `approve_entry` → 打印结果
- [x] T008 [US1] 在 `kb/holmes/cli.py` 的 `approve` 命令中新增 Step 4：approve 后若 `<category>/_index.md` 或 `pitfall/_index.md` 存在则调用 `rebuild_index_files(kb_root)`
- [x] T009 [US1] 在 `kb/tests/test_approve.py` 新增测试：`test_write_pending_creates_file`（验证 `_pending/<cat>/<id>.md` 存在）、`test_approve_entry_moves_file`（验证移动 + kb_status=active）、`test_approve_entry_visible_in_list`（list_entries 可见）

**Checkpoint**: `holmes kb approve <id>` 基础流程可用，approve 后 `holmes kb list` 立即可见

---

## Phase 4: User Story 2 — Approve 前冲突检测与 Deprecate (Priority: P2)

**Goal**: approve 前检测同 source_file 的旧 pending 和 active confirmed，提示用户处理，原子执行

**Independent Test**: 三层并存场景（confirmed 旧版 + pending 旧版 + pending 新版）一次 approve 正确清理

### 实现

- [x] T010 [US2] 在 `kb/holmes/cli.py` 的 `approve` 命令中新增 Step 1：读取待 approve entry 的 `source_file`；若有 `source_file`，调用 `find_entries_by_source_file` 查旧 pending（排除自身），展示列表，询问"取消旧 pending？[Y/n]"
- [x] T011 [US2] 在 `kb/holmes/cli.py` 的 `approve` 命令中新增 Step 2：调用 `find_entries_by_source_file` 查 active confirmed，展示列表，询问"标记为 deprecated？[Y/n]"
- [x] T012 [US2] 在 `kb/holmes/cli.py` 的 `approve` 命令中新增 Step 3：展示操作摘要（"执行：取消 N 个旧 pending + deprecate M 个旧 confirmed + approve 1 个新 entry"），最终 [Y/n] 确认后原子执行：先 approve 新 entry，再删旧 pending 文件，再调用 `deprecate_entry` 处理旧 confirmed
- [x] T013 [US2] 在 `kb/holmes/cli.py` 的 `approve` 命令中支持 `--no-interactive` flag：跳过所有确认提示，自动接受 Y
- [x] T014 [US2] 在 `kb/holmes/cli.py` 中为 HolmesLogger 写入 `kb.approve` span（含 `entry_id`、`user`（取自 config.username）、`duration_ms`）
- [x] T015 [US2] 在 `kb/tests/test_approve.py` 新增测试：`test_deprecate_entry_in_place`（文件不移动，kb_status=deprecated）、`test_approve_clears_old_pending`（旧 pending 被删除）、`test_approve_three_layer_scenario`（三层并存场景一次清理）

**Checkpoint**: 冲突检测流程完整，三层并存场景一次 approve 正确清理

---

## Phase 5: User Story 3 — holmes kb pending 按 Category 分组 (Priority: P3)

**Goal**: `holmes kb pending` 按 category 分组展示 `_pending/` 下所有 entries，兼容旧格式

**Independent Test**: 创建不同 category 的 pending entries，验证分组展示正确

### 实现

- [x] T016 [US3] 在 `kb/holmes/kb/pending.py`（或 `store.py`）新增 `list_new_pending(kb_root) -> list[dict]`：扫描 `_pending/<category>/*.md`，每个 entry 返回 `{id, type, title, category, created_at, path, format="new"}`
- [x] T017 [US3] 改造 `kb/holmes/cli.py` 中 `kb_pending` 命令：先调用 `list_new_pending` 拿新格式 entries，再调用现有 `list_pending`（旧格式）；新格式按 category 分组展示（`=== <category> ===` 为标题），旧格式在末尾 `--- legacy ---` 区块
- [x] T018 [US3] 改造 `kb_pending` 命令的 `--json` 输出：合并新旧格式结果，每项含 `format` 字段（"new" 或 "legacy"）
- [x] T019 [US3] 在 `kb/tests/test_approve.py` 新增测试：`test_list_new_pending_grouped`（验证分组正确）、`test_pending_command_shows_legacy`（旧格式兼容）

**Checkpoint**: `holmes kb pending` 正确按 category 分组，兼容旧格式

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T020 [P] 在 `kb/holmes/kb/store.py` 检查 `approve_entry` 和 `deprecate_entry` 的错误处理：entry 不存在时返回清晰错误，不抛裸异常
- [x] T021 [P] 在 `kb/holmes/cli.py` 的 `approve` 命令添加错误处理：entry_id 不在 `_pending/` 中时打印友好错误，exit code 1
- [x] T022 运行全量测试 `cd kb && python -m pytest tests/ -x -q`，确保现有测试不回归，新增测试全部通过

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: 无依赖，立即开始
- **Phase 2 (Foundational)**: 依赖 Phase 1 完成，**阻塞**所有 User Story
- **Phase 3 (US1)**: 依赖 Phase 2（T003–T006）
- **Phase 4 (US2)**: 依赖 Phase 2 + Phase 3（approve 基础命令）
- **Phase 5 (US3)**: 依赖 Phase 2（list_new_pending 独立）
- **Phase 6 (Polish)**: 依赖 Phase 3–5 完成

### User Story Dependencies

- **US1 (P1)**: Phase 2 完成后即可开始，无其他依赖
- **US2 (P2)**: 依赖 US1 的 `approve` 命令骨架
- **US3 (P3)**: 依赖 Phase 2，与 US1/US2 相对独立

### Parallel Opportunities

- T003 和 T004 可并行（不同函数）
- T009 和 T015 可在各自 US 实现后并行补充
- T020 和 T021 可并行（不同文件）

---

## Parallel Example: Phase 2

```
并行执行:
  Task: T003 write_pending() in kb/holmes/kb/store.py
  Task: T004 find_entries_by_source_file() in kb/holmes/kb/store.py

顺序执行（T003/T004 完成后）:
  Task: T005 approve_entry()
  Task: T006 deprecate_entry()
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup（T001–T002）
2. Phase 2: Foundational（T003–T006）— **CRITICAL**
3. Phase 3: US1（T007–T009）
4. **STOP & VALIDATE**: `holmes kb approve <id>` 基础流程可用

### Incremental Delivery

1. Setup + Foundational → 存储函数完备
2. US1 → approve 基础可用（MVP）
3. US2 → 冲突检测完备
4. US3 → pending 展示完备
5. Polish → 测试全通

---

## Notes

- `find_entries_by_source_file` 是 M2 前置依赖，在本模块一并实现（T004）
- `approve_entry` 只处理新格式 `_pending/<category>/`；旧格式 `contributions/pending/` 由现有 `confirm` 命令处理
- `deprecate_entry` 搜索范围：pitfall/model/guideline/process/decision 五个目录，不含 `_pending/`
- 测试文件：`kb/tests/test_approve.py`（新建）；现有测试文件不修改
- 所有文件操作使用 `atomic_write`（已在 `kb/holmes/kb/atomic.py`）
