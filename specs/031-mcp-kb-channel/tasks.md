# Tasks: MCP KB 透明通道 (Feature 031)

**Input**: Design documents from `specs/031-mcp-kb-channel/`

**Organization**: 按 User Story 分组，每个 Story 可独立实现和测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无未完成依赖）
- **[Story]**: 对应 spec.md 中的 User Story

---

## Phase 1: Setup（理解现有代码）

**Purpose**: 在动手前理解当前 MCP server 实现，避免破坏现有行为

- [ ] T001 阅读 `kb/holmes/mcp/server.py` 和 `kb/holmes/mcp/tools.py`，记录每个 handler 的当前签名和行为
- [ ] T002 [P] 阅读 `kb/holmes/kb/search.py`，确认 `search()` 函数签名和 `SearchResult` 字段
- [ ] T003 [P] 阅读 `kb/holmes/kb/skill/manager.py`，确认 `list_skills()`、`parse_skill_md()` 签名和返回类型
- [ ] T004 [P] 阅读 `kb/holmes/kb/importer.py`，确认 `import_document()` 签名、`DuplicatePendingError`、`ContentTooShortError` 异常类型
- [ ] T005 阅读 FastMCP 文档/源码，确认 per-connection 状态注入方式（lifespan、contextvars 或其他）

---

## Phase 2: Foundational（公共基础）

**Purpose**: 所有 US 共用的改动，必须优先完成

**⚠️ CRITICAL**: US1-US4 实现前必须完成本阶段

- [ ] T006 在 `kb/holmes/mcp/tools.py` 顶部新增二进制文件扩展名黑名单常量 `_BINARY_EXTENSIONS`，并实现 `_is_text_file(path: Path) -> bool` 工具函数
- [ ] T007 在 `kb/holmes/mcp/tools.py` 新增 `_is_entry_id(id_str: str) -> bool` 路由判断函数（正则：`^[A-Z]{2,3}-[A-Z]{2,3}-\d{3}$`）
- [ ] T008 运行现有测试确认基线通过：`cd kb && pytest tests/ -q`

**Checkpoint**: 基础工具函数就绪，可开始各 US 实现

---

## Phase 3: User Story 1 — 渐进式发现并读取知识（含 Skill）(Priority: P1) 🎯 MVP

**Goal**: agent 通过 `kb_overview` → `kb_list(type="skill")` → `kb_read(entry)` → `kb_read(skill)` → `kb_read(skill, path=...)` 读取所有 KB 内容

**Independent Test**: 配置 MCP 客户端连接 Server，依次调用全链路，各步骤返回正确结构且 hint 字段引导下一步

### 实现：`kb_overview` 扩展

- [ ] T009 [US1] 修改 `kb/holmes/mcp/tools.py` 中 `handle_kb_overview()`：新增 `skill_count`（扫描 `skills/` 目录计数）和 `hint` 字段，返回值类型更新
- [ ] T010 [US1] 在 `kb/holmes/mcp/server.py` 中更新 `kb_overview` tool description，明确列出所有有效 type 值（含 `"skill"`）及下一步操作

### 实现：`kb_list(type="skill")`

- [ ] T011 [US1] 修改 `kb/holmes/mcp/tools.py` 中 `handle_kb_list()`：
  - 新增 `type="skill"` 分支，调用 `list_skills(kb_root)`
  - 返回 `{id: name, description}` 格式
  - `category` 对 `type="skill"` 静默忽略
- [ ] T012 [US1] 在 `kb/holmes/mcp/server.py` 中更新 `kb_list` tool description，说明 `type="skill"` 用法及返回 `id` 可直接传给 `kb_read`

### 实现：`kb_read` 统一寻址

- [ ] T013 [US1] 修改 `kb/holmes/mcp/tools.py` 中 `handle_kb_read()`，新增路由逻辑：
  - 调用 `_is_entry_id(id)` 判断路由目标
  - 有 `path` 参数但 id 为 entry ID → 返回明确 error
- [ ] T014 [US1] 实现 skill SKILL.md 读取路径：
  - 解析 `skills/<name>/SKILL.md`，调用 `parse_skill_md()`
  - 动态计算 `linked_entries`（扫描所有 entry 的 `skill_refs`）
  - 扫描 skill 目录构建 `files` 列表（调用 `_is_text_file()` 过滤）
  - 返回 `{id, type, description, content, linked_entries, files, hint}` 结构
- [ ] T015 [US1] 实现 skill 子文件读取路径（`kb_read` 有 `path` 参数时）：
  - 路径安全验证（防目录穿越，确保在 skill 目录内）
  - 文本文件验证（调用 `_is_text_file()`，否则返回 error）
  - 读取并返回文件内容
- [ ] T016 [US1] 修改 entry 读取路径：确保响应中包含 `skill_refs` 字段（从 frontmatter 直接取，为空时返回空列表），并在 `skill_refs` 非空时附加 hint
- [ ] T017 [US1] 更新 `kb_read` tool description：说明 ID 路由规则（entry ID 格式 vs skill name 格式）、`path` 参数仅对 skill 有效

### 测试：US1

- [ ] T018 [P] [US1] 在 `kb/holmes/mcp/tests/test_mcp_tools.py` 中新增/更新测试：
  - `kb_overview` 含 `skill_count` 字段
  - `kb_list(type="skill")` 返回正确结构，`id` == skill name
  - `kb_list(type="skill", category="database")` 静默忽略 category
- [ ] T019 [P] [US1] 在 `kb/holmes/mcp/tests/test_mcp_tools.py` 中新增测试：
  - `kb_read(entry_id)` 含 `skill_refs` 字段
  - `kb_read(skill_name)` 含 `linked_entries`、`files`、`content`
  - `kb_read(skill_name, path="scripts/check.sh")` 返回文件内容
  - `kb_read(entry_id, path="scripts/foo.sh")` 返回 error
  - `kb_read(skill_name, path="../../../etc/passwd")` 路径穿越返回 error
  - `kb_read(skill_name, path="assets/diagram.png")` 二进制返回 error

**Checkpoint**: US1 全链路可独立验证

---

## Phase 4: User Story 2 — 搜索定位相关知识 (Priority: P1)

**Goal**: agent 通过 `kb_search(query=...)` 直接定位相关 entries，无需预先知道分类结构

**Independent Test**: `kb_search(query="Redis OOM")` 返回含相关 entry 的排序列表，`brief` 摘要可用

### 实现：`kb_search`

- [ ] T020 [P] [US2] 在 `kb/holmes/mcp/tools.py` 中新增 `handle_kb_search(kb_root, query, type=None, limit=10)`：
  - 调用 `search.search(kb_root, query, limit)`（来自 `kb/holmes/kb/search.py`）
  - 若指定 `type`，在结果中过滤 `kb_type`
  - 返回 `{items: [{id, title, type, maturity, score, brief}], total, hint}` 结构
  - 无结果时 hint 建议使用 `kb_list`
- [ ] T021 [US2] 在 `kb/holmes/mcp/server.py` 中注册 `@mcp.tool() def kb_search(query, type=None, limit=10)`，更新 tool description（说明仅搜索 entries，不搜索 skills）

### 测试：US2

- [ ] T022 [P] [US2] 在 `kb/holmes/mcp/tests/test_mcp_tools.py` 中新增测试：
  - 关键词命中返回相关 entries，score 降序
  - `type` 参数过滤正确
  - 无结果返回空列表 + hint
  - `limit` 参数生效

**Checkpoint**: `kb_search` 独立可用，与 US1 互相不依赖

---

## Phase 5: User Story 4 — Evidence 反馈推动知识成熟 (Priority: P1)

**Goal**: 不同 MCP 连接 confirm 同一 entry 时各自写入 evidence，同一连接重复 confirm 去重

**Independent Test**: 两次独立调用 `kb_confirm` 均写入 evidence；同一连接重复调用返回 duplicate

### 实现：per-connection session_id

- [ ] T023 [US4] 基于 T005 的调研结论，在 `kb/holmes/mcp/server.py` 中实现 per-connection session_id 生成：
  - 方案 A（FastMCP 支持 lifespan）：在 lifespan 上下文中生成 UUID，注入到工具调用
  - 方案 B（退而）：使用 `contextvars.ContextVar` 在每个请求中生成 UUID，不与其他连接共享
- [ ] T024 [US4] 修改 `kb/holmes/mcp/tools.py` 中 `handle_kb_confirm()`：
  - 签名加入 `session_id: str` 参数
  - 移除全局 `_session_id` 变量
  - 确保 `kb_confirm(skill_name)` 返回明确 error（非 entry ID 格式）
- [ ] T025 [US4] 更新 `kb_confirm` tool description：明确说明 `entry_id` 格式要求（结构化 ID，非 skill name），不得调用的条件

### 测试：US4

- [ ] T026 [P] [US4] 在 `kb/holmes/mcp/tests/test_mcp_tools.py` 中新增测试：
  - 同 session_id 对同一 entry confirm 两次 → 第二次返回 `{ok: false, reason: "duplicate"}`
  - 不同 session_id 各自 confirm 同一 entry → 两条 evidence 均写入
  - `kb_confirm("redis-oom-recovery")`（skill name）→ 返回 error

**Checkpoint**: Evidence 去重逻辑正确，多客户端场景隔离

---

## Phase 6: User Story 3 — 知识沉淀：提交新发现 (Priority: P2)

**Goal**: agent 提交自然语言描述，经 import pipeline 结构化后写入 pending；重复提交返回 existing_id

**Independent Test**: `kb_submit(content="...")` 创建 pending 条目；重复内容返回 `{status: "duplicate", existing_id}`

### 实现：`kb_submit` → import pipeline

- [ ] T027 [US3] 在 `kb/holmes/mcp/tools.py` 中重构 `handle_kb_submit()`：
  - 接收 `content: str`（移除原有 frontmatter 构造逻辑）
  - 将 `content` 写入临时文件（`tempfile.NamedTemporaryFile`）
  - 使用 `asyncio.run()` 调用 `import_document(kb_root, tmp_path, model, api_base_url, api_key)`
  - `finally` 块清理临时文件
  - 捕获 `DuplicatePendingError` → 返回 `{status: "duplicate", existing_id, existing_title, hint}`
  - 捕获 `ContentTooShortError` → 返回 error，提示需包含症状/根因/解决步骤
  - 成功 → 返回 `{id, status: "pending", message}`
- [ ] T028 [US3] 在 `kb/holmes/mcp/server.py` 中更新 `kb_submit` 函数签名和 tool description：
  - 参数改为仅 `content: str`
  - description 说明：内容应包含症状、根因、解决步骤；耗时 30-120s；重复提交返回 existing_id

### 测试：US3

- [ ] T029 [P] [US3] 在 `kb/holmes/mcp/tests/test_mcp_tools.py` 中新增测试（mock `import_document`）：
  - 成功提交 → `{id, status: "pending"}`
  - `DuplicatePendingError` → `{status: "duplicate", existing_id}` 含 hint
  - `ContentTooShortError` → error 响应
  - `import_document` 抛出其他异常 → error 响应，不崩溃

**Checkpoint**: `kb_submit` 可独立验证（mock LLM）

---

## Phase 7: 数据模型文档（FR-010）

**Goal**: 生成 `docs/kb-data-model.md` 作为 KB 数据模型权威参考，用于自动化质量验证

**Independent Test**: 文档中每条规则均可在对应源文件找到代码依据

- [ ] T030 阅读 `kb/holmes/kb/schema.py`，提取所有 frontmatter 字段（名称、类型、必填/可选、有效值、验证规则）及各 entry type 必需 body sections
- [ ] T031 [P] 阅读 `kb/holmes/kb/store.py`，提取 `EntryMeta` 字段、`MATURITY_UPGRADE_THRESHOLDS`（draft/verified/proven 阈值）、`EVIDENCE_SIDECAR_DIR` 路径规则、`derive_maturity()` 逻辑
- [ ] T032 [P] 阅读 `kb/holmes/kb/skill/manager.py` + `kb/holmes/kb/skill/template.py`，提取 `SkillDefinition` 字段、SKILL.md frontmatter 格式、skill name 格式约束
- [ ] T033 [P] 阅读 `kb/holmes/kb/pending.py`，提取 pending ID 格式（`pending-{YYYYMMDD}-{HHMMSS}-{rand4}`）、pending 特有字段（`pending: true`、`pending_since`）
- [ ] T034 基于 T030-T033 提取的内容，生成 `docs/kb-data-model.md`，章节包含：
  1. 文件系统布局（KB 目录结构，各子目录用途）
  2. Entry frontmatter 字段完整表（必填/可选、类型、有效值、来源文件:行号）
  3. 各 Entry 类型必需 body sections 表
  4. Skill 结构（SKILL.md frontmatter 字段表、body 格式说明、subdirectory 规范）
  5. ID 格式规则（entry ID pattern、skill name pattern、pending ID pattern，含正则）
  6. Maturity 升级规则（含阈值数据和 `derive_maturity()` 逻辑）
  7. Evidence sidecar 格式（字段、存储路径、去重规则）
  8. Pending entry 格式（与正式 entry 的差异、特有字段）
  9. `skill_refs` 字段格式约束（含正则）

---

## Phase 8: Polish（工具描述 & 集成验证）

**Purpose**: 确保所有工具 description 完整，全链路集成测试，无回归

- [ ] T035 [P] 复查全部 6 个工具的 tool description，确认均包含：何时调用、有效参数值、与其他工具的关系、不得调用的条件
- [ ] T036 运行完整测试套件确认无回归：`cd kb && pytest tests/ -v`
- [ ] T037 [P] 手动端到端验证：启动 MCP Server，按 `quickstart.md` 依次调用全链路（overview → list → search → read entry → read skill → read subfile → confirm）
- [ ] T038 [P] 检查 `kb_read` 的 hint 字段：entry 含 `skill_refs` 时有 hint；skill 含 files 时有 hint；无关联时无多余 hint

---

## Dependencies & Execution Order

### Phase 依赖

- **Phase 1（Setup）**: 无依赖，立即开始
- **Phase 2（Foundational）**: 依赖 Phase 1 → 阻塞 Phase 3-7
- **Phase 3（US1）**: 依赖 Phase 2 → MVP 核心，优先完成
- **Phase 4（US2）、Phase 5（US4）**: 依赖 Phase 2，可与 Phase 3 并行
- **Phase 6（US3）**: 依赖 Phase 2（可与 Phase 3-5 并行）
- **Phase 7（FR-010）**: 依赖 Phase 1（阅读代码），可与 Phase 3-6 完全并行
- **Phase 8（Polish）**: 依赖 Phase 3-7 全部完成

### Story 间依赖

- **US1、US2、US4** 均为 P1，修改不同函数，可并行实施
- **US3** 为 P2，与 US1-4 无代码依赖，可独立并行
- **FR-010** 与所有 US 无代码依赖，纯文档工作

### Parallel Opportunities

**Phase 3 内并行**：
```
T009（handle_kb_overview 扩展）
T011（handle_kb_list skill 路由）   ← 并行
T013~T016（handle_kb_read 路由+实现）
T018、T019（测试）                  ← 并行
```

**跨 Story 并行**（Phase 3 完成后）：
```
Phase 4 US2：T020-T022
Phase 5 US4：T023-T026   ← 可与 Phase 4 并行
Phase 6 US3：T027-T029   ← 可与 Phase 4、5 并行
Phase 7 FR-010：T030-T034 ← 全程可并行（阅读代码）
```

---

## Implementation Strategy

### MVP（只做 US1）

1. Phase 1: T001-T005（阅读理解）
2. Phase 2: T006-T008（基础工具函数）
3. Phase 3: T009-T019（US1 全部任务）
4. **验证 MVP**：`kb_overview` + `kb_list(type="skill")` + `kb_read` 全链路通过
5. 可在此交付，后续按 US 优先级追加

### 完整交付顺序

1. Setup + Foundational（T001-T008）
2. US1 MVP（T009-T019）— 验证
3. US2 + US4 并行（T020-T026）— 验证
4. US3（T027-T029）— 验证
5. FR-010 文档（T030-T034，可穿插）
6. Polish（T035-T038）— 最终验证

---

## Summary

| 阶段 | Task 范围 | Task 数 | 可并行 |
|------|-----------|---------|--------|
| Phase 1: Setup | T001-T005 | 5 | T002-T004 |
| Phase 2: Foundational | T006-T008 | 3 | T006-T007 |
| Phase 3: US1 (P1) | T009-T019 | 11 | T018-T019 |
| Phase 4: US2 (P1) | T020-T022 | 3 | T020, T022 |
| Phase 5: US4 (P1) | T023-T026 | 4 | T026 |
| Phase 6: US3 (P2) | T027-T029 | 3 | T029 |
| Phase 7: FR-010 | T030-T034 | 5 | T031-T033 |
| Phase 8: Polish | T035-T038 | 4 | T035, T037-T038 |
| **Total** | | **38** | |

- **MVP scope**: Phase 1-3（19 tasks）
- **Suggested start**: T001-T005 并行阅读，T006-T007 并行编码，T008 验证基线
