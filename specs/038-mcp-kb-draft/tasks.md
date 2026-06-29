# Tasks: M9 — MCP 接口重构（kb_draft + 日志集成）

**Input**: Design documents from `/specs/038-mcp-kb-draft/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓

**Organization**: 按用户故事分阶段，每个阶段可独立测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件，无依赖）
- **[Story]**: 对应 spec.md 中的用户故事（US1-US5）

---

## Phase 1: Setup（环境验证）

**Purpose**: 确认前置依赖（M1 store 接口、M8 HolmesLogger）可用，无需创建新文件。

- [x] T001 验证 `kb/holmes/kb/store.py` 中 `list_entries(kb_status=..., exclude_sub_entries=...)` 和 `find_entry()` 接口已实现（M1 依赖确认）
- [x] T00X 验证 `kb/holmes/kb/logger.py` 中 `HolmesLogger.write_span(trace_id, span, level, msg, **extra)` 接口已实现（M8 依赖确认）
- [x] T00X 验证 `kb/holmes/kb/store.py` 中 `atomic_write` 函数可导入（用于 handle_kb_draft）

**Checkpoint**: 前置依赖确认 → 可开始用户故事实现

---

## Phase 2: Foundational（基础设施）

**Purpose**: 在 tools.py 中初始化 HolmesLogger，添加 title 安全处理工具函数。所有后续用户故事依赖此阶段。

**⚠️ CRITICAL**: 必须在所有用户故事开始前完成

- [x] T00X 在 `kb/holmes/mcp/tools.py` 顶部添加模块级 `_logger = HolmesLogger(Path.home() / ".holmes" / "logs")` 实例，补全必要 import（datetime, timezone, HolmesLogger, atomic_write, HolmesConfig）
- [x] T00X [P] 在 `kb/holmes/mcp/tools.py` 中添加 `_sanitize_title(title: str) -> str` helper，过滤 `/`、`\`、`..` 为 `_`

**Checkpoint**: 基础设施就绪 → 用户故事可开始

---

## Phase 3: US2 (P1) — 删除 kb_submit

**Goal**: 从 MCP server 和 tools.py 中完全移除 `kb_submit`，清理相关测试。

**Independent Test**: 运行 `grep -r "kb_submit" kb/holmes/mcp/` 无任何输出；`pytest kb/tests/test_mcp_tools.py` 不含 TestKbSubmitPipeline。

- [x] T00X [US2] 删除 `kb/holmes/mcp/tools.py` 中的 `handle_kb_submit` 函数及其所有 import（`ImportAgentRunner`、`_pending_ids`）
- [x] T00X [P] [US2] 删除 `kb/holmes/mcp/server.py` 中的 `kb_submit` `@mcp.tool()` 函数和 `handle_kb_submit` import
- [x] T00X [P] [US2] 删除 `kb/tests/test_mcp_tools.py` 中的 `TestKbSubmitPipeline` 类及相关 helper（`_make_pending_file`、`_mock_runner`、`_GOOD_CONTENT`、`_PENDING_ID`）和 `handle_kb_submit` import

**Checkpoint**: kb_submit 完全不存在于代码库中，现有测试仍全部通过

---

## Phase 4: US1 (P1) — 新增 kb_draft 工具

**Goal**: 实现 `kb_draft` MCP 工具，纯文件写入（无 LLM），frontmatter 含 author/saved_at/source。

**Independent Test**: 调用 `handle_kb_draft(kb_root, content="test", title="redis-oom", config=cfg)` 验证 `_drafts/redis-oom.md` 创建，frontmatter 正确；username 未配置时返回 error dict。

- [x] T00X [US1] 在 `kb/holmes/mcp/tools.py` 中实现 `handle_kb_draft(kb_root, content, title, config, session_id=None) -> dict`，含：username 检查、title sanitize、_drafts/ mkdir、atomic_write frontmatter+body、write_span 日志、返回 saved+next_step
- [x] T0XX [US1] 在 `kb/holmes/mcp/server.py` 中注册 `@mcp.tool() def kb_draft(content, title=None, session_id=None)` 并添加 handle_kb_draft import
- [x] T0XX [P] [US1] 在 `kb/tests/test_mcp_tools.py` 中新增 `TestKbDraft` 类，覆盖场景：username 未配置返回 error、title 有值创建正确文件名、title 为 None 使用时间戳、frontmatter 含 author/saved_at/source、返回 saved 和 next_step 字段

**Checkpoint**: `kb_draft` 工具可独立测试通过，不调用任何 LLM

---

## Phase 5: US3 (P2) — holmes kb drafts 命令

**Goal**: 新增 `holmes kb drafts` CLI 子命令，列出 `_drafts/` 下待 import 草稿。

**Independent Test**: 在 `_drafts/` 下创建两个 `.md` 文件，运行 `holmes kb drafts`，输出含文件名和 saved_at；`_imported/` 中的文件不显示；空目录显示"暂无待 import 的草稿"。

- [x] T0XX [US3] 在 `kb/holmes/cli.py` 的 `kb` group 中新增 `@kb.command("drafts")` 函数，实现：扫描 `_drafts/`（跳过 `_imported/`）所有 `.md` 文件、读 frontmatter `saved_at`/`source`、按时间倒序输出、空时打印"暂无待 import 的草稿"

**Checkpoint**: `holmes kb drafts` 命令可独立运行和验证

---

## Phase 6: US4 (P2) — holmes import 草稿归档

**Goal**: `holmes import _drafts/<file>` 成功后自动将草稿移入 `_drafts/_imported/`。

**Independent Test**: 创建 `_drafts/test.md`，运行 `holmes import _drafts/test.md`（mock runner 返回成功），验证 `_drafts/_imported/test.md` 存在，`_drafts/test.md` 不存在；dry-run 时不移动。

- [x] T0XX [US4] 在 `kb/holmes/cli.py` 的 `import_cmd` 单文件模式中，在 `_print_report` 之后添加草稿归档逻辑：检测 `file` 是否在 `_drafts/` 下（非 `_imported/`）且非 dry_run 且 `not report.errors`，则 `shutil.move` 到 `_drafts/_imported/`；在文件顶部添加 `import shutil`

**Checkpoint**: `holmes import _drafts/<file>` 完成后草稿自动归档

---

## Phase 7: US5 (P3) — MCP session 日志

**Goal**: 所有 MCP 读操作（kb_overview/kb_list/kb_search/kb_read/kb_confirm）写入 session trace 日志。

**Independent Test**: 调用 `handle_kb_overview(kb_root)` 后，`~/.holmes/logs/<today>.jsonl` 含 `span: mcp.kb_overview` 记录且 trace 以 `session-` 开头（需注入临时日志目录的 logger）。

- [x] T0XX [US5] 在 `kb/holmes/mcp/tools.py` 的 `handle_kb_overview` 函数末尾添加 `_logger.write_span(f"session-{session_id}", "mcp.kb_overview", "INFO", "ok")`；更新 hint 文本移除 kb_submit 引用，改为 kb_draft 提示
- [x] T0XX [P] [US5] 在 `kb/holmes/mcp/tools.py` 的 `handle_kb_search` 添加 `session_id: str = ""` 参数，末尾添加 `_logger.write_span(session_id or "session-unknown", "mcp.kb_search", "INFO", "ok", query=query, results=len(items))`
- [x] T0XX [P] [US5] 在 `kb/holmes/mcp/tools.py` 的 `handle_kb_read` 添加 `session_id: str = ""` 参数，末尾添加 `_logger.write_span(session_id or "session-unknown", "mcp.kb_read", "INFO", "ok", entry_id=entry_id)`
- [x] T0XX [P] [US5] 在 `kb/holmes/mcp/tools.py` 的 `handle_kb_confirm` 末尾添加 `_logger.write_span(session_id, "mcp.kb_confirm", "INFO", "ok", entry_id=entry_id, promoted=result.get("promoted", False))`；在 `handle_kb_list` 末尾添加对应日志调用
- [x] T0XX [US5] 在 `kb/holmes/mcp/server.py` 中更新 `kb_search`/`kb_read`/`kb_confirm` 的 MCP 工具函数，传入 `session_id` 参数给对应 handler（`kb_search` 和 `kb_read` 新增 `session_id: str = ""` 参数）

**Checkpoint**: 所有 MCP 操作日志可在 `~/.holmes/logs/<today>.jsonl` 中验证

---

## Phase 8: Polish & 验收

**Purpose**: 全量验证，确认无残留引用，测试全绿。

- [x] T0XX [P] 运行 `grep -r "kb_submit" kb/` 确认零残留；运行 `grep -r "handle_kb_submit" kb/` 确认零残留
- [x] T0XX [P] 运行 `pytest kb/tests/test_mcp_tools.py -v` 确认全部测试通过（含新增 TestKbDraft）
- [x] T0XX 运行完整测试套件 `pytest kb/tests/ -v` 确认无回归

---

## Dependencies & Execution Order

### Phase 依赖

- **Phase 1 (Setup)**: 无依赖，立即开始
- **Phase 2 (Foundational)**: 依赖 Phase 1 → 阻塞所有 US
- **Phase 3 (US2)** 和 **Phase 4 (US1)**: 依赖 Phase 2，两者修改不同逻辑可顺序执行（同文件）
- **Phase 5 (US3)**: 依赖 Phase 2，可在 Phase 3/4 后执行
- **Phase 6 (US4)**: 依赖 Phase 2，独立于 Phase 3/4/5
- **Phase 7 (US5)**: 依赖 Phase 2，需在 Phase 4 (handle_kb_draft 已存在) 后执行
- **Phase 8 (Polish)**: 依赖所有 US 完成

### User Story 依赖

- **US2 (P1)**: Phase 2 完成后即可 → 无其他 US 依赖
- **US1 (P1)**: Phase 2 完成后，建议在 US2 后执行（同文件）
- **US3 (P2)**: Phase 2 完成后，独立
- **US4 (P2)**: Phase 2 完成后，独立
- **US5 (P3)**: US1 完成后（handle_kb_draft 存在），其余独立

### Parallel Opportunities

- T007、T008 可并行（不同文件，同属 US2）
- T015、T016、T017 可并行（不同函数，同属 US5）
- T019、T020 可并行（验收阶段）

---

## Parallel Example: US1（kb_draft）

```
# 并行：
Task T011: 写 TestKbDraft 测试（测试文件）
Task T010: 在 server.py 注册 kb_draft（server 文件）

# 顺序：
Task T009: 实现 handle_kb_draft（tools.py，被 T010 依赖）
```

---

## Implementation Strategy

### MVP First（US2 + US1，删除旧增加新）

1. 完成 Phase 1-2：环境验证 + 基础设施
2. 完成 Phase 3 (US2)：删除 kb_submit
3. 完成 Phase 4 (US1)：实现 kb_draft
4. **STOP 验证**：`pytest kb/tests/test_mcp_tools.py` 全绿，MCP 工具列表无 kb_submit

### Incremental Delivery

1. Phase 1-4 → MCP 核心功能完成（MVP）
2. Phase 5 → CLI 草稿列表
3. Phase 6 → Import 草稿归档
4. Phase 7 → Session 日志
5. Phase 8 → 全量验收

---

## Notes

- 所有文件写入使用 `atomic_write`（已在 store.py 中实现）
- `kb_draft` 禁止调用任何 LLM 或 `ImportAgentRunner`
- `shutil.move` 前先 `mkdir -p _drafts/_imported/`
- `_logger` 实例化时若 `~/.holmes/logs/` 不存在，`HolmesLogger.__init__` 会自动创建（已实现）
- title sanitize 仅过滤 `/`、`\`、`..`，不做全量 slug 化
