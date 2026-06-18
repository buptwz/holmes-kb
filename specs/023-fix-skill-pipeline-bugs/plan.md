# Implementation Plan: Import Pipeline v3 回归缺陷修复

**Branch**: `023-fix-skill-pipeline-bugs` | **Date**: 2026-06-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/023-fix-skill-pipeline-bugs/spec.md`

## Summary

修复回归测试报告 v1（`holmes-regression-report-v1.md`）中三个未修复的缺陷：

1. **P0 QA-18 裸文本崩溃**：`_extract_code_block_lines()` 未过滤编号步骤行（`1. 步骤说明`），导致此类行被写入 run.sh，在 `set -euo pipefail` 下运行时崩溃。
2. **P1 TC-D-02 语义去重 UPDATE 路径失效**：pipeline.py 的 system prompt 指示 LLM "call write_kb_entry with update=True"，但 `write_kb_entry` 工具 schema 无 `update` 参数，LLM 永远无法调用真正的 `update_kb_entry`，同根因文档始终走 create 路径。
3. **P2 TC-S-02 OPTIONAL Skill 候选提示缺失**：`_finalize_skill_generation()` 仅处理 `_created_entry_contents`，`update_kb_entry` 路径不填充该字典，导致更新路径永远不触发 OPTIONAL Skill 候选提示。

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: anthropic / openai (LLM provider), frontmatter, click, pytest

**Storage**: 文件系统 KB（`.md` 文件 + pending/ 目录）

**Testing**: pytest（当前基线 680 passed）

**Target Platform**: Linux CLI

**Project Type**: CLI tool / library (`kb/` Python 包)

**Performance Goals**: 单测运行时间 < 30s

**Constraints**: 新增测试不依赖真实 LLM；不改变现有通过测试的行为

**Scale/Scope**: 三处局部 bug 修复，各自独立，不涉及架构变更

## Constitution Check

*GATE: 修改前评估，修改后复评。*

| 原则 | 评估 | 备注 |
|------|------|------|
| 开闭原则 | ✅ | 在现有过滤链中追加条件，不改变接口 |
| 单一职责 | ✅ | 各修复只改对应职责模块 |
| 严禁特定场景修复 | ✅ | US1 改的是正则规则（通用）；US2 改的是 prompt 准确性（根因）；US3 改的是 finalize 逻辑覆盖（根因） |
| 验证原则 | ✅ | 每个 US 均补充自动化单测 |
| 渐进式实现 | ✅ | 最小改动，不引入新抽象 |
| 可观测性 | ✅ | 现有日志结构不变；update 路径现有 trace 记录保持 |

**Constitution Check POST-DESIGN**：所有原则通过，无需 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/023-fix-skill-pipeline-bugs/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (by /speckit-tasks)
```

### Source Code (修改范围)

```text
kb/
├── holmes/kb/skill/manager.py          # US1: _extract_code_block_lines() 过滤规则
├── holmes/kb/agent/pipeline.py         # US2: system prompt 更正
├── holmes/kb/agent/runner.py           # US3: _finalize_skill_generation() 更新路径覆盖
└── tests/
    ├── test_skill_manager.py           # US1 新增测试
    ├── test_pipeline.py                # US2 新增测试（mock LLM）
    └── test_skill_advisor.py           # US3 新增测试
```

**Structure Decision**: 纯 bug 修复，沿用现有单项目结构。

---

## US1 — Skill 脚本裸文本过滤（QA-18）

### 根因

`kb/holmes/kb/skill/manager.py` 中 `_extract_code_block_lines()` 第 77 行：

```python
if len(line) >= 5 and not line.startswith("#"):
    lines.append(line)
```

此检查不过滤 `1. 确认磁盘 I/O 瓶颈`、`2. 检查 TiKV Raft Log` 等编号步骤行，这些行被写入 run.sh 后因 `set -euo pipefail` 导致脚本崩溃。

### 修复方案

在 `_extract_code_block_lines()` 的提取循环中，在现有 `#` 注释判断之前，增加对编号步骤模式的过滤：

```python
# 在 line 77 的 len/startswith 检查之前插入
if re.match(r"^\d+[.)]\s", line):
    continue   # 跳过 "1. 步骤说明"、"2) 步骤说明" 等编号行
```

**过滤规则**：`^\d+[.)]\s`（一个或多个数字 + `.` 或 `)` + 空格）。不扩展到字母序号（`a.`、`A)`）。

**影响评估**：只影响 `_extract_code_block_lines()` 的输出；同一代码块中其余合法命令行不受影响。

### 测试方案

在 `kb/tests/test_skill_manager.py` 中新增：
- 代码块含编号步骤 + 合法命令 → 编号行被过滤，命令行保留
- 代码块只含编号步骤 → 返回空列表
- 不含编号步骤的正常代码块 → 行为不变

---

## US2 — 语义去重 UPDATE 路径（TC-D-02）

### 根因

`kb/holmes/kb/agent/pipeline.py` 中 `_build_import_agent_prompt()` / 主 user_prompt 拼接（约第 295–297 行）：

```python
f"call write_kb_entry with update=True (update existing) instead of "
f"creating a new entry.\n"
```

但 `write_kb_entry` 工具 schema 无 `update` 参数（schema 要求 `content, source_hash, confidence`），LLM 调用该 prompt 后执行的仍是 `write_kb_entry`（create 路径），且 `update=True` 被工具忽略。正确工具是 `update_kb_entry(entry_id, patch)`。

### 修复方案

将 prompt 中的错误指令改为：

```
If similarity >= 0.8 with an existing entry, call update_kb_entry with
"entry_id" set to the matching entry's ID and "patch" containing the new
content fields (at minimum include the body/resolution update). Do NOT call
write_kb_entry for this case.
```

**修改位置**：`pipeline.py` 第 295–297 行附近（`kp_drafts` 分支的 user_prompt 拼接）。

### 测试方案

在 `kb/tests/test_pipeline.py` 中新增（mock LLM，不调用真实 API）：
- Mock LLM 返回 `compare_root_cause` → similarity ≥ 0.8 → 验证 user_prompt 中包含 `update_kb_entry` 而不含 `write_kb_entry with update=True` 的错误指令
- 通过 spy 验证当 similarity ≥ 0.8 时，最终被调用的工具是 `update_kb_entry`（而非 `write_kb_entry`）

---

## US3 — OPTIONAL Skill 候选提示（TC-S-02，update 路径）

### 根因

`kb/holmes/kb/agent/runner.py` `_finalize_skill_generation()` 第 485 行：

```python
if not self._created_entry_contents:
    return
```

`update_kb_entry` 成功后（第 335 行 `report.updated.append(...)`）不填充 `_created_entry_contents`，导致 finalize 早返回，update 路径永远看不到 OPTIONAL skill 候选提示。

### 修复方案

**步骤 1**：在 `ImportAgentRunner.__init__` 中增加 `_updated_entry_ids: set[str]`。

**步骤 2**：在 `_handle_tool_result()` 的 `update_kb_entry` 成功分支（第 335 行）中：

```python
elif name == "update_kb_entry" and result.get("success") and not self.dry_run:
    entry_id = str(tool_input.get("entry_id", "unknown"))
    report.updated.append(entry_id)
    self._updated_entry_ids.add(entry_id)     # 新增：记录被更新的条目
```

**步骤 3**：在 `_finalize_skill_generation()` 末尾，对 `_updated_entry_ids` 中的条目执行 skill 评估（仅 OPTIONAL suggestion，不自动创建 Skill）：

```python
# 处理 update 路径：仅写入 OPTIONAL suggestion，不自动创建 Skill
for entry_id in self._updated_entry_ids:
    if entry_id in self._skill_evaluated_entries:
        continue
    # 从 KB 读取完整条目内容
    content = self._read_entry_content(entry_id)
    if not content:
        continue
    resolution_text = self._extract_resolution_section(content)
    if not resolution_text:
        continue
    try:
        post = fm.loads(content)
        category = str(post.metadata.get("category", "")) or None
        title = str(post.metadata.get("title", "")) or None
    except Exception:
        category = None; title = None
    self._run_skill_and_curation(entry_id, resolution_text, category, report, description=title)
```

**步骤 4**：新增辅助方法 `_read_entry_content(entry_id: str) -> str`，从 `list_entries(self.kb_root)` 中找到对应 entry_id，读取 `.md` 文件并返回内容字符串；找不到时返回 `""`。

**关键约束**：update 路径只产生 OPTIONAL suggestion（由 `_run_skill_and_curation` 的 SkillAdvisor 根据命令数量决定），不自动创建 Skill。已有 `_skill_evaluated_entries` 去重机制可防止重复触发。

### 测试方案

在 `kb/tests/test_skill_advisor.py` 或 `kb/tests/test_extractor_phase.py` 中新增：
- Mock `update_kb_entry` 成功 + entry 含 1 条命令 → `report.suggestions` 含 `skill candidate`
- Mock `update_kb_entry` 成功 + entry 含 2 条命令 → `report.suggestions` 含 `skill candidate`
- Mock `update_kb_entry` 成功 + entry 含 0 条命令 → `report.suggestions` 不含 `skill candidate`
- create 路径（`write_kb_entry`）含 1 条命令 → 现有 OPTIONAL 行为不变

---

## Complexity Tracking

> 无 constitution 违规，不需要填写。

---

## Implementation Notes

- US1、US2、US3 完全独立，可按优先级顺序实现，也可并行。
- US1 改动最小（2 行），US2 次之（prompt 字符串），US3 改动最多（新增字段 + 方法 + finalize 逻辑）。
- 所有测试必须使用 mock，不依赖真实 LLM（否则测试不稳定）。
- 目标：实现后运行 `cd kb && python -m pytest tests/ -q`，通过数 ≥ 680（基线），新增测试全部绿。
