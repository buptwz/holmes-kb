# Feature Specification: 长文档导入质量保证（Reader 对话历史压缩与覆盖保证）

**Feature Branch**: `022-reader-context-compression`

**Created**: 2026-06-10

**Status**: Draft

## User Scenarios & Testing

### User Story 1 - 长文档完整知识提取（Priority: P1）

工程师导入一份超长技术文档（如含多个事故分析、复杂多分支诊断流程的运维手册），系统应能提取其中所有知识点，不因文档长度而遗漏。当前问题：Reader 阶段随着文档长度增加，对话历史中堆积大量原始文本，导致上下文压力增大，LLM 的理解和提取质量随之下降。

**Why this priority**: 长文档是知识密度最高的文档类型。上下文压力导致的质量下降会静默发生，用户无法察觉知识被漏提，是最严重的数据质量风险。

**Independent Test**: 导入一份 50k+ 字符的技术文档 → 验证知识点数量与短文档等比例时的预期一致；验证运行时输出覆盖率日志；验证导入过程未因上下文过大而报错或降级。

**Acceptance Scenarios**:

1. **Given** 一份 50k 字符含 5 个独立事故分析的长文档，**When** 执行导入，**Then** 系统提取出 5 个知识点，覆盖率日志显示 ≥ 95%，无错误。
2. **Given** 一份结构不清晰的长流水文档（无标题、无明显分节），**When** 执行导入，**Then** 系统仍能基于文本语义提取知识点，不依赖文档格式。
3. **Given** 一份含复杂多分支诊断链路的技术文档（如"情况一/情况二/子情况 2a"），**When** 执行导入，**Then** 分支结构和跨节引用的语义被正确理解，不因分块而产生语义断层。
4. **Given** 长文档中某节使用指示代词引用前文（如"将上述配置修改后重启"），**When** 执行导入，**Then** 系统能正确理解引用关系，不产生悬空引用导致的错误提取。

---

### User Story 2 - 覆盖缺口保证（Priority: P2）

工程师导入文档后，系统应确保文档的所有区间都被处理，不因 LLM 自主决定读取顺序而遗漏某些段落。当前问题：Reader 的停止机制依赖 diminishing returns 检测，如果 LLM 未读某些区间但也没有继续寻找，这些区间会被静默跳过。

**Why this priority**: 漏读是静默发生的，用户无法感知。覆盖保证是提取完整性的工程基础。

**Independent Test**: 单测模拟 LLM 故意跳过文档中段 → 验证系统检测到未读区间并在同一对话上下文内强制要求 LLM 读取；最终覆盖率 ≥ 95%。

**Acceptance Scenarios**:

1. **Given** LLM 在一次 pass 中跳过了文档 40%-60% 的区间，**When** pass 结束，**Then** 系统检测到未读区间，在同一对话上下文内注入强制读取提示，LLM 继续读取。
2. **Given** 强制读取后覆盖率达到 ≥ 95%，**When** 导入完成，**Then** ImportReport 显示最终覆盖率，不低于阈值。
3. **Given** 强制读取时的未覆盖段落语义依赖前文（含指示代词等），**When** LLM 在同一对话上下文内读取该段落，**Then** 因上下文未被清除，LLM 拥有前文信息可正确理解。

---

### User Story 3 - 导入过程可观测（Priority: P3）

工程师导入长文档时，应能实时看到 Reader 阶段的读取进度和覆盖情况，而不是等待一个黑盒过程结束。

**Why this priority**: 可观测性是调试和信任系统的基础。长文档导入可能耗时较长，无进度输出会让用户不确定系统是否在正常工作。

**Independent Test**: 导入 50k+ 字符文档 → 终端输出包含每次读取 pass 的覆盖率、知识点数量、是否触发强制覆盖的日志。

**Acceptance Scenarios**:

1. **Given** 导入一份长文档，**When** Reader 完成每次 pass，**Then** 日志输出：已读字符数、覆盖率百分比、本次新增知识点数。
2. **Given** 系统触发强制覆盖（注入未读区间提示），**When** 该事件发生，**Then** 日志明确标注"强制覆盖未读区间 [start–end]"。
3. **Given** Reader 完成所有 pass，**When** 输出最终报告，**Then** ImportReport 包含总覆盖率字段，用户可通过 `--verbose` 查看完整读取轨迹。

---

### Edge Cases

- 文档完全没有 markdown 标题或任何结构信号：系统不依赖格式，纯依靠 LLM 文本理解能力处理。
- 文档包含跨越 2000+ 字符的单个段落：覆盖追踪确保该段落被处理，LLM 一次读取即可获得完整上下文。
- 文档长度超出 LLM context window 上限（极端情况）：系统在 ImportReport 中明确标注"文档超出单次处理上限，覆盖率 X%，建议分章节导入"，不静默降级。
- LLM 在强制读取区间后仍无法找到新知识点：正常结束，不无限循环，日志记录"强制覆盖后无新发现"。
- 对话历史压缩时 LLM 需要回读被压缩的内容：LLM 可随时调用 read_document_range 工具重新读取任意区间，文档始终完整。

---

## Requirements

### Functional Requirements

- **FR-001**: 系统对话历史压缩必须仅压缩 read_document_range 的原始文本返回值，保留 record_knowledge_point 调用记录不压缩。
- **FR-002**: 对话历史压缩后，原始文档必须始终通过 read_document_range 工具完整可访问，不允许任何形式的文档截断。
- **FR-003**: 每次 pass 结束后，系统必须计算未读字符区间，若存在显著未读区间（单段 > 500 字符），必须在同一 pass 上下文内注入强制读取提示。
- **FR-004**: 强制覆盖提示必须在同一对话上下文内发出（不开启新 pass、不清除历史），以保证 LLM 能访问前文内容解决语义依赖。
- **FR-005**: Reader 每次 pass 完成后必须输出结构化日志：已读字符数、覆盖率、本次新增知识点数、是否触发强制覆盖。
- **FR-006**: ImportReport 必须新增 `coverage_pct` 字段，记录最终文档覆盖率。
- **FR-007**: 当文档长度超出系统可处理阈值时，系统必须在 ImportReport.warnings 中输出明确提示，建议用户分章节导入，不静默降级。
- **FR-008**: 对话历史压缩阈值和覆盖率目标必须可通过配置项调整，不允许硬编码在业务逻辑中。

### Key Entities

- **DocumentCursor**: 追踪已读字符区间，提供覆盖率计算；文档原文始终完整存储，不随对话历史压缩而丢失。
- **ImportReport**: 新增 `coverage_pct` 字段（float），记录 Reader 阶段最终覆盖率。
- **ReaderConfig**: 新增配置项 `context_compression_threshold`（对话历史压缩触发阈值）和 `coverage_threshold`（目标覆盖率，现有常量改为可配置）。

---

## Success Criteria

### Measurable Outcomes

- **SC-001**: 50k 字符长文档的知识点提取数量与等量短文档分批导入的提取数量偏差 ≤ 10%。
- **SC-002**: Reader 覆盖率在所有测试文档（含无结构流水文）上均达到 ≥ 95%。
- **SC-003**: 长文档（50k+ 字符）导入过程不因对话历史过大而触发 LLM 上下文错误。
- **SC-004**: 每次导入的终端输出包含覆盖率和 pass 数量信息，用户无需查看内部日志即可了解处理进度。
- **SC-005**: 全量测试套件通过率不低于修复前基线。

---

## Assumptions

- 现有 DocumentCursor 和 read_document_range 工具架构保持不变，本 feature 在其基础上增加对话历史管理逻辑。
- 对话历史压缩的实现方式：将已处理的 read_document_range tool result 中的原始文本替换为位置摘要（如 "chars 0-3000: Redis 连接池配置相关内容"），不删除 tool call 记录。
- 覆盖率阈值默认值沿用现有 `COVERAGE_THRESHOLD = 95.0`，通过配置项暴露。
- 超出 context window 的情况在实际文档中极为罕见（技术文档通常 < 100k 字符），本 feature 处理常见情况，极端情况给出清晰提示。
- 强制覆盖机制只处理 > 500 字符的未读区间，忽略小片段（可能是格式符、空行等）。
