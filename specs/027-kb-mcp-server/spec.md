# Feature Specification: KB MCP Server & System Closure

**Feature Branch**: `027-kb-mcp-server`

**Created**: 2026-06-11

**Status**: Draft

---

## 背景与目标

将 KB 系统打通为一个完整闭环，消除现有数据矛盾，并通过 MCP 协议将 KB 暴露给任何支持 MCP 的 agent（Claude Desktop、Cursor 等）。

**部署模型：**
```
git clone kb-repo
  ↓
holmes start --kb-path ./kb-repo
  ↓
任何 MCP 客户端连接，读写本地 KB
  ↓
git push → 团队共享 evidence + maturity 状态
```

MCP 客户端配置示例（Claude Desktop / Cursor）：
```json
{
  "mcpServers": {
    "holmes-kb": {
      "url": "http://localhost:8765"
    }
  }
}
```

Server 使用 streamable-http transport，用户手动启动，多个 MCP 客户端可同时连接同一个 server 进程。

**核心原则：**
- MCP server 是透明通道，agent 体验等同于读本地 KB 目录，只是走 MCP 协议
- 不做内容转换，不改变语义，原样传输
- Evidence 只在显式确认（confirm）时写入，read 不记录
- 整个系统无数据矛盾，生命周期完整闭环

---

## User Scenarios & Testing

### User Story 1 - MCP 浏览与读取 (Priority: P1)

工程师在 Claude Desktop 遇到数据库问题，agent 调用 `kb_overview` 了解 KB 覆盖范围，调用 `kb_list` 浏览 database 分类的条目列表，调用 `kb_read` 读取匹配的 pitfall 全文，按 Resolution 指导用户操作。对于 skill 类型条目，agent 读取内容后自行创建本地脚本并执行。

**Why this priority**: 这是 MCP server 的核心功能，没有它 MCP server 毫无价值。

**Independent Test**: 配置 MCP server 连接测试 KB；依次调用 `kb_overview`、`kb_list(type="pitfall", category="database")`、`kb_read(entry_id)`，返回内容与直接读文件一致。

**Acceptance Scenarios**:

1. **Given** KB 有 pitfall 和 skill 条目，**When** 调用 `kb_overview()`，**Then** 返回各类型条目数量和所有分类名称
2. **Given** database 分类下有若干条目，**When** 调用 `kb_list(type="pitfall", category="database", limit=10)`，**Then** 返回条目列表，每条含 id、title、maturity 和简述；支持 offset 分页
3. **Given** 有效 entry_id，**When** 调用 `kb_read(entry_id)`，**Then** 返回原始 Markdown 内容，**不写入任何 evidence**
4. **Given** skill 类型条目，**When** 调用 `kb_read(entry_id)`，**Then** 返回内容中包含脚本代码块，agent 可自行提取、写文件、执行

---

### User Story 2 - MCP 确认并写回证据 (Priority: P1)

agent 按 KB 条目的指导帮助用户成功解决了问题，用户确认后，agent 调用 `kb_confirm` 将这次成功经验沉淀为 evidence。这推动条目 maturity 升级，后续搜索时该条目排名更靠前。

**Why this priority**: Evidence 是整个知识生命周期的驱动力。没有它，maturity 永远停滞，搜索排序失效。

**Independent Test**: 调用 `kb_confirm(entry_id="PT-001")`；检查 `contributions/evidence/PT-001/` 出现新 JSON 文件；文件含 session_id、contributor（来自 git config）、date；条目 maturity 可能升级。

**Acceptance Scenarios**:

1. **Given** maturity=draft 条目，**When** 调用 `kb_confirm(entry_id)`，**Then** evidence 文件写入，maturity 升级为 verified，返回 `{ok: true, maturity: "verified", promoted: true}`
2. **Given** 同 session 已 confirm 过，**When** 再次调用，**Then** 返回 `{ok: false, reason: "duplicate"}`，不写重复记录
3. **Given** git config 未设置，**When** 调用 `kb_confirm`，**Then** contributor 回退到 hostname，操作不阻断

---

### User Story 3 - MCP 提交新知识 (Priority: P2)

agent 协助用户整理了一个 KB 中没有的问题，调用 `kb_submit` 提交为 pending 条目，提交者作为第一条 evidence 自动记录。人工 approve 后，条目进入官方 KB，evidence 链完整保留。

**Why this priority**: 知识反哺的入口，让每次排障都能沉淀为团队知识。

**Independent Test**: 调用 `kb_submit`；`pending/` 目录出现条目文件；`contributions/evidence/<id>/` 出现提交者 evidence；approve 后条目移至官方目录，evidence 不丢失。

**Acceptance Scenarios**:

1. **Given** agent 提交完整的 pitfall 内容，**When** 调用 `kb_submit(title, type, content)`，**Then** `pending/` 创建条目文件，提交者 evidence 写入，返回 `{id, status: "pending"}`
2. **Given** pending 条目被 `holmes kb pending approve <id>` 审核通过，**Then** 条目移至官方目录，maturity 基于现有 evidence 自动计算，evidence sidecar 文件完整保留

---

### User Story 4 - 修复 Pending Evidence 存储（技术修复）(Priority: P1)

当前 `append_evidence()` 通过 `list_entries()` 查找条目，但 `list_entries()` 不扫描 `pending/` 目录，导致 pending 条目的 evidence 写不进去。

**Why this priority**: US3 的前提条件，不修则 kb_submit 的 evidence 静默失败。

**Independent Test**: 在 `pending/` 创建测试条目，调用 `append_evidence(kb_root, entry_id, record)`，evidence sidecar 写入成功。

**Acceptance Scenarios**:

1. **Given** `pending/PT-XXXX.md` 存在，**When** 调用 `append_evidence(kb_root, "PT-XXXX", record)`，**Then** evidence 文件写入 `contributions/evidence/PT-XXXX/`，返回 True
2. **Given** `list_entries(kb_root, include_pending=False)`（默认），**Then** 行为与现在完全一致，不扫描 pending 目录

---

### User Story 5 - 修复 Agent 内部 evidence 自动写回（行为修复）(Priority: P1)

Feature 025 的 engine.py 在每次 `kb_read_entry` 成功后自动写 evidence。Read ≠ 有用，这个信号有噪音，与 MCP 路径「只有 confirm 才写 evidence」的语义不一致。

**Why this priority**: 数据模型一致性，否则内部 agent 和 MCP agent 产生不同质量的 evidence，maturity 信号失真。

**Independent Test**: agent 调用 `kb_read_entry` 后不产生 evidence 文件；调用 `kb_confirm_entry` 后产生 evidence 文件。

**Acceptance Scenarios**:

1. **Given** agent session 中调用 `kb_read_entry("PT-001")` 成功，**When** session 结束，**Then** `contributions/evidence/PT-001/` 无新文件产生
2. **Given** agent 调用 `kb_confirm_entry("PT-001")`，**Then** evidence 文件立即写入（不等 session 结束），返回操作结果

---

### User Story 6 - Pending 条目审核 CLI (Priority: P2)

`kb_submit` 创建 pending 条目后，需要一个轻量的人工审核路径将其升级为官方条目。现有 import pipeline 面向外部文档（需要 LLM 提取），不适合已格式化的 pending 条目。

**Why this priority**: 没有 approve 路径，pending 条目永远是死库，知识反哺断路。

**Independent Test**: 运行 `holmes kb pending list` 列出所有 pending 条目；运行 `holmes kb pending approve PT-XXXX`，条目移至官方目录，evidence 保留，maturity 基于现有 evidence 重新计算。

**Acceptance Scenarios**:

1. **Given** `pending/` 有若干条目，**When** 运行 `holmes kb pending list`，**Then** 输出 id、title、type、提交时间、evidence 数量
2. **Given** `holmes kb pending approve PT-XXXX`，**When** 条目内容合法，**Then** 文件移至 `<type>/<category>/` 目录，maturity 由 `derive_maturity(evidence)` 计算，evidence sidecar 不变
3. **Given** 条目内容缺少必要 section，**When** approve，**Then** 报错拒绝，条目留在 pending

---

### Edge Cases

- KB 目录不存在：server 启动即报错，不在运行时每次报错
- git config 未设置：contributor 回退 hostname，不阻断操作
- KB 条目文件损坏：list/overview 跳过该条目，不崩溃
- 并发 confirm：sidecar 文件名含 session_id，天然无冲突
- pending 条目 ID 与官方条目 ID 冲突：ID 生成时检查官方和 pending 两个命名空间

---

## Requirements

### Functional Requirements

**MCP Server:**
- **FR-001**: MCP server 通过 `holmes start --kb-path <path> --port <port>` 启动，使用 streamable-http transport（默认端口 8765），`holmes start` 是 `holmes` CLI 的顶层子命令；server 常驻，多个 MCP 客户端可同时连接
- **FR-002**: 实现 5 个 MCP tool：`kb_overview`、`kb_list`、`kb_read`、`kb_confirm`、`kb_submit`
- **FR-003**: `kb_read` 不记录任何 evidence；`kb_confirm` 的 tool description 明确说明调用时机：当 KB 条目帮助成功解决了问题，调用此接口将成功经验沉淀为证据
- **FR-004**: `kb_list` 支持 `type`、`category`、`limit`、`offset` 参数
- **FR-005**: `kb_confirm` contributor 来自 `git -C <kb_path> config user.email`，回退 `user.name`，再回退 hostname
- **FR-006**: Session ID 为 MCP server 进程启动时生成的 UUID，贯穿该进程生命周期

**KB 包修复:**
- **FR-007**: `list_entries()` 新增 `include_pending: bool = False` 参数，True 时额外扫描 `pending/` 目录
- **FR-008**: `append_evidence()` 调用 `list_entries` 时传 `include_pending=True`，使 pending 条目可写入 evidence
- **FR-009**: `kb_submit` 分配 pending 条目 ID 时，检查官方目录和 pending 目录两个命名空间，确保唯一

**CLI 新增:**
- **FR-010**: `holmes kb pending list` 列出所有 pending 条目
- **FR-011**: `holmes kb pending approve <entry_id>` 将 pending 条目移至官方目录，基于现有 evidence 计算 maturity，evidence sidecar 原地保留

**Agent 包修复:**
- **FR-012**: `engine.py` 移除 `kb_read_entry` 成功后自动追加 `session.kb_refs` 的逻辑
- **FR-013**: 移除 `_flush_evidence()` 方法和 `session.kb_refs` 字段
- **FR-014**: 新增 `kb_confirm_entry` agent tool，调用时直接写入 evidence，不等 session 结束

### Key Entities

- **MCP Tool**: 5 个，对应 5 种 agent 操作
- **Session ID**: MCP server 进程级 UUID，用于 evidence 去重
- **Contributor**: git config user.email / user.name / hostname 三级回退
- **Pending Entry**: `pending/<id>.md`，maturity=pending，有独立 evidence sidecar
- **Evidence Sidecar**: `contributions/evidence/<entry_id>/<session_id>.json`，路径与条目文件位置无关

---

## Success Criteria

- **SC-001**: 完整闭环演示：`kb_submit` → `pending list` → `pending approve` → `kb_list` 找到条目 → `kb_read` → `kb_confirm` → evidence 文件存在，maturity 正确
- **SC-002**: 内部 agent 调用 `kb_read_entry` 不产生任何 evidence 文件
- **SC-003**: 两台不同 git 用户的机器各自 `kb_confirm` 同一条目后 git merge，无冲突，maturity=proven
- **SC-004**: `kb_list` 在 500 条目 KB 下响应 < 1 秒
- **SC-005**: 所有现有 KB 测试（733 个）无回归

---

## Assumptions

- MCP Python SDK（`mcp` 包）通过 `pip install mcp` 安装
- KB 所在目录是 git 仓库；非 git 时 contributor 回退 hostname
- Pending 条目 ID 格式：`<TYPE_PREFIX>-P<timestamp8>`，如 `PT-P20260611`，approve 后 ID 保持不变
- `kb_submit` 的 content 参数为完整 Markdown（含 frontmatter 或纯正文均可），server 端补全必要 frontmatter 字段
- MCP server 是单用户本地进程，不考虑多用户并发认证
