# Feature Specification: 修复 Holmes KB v3 报告缺陷

**Feature Branch**: `007-fix-kb-v3-bugs`

**Created**: 2026-06-06

**Status**: Draft

## User Scenarios & Testing

### User Story 1 - list --query 数字 tag 崩溃 (Priority: P0)

用户在 KB 条目中使用了纯数字 tag（如 `- 502`），然后执行 `holmes kb list --query <keyword>` 时，CLI 崩溃并抛出 `AttributeError: 'int' object has no attribute 'lower'`，导致无法搜索任何条目。

**Why this priority**: 这是阻断核心功能的崩溃缺陷，一旦 KB 存在数字 tag 的条目，所有带查询的列表操作均失败，影响范围为全部用户。

**Independent Test**: 创建一个含数字 tag（如 `tags: [502, redis]`）的条目，执行 `holmes kb list --query redis` 不崩溃，正常返回结果。

**Acceptance Scenarios**:

1. **Given** KB 中存在含纯数字 tag（如 `502`）的条目，**When** 执行 `holmes kb list --query <keyword>`，**Then** 命令正常返回条目列表，不抛出 `AttributeError`
2. **Given** KB 中存在含混合类型 tag（数字和字符串混合）的条目，**When** 执行 `holmes kb list --query <keyword>`，**Then** 字符串 tag 参与匹配，数字 tag 被自动转换后参与匹配
3. **Given** 查询关键词与某数字 tag 的字符串表示相匹配，**When** 执行搜索，**Then** 该条目被正确返回

---

### User Story 2 - import --dry-run 无 API Key 崩溃 (Priority: P1)

用户在没有配置 API Key 的环境中使用 `holmes import <file> --dry-run` 尝试预览导入结果，却收到网络认证错误而非预览输出，因为 dry-run 模式仍然调用了 LLM API。

**Why this priority**: dry-run 模式的设计意图是"无副作用预览"，当前实现违背了用户预期，且在 CI/沙箱环境中完全不可用。

**Independent Test**: 在未配置 API Key 的环境中执行 `holmes import <file> --dry-run`，命令成功输出文件内容预览，不尝试调用外部 API。

**Acceptance Scenarios**:

1. **Given** 未配置 API Key，**When** 执行 `holmes import <file> --dry-run`，**Then** 命令输出文件内容预览并以 `(dry-run)` 标注，不报网络/认证错误
2. **Given** 导入文件已有合法 KB frontmatter（含 `type` 和 `title`），**When** 执行 `--dry-run`，**Then** 原有 frontmatter 被解析并展示，不触发 LLM 调用
3. **Given** 执行 `--dry-run`，**When** 命令完成，**Then** pending 目录中不写入任何文件

---

### User Story 3 - correction confirm 不保留 created_at (Priority: P1)

用户通过纠错流程（`corrects: <id>`）修正一个已有条目，confirm 后发现该条目的 `created_at` 变成了纠错操作的时间，原始创建时间丢失，导致条目历史信息不准确。

**Why this priority**: 数据完整性问题，`created_at` 是条目的历史溯源字段，不应被修改。

**Independent Test**: 对一个 `created_at: 2020-01-01` 的条目执行纠错 confirm，确认后条目的 `created_at` 仍为 `2020-01-01`。

**Acceptance Scenarios**:

1. **Given** 原始条目的 `created_at` 为历史时间，**When** 执行纠错 confirm，**Then** 新条目的 `created_at` 与原始条目相同
2. **Given** 纠错 pending 条目本身有 `created_at` 字段，**When** confirm，**Then** 使用原始被纠错条目的 `created_at`，不使用 pending 条目的值
3. **Given** 原始条目不存在 `created_at` 字段，**When** 执行纠错 confirm，**Then** 使用当前时间作为 `created_at`（降级处理，不崩溃）

---

### User Story 4 - correction confirm 不追加 contributor (Priority: P1)

用户在纠错时通过 `--contributor <name>` 指定了贡献者，confirm 后查看条目发现 `contributors` 列表中没有新贡献者的名字，贡献记录丢失。

**Why this priority**: 贡献者追踪是 KB 治理的关键，丢失贡献者信息影响知识归因。

**Independent Test**: 对含 `contributors: [alice]` 的条目执行 `holmes kb confirm <id> --contributor bob`（纠错路径），确认后条目 `contributors` 为 `[alice, bob]`。

**Acceptance Scenarios**:

1. **Given** 原始条目有 `contributors: [alice]`，**When** 执行纠错 confirm 并传入 `--contributor bob`，**Then** 确认后条目 `contributors` 为 `[alice, bob]`
2. **Given** 原始条目有 `contributors: [alice]`，**When** 执行纠错 confirm 但不传 `--contributor`，**Then** `contributors` 保持原值 `[alice]`，不新增空值
3. **Given** `--contributor` 传入的名字已在 `contributors` 列表中，**When** confirm，**Then** 列表不重复追加

---

### User Story 5 - Gate 3 预览截断 (Priority: P1)

用户在 `holmes kb confirm` 的 Gate 3 预览阶段只能看到条目内容的前 800 字符，无法判断条目完整性，特别是对于长文档纠错场景，截断导致预览形同虚设。

**Why this priority**: Gate 3 是确认流程的最后防线，截断预览削弱了其把关作用，影响数据质量。

**Independent Test**: 执行 `holmes kb confirm <id>` 到 Gate 3，看到的提示引导用户使用 `holmes kb pending --show <id>` 查看完整内容，而非截断显示。

**Acceptance Scenarios**:

1. **Given** 待确认条目内容超过 800 字符，**When** Gate 3 显示预览，**Then** 提示中包含 `holmes kb pending --show <id>` 命令，引导用户查看完整内容
2. **Given** 待确认条目内容不足 800 字符，**When** Gate 3 显示预览，**Then** 显示完整内容（无需截断提示）
3. **Given** Gate 3 显示截断提示，**When** 用户执行 `holmes kb pending --show <id>`，**Then** 用户可查看完整内容

---

### User Story 6 - pending list 空 ID 显示 (Priority: P2)

用户执行 `holmes kb pending` 列表时，某些条目显示为空 ID（`""`），无法从列表中得知应使用哪个 ID 来 confirm 或 reject，操作受阻。

**Why this priority**: 影响日常操作便利性，但可通过直接查看文件绕过，因此为 P2。

**Independent Test**: 创建一个 frontmatter 中 `id: ""` 的 pending 条目，执行 `holmes kb pending` 能在列表中看到该条目的文件名（不含 `.md`）而非空字符串。

**Acceptance Scenarios**:

1. **Given** pending 条目的 frontmatter `id` 为空字符串，**When** 执行 `holmes kb pending` 列表，**Then** 该条目显示文件名 stem（不含 `.md` 后缀）作为 ID
2. **Given** pending 条目有正常 `id` 字段，**When** 执行列表，**Then** 显示正常 `id`，行为不变
3. **Given** 显示的是文件名 stem，**When** 用户使用该 stem 执行 `holmes kb confirm <stem>`，**Then** 操作成功

---

### User Story 7 - correction confirm 缺少 maturity 降级警告 (Priority: P2)

用户纠错 confirm 后，条目 maturity 被自动降级为 `verified`，但 CLI 没有给出任何提示，用户不知道这个副作用发生了，需要事后才能发现。

**Why this priority**: 改善用户感知，不影响数据正确性，因此为 P2。

**Independent Test**: 对 maturity 为 `proven` 的条目执行纠错 confirm，输出中包含明确的降级警告信息。

**Acceptance Scenarios**:

1. **Given** 原始条目 maturity 为 `proven`，**When** 执行纠错 confirm，**Then** 输出包含警告：maturity 已从 `proven` 降级至 `verified`
2. **Given** 原始条目 maturity 为 `verified`，**When** 执行纠错 confirm，**Then** 输出包含说明：maturity 保持 `verified`（无降级）
3. **Given** 原始条目 maturity 为 `draft`，**When** 执行纠错 confirm，**Then** 输出说明 maturity 升级为 `verified`

---

### Edge Cases

- 条目 `tags` 字段为空列表或 `null` 时，`list --query` 不崩溃
- `import --dry-run` 传入不存在的文件时，报错信息与不加 `--dry-run` 一致（文件不存在错误）
- 原始条目文件在 confirm 期间被删除时，纠错 confirm 给出明确的错误提示
- `contributors` 去重时大小写敏感（`Alice` 和 `alice` 视为不同贡献者）

## Requirements

### Functional Requirements

- **FR-001**: `list --query` 在处理 tag 时必须将每个 tag 转换为字符串后再进行大小写不敏感匹配，不因 tag 为整数类型而崩溃
- **FR-002**: `import --dry-run` 执行时必须跳过 LLM API 调用，直接解析文件并输出内容预览
- **FR-003**: 纠错路径的 confirm 必须从原始条目继承 `created_at` 字段
- **FR-004**: 纠错路径的 confirm 必须将 `--contributor` 参数值追加到原始条目的 `contributors` 列表（去重后）
- **FR-005**: Gate 3 预览在内容超过 800 字符时必须显示引导命令（`holmes kb pending --show <id>`），替代截断显示
- **FR-006**: `pending` 列表在条目 `id` 为空时必须显示文件名 stem 作为替代标识
- **FR-007**: 纠错 confirm 完成后必须在输出中显示 maturity 变更信息（降级/保持/升级）

### Key Entities

- **KB Entry**: 正式 KB 条目，包含 `id`, `type`, `title`, `maturity`, `created_at`, `updated_at`, `contributors`, `tags` 等字段
- **Pending Entry**: 待确认条目，存于 `contributions/pending/`，包含 `corrects` 字段（纠错类型）或无（新增类型）
- **Import Result**: import 命令的执行结果，dry-run 模式下包含内容预览但不写入磁盘

## Success Criteria

### Measurable Outcomes

- **SC-001**: 含数字 tag 的 KB 中执行 `list --query` 成功率从 0% 提升至 100%（零崩溃）
- **SC-002**: `import --dry-run` 在无 API Key 环境中的可用率从 0% 提升至 100%
- **SC-003**: 纠错 confirm 后条目数据完整性达到 100%（`created_at` 和 `contributors` 均正确）
- **SC-004**: Gate 3 预览用户满意度提升：用户能通过一条命令查看完整内容
- **SC-005**: `pending list` 中空 ID 条目的可操作性从 0% 提升至 100%
- **SC-006**: 全部 7 个缺陷修复后，现有测试套件（293 个测试）保持 100% 通过率，新增测试覆盖所有缺陷场景

## Assumptions

- 数字 tag 在 YAML 中被解析为整数类型（如 `- 502`），这是 YAML 规范行为，不作为配置修复
- `import --dry-run` 的预览内容基于文件原始内容或现有 frontmatter，不依赖 LLM 分类结果
- 贡献者去重逻辑大小写敏感（与现有行为保持一致）
- Gate 3 预览替换为提示命令后，旧的 800 字符截断逻辑完全移除
- `pending --show <id>` 命令已存在且可正常使用（引导命令的前提）
