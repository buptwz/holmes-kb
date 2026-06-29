# Contract: CLI `holmes import --type`

**Date**: 2026-06-23

## 接口定义

```
holmes import <FILE> [OPTIONS]

OPTIONS:
  --type [pitfall]   强制指定文档类型，跳过 Classifier 判断。
                     当前仅支持 "pitfall"（路由至 DAG pipeline）。
```

## 行为契约

| 调用方式 | 行为 |
|----------|------|
| `holmes import doc.md` | 调用 Classifier，根据结果自动路由 |
| `holmes import doc.md --type pitfall` | 跳过 Classifier，直接进入 DAG pipeline |
| `holmes import doc.md --type invalid` | Click 报错退出（Choice 校验），exit code 2 |

## 参数传递链

```
CLI (force_type="pitfall")
  → ImportAgentRunner(force_type="pitfall")
    → ThreePhaseImportPipeline(force_type="pitfall")
      → pipeline.run() 检查 self.force_type == "pitfall"
        → _run_dag_pipeline(source_text, file_path)
```

## 稳定性保证

- `--type pitfall` 是 M3 新增接口，**M4 前会抛 NotImplementedError**，属预期行为
- 不带 `--type` 的现有调用行为不变（向后兼容）
- `--type guideline` / `--type model` 等旧用法在 M3 后不再被 Click 接受
