# M3 — Classifier 路由

## 项目与代码库背景

**Holmes KB** 是一个 Python CLI 工具，用 Click 框架实现，管理工程团队的 Markdown 知识库。

- 代码库根：`/home/wangzhi/project/projectTmp/holmes/holmes/kb/`
- 配置文件：`~/.holmes/config.json`（api_key / api_base_url / model / username）

## 必读参考文档（实现前全部通读）

### 1. 施工蓝图（最重要，逐字阅读）
`/home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/blueprint.md`

**必须全部读完的章节**：

- `§ 适用范围`
  - 本流程仅适用于 pitfall 类型（故障排查链路）
  - `single_incident` 或 `multi_incident` 走 DAG 流程
  - 其他类型（`runbook / guideline / model / decision`）继续走现有 Reader → Extractor 流程
  - `non_kb` → 跳过

- `§ Step 1：Classifier`（全节）
  - 单次 LLM 调用，判断文档类型
  - `single_incident` → 走 DAG 流程
  - `multi_incident` → 走 DAG 流程 + 输出 warning："建议拆分为独立文档分别导入"
  - `runbook / guideline / model / decision` → 切换到现有 pipeline
  - `non_kb` → 跳过

- `§ 整体流程`：理解 Step 1 在整个 pipeline 中的位置（Step 0 去重之后，Step 2 Agent 1 之前）

- `§ 与现有 Pipeline 的关系`：两条流程共存结构
  ```
  现有流程（保留，用于非 pitfall 类型）：
    Classifier → Reader → Extractor → Normalizer → Phase 3 → Pending

  新流程（pitfall 类型）：
    Classifier → 去重检测 → Agent 1（DAG 提取）→ DAG 确认 → Agent 2（双源生成）→ Pending
  ```

- `§ CLI 兼容性`
  - `holmes import --type pitfall`：强制走 DAG pipeline，跳过 Classifier 判断

### 2. 知乎 KB 数据模型
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/kb-data-model.md`

了解 §1 文件系统布局（理解 pitfall / model / guideline / process / decision 各类型的目录结构）、§2 Entry Frontmatter 字段（了解 `type` 字段的合法值）。

### 3. 开发者指南
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/developer-guide.md`

了解项目架构（Python 包结构、pipeline 模块位置、测试约定）。

## 涉及的现有代码（实现前全部通读）

```
kb/holmes/kb/agent/phases/classifier.py  # DocumentType 枚举（single_incident / multi_incident /
                                          # runbook / guideline / model / decision / non_kb）
                                          # DocumentClassifier 类和分类逻辑
                                          # M3 不修改分类逻辑，只新增路由分支
kb/holmes/kb/agent/pipeline.py           # ThreePhaseImportPipeline 类
                                          # 重点：run() 方法中现有 Classifier 调用位置和路由逻辑
                                          # _run_dag_pipeline() 框架（M3 建立框架，M4 填充实现）
kb/holmes/cli.py                         # holmes import 子命令参数定义
                                          # 了解 --force / --dry-run / --resume 等现有参数
```

相关测试文件（理解现有测试覆盖范围）：
```
kb/tests/test_pipeline.py        # pipeline 路由测试，了解现有测试模式
kb/tests/test_classifier.py      # DocumentClassifier 测试（若存在）
```

## 前置依赖

无。本模块独立，改动量小，**但 M4 必须等 M3 完成**（M4 填充 `_run_dag_pipeline()` 框架）。

## 本模块目标

1. 新增 `holmes import --type pitfall` flag：强制走 DAG pipeline，跳过 Classifier 判断
2. `pipeline.py` 中 Classifier 返回 `single_incident` / `multi_incident` 时路由到 DAG pipeline
3. `multi_incident` 时额外打印 warning："建议拆分为独立文档分别导入"
4. 搭建 `_run_dag_pipeline()` 框架（内部 `raise NotImplementedError`，M4 填充）

## 主要改动清单

### pipeline.py
在 `run()` 方法的 Classifier 调用之后，新增路由判断：

```python
if force_type == "pitfall" or result.doc_type in (
    DocumentType.single_incident,
    DocumentType.multi_incident
):
    if result.doc_type == DocumentType.multi_incident:
        print("⚠ 警告：文档包含多个独立事件，建议拆分为独立文档分别导入。"
              "（当前流程不阻断，将生成多棵独立排查树）")
    return self._run_dag_pipeline(source_text, file_path)  # M4 实现
else:
    return self._run_existing_pipeline(source_text, file_path)  # 现有流程

def _run_dag_pipeline(self, source_text: str, file_path: Path):
    """DAG pipeline 框架。M3 先放 NotImplementedError，M4 完整实现。"""
    raise NotImplementedError("DAG pipeline (M4)")
```

### cli.py
`holmes import` 子命令新增参数：
```python
@click.option(
    "--type", "force_type",
    type=click.Choice(["pitfall"]),
    default=None,
    help="强制指定文档类型，跳过 Classifier 判断。"
)
```

将 `force_type` 传入 `pipeline.run()`（或 `ThreePhaseImportPipeline.__init__`），让路由判断可以使用该值。

## 关键设计细节

### DocumentType 枚举值（现有 classifier.py）
```python
class DocumentType(str, Enum):
    single_incident = "single_incident"
    multi_incident  = "multi_incident"
    runbook         = "runbook"
    guideline       = "guideline"
    model           = "model"
    decision        = "decision"
    non_kb          = "non_kb"
```

### multi_incident 的特殊语义
Agent 1 对 multi_incident 文档可能产生多个不相连的子树（多个根节点），这是蓝图允许的合法输出（output_dag 校验允许多个根节点）。M3 只需打印 warning，不阻断流程。Agent 1 的 harness 层由 M4 处理。

### 非 pitfall 类型不改变
`runbook / guideline / model / decision / non_kb` 继续走现有 `_run_existing_pipeline()`，M3 零改动。

## 验收条件

- [ ] `holmes import doc.md --type pitfall` 跳过 Classifier，直接进 DAG pipeline 路径
- [ ] 不带 `--type` 时，Classifier 返回 `single_incident` → 进 DAG pipeline 路径
- [ ] Classifier 返回 `multi_incident` → 进 DAG pipeline 路径 + 打印 warning
- [ ] Classifier 返回 `runbook / guideline / model / decision / non_kb` → 继续走现有 pipeline，不变
- [ ] `_run_dag_pipeline()` 框架已建立（`NotImplementedError`，M4 填充）
- [ ] 有单元测试：各文档类型路由正确性；`--type pitfall` 强制路由

## 执行步骤

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/modules/M3-classifier/
/speckit-specify
/speckit-plan
/speckit-tasks
/speckit-implement
/speckit-analyze
```

**实现前务必**：读完 `classifier.py` 中的 `DocumentType` 枚举和分类逻辑，读完 `pipeline.py` 中的 `run()` 方法结构，理解现有路由位置，再动手新增分支。
