# Feature 037 — 施工路线图

## 蓝图位置

`specs/037-dag-import-pipeline/blueprint.md` — 完整设计文档，所有模块 brief 均以此为权威来源。

## 代码库位置

```
/home/wangzhi/project/projectTmp/holmes/holmes/
  kb/                        ← Python 包根目录（所有改动在此）
    holmes/
      config.py              ← HolmesConfig
      cli.py                 ← Click CLI 入口
      kb/
        schema.py            ← KB 类型定义
        store.py             ← entry 读写层
        search.py            ← 关键词搜索
        importer.py          ← import pipeline 入口
        linter.py            ← KB lint 规则
        agent/
          pipeline.py        ← ThreePhaseImportPipeline
          phases/
            classifier.py    ← 文档类型分类
      mcp/
        server.py            ← MCP server
        tools.py             ← MCP tool handlers
```

## 模块执行顺序

```
阶段一（可并行）          阶段二（顺序）    阶段三（顺序）    阶段四
────────────────          ──────────────    ──────────────    ──────
M1  基础字段与过滤    →   M2  去重检测  →  M3  Classifier →  M6b  树级联 approve
M7  kb delete 垃圾箱      M6a 基础 approve  M4  Agent 1
M8  可观测性与日志                          M5  Agent 2
M9  MCP 接口
```

## 各模块一览

| 模块 | brief 位置 | 依赖 | 体量 | 无 LLM |
|---|---|---|---|---|
| M1 | modules/M1-basic-fields/brief.md | 无 | 小 | ✓ |
| M7 | modules/M7-delete/brief.md | 无 | 小 | ✓ |
| M8 | modules/M8-logging/brief.md | 无 | 小 | ✓ |
| M9 | modules/M9-mcp/brief.md | M1、M8 | 小 | ✓ |
| M2 | modules/M2-dedup/brief.md | M1 | 中 | ✓ |
| M6a | modules/M6a-approve-base/brief.md | M1、M2 | 中 | ✓ |
| M3 | modules/M3-classifier/brief.md | 无 | 小 | ✓ |
| M4 | modules/M4-agent1/brief.md | M3 | **大** | ✗ |
| M5 | modules/M5-agent2/brief.md | M4 | 大 | ✗ |
| M6b | modules/M6b-approve-tree/brief.md | M5、M6a | 中 | ✓ |

## 每个模块的执行方式

进入对应模块目录，按以下 speckit 流程操作：

```
cd specs/037-dag-import-pipeline/modules/<模块>/
/speckit-specify    # 从 brief.md 提取功能描述，生成 spec.md
/speckit-plan       # 生成实现方案 plan.md
/speckit-tasks      # 生成任务列表 tasks.md
/speckit-implement  # 按任务逐步实现
/speckit-analyze    # 完成后一致性检查
```
