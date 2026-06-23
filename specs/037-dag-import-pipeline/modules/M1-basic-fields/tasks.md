# Tasks: M1 — 基础字段与过滤

**Input**: Design documents from `specs/037-dag-import-pipeline/modules/M1-basic-fields/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-schema.md

**Organization**: 按 User Story 分组，支持独立实现和测试每个 Story。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖冲突）
- **[Story]**: 所属 User Story（US1…US6）
- 每项包含精确文件路径

---

## Phase 1: Setup（共享基础设施）

**Purpose**: 读取现有代码，确认理解，无需创建新文件

- [X] T001 通读 `kb/holmes/kb/schema.py`、`kb/holmes/kb/store.py`、`kb/holmes/kb/search.py`、`kb/holmes/cli.py`、`kb/holmes/config.py`、`kb/holmes/mcp/tools.py`，理解现有接口和测试覆盖

---

## Phase 2: Foundational（所有 Story 的前置基础）

**Purpose**: schema.py 中新增 KBStatus 类型和字段文档注释；EntryMeta 新增字段。所有后续 Story 均依赖此 Phase。

**⚠️ CRITICAL**: 所有 User Story 实现必须在此 Phase 完成后开始。

- [X] T002 在 `kb/holmes/kb/schema.py` 中新增 `KBStatus = Literal["pending", "active", "deprecated"]` 类型定义，并添加 8 个新增可选字段的注释说明（`kb_status`、`source_file`、`source_hash`、`description`、`import_trace_id`、`pitfall_structure`、`child_entry_ids`、`parent_id`）
- [X] T003 在 `kb/holmes/kb/store.py` 的 `EntryMeta` dataclass 中新增字段：`kb_status: str = "active"`、`parent_id: Optional[str] = None`，并在 `list_entries()` 的 entry 构建处（`results.append(EntryMeta(...))` 部分）同步填充这两个字段（从 frontmatter 读取）

**Checkpoint**: schema.py KBStatus 类型可用，EntryMeta 包含 kb_status 和 parent_id 字段

---

## Phase 3: US1 — KB 状态过滤（Priority: P1）🎯 MVP

**Goal**: `holmes kb list` 和 `holmes kb search` 默认只显示 `kb_status: active` 的条目；旧 entry 无该字段时视为 active。

**Independent Test**: 创建三个测试 entry（active/pending/deprecated），运行 `holmes kb list`，验证只返回 active 那个。

### Implementation for US1

- [X] T004 [US1] 在 `kb/holmes/kb/store.py` 的 `list_entries()` 函数签名新增参数 `kb_status: Optional[str] = "active"`；在正式 entry 循环（`for md_file in sorted(d.rglob("*.md")):`）内新增过滤逻辑：`entry_kb_status = meta.get("kb_status", "active")`，当 `kb_status` 参数非 None 时，跳过 `entry_kb_status != kb_status` 的 entry
- [X] T005 [US1] 在 `kb/holmes/cli.py` 的 `kb_list` 命令（`@kb.command("list")`）新增 `--all` flag（`is_flag=True`），传入时将 `kb_status=None` 传递给 `list_entries()`，实现包含 deprecated 的列表显示
- [X] T006 [US1] 在 `kb/holmes/cli.py` 的 `kb_search` 命令（`@kb.command("search")`）新增 `--all` flag，通过参数传递到 `search()` 调用，实现搜索时不过滤 deprecated 条目
- [X] T007 [P] [US1] 在 `kb/tests/test_m1_store_filter.py`（新建文件）中编写 `kb_status` 过滤测试：happy path（active/pending/deprecated 三种状态过滤）+ 向后兼容测试（无 kb_status 字段的旧 entry 视为 active）+ `kb_status=None` 时返回所有状态的测试

**Checkpoint**: `holmes kb list` 只返回 active 条目；`--all` 含 deprecated；旧 entry 不受影响

---

## Phase 4: US2 — Process Sub-entry 可见性（Priority: P1）

**Goal**: `holmes kb list` 默认不显示 `type: process` 且有 `parent_id` 的 sub-entries；`--all-types` 可显示；`holmes kb show <sub-id>` 正常展示并带 `[sub-entry of: <parent_id>]` 标签。

**Independent Test**: 创建 pitfall root 和 process sub-entry（含 parent_id），运行 `holmes kb list` 验证 sub-entry 不出现；运行 `holmes kb show <sub-id>` 验证显示标签。

### Implementation for US2

- [X] T008 [US2] 在 `kb/holmes/kb/store.py` 的 `list_entries()` 函数签名新增参数 `exclude_sub_entries: bool = True`；在循环过滤逻辑中新增：当 `exclude_sub_entries=True` 且 `meta.get("type") == "process"` 且 `meta.get("parent_id")` 非空时，跳过该 entry
- [X] T009 [US2] 在 `kb/holmes/cli.py` 的 `kb_list` 命令新增 `--all-types` flag，传入时将 `exclude_sub_entries=False` 传递给 `list_entries()`
- [X] T010 [US2] 在 `kb/holmes/cli.py` 的 `kb_show` 命令（`@kb.command("show")`）中，解析返回 content 的 frontmatter，检查 `parent_id` 字段；若非空，在 `click.echo(content)` 之前先输出 `click.echo(f"[sub-entry of: {parent_id}]")`
- [X] T011 [P] [US2] 在 `kb/tests/test_m1_store_filter.py` 中追加 `exclude_sub_entries` 测试：process 有 parent_id 时默认隐藏；process 无 parent_id 时正常显示；`exclude_sub_entries=False` 时全部显示；pitfall 有 parent_id（异常情况）也被过滤

**Checkpoint**: `holmes kb list` 不显示 process sub-entry；`--all-types` 显示；`kb show` 带标签

---

## Phase 5: US3 — 树导航 children 字段（Priority: P2）

**Goal**: `read_entry()` 对有 `child_entry_ids` 的 entry，在返回内容末尾附加 `## Children` Markdown 表格（含 id 和 title）。

**Independent Test**: 创建 pitfall entry（含 child_entry_ids）和对应子 entries，调用 `store.read_entry()`，验证返回内容末尾有 `## Children` 表格。

### Implementation for US3

- [X] T012 [US3] 在 `kb/holmes/kb/store.py` 新增 `find_entry(kb_root: Path, entry_id: str) -> Optional[Path]` 函数（T013 依赖此函数；但 find_entry 实现见 US4 Phase 6）。在此 Phase 先实现 `read_entry()` 的 children 附加逻辑：在返回内容前，解析 frontmatter 获取 `child_entry_ids`；若非空，对每个 child_id 调用 `list_entries(include_pending=True)` 快速查找 title（US4 完成后改用 `find_entry()`）；在内容末尾追加 `\n\n## Children\n\n| ID | Title |\n|----|-------|\n| {id} | {title} |\n...`

  **Note**: 若 child entry 未找到，输出 `| {child_id} | (not found) |`

- [X] T013 [P] [US3] 在 `kb/tests/test_m1_read_entry.py`（新建文件）中编写 children 附加测试：pitfall entry 有 child_entry_ids 时末尾包含 `## Children` section；无 child_entry_ids 时不附加；child_id 不存在时安全忽略（显示 not found）

**Checkpoint**: `read_entry()` 对有子节点的 pitfall entry 返回含 children 表格的内容

---

## Phase 6: US4 — ID 格式无关化（Priority: P2）

**Goal**: `find_entry(id)` 文件系统扫描，支持新旧两种 ID 格式（`PT-DB-001` 和 `gpu-init-failure-root-001`），大小写不敏感。同时更新 `read_entry()` 使用 `find_entry()`。

**Independent Test**: 在 KB 目录放置旧格式和新格式 ID 的文件，分别调用 `find_entry()`，验证均能返回正确路径。

### Implementation for US4

- [X] T014 [US4] 在 `kb/holmes/kb/store.py` 实现 `find_entry(kb_root: Path, entry_id: str) -> Optional[Path]` 函数：使用 `kb_root.rglob("*.md")` 扫描所有目录，跳过 `_` 开头文件；优先比较 frontmatter `id` 字段（大小写不敏感）；回退到文件名 stem 比较；扫描范围包含 `contributions/pending/` 目录（通过将 `kb_root` 的全部 rglob 实现）
- [X] T015 [US4] 更新 `kb/holmes/kb/store.py` 的 `read_entry()` 函数：改用 `find_entry()` 查找文件路径，替代原来基于 `list_entries(include_pending=True)` 的迭代查找（保持大小写不敏感匹配行为不变）
- [X] T016 [US4] 回到 T012 中的 `read_entry()` children 逻辑，将查找 child title 的方式从 `list_entries()` 迭代改为 `find_entry()` + frontmatter 读取（更高效）
- [X] T017 [P] [US4] 在 `kb/tests/test_m1_find_entry.py`（新建文件）中编写测试：旧格式 ID（`PT-DB-001`）可查找；新格式 ID（`gpu-init-failure-root-001`）可查找；大小写不敏感；不存在的 ID 返回 None；pending 目录内的 entry 也可查找

**Checkpoint**: `find_entry()` 支持所有 ID 格式；`read_entry()` 基于 `find_entry()` 实现

---

## Phase 7: US5 — MCP 工具同步更新（Priority: P2）

**Goal**: MCP 工具层同步 M1 过滤逻辑：`handle_kb_list` 传状态过滤参数；`handle_kb_read` 路由支持新格式 ID；`_read_entry` 返回 dict 含 `children` 字段。

**Independent Test**: 单元测试模拟 kb_root，验证 `handle_kb_list` 不返回 deprecated 条目；验证新格式 ID 路由到 `_read_entry` 而非 `_read_skill`；验证有 child_entry_ids 的 entry 返回 dict 含 children。

### Implementation for US5

- [X] T018 [US5] 在 `kb/holmes/mcp/tools.py` 的 `handle_kb_list()` 函数（约 L134）修改 `list_entries()` 调用，增加 `kb_status="active", exclude_sub_entries=True` 参数
- [X] T019 [US5] 在 `kb/holmes/mcp/tools.py` 的 `handle_kb_read()` 函数（约 L205）替换路由逻辑：删除基于 `_is_entry_id()` 正则的判断，改为先调用 `find_entry(kb_root, entry_id)`；若返回非 None 则路由到 `_read_entry()`；否则保留 `pending-` 前缀判断和 `_read_skill()` 回退
- [X] T020 [US5] 在 `kb/holmes/mcp/tools.py` 的 `_read_entry()` 函数（约 L230）中，解析 frontmatter 后读取 `child_entry_ids`；若非空，调用 `find_entry()` 逐一获取子节点 title，构造 `children: list[dict]`，加入返回 dict
- [X] T021 [P] [US5] 在 `kb/tests/test_m1_mcp.py`（新建文件）中编写测试：`handle_kb_list` 不返回 deprecated/pending 条目；`handle_kb_list` 不返回 process sub-entry；新格式 ID 路由到 entry 而非 skill；`_read_entry` 有 child_entry_ids 时返回 children 列表

**Checkpoint**: MCP 层完全同步 M1 过滤和树导航行为

---

## Phase 8: US6 — Username 配置（Priority: P3）

**Goal**: `holmes config set username <name>` 写入 `~/.holmes/config.json`；`HolmesConfig` 支持 `username` 字段。

**Independent Test**: 运行 `holmes config set username testuser` 后调用 `load_config()`，验证 `config.username == "testuser"`。

### Implementation for US6

- [X] T022 [US6] 在 `kb/holmes/config.py` 的 `HolmesConfig` dataclass 新增字段 `username: str = ""`；在 `from_dict()` 中增加 `username=data.get("username", "")`；`to_dict()` 通过 `asdict()` 自动包含
- [X] T023 [US6] 在 `kb/holmes/cli.py` 的 `config_set` 命令（约 L1648）将 `allowed_keys` 集合增加 `"username"`
- [X] T024 [US6] 在 `kb/holmes/cli.py` 的 `config_show` 命令（约 L1632）输出 JSON 中增加 `"username": cfg.username` 字段
- [X] T025 [P] [US6] 在 `kb/tests/test_m1_config.py`（新建文件）中编写测试：`holmes config set username wangzhi` 写入后可读取；`load_config()` 在无 username 字段时默认返回空字符串；`config show` 输出包含 username 字段

**Checkpoint**: `holmes config set username wangzhi` 成功写入并可读取

---

## Phase 9: Polish & 搜索过滤同步

**Purpose**: search.py 的 `LinearScanBackend` 内部状态过滤，以及最终集成验证

- [X] T026 在 `kb/holmes/kb/search.py` 的 `LinearScanBackend.search()` 循环（约 L126）新增过滤逻辑：读取每个文件 frontmatter 的 `kb_status`（缺省 active）和 `parent_id`；默认跳过 non-active 和 sub-entry；在 `search()` 模块函数（约 L195）新增 `exclude_sub_entries: bool = True` 参数并透传
- [X] T027 [P] 在 `kb/tests/test_m1_search_filter.py`（新建文件）中编写测试：search 默认不返回 deprecated/pending 条目；search 默认不返回 process sub-entry；`exclude_sub_entries=False` 时返回 sub-entry
- [X] T028 [P] 在 `kb/holmes/cli.py` 的 `kb_search` 命令（已有 `--all` flag，T006 添加）补充将 `exclude_sub_entries` 通过 `--all` flag 一并控制（即 `--all` 同时设 `kb_status=None` 和 `exclude_sub_entries=False`）
- [X] T029 运行全量测试套件 `cd kb && python -m pytest tests/ -x -v`，确保所有现有测试和新增测试均通过，无回归

---

## Dependencies & Execution Order

### Phase 依赖

- **Phase 1（Setup）**: 无依赖，立即开始
- **Phase 2（Foundational）**: 依赖 Phase 1 通读完成 — **BLOCKS 所有 User Story**
- **Phase 3（US1）**: 依赖 Phase 2
- **Phase 4（US2）**: 依赖 Phase 2（可与 US1 并行）
- **Phase 5（US3）**: 依赖 Phase 2（需要 find_entry 雏形，T014 后完善）
- **Phase 6（US4）**: 依赖 Phase 2；US3 T012 完成后补充 T016
- **Phase 7（US5/MCP）**: 依赖 Phase 6（find_entry 必须先实现）
- **Phase 8（US6）**: 依赖 Phase 2（独立，可与其他并行）
- **Phase 9（Polish）**: 依赖所有 User Story Phase 完成

### User Story 依赖

- **US1**: 无依赖其他 Story → 最早可完成
- **US2**: 无依赖其他 Story → 可与 US1 并行
- **US3**: 部分依赖 US4（T016 refinement），但 T012 可先实现基础版本
- **US4（find_entry）**: 无依赖其他 Story，US3/US5 依赖它
- **US5（MCP）**: 依赖 US4（find_entry 必须先完成）
- **US6（username）**: 完全独立

### Parallel Opportunities

- T007（US1 test）、T011（US2 test）、T013（US3 test）可在实现任务之后并行编写
- T022-T024（US6 实现）可与任何其他 Story 并行进行
- T026-T028（search 过滤）可与 US5/US6 并行

---

## Parallel Example: Core Stories

```bash
# 完成 Phase 2 后，可并行启动：
Task A: US1 — list_entries kb_status 过滤 (T004 → T005 → T006 → T007)
Task B: US2 — sub-entry 可见性 (T008 → T009 → T010 → T011)
Task C: US6 — username config (T022 → T023 → T024 → T025)

# US4 完成后启动：
Task D: US3 children refinement (T016)
Task E: US5 MCP 更新 (T018 → T019 → T020 → T021)
```

---

## Implementation Strategy

### MVP First（US1 + US2 Only）

1. Phase 1: 通读代码
2. Phase 2: schema 类型 + EntryMeta 字段
3. Phase 3: US1 — kb_status 过滤
4. Phase 4: US2 — sub-entry 可见性 + kb show 标签
5. **STOP and VALIDATE**: `holmes kb list` 行为符合预期

### Incremental Delivery

1. Phase 2 完成 → 基础类型就绪
2. US1 + US2 完成 → 核心过滤行为就绪（MVP）
3. US3 + US4 完成 → 树导航 children 就绪
4. US5 完成 → MCP 同步
5. US6 + Phase 9 完成 → 全部功能就绪，测试通过

---

## Notes

- `[P]` 任务 = 不同文件，无依赖冲突，可并行
- T003（EntryMeta 新字段）填充时注意同步更新 pending 目录 entry 的构建逻辑（`list_entries` 的 pending 分支，约 L116-L137）
- `find_entry()` 扫描时需跳过 `_index.md` 等 `_` 开头文件（与 `list_entries()` 行为一致）
- `list_entries()` 的 `kb_status` 参数过滤只作用于正式 entries（非 pending），pending entries 不参与此过滤（与 `include_pending` 参数独立）
- 运行测试前确认安装包：`cd kb && pip install -e .`
