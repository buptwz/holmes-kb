# Feature Specification: M9 — MCP 接口重构（kb_draft + 日志集成）

**Feature Branch**: `038-mcp-kb-draft`

**Created**: 2026-06-23

**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Agent 保存草稿到 _drafts/ (Priority: P1)

AI agent 在排查结束后，通过 MCP 调用 `kb_draft` 将现场信息保存为草稿文件，等待工程师用 `holmes import` 正式导入。

**Why this priority**: 替换被删除的 `kb_submit`（内联 LLM pipeline），是本模块核心价值：MCP 侧不运行 LLM，质量由人工审阅保障。

**Independent Test**: 可独立测试：调用 `kb_draft(content="...", title="redis-oom-2026-06-23")`，验证 `_drafts/redis-oom-2026-06-23.md` 被创建，frontmatter 含 `author / saved_at / source: mcp.draft`，返回包含 `saved` 和 `next_step` 字段。

**Acceptance Scenarios**:

1. **Given** `config.username` 已配置，**When** agent 调用 `kb_draft(content="...", title="redis-oom")`，**Then** `_drafts/redis-oom.md` 被创建，frontmatter 含正确 author/saved_at/source，返回 `{"saved": "_drafts/redis-oom.md", "next_step": "holmes import _drafts/redis-oom.md"}`
2. **Given** `config.username` 未配置，**When** agent 调用 `kb_draft(content="...")`，**Then** 返回 `{"error": "config.username not set, run: holmes config set username <name>"}` 且不写文件
3. **Given** `title` 参数未提供，**When** agent 调用 `kb_draft(content="...")`，**Then** 文件名使用时间戳格式 `<YYYY-MM-DD-HHMMSS>.md`

---

### User Story 2 - kb_submit 工具从 MCP 服务中消失 (Priority: P1)

工程师/agent 调用旧的 `kb_submit` 工具时收到明确的工具不存在错误，不再运行任何 LLM pipeline。

**Why this priority**: 与 kb_draft 同优先级，是架构清理的必要步骤，防止 agent 继续走旧的内联 import 路径。

**Independent Test**: 启动 MCP 服务后检查工具列表，`kb_submit` 不出现；或直接调用 `handle_kb_submit` 确认函数已不存在。

**Acceptance Scenarios**:

1. **Given** MCP 服务已启动，**When** 列举所有 MCP 工具，**Then** 工具列表中不包含 `kb_submit`
2. **Given** `test_mcp_tools.py`，**When** 运行测试，**Then** 所有 `TestKbSubmitPipeline` 测试用例已被移除，新增 `TestKbDraft` 测试用例

---

### User Story 3 - holmes kb drafts 列出待 import 草稿 (Priority: P2)

工程师运行 `holmes kb drafts` 查看 `_drafts/` 下所有待 import 的草稿文件，包括保存时间和来源。

**Why this priority**: 帮助工程师管理积压的草稿，防止遗漏导入。

**Independent Test**: 创建 `_drafts/test.md` 后运行 `holmes kb drafts`，验证输出含文件名、`saved_at` 和 `source` 字段，不显示 `_drafts/_imported/` 中的文件。

**Acceptance Scenarios**:

1. **Given** `_drafts/` 含两个草稿文件，**When** 运行 `holmes kb drafts`，**Then** 列出文件名、保存时间和来源（mcp.draft）
2. **Given** `_drafts/_imported/` 含已 import 的草稿，**When** 运行 `holmes kb drafts`，**Then** `_imported/` 中的文件不显示
3. **Given** `_drafts/` 不存在或为空，**When** 运行 `holmes kb drafts`，**Then** 打印"暂无待 import 的草稿"

---

### User Story 4 - holmes import 完成后草稿移入 _imported/ (Priority: P2)

工程师运行 `holmes import _drafts/redis-oom.md` 完成后，源草稿文件自动移入 `_drafts/_imported/`。

**Why this priority**: 实现 draft 生命周期闭环，防止草稿文件残留在待处理目录。

**Independent Test**: 创建 `_drafts/test.md` 后运行 `holmes import _drafts/test.md`，验证文件被移入 `_drafts/_imported/test.md`，原路径文件不存在。

**Acceptance Scenarios**:

1. **Given** `_drafts/redis-oom.md` 存在，**When** `holmes import _drafts/redis-oom.md` 成功完成，**Then** `_drafts/_imported/redis-oom.md` 存在，`_drafts/redis-oom.md` 不存在
2. **Given** `_drafts/` 之外的普通文件，**When** `holmes import /tmp/doc.md`，**Then** 不触发移动逻辑，文件原位不变

---

### User Story 5 - MCP 操作写入 session 日志 (Priority: P3)

所有 MCP 读操作（kb_overview / kb_search / kb_read / kb_confirm）均写入以 `session-` 为前缀的 trace 日志；`kb_draft` 写入以文件名为 trace_id 的文档日志。

**Why this priority**: 可观测性需求，不影响核心功能，但对运维和调试有价值。

**Independent Test**: 调用 `kb_overview` 后检查 `~/.holmes/logs/<today>.jsonl`，确认存在 `span: mcp.kb_overview` 的日志记录，trace 字段以 `session-` 开头。

**Acceptance Scenarios**:

1. **Given** 调用 `kb_overview`，**When** 检查日志，**Then** 存在 `{"span":"mcp.kb_overview","trace":"session-<id>"}` 记录
2. **Given** 调用 `kb_draft(content="...", title="redis-oom")`，**When** 检查日志，**Then** 存在 `{"span":"mcp.draft","trace":"redis-oom","file":"_drafts/redis-oom.md"}` 记录

---

### Edge Cases

- `_drafts/<title>.md` 已存在同名文件时，后续调用覆盖还是报错？（采用覆盖/atomic_write，与现有 KB 写入一致）
- `_drafts/_imported/` 目录不存在时，`holmes import` 自动创建
- `kb_draft` 的 title 含路径分隔符（`/`、`..`）时，需sanitize防止路径穿越
- `kb_overview` 生成 session_id 后，后续调用（`kb_search`/`kb_read`）的 session_id 由调用方传入（agent 负责传递）

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `kb_submit` 工具必须从 MCP server 和 tools.py 中完全删除（无向后兼容）
- **FR-002**: 新增 `kb_draft(content, title=None)` MCP 工具，检查 config.username 后将内容保存到 `_drafts/<title>.md`，frontmatter 含 `author / saved_at / source: mcp.draft`
- **FR-003**: `kb_draft` 必须不运行任何 LLM，仅做文件写入
- **FR-004**: `kb_draft` 在 config.username 未配置时返回明确错误消息，不写文件
- **FR-005**: `kb_draft` 写入一条日志事件（trace_id = 文件名 stem，span = mcp.draft），含 session 字段
- **FR-006**: 新增 `holmes kb drafts` CLI 子命令，列出 `_drafts/`（不含 `_imported/`）下所有 `.md` 文件，显示文件名、saved_at 和 source
- **FR-007**: `holmes import _drafts/<file>` 完成后将源文件移入 `_drafts/_imported/`（使用 shutil.move，atomic）
- **FR-008**: `kb_list` / `kb_search` 调用 `list_entries(kb_status="active", exclude_sub_entries=True)` (M1 接口)
- **FR-009**: `kb_read` 返回值包含 `children` 字段（从 M1 store 的 read_entry 直接透传）
- **FR-010**: `kb_overview` / `kb_search` / `kb_read` / `kb_confirm` 各自写入 `write_span(session_id, "mcp.<op>", "INFO", ...)` 日志
- **FR-011**: `test_mcp_tools.py` 移除 TestKbSubmitPipeline，新增 TestKbDraft（含 username 未配置场景）

### Key Entities

- **Draft 文件**：`_drafts/<title>.md`，frontmatter 含 `author / saved_at / source`，body 为 agent 提供的原始内容
- **_drafts/_imported/ 目录**：已被 holmes import 处理的草稿归档，不再显示在 `holmes kb drafts` 列表中
- **Session Trace**：以 `session-<id>` 为 trace_id 的 MCP 会话日志，记录同一 agent 会话内所有读操作
- **HolmesLogger**：M8 实现的日志写入器，通过 `write_span(trace_id, span, level, msg, **extra)` 写入

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `kb_submit` 从 MCP 工具列表中消失，调用返回工具不存在错误
- **SC-002**: `kb_draft` 调用后 `_drafts/` 下文件在 1 秒内创建完成（纯文件写入，无 LLM 等待）
- **SC-003**: `holmes kb drafts` 在 `_drafts/` 含 10 个文件时响应时间 < 1 秒
- **SC-004**: `holmes import _drafts/<file>` 完成后 100% 情况下草稿文件被移入 `_imported/`（非 dry-run 模式）
- **SC-005**: 所有 MCP 操作写入日志，无遗漏（11 个验收条件全部通过）
- **SC-006**: 全部现有 MCP 测试通过，新增 kb_draft 测试覆盖 username 未配置、有/无 title、日志写入三个场景

## Assumptions

- M1（store 层适配：list_entries kb_status 过滤、exclude_sub_entries、find_entry 文件系统扫描、children 字段）已完成并可用
- M8（HolmesLogger.write_span 接口）已完成并可用
- `atomic_write` 已在现有 store.py 或 utils 中实现，可直接调用
- `kb_draft` 的 session_id 参数由 agent 从 `kb_overview` 响应中获取后传入（agent 侧负责传递）
- 草稿文件的 title 使用原始字符串作为文件名，不做 slug 化，由 agent 提供合法文件名
- `holmes import` 的 `--dry-run` 模式不触发草稿移动
- `_drafts/` 随 git 追踪，`_drafts/_imported/` 同样随 git 追踪
