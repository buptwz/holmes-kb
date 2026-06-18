# Feature Specification: MCP KB 透明通道

**Feature Branch**: `031-mcp-kb-channel`

**Created**: 2026-06-13

**Status**: Draft

---

## 背景

Feature 027 实现了初版 MCP Server（5 个工具），存在以下缺陷：

- Skills 完全不可访问（`skills/` 目录无任何 MCP 工具覆盖）
- 无搜索能力，agent 只能按类型逐层浏览
- Entry 与 Skill 之间的关联无法被 agent 利用导航
- `kb_submit` 绕过 import pipeline，写入质量无保障
- Session ID 全局共享，`kb_confirm` 去重逻辑在多客户端场景下失效

本 Feature 将 MCP Server 重构为完整的 **KB 透明通道**：外部 agent 通过 6 个工具可访问知识库所有内容（entries + skills + skill 子文件），并通过自然语言提交沉淀新知识。

**核心设计原则**：
- **渐进式披露**：工具描述 + 响应 hint 逐步引导 agent 深入，无需预先了解 KB 结构
- **统一寻址**：`kb_read` 通过 ID 格式自动路由，agent 无需区分 entry 和 skill
- **Agent 只读 skill，不写 skill**：skill 是从 entry 派生的产物，agent 通过提交 entry 间接触发 skill 生成
- **工具描述是主文档**：关键约定写在 tool description 里，response hint 是辅助引导

---

## User Scenarios & Testing

### User Story 1 — 渐进式发现并读取知识（含 Skill）(Priority: P1)

外部 agent（如 Claude Desktop、Cursor）遇到技术问题，通过 MCP 逐层深入知识库，找到相关 entry 和关联 skill，读取 skill 中的操作指令及子文件，按指令处理问题。

**Why this priority**: 这是 MCP 通道的核心读取能力。没有完整的读取路径（entry → skill → 子文件），知识库对外部 agent 价值有限。

**Independent Test**: 配置 MCP 客户端连接本地 Server；依次调用 `kb_overview` → `kb_list` → `kb_read(entry)` → `kb_read(skill)` → `kb_read(skill, path)` 全链路，无需其他功能即可独立验证。

**Acceptance Scenarios**:

1. **Given** KB 有 entries 和 skills，**When** agent 调用 `kb_overview()`，**Then** 返回各 entry 类型数量、skill 总数、可用 categories 列表，并在 hint 中告知下一步可调用的工具及有效参数值
2. **Given** `skill_count > 0`，**When** agent 调用 `kb_list(type="skill")`，**Then** 返回 skills 列表，每条含 `id`（= skill name，可直接传给 `kb_read`）和 `description`
3. **Given** 有效 entry ID，**When** agent 调用 `kb_read("PT-DB-001")`，**Then** 返回完整 Markdown 内容，`skill_refs` 字段列出关联 skill name（可直接作为 `kb_read` 的 `id` 参数），hint 引导读取 skill
4. **Given** `skill_refs` 非空，**When** agent 调用 `kb_read("redis-oom-recovery")`（skill name），**Then** 返回 SKILL.md body、`linked_entries` 列表（关联 entry ID）、`files` 列表（可用子文件路径）、hint 引导读取子文件
5. **Given** skill 有子文件，**When** agent 调用 `kb_read("redis-oom-recovery", path="scripts/check-memory.sh")`，**Then** 返回该文件的文本内容
6. **Given** entry 无关联 skill，**When** agent 读取该 entry，**Then** 返回内容中 `skill_refs` 为空列表，无 skill 相关 hint

---

### User Story 2 — 搜索定位相关知识 (Priority: P1)

外部 agent 根据用户描述的症状关键词，直接搜索相关 entries，无需预先知道分类结构。

**Why this priority**: 搜索是比浏览更高效的知识发现路径，对症状驱动的诊断场景至关重要。

**Independent Test**: 调用 `kb_search(query="Redis OOM")`，返回相关 entries；对结果中任意一条调用 `kb_read` 读取全文；无需其他工具即可独立验证。

**Acceptance Scenarios**:

1. **Given** 用户描述症状关键词，**When** agent 调用 `kb_search(query="...")`，**Then** 返回相关 entries，按相关度排序，每条含 `id`、`title`、`maturity`、`brief` 摘要
2. **Given** 搜索结果含相关 entry，**When** agent 调用 `kb_read(id)`，**Then** 返回完整内容，含 `skill_refs`
3. **Given** 搜索无结果，**Then** 返回空列表，hint 建议用 `kb_list` 按类型浏览
4. **Given** `kb_search` 调用时，KB 中只有匹配的 skill 但无对应 entry，**Then** 搜索无法发现该 skill（已知限制，可通过 `kb_list(type='skill')` 浏览）

---

### User Story 3 — 知识沉淀：提交新发现 (Priority: P2)

外部 agent 协助用户解决了一个 KB 中不存在的问题，将解决经验以自然语言提交，经结构化处理后供人工审核发布。

**Why this priority**: 知识反哺是 KB 持续生长的入口。Agent 不需要了解 KB schema，只需提供清晰描述。

**Independent Test**: 调用 `kb_submit(content="...")`，`contributions/pending/` 出现新条目，返回 pending ID；可独立验证，无需其他工具。

**Acceptance Scenarios**:

1. **Given** agent 有完整问题描述（含症状、根因、解决步骤），**When** 调用 `kb_submit(content="...")`，**Then** 知识被结构化处理并写入 pending 区，返回 `{id, status: "pending"}`
2. **Given** 提交内容与已有 entry 高度相似，**When** 调用 `kb_submit`，**Then** 返回 `{status: "duplicate", existing_id: "PT-DB-001", hint: "Use kb_confirm(entry_id='PT-DB-001')"}`，不创建重复条目
3. **Given** 提交内容信息不足（无法提取有效结构），**When** 调用 `kb_submit`，**Then** 返回 error，提示需包含症状、根因、解决步骤
4. **Given** 提交成功，**Then** agent 将 pending ID 和审核方式告知用户

---

### User Story 4 — Evidence 反馈推动知识成熟 (Priority: P1)

外部 agent 按 KB 条目指导成功解决问题后，记录反馈，推动条目 maturity 升级，使知识在未来搜索中排名更靠前。

**Why this priority**: Evidence 是知识生命周期的驱动力，没有反馈机制则 maturity 永远停滞。

**Independent Test**: 调用 `kb_confirm(entry_id="PT-DB-001")`；检查 evidence 文件写入；同一连接再次调用返回 duplicate；不同连接调用均写入；可独立验证。

**Acceptance Scenarios**:

1. **Given** 用户确认问题已解决，**When** agent 调用 `kb_confirm(entry_id="PT-DB-001")`，**Then** evidence 文件写入，maturity 按规则升级，返回 `{ok: true, maturity, promoted, contributor}`
2. **Given** 同一 MCP 连接内已 confirm 过同一 entry，**When** 再次调用，**Then** 返回 `{ok: false, reason: "duplicate"}`，不写重复 evidence
3. **Given** 两个不同 MCP 连接各自 confirm 同一 entry，**Then** 两条 evidence 均写入，maturity 正确累计
4. **Given** agent 传入 skill name（如 `redis-oom-recovery`）而非 entry ID，**When** 调用 `kb_confirm`，**Then** 返回明确错误，提示应传 entry ID

---

### Edge Cases

- KB 目录为空：`kb_overview` 返回全 0，不报错
- KB 目录不存在：Server 启动即报错，运行时不崩溃
- `id` 格式区分：entry ID 为大写字母前缀 + 数字（如 `PT-DB-001`），skill name 为小写 kebab（如 `redis-oom-recovery`），格式天然互斥，Server 无需额外约束
- Skill 子目录含二进制文件（如 `.png`）：`files` 列表只返回文本文件，二进制文件过滤不展示
- `kb_read(entry_id, path="scripts/foo.sh")`：entry 不支持 `path` 参数，返回明确 error
- `kb_list(type="skill", category="database")`：`category` 对 skill 无意义，静默忽略，返回全部 skills
- `kb_submit` pipeline 耗时长（30-120 秒）：Server 不设超时限制，客户端配置足够的超时时间（建议 ≥ 180 秒）
- `kb_confirm` 传入 pending 条目 ID：pending 条目不可被 confirm，返回明确 error
- git config 未设置：contributor 回退 hostname，操作不阻断

---

## Requirements

### Functional Requirements

**新增工具：**
- **FR-001**: 新增 `kb_search` 工具，支持关键词搜索 entries，结果按相关度排序，支持 `type` 过滤和 `limit` 参数

**扩展现有工具：**
- **FR-002**: `kb_overview` 新增 `skill_count` 字段（扫描 `skills/` 目录统计），hint 字段明确列出 `kb_list` 的所有有效 `type` 值（含 `"skill"`）
- **FR-003**: `kb_list` 支持 `type="skill"`，返回 skills 列表，每条的 `id` 字段为 skill name（可直接传给 `kb_read`）；`category` 参数对 `type="skill"` 静默忽略
- **FR-004**: `kb_read` 实现统一寻址路由：
  - `id` 匹配 entry ID 格式（`[A-Z]{2,3}-[A-Z]{2,3}-\d{3}`）→ 读 entry，响应含 `skill_refs`（原始 skill name 列表，直接可用）
  - `id` 不匹配 entry 格式且无 `path` → 读 `skills/<id>/SKILL.md`，响应含 `linked_entries`（动态反查）、`files`（过滤二进制后的子文件列表）
  - `id` 不匹配 entry 格式且有 `path` → 读 `skills/<id>/<path>` 指定子文件（仅文本文件）
  - entry ID 传入 `path` 参数时返回明确 error

**`kb_submit` 走 import pipeline：**
- **FR-005**: `kb_submit` 接收自然语言 `content`，调用 `ImportAgentRunner` headless 模式处理；成功返回 `{id, status: "pending"}`；检测到重复时返回 `{status: "duplicate", existing_id, existing_title, hint}`

**`kb_confirm` 去重修复：**
- **FR-006**: `kb_confirm` 的 session_id 改为 per-connection 生成（MCP 连接建立时生成 UUID），替换现有 per-server-process session_id；同一连接内对同一 entry 只记录一次 evidence

**ImportAgentRunner headless 支持：**
- **FR-007**: `ImportAgentRunner` 新增 `run_headless(content: str) -> dict` 方法，支持从 MCP 上下文同步调用，无 CLI 依赖，返回结构化结果

**Tool Descriptions：**
- **FR-008**: 每个工具的 description 明确说明：何时调用、有效参数值、与其他工具的调用关系、不得调用的条件
- **FR-009**: `kb_read` 的 description 中说明 ID 路由规则（entry ID 格式 vs skill name 格式，server 自动路由）

**数据模型文档：**
- **FR-010**: 实现阶段必须生成 `docs/kb-data-model.md`，作为整个项目知识库数据模型的权威参考文档，用于后续自动化质量验证和开发理解
  - **约束**：文档内容必须从现有代码反向提取（`schema.py`、`store.py`、`skill/manager.py`、`skill/template.py`、`pending.py` 等），不得凭空描述；每个字段、规则、格式均需与代码实现对齐
  - **覆盖范围**：
    - 文件系统布局（KB 目录结构，各子目录用途）
    - 所有 Entry 类型的 frontmatter 字段（必填/可选、类型、有效值、格式约束）
    - 各 Entry 类型的必需 body sections
    - Skill 结构（`SKILL.md` frontmatter 字段、body 格式、subdirectory 规范）
    - ID 格式规则（entry ID pattern、skill name pattern、pending ID pattern）
    - Maturity 级别定义及升级规则（evidence 数量/来源阈值）
    - Evidence sidecar 格式（字段、存储路径、去重规则）
    - Pending entry 格式（与正式 entry 的差异、临时 ID 格式）
    - `skill_refs` 字段格式约束
  - **用途**：作为 MCP `kb_submit` 质量验证基准、import pipeline 输出校验依据、开发人员 onboarding 参考

### Key Entities

- **Entry ID**：`[A-Z]{2,3}-[A-Z]{2,3}-\d{3}` 格式，唯一标识一条已发布知识条目
- **Skill Name**：小写 kebab 字符串，唯一标识一个 skill，与 entry ID 格式天然互斥；同时作为 `kb_read` 的 skill 寻址参数
- **`skill_refs`**：Entry frontmatter 中存储的关联 skill name 列表；`kb_read` entry 时原样返回，可直接作为 `kb_read(id)` 的参数
- **`linked_entries`**：读取 skill 时动态计算（扫描所有 entry 的 `skill_refs` 反查），返回关联 entry 的 ID 列表
- **Connection Session ID**：每个 MCP 连接建立时生成的 UUID，用于 `kb_confirm` 去重隔离

---

## Success Criteria

- **SC-001**: 完整读取链路验证：`kb_overview` → `kb_list(type="skill")` → `kb_read(skill_name)` → `kb_read(skill_name, path="scripts/...")` 全链路返回正确内容，agent 无需做任何格式转换
- **SC-002**: 双向导航验证：`kb_search` 找到 entry → `kb_read(entry_id)` 从 `skill_refs` 读到 skill → skill 响应的 `linked_entries` 指回原 entry，全链路无需 agent 手动构造任何 ID 格式
- **SC-003**: 知识沉淀验证：`kb_submit` 提交自然语言 → pending 条目创建，内容已结构化；重复提交时返回已有 entry ID
- **SC-004**: 去重隔离验证：两个不同 MCP 连接对同一 entry confirm 时两条 evidence 均写入；同一连接重复 confirm 时只写一条
- **SC-005**: 所有现有 KB 测试无回归

---

## Assumptions

- Skill name 与 entry ID 格式天然互斥（entry ID 含大写前缀和数字后缀，skill name 为纯小写 kebab），`kb_read` 路由无歧义，无需 agent 显式声明类型
- `ImportAgentRunner` 可被重构为支持 headless 同步调用（无 CLI 依赖）
- MCP 连接生命周期与单次 agent session 对应，连接断开视为 session 结束
- Skill 子文件文本/二进制按扩展名判断（`.sh`、`.py`、`.md`、`.txt`、`.json`、`.yaml`、`.yml` 等为文本）
- `kb_confirm` 仅操作已发布 entries（非 pending）；agent 通过 skill 解决问题后，应 confirm 该 skill 的 `linked_entries` 中的 entry
- 现有 `holmes start` 命令已支持 MCP Server 启动（Feature 027 实现），本 Feature 在此基础上扩展
- `kb_submit` 调用涉及 LLM 处理，耗时 30-120 秒；客户端需配置 ≥ 180 秒超时，Server 不设上限
