# Tasks: M3 — Classifier 路由

**Input**: Design documents from `specs/037-dag-import-pipeline/modules/M3-classifier/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓

**Organization**: 任务按 User Story 分组，每组独立可测试。改动量极小（2 个生产文件 + 1 个现有测试更新 + 1 个新测试文件）。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖关系）
- **[Story]**: 对应 spec.md 中的 User Story（US1/US2/US3）
- 每个任务包含精确文件路径

---

## Phase 1: Setup（理解现有代码）

**Purpose**: 通读需改动的现有代码，确认路由插入点

- [x] T001 通读 `kb/holmes/kb/agent/pipeline.py`：定位 `run()` 方法中 Classifier 调用位置（line ~172）及 non_kb 处理块结束位置（line ~190），记录两处插入点
- [x] T002 通读 `kb/holmes/kb/agent/phases/classifier.py`：确认 `DocumentType` 枚举值（single_incident / multi_incident / runbook / guideline / non_kb）
- [x] T003 [P] 通读 `kb/holmes/cli.py`：定位 `import_cmd` 中 `--type` 选项定义（line ~227）及 `_make_runner()` 中 `force_type=kb_type` 传参位置

---

## Phase 2: Foundational（建立 DAG pipeline stub）

**Purpose**: 新增 `_run_dag_pipeline()` 方法——这是 US1、US2、US3 共同依赖的基础接口

**⚠️ CRITICAL**: US1、US2、US3 的路由代码都必须 return `_run_dag_pipeline()`，本阶段必须先完成

- [x] T004 在 `kb/holmes/kb/agent/pipeline.py` 的 `ThreePhaseImportPipeline` 类中，在 `_run_intra_import_dedup()` 和 `_run_extraction_loop()` 之间新增 `_run_dag_pipeline(self, source_text: str, file_path: Optional[Path] = None) -> "ImportReport"` 方法，方法体为 `raise NotImplementedError("DAG pipeline (M4)")`，附完整 docstring 说明 dry_run / no_interactive 通过 self 访问

**Checkpoint**: `_run_dag_pipeline()` 存在且可被调用（抛 NotImplementedError）

---

## Phase 3: User Story 1 — 强制走 DAG pipeline（Priority: P1）🎯 MVP

**Goal**: `holmes import <file> --type pitfall` 跳过 Classifier，直接进入 `_run_dag_pipeline()`

**Independent Test**: `holmes import doc.md --type pitfall` → 触发 NotImplementedError，且 Classifier mock 未被调用

### Tests for User Story 1

- [x] T005 [US1] 在 `kb/tests/test_pipeline_m3_routing.py` 中新建测试文件，创建 `TestForcePitfallBypassesClassifier` 类，包含三个测试：
  - `test_classifier_not_called_when_force_type_pitfall`：patch `_run_dag_pipeline` 和 `DocumentClassifier`，断言 dag called、classifier not called
  - `test_dag_receives_source_text`：验证 `_run_dag_pipeline` 接收到原始 source_text
  - `test_dag_receives_file_path`：验证 `_run_dag_pipeline` 接收到 file_path

### Implementation for User Story 1

- [x] T006 [US1] 在 `kb/holmes/cli.py` 的 `import_cmd` decorator 中，将 `@click.option("--type", "kb_type", default=None)` 替换为带 `type=click.Choice(["pitfall"])` 和 help 文本的新声明，参数名改为 `force_type`；同步更新函数签名（`kb_type` → `force_type`）及 `_make_runner()` 内的 `force_type=force_type`
- [x] T007 [US1] 在 `kb/holmes/kb/agent/pipeline.py` 的 `run()` 方法中，在 ctx 字典构建完成之后、Classifier 注释块之前，插入 `if self.force_type == "pitfall": return self._run_dag_pipeline(source_text, file_path)` 分支

**Checkpoint**: `test_pipeline_m3_routing.py::TestForcePitfallBypassesClassifier` 全部通过（3/3）

---

## Phase 4: User Story 2 — Classifier 自动路由（Priority: P2）

**Goal**: Classifier 返回 single_incident / multi_incident 时自动进入 DAG pipeline；multi_incident 打印警告

**Independent Test**: mock Classifier 返回各类型，断言 DAG pipeline 被/未被调用；multi_incident 时 capsys 捕获警告文本

### Tests for User Story 2

- [x] T008 [US2] 在 `kb/tests/test_pipeline_m3_routing.py` 中新增 `TestSingleIncidentRouting` 类（2 个测试：`test_single_incident_calls_dag_pipeline`、`test_single_incident_no_warning_printed`）和 `TestMultiIncidentRouting` 类（2 个测试：`test_multi_incident_calls_dag_pipeline`、`test_multi_incident_prints_warning`）以及 `TestNonPitfallRoutesToExistingPipeline` 类（3 个 parametrize 测试：runbook、guideline、non_kb 均不触发 DAG）

### Implementation for User Story 2

- [x] T009 [US2] 在 `kb/holmes/kb/agent/pipeline.py` 的 `run()` 方法中，在 non_kb 处理块之后、`granularity_hint` 赋值之前，插入以下路由分支：
  ```python
  if classification.doc_type in (DocumentType.single_incident, DocumentType.multi_incident):
      if classification.doc_type == DocumentType.multi_incident:
          print("⚠ 警告：文档包含多个独立事件，建议拆分为独立文档分别导入。（当前流程不阻断，将生成多棵独立排查树）")
      return self._run_dag_pipeline(source_text, file_path)
  ```

**Checkpoint**: `TestSingleIncidentRouting` 和 `TestMultiIncidentRouting` 和 `TestNonPitfallRoutesToExistingPipeline` 全部通过（7/7）

---

## Phase 5: User Story 3 — _run_dag_pipeline 框架签名（Priority: P3）

**Goal**: 验证 `_run_dag_pipeline()` 通过 self 正确暴露 dry_run / no_interactive 给 M4

**Independent Test**: 直接调用 `pipeline._run_dag_pipeline(source_text)` 抛 NotImplementedError；pipeline 属性 dry_run/no_interactive 可访问

### Tests for User Story 3

- [x] T010 [P] [US3] 在 `kb/tests/test_pipeline_m3_routing.py` 中新增 `TestDagPipelineStub` 类（`test_raises_not_implemented`、`test_accepts_file_path_kwarg`）和 `TestDagPipelineParameterPropagation` 类（`test_dry_run_propagated`、`test_no_interactive_propagated`、`test_dag_called_with_dry_run_accessible`）

**Checkpoint**: `TestDagPipelineStub` 和 `TestDagPipelineParameterPropagation` 全部通过（5/5）

---

## Phase 6: Polish & 兼容性修复

**Purpose**: 修复现有测试因 M3 路由变更导致的兼容性问题，并运行完整测试套件

- [x] T011 在 `kb/tests/test_pipeline.py` 顶部添加 `from holmes.kb.agent.phases.classifier import ClassificationResult, DocumentType` import，并新增 module-level `autouse` fixture `_classifier_returns_runbook`，patch `holmes.kb.agent.pipeline.DocumentClassifier` 使其返回 runbook 类型（避免现有测试因默认 single_incident 路由至 DAG pipeline 而失败）
- [x] T012 在 `kb/tests/test_pipeline.py` 中更新 `TestForceTypeOverride::test_force_type_overrides_llm_type_in_draft`：反映 M3 新语义（`force_type='pitfall'` 路由至 DAG pipeline 而非现有 pipeline），断言 `_run_dag_pipeline` 被调用、`DocumentClassifier` 未被调用
- [x] T013 [P] 运行 `python -m pytest kb/tests/test_pipeline_m3_routing.py -v` 确认全部 15 个 M3 测试通过
- [x] T014 [P] 运行 `python -m pytest kb/tests/test_pipeline.py kb/tests/test_classifier.py -q` 确认现有测试无回归

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: 无依赖，立即开始
- **Phase 2 (Foundational)**: 依赖 Phase 1 完成
- **Phase 3 (US1)**: 依赖 Phase 2（`_run_dag_pipeline` stub 必须存在）
- **Phase 4 (US2)**: 依赖 Phase 2；可与 Phase 3 并行（不同代码区域）
- **Phase 5 (US3)**: 依赖 Phase 2；可与 Phase 3/4 并行
- **Phase 6 (Polish)**: 依赖 Phase 3、4、5 全部完成

### User Story Dependencies

- **US1 (P1)**: 依赖 T004（stub 存在）— 无需等待 US2/US3
- **US2 (P2)**: 依赖 T004（stub 存在）— 无需等待 US1/US3
- **US3 (P3)**: 依赖 T004（stub 存在）— 无需等待 US1/US2

### Within Each User Story

- Tests（T005、T008、T010）先写，确认逻辑后再实现
- Implementation（T006/T007、T009）在测试框架建好后实现
- 每个 Checkpoint 验证该 Story 独立可测

### Parallel Opportunities

- T001、T002、T003 可并行（不同文件，只读）
- T005、T008、T010 可并行（不同测试类，同一新文件但不冲突）
- T013、T014 可并行（不同测试文件）
- Phase 3、Phase 4、Phase 5 的 Implementation 任务在 Phase 2 完成后可并行

---

## Parallel Example: 单人执行最优顺序

```
顺序执行: T001 → T002 → T003 → T004
  然后并行: T005 | T008 | T010  (写测试框架)
  然后顺序: T006 → T007 (US1 实现)
  然后顺序: T009 (US2 实现)
  然后顺序: T011 → T012 (修复现有测试)
  最后并行: T013 | T014 (验证)
```

---

## Implementation Strategy

### MVP First（US1 Only）

1. 完成 Phase 1: Setup（T001-T003）
2. 完成 Phase 2: Foundational（T004）
3. 完成 Phase 3: US1（T005-T007）
4. **STOP and VALIDATE**: `test_pipeline_m3_routing.py::TestForcePitfallBypassesClassifier` 全部通过
5. 继续 US2、US3

### Incremental Delivery

1. T001-T004 → 框架就绪
2. T005-T007 → `--type pitfall` 可用（MVP）
3. T008-T009 → 自动路由可用
4. T010 → 签名验证完整
5. T011-T014 → 全量测试绿色

---

## Notes

- [P] 任务 = 不同文件或独立逻辑，无依赖冲突
- 每个 Checkpoint 后验证对应 User Story 独立可用
- M4 开发者可直接在 `_run_dag_pipeline()` 中填充实现，无需修改签名
- 避免：在 M3 中添加任何 M4 相关的实现逻辑
