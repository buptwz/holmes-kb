# Research: M3 — Classifier 路由

**Date**: 2026-06-23

## 研究结论

### R-001: `force_type == "pitfall"` 的插入点

**Decision**: 在 `ctx` 字典构建完毕之后、Classifier 调用之前插入 bypass 判断

**Rationale**:
- 去重检测（Step 0，lines 110-150）必须先于 Classifier 执行，M3 不动
- `ctx` 构建（lines 152-167）须在 bypass 之前完成，确保 `report` 已初始化
- Classifier 调用点（line 172）是路由分叉的天然位置
- 早期 bypass 避免了 Classifier LLM 调用（FR-001 满足）

**Alternatives considered**: 在 `__init__` 中存储 `force_type` 并在 `run()` 入口处立即跳转 → 会跳过 dedup 检测，与 Step 0 设计冲突，拒绝。

---

### R-002: `single_incident`/`multi_incident` 路由的插入点

**Decision**: 在 non_kb 检测块之后、`granularity_hint` 赋值之前插入路由判断

**Rationale**:
- `non_kb` 处理块中有 `return report`（force=False 时），确保 non_kb 不会进入 DAG 路径
- `granularity_hint` 仅对现有 pipeline（Reader）有意义，DAG pipeline 不需要
- 将路由判断放在此处，非 pitfall 类型自然继续执行现有逻辑，零改动

**Alternatives considered**: 在 Classifier 调用前用 `doc_type` 检查 → 无法获取 doc_type（还未调用 Classifier），不可行。

---

### R-003: `_run_dag_pipeline()` 签名设计

**Decision**: `def _run_dag_pipeline(self, source_text: str, file_path: Optional[Path] = None) -> ImportReport`

**Rationale**:
- `dry_run`、`no_interactive`、`force_type` 等参数通过 `self` 访问，避免重复参数列表
- 与 `_run_extraction_loop()` 风格一致（内部方法，不在接口上暴露 ctx）
- M4 可在方法体内自由访问所有 pipeline 状态，签名不需要修改

---

### R-004: 现有测试的兼容性处理

**Decision**: 在 `test_pipeline.py` 中添加 module-level `autouse` fixture，patch Classifier 返回 `runbook`

**Rationale**:
- 现有测试使用 noop provider，Classifier 因 JSON 解析失败默认返回 `single_incident`
- M3 后 `single_incident` 路由至 `_run_dag_pipeline()`（NotImplementedError），导致所有现有测试失败
- `autouse` fixture 是最小改动方案（只加一个 fixture + 两行 import），不修改任何测试逻辑
- 现有 `TestForceTypeOverride::test_force_type_overrides_llm_type_in_draft` 测试 `force_type='pitfall'` 的行为，M3 后语义变更（进 DAG pipeline），需更新断言

---

### R-005: CLI `--type` 选项的修改范围

**Decision**: 将 `--type` 从任意字符串改为 `click.Choice(["pitfall"])`，参数名从 `kb_type` 改为 `force_type`

**Rationale**:
- 原 `kb_type` 语义是"覆盖 LLM 判断的类型"，现在的语义是"强制走 DAG pipeline"，名称应反映新语义
- `click.Choice(["pitfall"])` 提供内置参数验证和 help 文档生成
- 原 `--type guideline` 等用法在现有文档中无记录，被视为未公开特性，Breaking change 风险低
- `force_type` 参数名与 pipeline/runner 内部一致，减少名称映射

**Alternatives considered**: 新增独立 `--force-pitfall` flag → 增加 CLI 复杂度，与原设计 `--type pitfall` 不一致，拒绝。
