# Tasks: 修复 Holmes KB v3 报告缺陷

**Input**: Design documents from `specs/007-fix-kb-v3-bugs/`

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

## Phase 2: User Story 1 — list --query 数字 tag 崩溃 (Priority: P0) 🎯 MVP

**Goal**: 修复 `store.py` 中 tag 搜索时 `t.lower()` 对整数类型崩溃的问题，使 `list --query` 能兼容任意类型 tag。

**Independent Test**: 创建含 `tags: [502, redis]` 的条目，执行 `holmes kb list --query redis` 不崩溃并正常返回结果。

### 实现任务

- [X] T002 [US1] 在 `kb/holmes/kb/store.py` 的 `list_entries()` 函数中，将 `any(q in t.lower() for t in e.tags)` 修改为 `any(q in str(t).lower() for t in e.tags)`

### 测试任务

- [X] T003 [P] [US1] 在 `kb/tests/test_store.py` 中新增测试类 `TestNumericTagSearch`，包含测试：含整数 tag（如 `502`）的条目在 `list --query` 时不抛出 `AttributeError`
- [X] T004 [P] [US1] 在 `kb/tests/test_store.py` `TestNumericTagSearch` 中新增测试：查询关键词与数字 tag 的字符串表示匹配时，条目被正确返回
- [X] T005 [P] [US1] 在 `kb/tests/test_store.py` `TestNumericTagSearch` 中新增回归测试：tags 为混合类型（int + str）时，字符串 tag 仍正常参与匹配

**Checkpoint**: `pytest tests/test_store.py -v -k "NumericTagSearch"` 通过，`holmes kb list --query <keyword>` 在含数字 tag 的 KB 中不崩溃

---

## Phase 3: User Story 2 — import --dry-run 跳过 LLM (Priority: P1)

**Goal**: 修复 `importer.py` 中 `dry_run=True` 时仍调用 LLM API 的问题，使 dry-run 在无 API Key 环境可用。

**Independent Test**: 在未配置 API Key 的环境执行 `holmes import <file> --dry-run`，输出文件内容预览，不报认证错误。

### 实现任务

- [X] T006 [P] [US2] 在 `kb/holmes/kb/importer.py` 的 `import_document()` 函数中，在 `if not structured_content:` 代码块内，`client = openai.AsyncOpenAI(...)` 调用之前添加判断：`if dry_run: structured_content = content`，跳过 LLM 调用

### 测试任务

- [X] T007 [P] [US2] 在 `kb/tests/test_importer.py` 中（若无此文件则新建）新增测试类 `TestDryRunSkipsLLM`，包含测试：`dry_run=True` 时 `import_document()` 不调用 `openai.AsyncOpenAI`（使用 mock patch 验证）
- [X] T008 [P] [US2] 在 `kb/tests/test_importer.py` `TestDryRunSkipsLLM` 中新增测试：`dry_run=True` 时返回 `ImportResult` 的 `pending_id` 为 `"(dry-run)"`，且 `content_preview` 包含原始文件内容
- [X] T009 [P] [US2] 在 `kb/tests/test_importer.py` `TestDryRunSkipsLLM` 中新增测试：`dry_run=True` 且文件已有合法 KB frontmatter 时，仍跳过 LLM 调用（现有路径回归测试）

**Checkpoint**: `pytest tests/test_importer.py -v -k "DryRunSkipsLLM"` 通过，`holmes import <file> --dry-run` 在无 API Key 时正常工作

---

## Phase 4: User Story 3+4+5+7 — correction confirm 数据完整性与 UX (Priority: P1)

**Goal**: 修复 `cli.py` 纠错路径中 `created_at` 丢失、`contributor` 未追加、Gate 3 截断、maturity 无警告四个问题。

**Independent Test**: 对含历史 `created_at` 和 `contributors: [alice]` 的条目执行纠错 confirm（`--contributor bob`），确认后：`created_at` 为历史时间、`contributors: [alice, bob]`、maturity 降级有警告输出。

### 实现任务（US3: created_at 继承）

- [X] T010 [US3] 在 `kb/holmes/cli.py` `kb_confirm()` 纠错路径中，在现有 `post.metadata["evidence"] = ...` 行之后，添加 `created_at` 继承：`orig_created = orig_post.metadata.get("created_at"); if orig_created: post.metadata["created_at"] = orig_created`

### 实现任务（US4: contributor 追加）

- [X] T011 [US4] 在 `kb/holmes/cli.py` `kb_confirm()` 纠错路径中，在 `post.metadata["contributors"] = orig_post.metadata.get("contributors") or []` 行之后，添加 contributor 追加逻辑：若 `contributor` 参数非空且不在列表中，则 `post.metadata["contributors"] = list(dict.fromkeys(post.metadata["contributors"] + [contributor]))`

### 实现任务（US5: Gate 3 截断替换）

- [X] T012 [US5] 在 `kb/holmes/cli.py` `kb_confirm()` Gate 3 预览部分，将 `click.echo(raw[:800])` 及后续截断逻辑替换为：若 `len(raw) > 800` 则输出 `f"Content exceeds 800 chars. To review full content:\n  holmes kb pending --show {pending_id}\n"`，否则输出完整内容

### 实现任务（US7: maturity 降级警告）

- [X] T013 [US7] 在 `kb/holmes/cli.py` `kb_confirm()` 纠错路径 confirm 完成后，在 `click.echo(f"✓ Corrected: ...")` 之后添加 maturity 变更提示：读取 `orig_maturity`（original entry 的 maturity），新 maturity 固定为 `verified`，输出 `f"  maturity: {orig_maturity} → verified"`

### 测试任务

- [X] T014 [P] [US3] 在 `kb/tests/test_integration.py` 末尾新增测试类 `TestCorrectionDataIntegrity`，包含测试：纠错 confirm 后正式条目的 `created_at` 与原始条目相同
- [X] T015 [P] [US4] 在 `kb/tests/test_integration.py` `TestCorrectionDataIntegrity` 中新增测试：纠错 confirm 传入 `--contributor bob` 后，`contributors` 列表包含原始 `alice` 和新增 `bob`
- [X] T016 [P] [US4] 在 `kb/tests/test_integration.py` `TestCorrectionDataIntegrity` 中新增测试：同名 contributor 不重复追加（去重验证）
- [X] T017 [P] [US5] 在 `kb/tests/test_integration.py` `TestCorrectionDataIntegrity` 中新增测试：Gate 3 对超过 800 字符的内容输出包含 `holmes kb pending --show` 的提示命令，不截断内容
- [X] T018 [P] [US7] 在 `kb/tests/test_integration.py` `TestCorrectionDataIntegrity` 中新增测试：纠错 confirm 输出包含 `maturity: proven → verified` 字样

**Checkpoint**: `pytest tests/test_integration.py -v -k "CorrectionDataIntegrity"` 通过

---

## Phase 5: User Story 6 — pending list 空 ID 显示 (Priority: P2)

**Goal**: 修复 `kb_pending()` 列表输出中 `id` 为空字符串时显示空白的问题，改为显示文件名 stem。

**Independent Test**: 创建 `id: ""` 的 pending 条目（文件名 `MY-STEM-001.md`），执行 `holmes kb pending` 看到 `MY-STEM-001`。

### 实现任务

- [X] T019 [US6] 在 `kb/holmes/kb/pending.py` `list_pending()` 中，将 `post.metadata.get("id", path.stem)` 修改为 `post.metadata.get("id") or path.stem`

### 测试任务

- [X] T020 [P] [US6] 在 `kb/tests/test_integration.py` 末尾新增测试类 `TestPendingListEmptyId`，包含测试：frontmatter `id: ""` 的 pending 条目在列表输出中显示文件名 stem（不含 `.md`）而非空字符串
- [X] T021 [P] [US6] 在 `kb/tests/test_integration.py` `TestPendingListEmptyId` 中新增回归测试：正常 `id` 的 pending 条目显示不变

**Checkpoint**: `pytest tests/test_integration.py -v -k "PendingListEmptyId"` 通过，`holmes kb pending` 对空 id 条目正常显示

---

## Phase 6: Polish & 最终验证

**Purpose**: 全套回归验证，确保所有修复协同工作且无回归

- [X] T022 在 `kb/` 目录下运行完整测试套件：`pytest tests/ -v`，确认全部通过（307 passed）
- [X] T023 [P] 按 `specs/007-fix-kb-v3-bugs/quickstart.md` 逐步执行 5 个验证场景，记录实际输出
- [X] T024 [P] 执行代码风格检查：`flake8 holmes/ --max-line-length=100`，确认无新增违规

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Baseline)**: 无依赖，立即开始
- **Phase 2 (US1)**: 依赖 Phase 1，独立文件（`store.py`）
- **Phase 3 (US2)**: 依赖 Phase 1，与 Phase 2 完全并行（`importer.py`）
- **Phase 4 (US3/4/5/7)**: 依赖 Phase 1，与 Phase 2/3 可并行（`cli.py` 纠错路径，同函数内顺序执行）
- **Phase 5 (US6)**: 依赖 Phase 1，与其他 Phase 可并行（`cli.py` pending 列表，不同函数）
- **Phase 6 (Polish)**: 依赖所有 Phase 完成

### User Story 依赖关系

所有 User Story 均独立，无相互依赖。

| 文件 | 涉及 Story | 可并行 |
|------|-----------|--------|
| `store.py` | US1 | ✅ 完全独立 |
| `importer.py` | US2 | ✅ 完全独立 |
| `cli.py` (kb_confirm 纠错路径) | US3/US4/US5/US7 | ⚠️ 同函数，顺序执行 |
| `cli.py` (kb_pending 列表) | US6 | ✅ 与 US3/4/5/7 不同函数，可并行 |

---

## Parallel Execution Example

```bash
# Phase 1 完成后，以下可并行：

# Terminal 1 — US1: store.py
Task: T002 "Fix numeric tag crash in kb/holmes/kb/store.py"
Task: T003-T005 "Tests for NumericTagSearch"

# Terminal 2 — US2: importer.py (完全独立)
Task: T006 "Fix dry-run skip LLM in kb/holmes/kb/importer.py"
Task: T007-T009 "Tests for DryRunSkipsLLM"

# Terminal 3 — US3/4/5/7: cli.py correction path (同函数顺序)
Task: T010 "Add created_at inheritance in kb/holmes/cli.py"
Task: T011 "Add contributor append in kb/holmes/cli.py"
Task: T012 "Fix Gate 3 truncation in kb/holmes/cli.py"
Task: T013 "Add maturity downgrade warning in kb/holmes/cli.py"

# Terminal 4 — US6: cli.py pending list (不同函数)
Task: T019 "Fix empty id display in kb/holmes/cli.py kb_pending()"
```

---

## Implementation Strategy

### MVP First (US1，P0 崩溃阻断)

1. 完成 Phase 1：Baseline
2. 完成 Phase 2：US1（数字 tag 崩溃）
3. **STOP & VALIDATE**：`holmes kb list --query redis` 在含数字 tag 的 KB 不崩溃
4. P0 阻断问题解除

### Incremental Delivery

1. Phase 1 → 建立基线
2. Phase 2 (US1 P0) → 数字 tag 崩溃修复 → 验证
3. Phase 3 (US2 P1) → dry-run 修复 → 验证
4. Phase 4 (US3/4/5/7 P1) → correction confirm 数据完整性 → 验证
5. Phase 5 (US6 P2) → pending list 空 ID 修复 → 验证
6. Phase 6 → 全套回归 → 发布

---

## Notes

- T010/T011/T012/T013 修改 `cli.py` 同一函数（`kb_confirm` 纠错路径），必须顺序执行
- T019 可能需要同时修改 `cli.py` 和 `store.py`（确认 `_stem` 字段是否已有）
- test_importer.py 可能是新文件，需先确认是否存在
- 完成 T010-T013 后立即运行 T014-T018，不要等到最后
