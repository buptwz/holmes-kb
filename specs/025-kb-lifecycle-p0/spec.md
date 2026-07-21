# Feature Specification: Knowledge Lifecycle 核心数据流打通

**Feature Branch**: `025-kb-lifecycle-p0`

**Created**: 2026-06-11

**Status**: Draft

**Input**: User description: "Knowledge Lifecycle 核心数据流打通：三个 P0 缺失环节实现"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Evidence 写回：使用记录自动留存 (Priority: P1)

运维人员使用 Holmes agent 排障时，agent 查阅了若干 KB 知识条目。本次排障会话结束后，系统自动将"哪些条目被查阅过"这一事实写回到对应条目的历史记录中，使每个条目都积累自己的使用证据。知识作者和系统可凭此判断哪些条目在真实排障中确实有效。

**Why this priority**: Evidence 写回是整个知识生命周期的数据源头。没有 evidence，maturity 无法提升，搜索无法按新鲜度排序，整个数据模型无法运转。

**Independent Test**: 启动一个 agent 排障会话，让 agent 读取至少一条 KB 条目，会话结束后检查该条目的 evidence 文件——应新增一条包含日期的引用记录。

**Acceptance Scenarios**:

1. **Given** agent 在排障会话中调用读取 KB 条目操作，**When** 会话正常结束，**Then** 该条目的 evidence sidecar 中新增一条引用记录，包含引用日期。
2. **Given** agent 在同一会话中读取了多条不同 KB 条目，**When** 会话结束，**Then** 每条被读取的条目都各自获得一条新 evidence 记录。
3. **Given** agent 读取同一条目多次，**When** 会话结束，**Then** 该条目 evidence 中只新增一条记录（每次会话去重，不重复计数）。
4. **Given** 会话中未读取任何 KB 条目，**When** 会话结束，**Then** 不产生任何 evidence 写入操作。

---

### User Story 2 — Maturity 自动提升：知识成熟度随使用自动演进 (Priority: P2)

运维团队积累了大量 KB 知识条目。目前所有条目的成熟度字段（draft/verified/proven）需要人工维护，无法反映实际使用情况。本 feature 后，每当一条条目积累到足够 evidence，系统自动将其成熟度升级；长期无人使用的条目成熟度自动降级，使知识库的质量标签与实际有效性保持一致，无需人工干预。

**Why this priority**: Maturity 是知识可信度的核心标签，直接影响用户信任度和搜索结果的解读。P0-1 打通后，P0-2 才能将 evidence 转化为有意义的成熟度信号。

**Independent Test**: 在一个 maturity=draft 的条目上手动追加足够多的 evidence 记录（达到 verified 阈值），然后触发 evidence 写入——条目的 maturity 字段应自动变为 verified，无需任何人工操作。

**Acceptance Scenarios**:

1. **Given** 一个 maturity=draft 的条目，**When** 其 evidence 累计达到 verified 阈值（至少 1 次工作流引用），**Then** 条目 frontmatter 中的 maturity 字段自动更新为 verified。
2. **Given** 一个 maturity=verified 的条目，**When** 其 evidence 达到 proven 阈值（来自 ≥2 人、≥2 项目的引用），**Then** maturity 自动更新为 proven。
3. **Given** evidence 写入触发后，**When** 成熟度计算完成，**Then** maturity 字段更新与 evidence 写入在同一次操作中完成，不需要额外的手动步骤。
4. **Given** evidence 写入后成熟度未达到提升阈值，**When** 计算完成，**Then** maturity 字段保持不变（不错误降级）。

---

### User Story 3 — 搜索按 Evidence 新鲜度排序：最近验证的知识优先呈现 (Priority: P3)

运维人员通过 Holmes 搜索 KB 时，当前结果按关键词命中率排序，无法区分"上周刚验证过的有效条目"和"两年前创建从未被引用的过期条目"。本 feature 后，搜索结果优先返回最近在真实排障中被引用验证的条目，帮助运维人员快速找到最可能有效的知识。

**Why this priority**: 前两个 P0 打通了 evidence 数据流，P0-3 让 evidence 数据在搜索中发挥作用，完成"证据驱动知识发现"的闭环。

**Independent Test**: 准备两条关键词相同的 KB 条目——一条有近期 evidence，一条没有 evidence——执行搜索，有 evidence 的条目应排在前面。

**Acceptance Scenarios**:

1. **Given** 两条关键词命中率相同的条目，一条有近期 evidence，一条无 evidence，**When** 执行搜索，**Then** 有近期 evidence 的条目排在前面。
2. **Given** 多条条目均有 evidence，**When** 执行搜索，**Then** 按最近 evidence 日期降序排列，evidence 最新的条目优先。
3. **Given** 所有搜索结果均无 evidence，**When** 执行搜索，**Then** 退回按关键词命中率排序（保持向后兼容）。
4. **Given** 条目有 evidence 但关键词完全不匹配，**When** 执行搜索，**Then** 该条目不出现在结果中（evidence 不影响关键词过滤）。

---

### Edge Cases

- agent 会话异常中断（崩溃、超时）时，evidence 写回是否仍被保证？（假设：尽力写入，不保证原子性；后续可加幂等重试）
- evidence sidecar 文件不存在或损坏时，写入操作如何处理？（假设：重新创建，不影响主条目）
- 同时有多个 agent 会话并发写入同一条目的 evidence 时如何处理？（假设：逐条追加，文件锁保证顺序写入）
- maturity 计算中，contributor 和 project_id 字段缺失时如何处理？（假设：无 contributor/project_id 的 evidence 仍计入引用次数，但不计入 proven 阈值的"多人多项目"条件）

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须在 agent 排障会话中记录所有被读取的 KB 条目 ID
- **FR-002**: 系统必须在 agent 会话结束时将记录的条目引用批量写入各条目的 evidence 存储，每条引用包含日期信息
- **FR-003**: 同一会话内对同一条目的多次读取只写入一条 evidence 记录（会话级去重）
- **FR-004**: evidence 写入完成后，系统必须立即重新计算该条目的成熟度并更新 maturity 字段
- **FR-005**: maturity 计算规则：draft → verified 阈值为至少 1 次有效工作流引用；verified → proven 阈值为来自 ≥2 名不同贡献者且跨 ≥2 个不同项目的引用
- **FR-006**: 知识搜索结果必须以最近 evidence 日期为主排序键，关键词命中率为次排序键
- **FR-007**: 无 evidence 的条目在搜索排序中等同于日期为"无穷远过去"，不影响关键词过滤逻辑

### Key Entities

- **Evidence 记录**: 代表一次 KB 条目被实际使用的事实，包含引用日期、贡献者标识、项目标识
- **Maturity**: 条目的成熟度标签（draft / verified / proven），由 evidence 数量和多样性自动派生
- **KB 条目**: 知识库中的一个知识点条目，包含内容和 maturity 字段，关联若干 evidence 记录

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: agent 排障会话结束后 evidence 写回成功率 ≥ 99%（会话正常结束时）
- **SC-002**: evidence 写入到 maturity 字段更新的端到端延迟 < 1 秒（单次操作）
- **SC-003**: 搜索结果中，有近期 evidence（30 天内）的条目排名高于同等关键词命中率但无 evidence 的条目，覆盖率 100%
- **SC-004**: 整个数据流（使用 → evidence → maturity 更新 → 搜索排序）在现有测试套件中有端到端测试覆盖，零回归

## Assumptions

- Holmes agent 排障会话有明确的"会话开始"和"会话结束"边界，可以在结束点触发批量写回
- KB 条目已存在 evidence sidecar 格式（由前序 feature 003 定义），本 feature 只负责写入，不重新设计格式
- maturity 的 proven 阈值数值（≥2 人，≥2 项目）由现有 derive_maturity() 逻辑定义，本 feature 不修改阈值，只负责在正确时机调用
- 本 feature 不实现 maturity 降级（decay）逻辑，decay 属于独立 feature
- MCP server 暴露不在本 feature 范围内
- 并发写入冲突通过现有文件锁机制处理，本 feature 不需要引入新的并发控制
