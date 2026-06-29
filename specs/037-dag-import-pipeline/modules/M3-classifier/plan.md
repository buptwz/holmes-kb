# Implementation Plan: M3 — Classifier 路由

**Branch**: `dev-M3` | **Date**: 2026-06-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/037-dag-import-pipeline/modules/M3-classifier/spec.md`

## Summary

在 `ThreePhaseImportPipeline.run()` 中新增 DAG pipeline 路由分支：当 `force_type == "pitfall"` 时跳过 Classifier，当 Classifier 返回 `single_incident`/`multi_incident` 时路由到 `_run_dag_pipeline()`（M3 建立 stub，M4 填充）。同时为 `holmes import` CLI 新增 `--type pitfall` 参数（`click.Choice(["pitfall"])`）。改动量极小：2 个生产文件 + 1 个现有测试文件 + 1 个新测试文件。

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Click 8.x（CLI）、holmes.kb.agent.pipeline、holmes.kb.agent.phases.classifier（均已存在）

**Storage**: N/A（纯路由逻辑，无新数据存储）

**Testing**: pytest

**Target Platform**: Linux CLI

**Project Type**: CLI tool（Python Click）

**Performance Goals**: `--type pitfall` 时 Classifier LLM 调用次数 = 0

**Constraints**: 非 pitfall 类型的现有 pipeline 行为零改动；`_run_dag_pipeline()` 在 M3 只是 stub

**Scale/Scope**: 极小 — 2 个生产文件改动，1 个现有测试更新，1 个新测试文件

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 评估 | 结论 |
|------|------|------|
| 开闭原则 | `ThreePhaseImportPipeline` 通过新增方法扩展，现有 `_run_extraction_loop()` 不动 | ✓ Pass |
| 单一职责 | `_run_dag_pipeline()` 独立方法，路由逻辑与执行逻辑分离 | ✓ Pass |
| 渐进式实现 | M3 只建 stub（NotImplementedError），不做超前抽象 | ✓ Pass |
| 验证原则 | 新增专项测试文件 `test_pipeline_m3_routing.py`，覆盖所有路由分支 | ✓ Pass |
| 可观测性 | `report.phase_traces` 已记录 Classifier 结果；`--type pitfall` 路径无 Classifier trace（符合预期） | ✓ Pass |

**Constitution Check 结论**: 无违规，可进入 Phase 1。

## Project Structure

### Documentation (this feature)

```text
specs/037-dag-import-pipeline/modules/M3-classifier/
├── brief.md             # 需求说明（原始输入）
├── spec.md              # 功能规格（/speckit-specify 输出）
├── plan.md              # 本文件（/speckit-plan 输出）
├── research.md          # Phase 0 研究结果
├── data-model.md        # Phase 1 数据模型（本模块无新实体，简化版）
├── contracts/           # Phase 1 CLI 接口契约
└── tasks.md             # Phase 2 输出（/speckit-tasks 生成）
```

### Source Code (repository root)

```text
kb/holmes/
├── cli.py                          # 修改：--type 选项改为 click.Choice(["pitfall"])
└── kb/agent/
    └── pipeline.py                 # 修改：新增路由逻辑 + _run_dag_pipeline() stub

kb/tests/
├── test_pipeline.py                # 修改：添加 autouse fixture 避免路由冲突
└── test_pipeline_m3_routing.py     # 新建：M3 路由专项测试（15 个测试用例）
```

**Structure Decision**: 单项目结构，改动集中在 `pipeline.py` 和 `cli.py`，新增测试文件与现有测试并列。

## Complexity Tracking

无 Constitution 违规，本表留空。
