# Feature Specification: M3 — Classifier 路由

**Feature Branch**: `dev-M3`

**Created**: 2026-06-23

**Status**: Draft

**Input**: M3 模块 — 在 ThreePhaseImportPipeline 中新增 DAG pipeline 路由分支，以及 `holmes import --type pitfall` CLI 参数。

## User Scenarios & Testing *(mandatory)*

### User Story 1 — 强制走 DAG pipeline（Priority: P1）

工程师发现一篇已知的 pitfall 文档，希望直接进入 DAG import 流程而跳过分类器判断。

**Why this priority**: `--type pitfall` 是 DAG pipeline 的主入口，其他所有路径都依赖该路由工作正常。

**Independent Test**: 可通过 `holmes import doc.md --type pitfall` 单独测试；只要该命令触发 DAG pipeline 即为成功（M4 前以 NotImplementedError 表示）。

**Acceptance Scenarios**:

1. **Given** 工程师有一篇 pitfall 文档, **When** 执行 `holmes import doc.md --type pitfall`, **Then** 跳过 Classifier 调用，直接进入 `_run_dag_pipeline()`
2. **Given** `--type pitfall` 已指定, **When** pipeline 执行, **Then** `DocumentClassifier.classify()` 不被调用
3. **Given** M4 尚未实现, **When** `_run_dag_pipeline()` 被调用, **Then** 抛出 `NotImplementedError("DAG pipeline (M4)")`

---

### User Story 2 — Classifier 自动路由至 DAG pipeline（Priority: P2）

工程师未指定 `--type`，但文档被 Classifier 识别为 `single_incident` 或 `multi_incident` 类型时，自动进入 DAG pipeline。

**Why this priority**: 自动路由是最常见的使用路径，无需用户显式指定类型。

**Independent Test**: 通过 mock Classifier 返回 `single_incident` / `multi_incident`，验证 pipeline 进入 DAG 路径。

**Acceptance Scenarios**:

1. **Given** Classifier 返回 `single_incident`, **When** `pipeline.run()` 执行, **Then** 调用 `_run_dag_pipeline()`，不调用 Reader/Extractor
2. **Given** Classifier 返回 `multi_incident`, **When** `pipeline.run()` 执行, **Then** 调用 `_run_dag_pipeline()` 并打印警告："建议拆分为独立文档分别导入"
3. **Given** Classifier 返回 `runbook` / `guideline` / `non_kb`, **When** `pipeline.run()` 执行, **Then** 继续走现有 Reader → Extractor → Phase3 pipeline，不触发 DAG 路径

---

### User Story 3 — `_run_dag_pipeline()` 框架具备正确签名（Priority: P3）

M4 开发者能够在 `_run_dag_pipeline()` 中访问 `self.dry_run`、`self.no_interactive` 等参数，无需修改方法签名。

**Why this priority**: M4 必须在 M3 搭建的框架上填充实现，签名正确性是前提。

**Independent Test**: 通过检查方法签名及访问 `self.dry_run`/`self.no_interactive` 验证。

**Acceptance Scenarios**:

1. **Given** pipeline 以 `dry_run=True` 创建, **When** `_run_dag_pipeline()` 被调用, **Then** `self.dry_run` 为 `True`（可从方法内访问）
2. **Given** pipeline 以 `no_interactive=True` 创建, **When** `_run_dag_pipeline()` 被调用, **Then** `self.no_interactive` 为 `True`

---

### Edge Cases

- 当 `force_type == "pitfall"` 时，Classifier 完全不调用（不消耗 LLM token）
- `multi_incident` 警告只打印一次，不阻断流程
- `non_kb` 类型仍走现有的 non_kb 处理逻辑（早期返回），不进入 DAG 路由判断
- `dry_run` 与 `--type pitfall` 同时使用时，正确进入 `_run_dag_pipeline()`（M4 负责处理 dry_run 语义）

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: CLI MUST 支持 `holmes import <file> --type pitfall` 参数，参数值仅限 `pitfall`（`click.Choice(["pitfall"])`）
- **FR-002**: 当 `force_type == "pitfall"` 时，pipeline MUST 跳过 Classifier，直接调用 `_run_dag_pipeline()`
- **FR-003**: 当 Classifier 返回 `single_incident` 或 `multi_incident` 时，pipeline MUST 调用 `_run_dag_pipeline()`
- **FR-004**: 当 Classifier 返回 `multi_incident` 时，MUST 打印警告："建议拆分为独立文档分别导入"
- **FR-005**: `_run_dag_pipeline(self, source_text, file_path)` MUST 存在于 `ThreePhaseImportPipeline` 类中，在 M3 阶段 `raise NotImplementedError("DAG pipeline (M4)")`
- **FR-006**: `_run_dag_pipeline()` MUST 通过 `self.dry_run` / `self.no_interactive` 访问参数（供 M4 使用）
- **FR-007**: `runbook / guideline / non_kb` 等非 pitfall 类型 MUST 继续走现有 pipeline，无任何行为变化

### Key Entities

- **DocumentType**: 枚举值 `single_incident`, `multi_incident`, `runbook`, `guideline`, `non_kb`（已有）
- **ThreePhaseImportPipeline**: 新增 `_run_dag_pipeline()` 方法（M3 框架，M4 实现）
- **ImportAgentRunner**: `force_type` 参数已存在，透传至 pipeline（无需修改）

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `holmes import doc.md --type pitfall` 执行后，Classifier 的 LLM 调用次数为 0
- **SC-002**: 所有 non-pitfall 文档类型（runbook / guideline / non_kb）的现有测试通过率保持 100%
- **SC-003**: 新增单元测试覆盖所有 5 种路由分支（single_incident / multi_incident / runbook / guideline / non_kb）及 `--type pitfall` 强制路由
- **SC-004**: `multi_incident` 警告消息仅出现 1 次，不重复打印

## Assumptions

- 现有 `DocumentClassifier` 和 `DocumentType` 枚举无需修改（M3 零改动）
- `force_type` 参数已在 `ThreePhaseImportPipeline.__init__` 和 `ImportAgentRunner` 中存在，无需新增
- `_run_dag_pipeline()` 框架在 M3 中只需 `raise NotImplementedError`，M4 负责完整实现
- CLI 的 `--type` 参数从接受任意字符串改为 `click.Choice(["pitfall"])`（Breaking change：原 `--type guideline` 等用法不再支持，但实际未被文档化使用）
- 去重检测（Step 0）发生在 Classifier 和 DAG 路由之前，M3 不影响其逻辑
