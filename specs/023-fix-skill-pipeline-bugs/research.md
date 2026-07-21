# Research: Import Pipeline v3 回归缺陷修复

**Date**: 2026-06-10 | **Feature**: 023-fix-skill-pipeline-bugs

## 结论：无未解决的 NEEDS CLARIFICATION

所有三个缺陷的根因均已通过代码审查确认。以下记录各决策及其依据。

---

## Decision 1: 编号步骤过滤模式

**Decision**: 使用正则 `^\d+[.)]\s` 过滤编号步骤行。

**Rationale**:
- 目标模式：`1. 说明文字`、`2) 说明文字`（数字 + `.` 或 `)` + 空格）
- 中文故障文档中最常见的编号格式
- 不扩展到字母序号（`a.`、`A)`），避免误过滤 `a.out`、`A.txt` 等合法命令参数

**Alternatives considered**:
- 过滤所有非 ASCII 开头的行：范围过宽，会误过滤合法的中文命令注释
- 要求 LLM 在 prompt 中显式标注步骤与命令：依赖 LLM 遵守格式，已被证明不可靠（QA-18 根因）
- 在写入 run.sh 时进行 bash 语法预检（`bash -n`）并过滤失败行：正确但工程复杂度高，当前修复不需要

**Source**: `kb/holmes/kb/skill/manager.py:61-79` 代码审查；`holmes-regression-report-v1.md` QA-18 现象分析。

---

## Decision 2: Pipeline Prompt 修正方式

**Decision**: 直接修改 `pipeline.py` user_prompt 中的错误指令，将 `write_kb_entry with update=True` 改为 `update_kb_entry with entry_id ... and patch`。

**Rationale**:
- 根因是 prompt 中工具名写错：`write_kb_entry` 无 `update` 参数，LLM 永远不会调用 `update_kb_entry`
- 最小改动：只改 prompt 字符串，不改任何工具 schema 或执行逻辑
- `update_kb_entry` 工具 schema 已完整定义（`entry_id: str, patch: object`），LLM 能正确调用

**Alternatives considered**:
- 给 `write_kb_entry` 增加 `update` 参数并在内部路由到 `update_kb_entry`：引入工具职责混乱，违反接口隔离原则
- 完全重写 dedup 逻辑：范围过大，超出本次修复目标

**Source**: `kb/holmes/kb/agent/pipeline.py:293-301` + `kb/holmes/kb/agent/tools.py:669-680` schema 对比审查。

---

## Decision 3: TC-S-02 修复策略

**Decision**: 在 `runner.py` 中新增 `_updated_entry_ids: set[str]`，`update_kb_entry` 成功时记录 entry_id；在 `_finalize_skill_generation()` 末尾追加 update 路径的 skill 评估（仅写 suggestion，不自动创建 Skill）。

**Rationale**:
- `_finalize_skill_generation` 的职责是"兜底 skill 评估"（防止 LLM 漏调 evaluate_skill），update 路径应受相同保护
- update 路径只输出 OPTIONAL suggestion，不自动创建 Skill：因为 entry 已存在，Skill 可能已创建；由 SkillAdvisor 的命令数量判断决定 OPTIONAL vs RECOMMENDED，与 create 路径逻辑一致
- 读取更新后 entry 内容用于 skill 评估：通过 `list_entries(kb_root)` 找到 entry_id 对应文件，读取完整 `.md` 内容（工具层已有此逻辑，直接复用）
- 已有 `_skill_evaluated_entries` 去重机制：防止 LLM 已评估的条目被 finalize 重复触发

**Alternatives considered**:
- 在 `update_kb_entry` 成功时同步触发 skill 评估：会在工具结果处理循环内嵌套 skill 逻辑，耦合性高
- 修改 LLM prompt 要求其在 update 后也调用 evaluate_skill：依赖 LLM 遵守格式，可靠性低
- 将 `_updated_entry_ids` 改为 `_updated_entry_contents`（存储内容）：可以，但每次 update 后读文件更准确（包含 update 后的最新内容）

**Source**: `kb/holmes/kb/agent/runner.py:473-508` + `:294-336` 代码审查；`holmes-regression-report-v1.md` TC-S-02 根因分析。
