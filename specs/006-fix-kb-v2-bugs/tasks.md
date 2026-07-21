# Tasks: 修复 Holmes KB v2 报告缺陷

**Input**: Design documents from `specs/006-fix-kb-v2-bugs/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/cli-contracts.md ✅

**Tests**: 包含（Constitution 要求：所有模块必须有自动化验证）

**Organization**: 按 User Story 分阶段，每个故事独立可测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 对应 spec.md 中的 User Story 编号
- 所有路径相对于仓库根目录

---

## Phase 1: Baseline（基线验证）

**Purpose**: 在任何修改前确认现有测试套件通过，建立基线

- [X] T001 在 `kb/` 目录下运行 `pytest tests/ -v` 并记录当前通过/失败状态

---

## Phase 2: User Story 1 — 纠错路径字段清理 (Priority: P1) 🎯 MVP

**Goal**: 修复 `kb_confirm()` 纠错路径（含 `corrects` 字段）在写入正式条目前不清除 pending 内部字段的问题，使纠错 confirm 后条目干净无残留。

**Independent Test**: `echo "y" | holmes kb confirm <correction-pending-id>` 后，`holmes kb show <corrected-id>` 不含 `pending`/`source`/`suggested_type` 等字段。

### 实现任务

- [X] T002 [US1] 在 `kb/holmes/cli.py` `kb_confirm()` 纠错路径中，`del post.metadata["corrects"]` 之后、`write_entry()` 之前，添加 pending 内部字段清理循环：`for _f in ("pending", "pending_since", "source_session", "source", "suggested_type", "suggested_category"): post.metadata.pop(_f, None)`

### 测试任务

- [X] T003 [P] [US1] 在 `kb/tests/test_integration.py` 末尾新增测试类 `TestCorrectionFieldCleanup`，包含测试：纠错 confirm 后正式条目不含任何 pending 内部字段（6 个字段均不出现）
- [X] T004 [P] [US1] 在 `kb/tests/test_integration.py` `TestCorrectionFieldCleanup` 中新增回归测试：普通路径（无 corrects）confirm 行为不变，字段仍被正确清理

**Checkpoint**: `pytest tests/test_integration.py -v -k "CorrectionFieldCleanup"` 通过，`holmes kb show <corrected-id>` 不含 pending 内部字段

---

## Phase 3: User Story 2 — lint conflict_count 准确计数 (Priority: P2)

**Goal**: 修复 `linter.py` 统计所有冲突文件（含已解决）的问题，只计 `status == "pending_review"` 的冲突。

**Independent Test**: 解决一个冲突后，`holmes kb lint` 的 `Conflicts` 计数减少 1；`holmes kb lint --report` JSON 中 `conflict_count` 准确。

### 实现任务

- [X] T005 [US2] 在 `kb/holmes/kb/linter.py` 的 `lint()` 函数中，将 `report.conflict_count = len(list(conflicts_dir.glob("*.json")))` 替换为逐文件解析 JSON、只计 `status == "pending_review"` 的记录、异常静默跳过的逻辑（需在文件顶部确认已 `import json`）

### 测试任务

- [X] T006 [P] [US2] 创建 `kb/tests/test_linter.py`，新增测试：冲突目录含 1 个 `pending_review` 和 1 个 `resolved` 文件时，`lint()` 返回 `conflict_count == 1`
- [X] T007 [P] [US2] 在 `kb/tests/test_linter.py` 中新增测试：冲突目录含损坏 JSON 文件时，`lint()` 不报错，损坏文件不计入计数
- [X] T008 [P] [US2] 在 `kb/tests/test_linter.py` 中新增测试：冲突目录为空时，`conflict_count == 0`

**Checkpoint**: `pytest tests/test_linter.py -v` 通过，`holmes kb lint` 计数与实际 `pending_review` 数一致

---

## Phase 4: User Story 3 — skill run 退出码一致性 (Priority: P2)

**Goal**: 修复 `skill run --json` 模式始终返回 0 的问题，使 CLI 退出码与 skill 脚本实际 exit code 一致。

**Independent Test**: 执行失败 skill（exit 1）时，`holmes kb skill run <name> --json; echo $?` 输出 1。

### 实现任务

- [X] T009 [US3] 在 `kb/holmes/cli.py` `skill_run()` 函数的 `if as_json:` 分支末尾（`click.echo(json.dumps(output))` 之后）添加：`if result.exit_code != 0: sys.exit(result.exit_code)`

### 测试任务

- [X] T010 [P] [US3] 在 `kb/tests/test_skill_runner.py` 中新增测试（或在适合的测试文件中）：通过 CLI runner 调用 `skill run --json`，当 skill 脚本退出 1 时，CliRunner result.exit_code 为 1
- [X] T011 [P] [US3] 新增测试：`skill run --json` 成功时 exit_code 为 0，JSON 输出完整

**Checkpoint**: `pytest tests/ -v -k "exit_code or skill_run"` 通过，`--json` 模式退出码与 JSON 中 `exit_code` 字段一致

---

## Phase 5: User Story 4 — detect_commands SQL 过滤 (Priority: P3)

**Goal**: 修复 `_extract_code_block_lines()` 不过滤 SQL 关键字的问题，防止 SQL 语句被识别为 shell 命令。

**Independent Test**: 向 `detect-commands` 传入含 `SHOW SLAVE STATUS\G` 的代码块，返回结果不含该行。

### 实现任务

- [X] T012 [US4] 在 `kb/holmes/kb/skill/manager.py` 中，`CMD_PATTERN` 定义之前（或 `_CODE_BLOCK_RE` 之前）添加 SQL 关键字黑名单：`_SQL_KEYWORDS = frozenset({"select", "show", "insert", "update", "delete", "drop", "create", "alter", "truncate", "replace", "describe", "explain"})`
- [X] T013 [US4] 在 `kb/holmes/kb/skill/manager.py` `_extract_code_block_lines()` 函数中，现有 `if len(line) >= 5 and not line.startswith("#"):` 条件之前，添加 SQL 关键字过滤：`first_word = line.split()[0].lower() if line.split() else ""; if first_word in _SQL_KEYWORDS: continue`

### 测试任务

- [X] T014 [P] [US4] 在 `kb/tests/test_skill_manager.py` 中新增测试：传入含 `SHOW SLAVE STATUS\G` 和 `SELECT * FROM users` 的代码块，`detect_commands()` 返回结果不含这两行
- [X] T015 [P] [US4] 在 `kb/tests/test_skill_manager.py` 中新增测试：大小写不敏感验证——`show`, `SHOW`, `Show` 开头的行均被过滤
- [X] T016 [P] [US4] 在 `kb/tests/test_skill_manager.py` 中新增测试：同一代码块中混合 SQL 和 shell 命令，shell 命令被正常返回，SQL 被过滤（无误过滤）

**Checkpoint**: `pytest tests/test_skill_manager.py -v -k "sql or SQL"` 通过，`detect-commands` 对 SQL 输入返回空列表

---

## Phase 6: Polish & 最终验证

**Purpose**: 全套回归验证，确保所有修复协同工作且无回归

- [X] T017 在 `kb/` 目录下运行完整测试套件：`pytest tests/ -v`，确认全部通过
- [X] T018 [P] 按 `specs/006-fix-kb-v2-bugs/quickstart.md` 逐步执行 4 个验证场景，记录实际输出
- [X] T019 [P] 执行代码风格检查：`flake8 holmes/ --max-line-length=100`，确认无新增违规

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Baseline)**: 无依赖，立即开始
- **Phase 2 (US1)**: 依赖 Phase 1
- **Phase 3 (US2)**: 依赖 Phase 1，与 Phase 2 可并行（不同文件）
- **Phase 4 (US3)**: 依赖 Phase 1，与 Phase 2/3 可并行（cli.py 不同函数）
- **Phase 5 (US4)**: 依赖 Phase 1，与其他 Phase 完全独立（manager.py）
- **Phase 6 (Polish)**: 依赖所有 Phase 完成

### User Story 依赖关系

所有 User Story 均独立，无相互依赖。

| 文件 | 涉及 Story | 可并行 |
|------|-----------|--------|
| `cli.py` (kb_confirm 纠错路径) | US1 | ⚠️ 与 US3 同文件，不同函数，可谨慎并行 |
| `linter.py` | US2 | ✅ 完全独立 |
| `cli.py` (skill_run) | US3 | ⚠️ 与 US1 同文件，不同函数 |
| `skill/manager.py` | US4 | ✅ 完全独立 |

---

## Parallel Execution Example

```bash
# Phase 1 完成后，以下可并行：

# Terminal 1 — US1: cli.py correction path
Task: T002 "Fix correction path field cleanup in kb/holmes/cli.py"

# Terminal 2 — US2: linter.py
Task: T005 "Fix conflict_count in kb/holmes/kb/linter.py"

# Terminal 3 — US4: manager.py (完全独立)
Task: T012 "Add _SQL_KEYWORDS in kb/holmes/kb/skill/manager.py"
Task: T013 "Add SQL filter in _extract_code_block_lines"

# Terminal 4 — US1+US3 测试（T001/T002 完成后）
Task: T003/T004 "Tests for correction field cleanup"
Task: T009 "Fix skill_run exit code in kb/holmes/cli.py"
```

---

## Implementation Strategy

### MVP First (US1，核心数据正确性)

1. 完成 Phase 1：Baseline
2. 完成 Phase 2：US1（纠错字段清理）
3. **STOP & VALIDATE**：`holmes kb show <corrected-id>` 不含 pending 字段
4. 核心数据质量恢复

### Incremental Delivery

1. Phase 1 → 建立基线
2. Phase 2 (US1 P1) → 纠错路径数据正确性 → 验证
3. Phase 3 (US2 P2) → lint 计数准确 → 验证
4. Phase 4 (US3 P2) → skill run 退出码一致 → 验证
5. Phase 5 (US4 P3) → SQL 过滤 → 验证
6. Phase 6 → 全套回归 → 发布

---

## Notes

- T002 和 T009 修改同一文件 (`cli.py`)，但函数不同，可顺序执行
- T012/T013 修改 `manager.py`，与 005 特性添加的代码（`_CODE_BLOCK_RE` 等）在同文件，需注意插入位置
- 完成 T002 后立即跑 T003/T004，不要等到最后
- test_linter.py 是新文件，需先创建再添加测试（T006 完成 T005 实现后）
