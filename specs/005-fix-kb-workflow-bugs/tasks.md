# Tasks: 修复 Holmes KB 核心工作流缺陷

**Input**: Design documents from `specs/005-fix-kb-workflow-bugs/`

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

- [ ] T001 在 `kb/` 目录下运行 `pytest tests/ -v` 并记录当前通过/失败状态

---

## Phase 2: User Story 1 — Agent 自动沉淀知识完整闭环 (Priority: P1) 🎯 MVP

**Goal**: 修复 Agent 写入 pending 条目缺少 `maturity` 字段导致 Gate 1 失败，并清理 confirm 后残留的 pending 内部字段，使"写入 → 确认 → 入库"完整闭环可用。

**Independent Test**: `echo "y" | holmes kb confirm <agent-written-pending-id>` 全程通过，正式条目不含任何 pending 内部字段。

### 实现任务

- [ ] T002 [US1] 在 `kb/holmes/kb/pending.py` 第 62 行 `post = frontmatter.loads(content)` 之后添加 `post.metadata.setdefault("maturity", "draft")`
- [ ] T003 [US1] 在 `kb/holmes/cli.py` `kb_confirm()` 正常确认路径中（现有 `pop("pending_since")` 行之后）新增三行：`post.metadata.pop("source", None)`、`post.metadata.pop("suggested_type", None)`、`post.metadata.pop("suggested_category", None)`

### 测试任务

- [ ] T004 [P] [US1] 在 `kb/tests/test_pending.py` 中新增测试：`write_pending()` 传入无 maturity 内容时，生成的 pending 文件包含 `maturity: draft`
- [ ] T005 [P] [US1] 在 `kb/tests/test_pending.py` 中新增测试：`write_pending()` 传入已含 `maturity: verified` 内容时，生成的文件保留 `maturity: verified`（setdefault 不覆盖）
- [ ] T006 [US1] 在 `kb/tests/test_integration.py` 中新增端到端测试：Agent 写入 pending → `kb confirm` → 验证 Gate 1 通过，正式条目不含 `pending`、`source`、`suggested_type`、`suggested_category` 字段

**Checkpoint**: `pytest tests/test_pending.py tests/test_integration.py -v` 通过，`holmes kb confirm` 对 Agent 写入的 pending 条目成功入库

---

## Phase 3: User Story 2 — Skill 自动发现与创建 (Priority: P1)

**Goal**: 修复 `detect_commands()` 对多行文本返回空数组的问题，使其能从 triple-backtick 代码块中识别命令。

**Independent Test**: 向 `detect_commands()` 传入含 ` ```bash ... ``` ` 块的 Resolution 文本，返回非空命令列表。

### 实现任务

- [ ] T007 [US2] 在 `kb/holmes/kb/skill/manager.py` 中 `CMD_PATTERN` 定义之后添加：
  ```python
  _CODE_BLOCK_RE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)

  def _extract_code_block_lines(text: str) -> list[str]:
      lines = []
      for m in _CODE_BLOCK_RE.finditer(text):
          for line in m.group(1).splitlines():
              line = line.strip()
              for prefix in ("$ ", "# ", "> "):
                  if line.startswith(prefix):
                      line = line[len(prefix):]
                      break
              if len(line) >= 5 and not line.startswith("#"):
                  lines.append(line)
      return lines
  ```
- [ ] T008 [US2] 在 `kb/holmes/kb/skill/manager.py` `detect_commands()` 函数中：先调用 `_extract_code_block_lines(resolution_text)` 将代码块命令行加入候选池（去重），再运行现有 `CMD_PATTERN.finditer(resolution_text)` 逻辑

### 测试任务

- [ ] T009 [P] [US2] 在 `kb/tests/test_skill_manager.py` 中新增测试：传入含 triple-backtick `bash` 块的文本，`detect_commands()` 返回块内所有非注释命令
- [ ] T010 [P] [US2] 在 `kb/tests/test_skill_manager.py` 中新增测试：传入含注释行（`# comment`）的代码块，注释行不被识别为命令
- [ ] T011 [P] [US2] 在 `kb/tests/test_skill_manager.py` 中新增测试：传入空字符串或纯中文文本，返回空列表（无误报）

**Checkpoint**: `pytest tests/test_skill_manager.py -v` 通过，`holmes kb skill detect-commands --content "$(cat kb_entry_with_codeblock.md)"` 返回非空结果

---

## Phase 4: User Story 3 — 知识修正工作流 (Priority: P2)

**Goal**: 修复修正提案（含 `corrects` 字段的 pending 条目）被 Gate 2 误判为重复，使修正工作流只需一次确认、可脚本化执行。

**Independent Test**: `echo "y" | holmes kb confirm <correction-pending-id>` 成功完成（Gate 2 输出 `✓ Skipped (correction proposal)`）。

### 实现任务

- [ ] T012 [US3] 在 `kb/holmes/cli.py` `kb_confirm()` 中将 `post = fm.loads(raw)` 提前至 Gate 1 验证之后（L648 → 移至 L624 之后）
- [ ] T013 [US3] 在 `kb/holmes/cli.py` `kb_confirm()` Gate 2 之前添加：
  ```python
  _corrects_check = str(post.metadata.get("corrects", "")).strip()
  click.echo("Gate 2: Duplicate detection...")
  if _corrects_check:
      click.echo("  ✓ Skipped (correction proposal)")
  else:
      dup = check_duplicate(kb_root, raw)
      # ... 现有 Gate 2 逻辑保持不变
  ```

### 测试任务

- [ ] T014 [US3] 在 `kb/tests/test_integration.py` 中新增测试：`confirm` 一个含 `corrects` 字段的 pending 条目时，Gate 2 被跳过，流程只触发一次用户交互
- [ ] T015 [US3] 在 `kb/tests/test_integration.py` 中新增测试：普通（无 `corrects`）pending 条目的 Gate 2 逻辑不受影响（回归测试）

**Checkpoint**: `pytest tests/test_integration.py -v` 通过，`echo "y" | holmes kb confirm <correction_id>` 一次成功

---

## Phase 5: User Story 4 — CLI 文档修正 (Priority: P2)

**Goal**: 更新 README.md，消除三处参数名不符，删除两条不存在的命令记录。

**Independent Test**: 按 README 文档逐条执行示例命令，所有命令均正常运行无报错。

### 实现任务（均可并行）

- [ ] T016 [P] [US4] 在 `README.md` 中将 `resolve` 命令示例的 `--side A` / `--side B` 全部替换为 `--keep A` / `--keep B`
- [ ] T017 [P] [US4] 在 `README.md` 中将 `lint --report report.json`（或类似接路径的写法）更新为 `lint --report`（flag，输出 JSON 到 stdout）
- [ ] T018 [P] [US4] 在 `README.md` 中将 `skill list --entry <id>` 更新为 `skill list <entry_id>`（位置参数）
- [ ] T019 [P] [US4] 在 `README.md` 中找到并删除 `session list` 和 `session show` 相关的所有文档段落（命令不存在）

**Checkpoint**: 按 README 文档依次执行 `resolve`、`lint`、`skill list` 示例，所有命令运行成功

---

## Phase 6: User Story 5 — KB 条目 ID 大小写不敏感查询 (Priority: P3)

**Goal**: 修复 `kb show` 大小写敏感问题，使 `pt-db-002` 与 `PT-DB-002` 返回相同结果。

**Independent Test**: `holmes kb show pt-db-001`（全小写）返回条目内容而非"Entry not found"。

### 实现任务

- [ ] T020 [US5] 在 `kb/holmes/kb/store.py` `read_entry()` 函数中将 `if meta.id == entry_id:` 改为 `if meta.id.upper() == entry_id.upper():`

### 测试任务

- [ ] T021 [P] [US5] 在 `kb/tests/test_store.py` 中新增测试：对已存在条目（ID 为大写），分别用全小写、全大写、混合大小写查询，均返回相同内容
- [ ] T022 [P] [US5] 在 `kb/tests/test_store.py` 中新增测试：不存在的 ID（任意大小写）仍返回 None

**Checkpoint**: `pytest tests/test_store.py -v` 通过，`holmes kb show pt-db-001` 返回条目

---

## Phase 7: Polish & 最终验证

**Purpose**: 全套回归验证，确保所有修复协同工作且无回归

- [ ] T023 在 `kb/` 目录下运行完整测试套件：`pytest tests/ -v`，确认全部通过
- [ ] T024 [P] 按 `specs/005-fix-kb-workflow-bugs/quickstart.md` 逐步执行 5 个验证场景，记录实际输出
- [ ] T025 [P] 执行代码风格检查：`flake8 holmes/kb/ --max-line-length=100`（Google style 要求）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Baseline)**: 无依赖，立即开始
- **Phase 2 (US1)**: 依赖 Phase 1 完成
- **Phase 3 (US2)**: 依赖 Phase 1 完成，与 Phase 2 可并行
- **Phase 4 (US3)**: 依赖 Phase 1 完成，与 Phase 2/3 可并行
- **Phase 5 (US4)**: 无代码依赖，可立即开始（README 独立文件）
- **Phase 6 (US5)**: 依赖 Phase 1 完成，独立
- **Phase 7 (Polish)**: 依赖所有 Phase 完成

### User Story 依赖关系

所有 User Story 均独立，无相互依赖。

- **US1 (P1)**: 独立 — 修改 `pending.py` + `cli.py` confirm 路径
- **US2 (P1)**: 独立 — 修改 `skill/manager.py`
- **US3 (P2)**: 独立 — 修改 `cli.py` confirm 逻辑（与 US1 改动在同文件但不同代码路径）
- **US4 (P2)**: 独立 — 修改 `README.md`
- **US5 (P3)**: 独立 — 修改 `store.py`

⚠️ **注意**: US1 和 US3 均修改 `cli.py` 的 `kb_confirm()` 函数。建议顺序执行（先 US1 后 US3），或使用单次 PR 合并。

### 文件级并行机会

| 文件 | 涉及 Story | 可并行 |
|------|-----------|--------|
| `pending.py` | US1 | ✅ 与其他文件完全独立 |
| `skill/manager.py` | US2 | ✅ 与其他文件完全独立 |
| `store.py` | US5 | ✅ 与其他文件完全独立 |
| `README.md` | US4 | ✅ 与所有代码文件独立 |
| `cli.py` | US1 + US3 | ⚠️ 同文件，建议顺序处理 |

---

## Parallel Execution Example

```bash
# Phase 1 完成后，以下可并行开始：

# Terminal 1 — US1: pending.py fix
Task: T002 "Fix write_pending() maturity field in kb/holmes/kb/pending.py"

# Terminal 2 — US2: manager.py fix
Task: T007 "Add _CODE_BLOCK_RE and _extract_code_block_lines() in kb/holmes/kb/skill/manager.py"

# Terminal 3 — US4: README (无需等待 Phase 1)
Task: T016 "Fix resolve --side → --keep in README.md"
Task: T017 "Fix lint --report description in README.md"
Task: T018 "Fix skill list parameter in README.md"
Task: T019 "Remove session list/show from README.md"

# Terminal 4 — US5: store.py fix
Task: T020 "Fix read_entry() case-insensitive comparison in kb/holmes/kb/store.py"
```

---

## Implementation Strategy

### MVP First (US1 + US2，核心闭环)

1. 完成 Phase 1：Baseline
2. 完成 Phase 2：US1（maturity + confirm cleanup）
3. 完成 Phase 3：US2（detect_commands）
4. **STOP & VALIDATE**：运行 quickstart.md 前两个场景
5. 核心闭环恢复后即可部署/演示

### Incremental Delivery

1. Phase 1 → 建立基线
2. Phase 2 (US1) → Agent 知识入库恢复 → 验证
3. Phase 3 (US2) → Skill 自动化恢复 → 验证
4. Phase 4 (US3) → 修正工作流改善 → 验证
5. Phase 5 (US4) → 文档一致性 → 验证（无需代码测试）
6. Phase 6 (US5) → ID 查询体验改善 → 验证
7. Phase 7 → 全套回归 → 发布

---

## Notes

- `[P]` 任务 = 不同文件，无依赖，可并行
- `[Story]` 标签将任务与 spec.md 中的 User Story 对应，便于追溯
- US1 和 US3 修改同一文件 (`cli.py`)，建议顺序实现避免合并冲突
- 完成 T002 后立即跑 T004/T005 验证，不要等到最后
- README 修改（Phase 5）可在任何时候独立进行
