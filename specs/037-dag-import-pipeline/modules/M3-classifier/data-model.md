# Data Model: M3 — Classifier 路由

**Date**: 2026-06-23

## 概述

M3 是纯路由模块，**不引入任何新实体、新字段或新存储**。所有改动发生在控制流层面。

## 受影响的现有实体

### ThreePhaseImportPipeline（改动）

| 属性/方法 | 类型 | 变更 |
|-----------|------|------|
| `force_type` | `Optional[str]` | 已有，无改动 |
| `dry_run` | `bool` | 已有，无改动 |
| `no_interactive` | `bool` | 已有，无改动 |
| `_run_dag_pipeline()` | method | **新增**（M3 stub） |
| `run()` | method | **修改**：新增两处路由分叉 |

### CLI import 命令（改动）

| 参数 | 旧值 | 新值 |
|------|------|------|
| `--type` 变量名 | `kb_type` | `force_type` |
| `--type` 类型约束 | `str`（任意） | `click.Choice(["pitfall"])` |
| `--type` help | 无 | `"强制指定文档类型，跳过 Classifier 判断。"` |

## 路由状态机

```
pipeline.run(source_text, file_path)
    │
    ├─ force_type == "pitfall"?
    │       ├─ YES → _run_dag_pipeline()  [raises NotImplementedError in M3]
    │       └─ NO  → DocumentClassifier.classify()
    │                       │
    │                       ├─ non_kb + !force → return report (skip)
    │                       ├─ single_incident → _run_dag_pipeline()
    │                       ├─ multi_incident  → print warning → _run_dag_pipeline()
    │                       └─ runbook / guideline → existing pipeline (Reader→Extractor→Phase3)
```

## 验证规则

- `_run_dag_pipeline()` 的返回类型为 `ImportReport`（M4 实现时须遵守）
- M3 中 `_run_dag_pipeline()` 必须 raise `NotImplementedError("DAG pipeline (M4)")`
- `force_type == "pitfall"` 路径不调用 `DocumentClassifier`（可通过测试验证 mock 未被调用）
