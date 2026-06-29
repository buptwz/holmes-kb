# Feature Specification: M1 — 基础字段与过滤

**Feature Branch**: `dev-M1`

**Created**: 2026-06-23

**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - KB 状态过滤 (Priority: P1)

用户使用 `holmes kb list` 时，只想看到当前有效的知识条目（active），不想被 pending 或 deprecated 的旧条目干扰。

**Why this priority**: 这是 M1 的核心功能，所有其他模块的搜索和列表逻辑都依赖此过滤行为。

**Independent Test**: 可以通过在 KB 目录下创建带有不同 `kb_status` 值的测试文件，运行 `holmes kb list` 验证只返回 active 条目。

**Acceptance Scenarios**:

1. **Given** KB 中存在 `kb_status: active` 的 entry，**When** 用户运行 `holmes kb list`，**Then** 该 entry 出现在结果中
2. **Given** KB 中存在 `kb_status: pending` 的 entry，**When** 用户运行 `holmes kb list`，**Then** 该 entry 不出现在结果中
3. **Given** KB 中存在 `kb_status: deprecated` 的 entry，**When** 用户运行 `holmes kb list`，**Then** 该 entry 不出现在结果中
4. **Given** KB 中存在无 `kb_status` 字段的旧 entry，**When** 用户运行 `holmes kb list`，**Then** 该 entry 出现在结果中（向后兼容，视为 active）
5. **Given** `holmes kb list --all` flag，**When** 用户运行，**Then** active 和 deprecated entry 均显示
6. **Given** KB 中存在 `kb_status: deprecated` 的 entry，**When** 用户运行 `holmes kb search <query>`，**Then** 该 entry 不出现在搜索结果中

---

### User Story 2 - Process Sub-entry 可见性 (Priority: P1)

用户使用 `holmes kb list` 时，只想看到可以作为独立诊断起点的顶层条目，不想看到 DAG 树内部的 process sub-entries。

**Why this priority**: Process sub-entries 是 Agent 2 生成的树内部节点，用户直接 `holmes kb list` 时不应看到这些中间节点。

**Independent Test**: 创建一个带有 `type: process` 且有 `parent_id` 字段的测试条目，验证其不出现在 `holmes kb list` 结果中，但 `holmes kb show <id>` 可正常访问。

**Acceptance Scenarios**:

1. **Given** KB 中存在 `type: process` 且 `parent_id` 非空的 entry，**When** 用户运行 `holmes kb list`，**Then** 该 entry 不出现
2. **Given** KB 中存在 `type: process` 但无 `parent_id` 字段的 entry，**When** 用户运行 `holmes kb list`，**Then** 该 entry 正常显示
3. **Given** `holmes kb list --all-types` flag，**When** 用户运行，**Then** process sub-entries 也出现在结果中
4. **Given** 某个 process sub-entry 的 ID，**When** 用户运行 `holmes kb show <id>`，**Then** 正常显示该条目内容，并在输出中包含 `[sub-entry of: <parent_id>]` 标签

---

### User Story 3 - 树导航：children 字段 (Priority: P2)

Agent 通过 pitfall root 进入，需要沿 `child_entry_ids` 链接递归深入。`read_entry` 应在 pitfall entry 有子节点时，自动附加 `children` 字段，让 Agent 一次调用即可获得树导航信息。

**Why this priority**: 这是 DAG 树形导航的基础，Agent 2 生成树形结构后需要依赖此字段遍历子节点。

**Independent Test**: 创建一个带有 `child_entry_ids` 的 pitfall entry 和对应的 process sub-entries，调用 `holmes kb show <pitfall-id> --json`，验证返回的 JSON 中包含 `children` 数组。

**Acceptance Scenarios**:

1. **Given** pitfall entry 的 frontmatter 包含 `child_entry_ids: [id1, id2]`，**When** 调用 `read_entry()`，**Then** 返回内容中附加了 `## Children` 信息块，包含每个子 entry 的 id 和 title
2. **Given** pitfall entry 无 `child_entry_ids` 字段，**When** 调用 `read_entry()`，**Then** 返回内容不附加任何 children 信息
3. **Given** `child_entry_ids` 中某个 ID 的 entry 不存在，**When** 调用 `read_entry()`，**Then** 忽略该 ID，不报错

---

### User Story 4 - ID 格式无关化 (Priority: P2)

旧 KB 使用 `PT-DB-001` 格式的 ID，新 KB 使用 `gpu-init-failure-root-001` 格式。`find_entry` 应同时支持两种格式，不依赖正则匹配特定格式。

**Why this priority**: 是向后兼容的关键，确保旧条目不会因 ID 格式变化而丢失访问能力。

**Independent Test**: 在 KB 中放置旧格式 ID 文件和新格式 ID 文件，分别使用两种 ID 调用 `holmes kb show`，验证均能找到。

**Acceptance Scenarios**:

1. **Given** ID 为 `PT-DB-001` 的旧格式 entry，**When** 调用 `find_entry("PT-DB-001")`，**Then** 正确返回该 entry
2. **Given** ID 为 `gpu-init-failure-root-001` 的新格式 entry，**When** 调用 `find_entry("gpu-init-failure-root-001")`，**Then** 正确返回该 entry
3. **Given** 不存在的 ID，**When** 调用 `find_entry()`，**Then** 返回 None

---

### User Story 5 - MCP 工具同步更新 (Priority: P2)

MCP 工具层（`mcp/tools.py`）通过 `handle_kb_list` / `handle_kb_search` / `handle_kb_read` 暴露 KB 功能给 Agent。M1 的过滤改动必须同步到 MCP 层，否则 Agent 会看到 pending/deprecated 条目，以及 `handle_kb_read` 对新格式 ID 路由错误。

**Why this priority**: MCP 是 Agent 的主要访问入口，不同步会导致 Agent 看到应隐藏的条目，且新格式 ID 无法通过 MCP 访问（被误判为 skill）。

**Independent Test**: 创建含新格式 ID 的 entry，通过 MCP `kb_read` 工具调用验证能正确返回内容（而非 "skill not found"）。创建 deprecated entry，通过 MCP `kb_list` 验证不返回该条目。

**Acceptance Scenarios**:

1. **Given** 新格式 ID（`gpu-init-failure-root-001`），**When** 通过 MCP `handle_kb_read` 访问，**Then** 正确返回 entry 内容（不路由到 `_read_skill`）
2. **Given** `kb_status: deprecated` 的 entry，**When** 通过 MCP `handle_kb_list` 列出，**Then** 不出现在结果中
3. **Given** process sub-entry，**When** 通过 MCP `handle_kb_list`，**Then** 不出现在结果中
4. **Given** pitfall entry 有 `child_entry_ids`，**When** 通过 MCP `handle_kb_read` 读取，**Then** 返回 dict 中包含 `children` 列表（`[{id, title}, ...]`）

---

### User Story 6 - Username 配置 (Priority: P3)

用户在执行 import 时，系统需要知道是谁发起的 import，以写入 `contributors` 字段。`holmes config set username <name>` 提供了这一配置能力。

**Why this priority**: 是 contributors 字段正确写入的前置条件，M2 及以后的模块依赖此字段。

**Independent Test**: 运行 `holmes config set username testuser`，然后运行 `holmes config show`，验证 username 字段被正确保存和读取。

**Acceptance Scenarios**:

1. **Given** 用户运行 `holmes config set username wangzhi`，**When** 命令执行成功，**Then** `~/.holmes/config.json` 中的 `username` 字段值为 `"wangzhi"`
2. **Given** 已设置 username，**When** 用户运行 `holmes config show`，**Then** 输出中包含 `username` 字段
3. **Given** 尚未设置 username，**When** 调用 `load_config()`，**Then** `config.username` 默认为空字符串

---

### Edge Cases

- 旧 entry 无 `kb_status` 字段时，视为 `active`（向后兼容）
- `child_entry_ids` 中引用的 entry 不存在时，安全忽略，不抛异常
- `find_entry` 大小写不敏感匹配（保持现有行为）
- `exclude_sub_entries=True` 时，`type: pitfall` 有 `parent_id` 的 entry 应被过滤（理论上不应出现，但需防御）
- `holmes kb list --all` 包含 deprecated 但仍过滤 pending（pending 条目在 contributions/pending 目录，不在正式条目目录）
- `read_entry` 附加的 children 信息以结构化注释形式追加，不破坏原始 Markdown 内容

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `schema.py` 中 MUST 新增 `KBStatus = Literal["pending", "active", "deprecated"]` 类型定义
- **FR-002**: `EntryFrontmatter` 中 MUST 新增可选字段：`kb_status`、`source_file`、`source_hash`、`description`、`import_trace_id`、`pitfall_structure`、`child_entry_ids`、`parent_id`
- **FR-003**: `list_entries()` MUST 新增 `kb_status: str = "active"` 参数，过滤 frontmatter 中 `kb_status` 不匹配的 entry；缺省 `kb_status` 字段的旧 entry 视为 `active`
- **FR-004**: `list_entries()` MUST 新增 `exclude_sub_entries: bool = True` 参数，过滤 `type == "process"` 且 `parent_id` 非空的 entry
- **FR-005**: `list_entries()` 中 `kb_status="*"` 或传入特殊值 `None` MUST 跳过状态过滤（供内部使用）
- **FR-006**: `find_entry(id)` MUST 改为文件系统扫描（`kb_root.rglob("*.md")`），通过文件名 stem 或 frontmatter id 字段匹配，支持新旧两种 ID 格式
- **FR-007**: `read_entry()` MUST 在返回内容的末尾附加 `children` 结构化块（当 frontmatter 中存在 `child_entry_ids` 且非空时），格式为可被解析的 Markdown 注释或专属 section
- **FR-008**: `LinearScanBackend.search()` MUST 默认只搜索 `kb_status: active` 且非 sub-entry 的 entries（`exclude_sub_entries=True`）
- **FR-009**: `holmes kb list` MUST 新增 `--all` flag，当传入时 `kb_status` 过滤改为包含 active + deprecated
- **FR-010**: `holmes kb list` MUST 新增 `--all-types` flag，当传入时 `exclude_sub_entries=False`
- **FR-011**: `holmes kb search` MUST 新增 `--all` flag，行为与 `kb list --all` 一致
- **FR-012**: `holmes kb show` MUST 在显示 process sub-entry 时，在输出前附加 `[sub-entry of: <parent_id>]` 标签行
- **FR-013**: `holmes config set` MUST 支持 `username` 作为合法的 key，写入 `~/.holmes/config.json`
- **FR-014**: `HolmesConfig` MUST 新增 `username: str = ""` 字段，并在 `from_dict()` 和 `to_dict()` 中正确处理
- **FR-015**: `mcp/tools.py` 的 `handle_kb_list()` MUST 传入 `kb_status="active", exclude_sub_entries=True` 到 `list_entries()`
- **FR-016**: `mcp/tools.py` 的 `_is_entry_id()` / routing 逻辑 MUST 支持新格式 ID（`gpu-init-failure-root-001`），确保新格式 ID 路由到 `_read_entry()` 而非 `_read_skill()`
- **FR-017**: `mcp/tools.py` 的 `_read_entry()` MUST 在返回 dict 中增加 `children` 字段（当 entry 有 `child_entry_ids` 时，值为 `[{id, title}, ...]`）
- **FR-018**: 所有改动 MUST 向后兼容旧格式 entry（无新字段的 entry 不受影响）

### Key Entities

- **KBStatus**: `"pending" | "active" | "deprecated"` — KB 管理工作流状态，与 `decay_status`（知识质量生命周期）正交
- **EntryFrontmatter 新字段**:
  - `kb_status`: KBStatus — 默认视为 `active` 当字段缺失时
  - `source_file`: str — 相对于 KB root 的源文档路径
  - `source_hash`: str — 文档内容 sha256 前缀
  - `description`: str — 1-2 句话的条目摘要
  - `import_trace_id`: str — 源文档文件名 stem，用于日志关联
  - `pitfall_structure`: `"tree" | "flat"` — 区分新式树形和旧式扁平 pitfall
  - `child_entry_ids`: list[str] — 树结构子节点 ID 列表
  - `parent_id`: str — 父 entry ID（process sub-entry 指向）
- **ChildrenBlock**: `{id: str, title: str}` 列表 — `read_entry()` 附加的导航信息

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `holmes kb list` 在包含 deprecated/pending/active 混合条目的 KB 中，只返回 active 条目（100% 准确率）
- **SC-002**: 旧 entry（无 `kb_status` 字段）在 `holmes kb list` 中正常显示，不因新字段缺失而丢失（向后兼容 100%）
- **SC-003**: `holmes kb list --all-types` 可以显示包含 process sub-entries 在内的全部条目，数量与实际文件数一致
- **SC-004**: `holmes kb show <process-sub-entry-id>` 能访问任何有效的 sub-entry，并在输出中包含父节点标签
- **SC-005**: `find_entry` 对旧格式（`PT-DB-001`）和新格式（`gpu-init-failure-root-001`）ID 均能正确返回结果
- **SC-006**: 单元测试覆盖所有 happy path 场景和向后兼容旧 entry 场景，测试全部通过

## Assumptions

- `holmes kb list --all` 包含 deprecated 但不包含 pending（pending 条目存放在 `contributions/pending/` 目录，由 `include_pending=True` 参数控制，与 `kb_status` 过滤独立）
- `read_entry()` 附加的 children 块以 YAML front-matter 追加注释形式实现，不修改原始 Markdown body；具体格式在 plan 阶段确定
- `search.py` 的过滤通过在 `LinearScanBackend.search()` 中读取每个文件的 frontmatter 实现，性能可接受（KB 规模 ≤1000 条）
- `find_entry` 使用文件系统扫描后，`read_entry()` 内部调用 `list_entries(include_pending=True)` 的现有实现需重构为使用新的 `find_entry` 或直接扫描
- 新增的 `username` 字段不影响 `holmes setup` 命令（setup 不写入 username，username 只通过 `holmes config set username` 设置）
