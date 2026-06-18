# Research: 步骤级 Skill 模型

**Date**: 2026-06-17 | **Feature**: 033-step-level-skill-model

---

## Bug-1 根因确认

**Decision**: 修复 `\n##` → `\n## `（加空格）

**Rationale**:
- 原正则 `(?=\n##|\Z)` 匹配 `\n###` 是因为 `###` 以 `##` 开头，Python re 的正向先行断言会在 `\n###` 处匹配 `\n##`
- 修改为 `(?=\n## |\Z)` — `\n## `（两个 `#` + 一个空格）不匹配 `\n### `（三个 `#` + 一个空格），精确区分 H2 与 H3
- 适用范围：`_extract_resolution_section()` 和 `_extract_section()` 共用同一正则模式，同步修复

**Alternatives considered**:
- 改用 `\n# ` 停止（H1），但 KB 条目体内通常不用 H1，会造成其他问题
- 改为按 `## ` 标题分割全文再取对应节，代码改动更大但更健壮；当前修复最小化改动

---

## Bug-3 pending 可见性

**Decision**: 双路修复（A + B）

**A — `_compute_linked_entries()` 扩展**:
- 额外扫描 `contributions/pending/*.md`，提取有 `skill_refs` 的条目
- 返回格式改为 `list[dict]`（`{id, pending: bool}`），向后兼容（调用方更新）

**B — `read_entry()` + `handle_kb_read()` pending 支持**:
- `store.read_entry()` 已有 `include_pending` 参数，只需在调用处传 `True`
- `handle_kb_read()` 当前路由：entry ID → `_read_entry()`，其他 → `_read_skill()`
  - pending ID 格式：`pending-YYYYMMDD-HHMMSS-xxxx`，不匹配 `_ENTRY_ID_PATTERN`，会错误路由到 skill 分支
  - 新增 pending ID 检测（前缀 `pending-`），路由到 `_read_entry()` with `include_pending=True`

---

## FR-1 Skill 标记语法

**Decision**: 同时支持 blockquote + inline 两种形式

**Rationale**:
- Blockquote 形式（`> skill: name`）：Markdown 渲染为引用块，语义清晰，适合独立步骤
- Inline 形式（`` `[skill:name]` ``）：行内代码风格，适合列表步骤中的嵌入引用
- 两种形式不冲突，同时解析

**Parser location**: 新建 `kb/holmes/kb/skill/markers.py`，保持关注点分离

**Skill name validation**: 复用 `schema.py` 中 `skill_name_re = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]{1,2}$")`

---

## FR-2/FR-3 形态 B 触发条件

**Decision**: 纯文本结构规则，不依赖 LLM

**手动标记触发（优先级最高）**: Resolution 含 `> skill:` 或 `` `[skill:]` `` 标记 → 强制形态 B

**自动拆分触发**: 满足以下任一条件：
- 步骤计数 > 10（通过 `^(\d+\.|Step \d+|步骤 \d+)` 计数）AND 并列路径 ≥ 3（识别 `Step \d+[A-Z]`、`分支[A-Z\d]`、`[若如当].{1,20}[则就]`）

**不触发自动拆分（形态 A）**: 步骤 ≤ 10 且无标记，现有 RECOMMENDED/SKIP 逻辑不变

**Alternatives considered**:
- LLM 判断形态：结果不稳定，且会增加 LLM 调用次数；当前规则基于已知文档结构可靠

---

## FR-5 skill_invocations

**Decision**: 实时解析，不持久化

**Rationale**:
- `skill_invocations` 可从 Resolution 文本实时提取（调用 `extract_skill_markers()`）
- 无需新增存储字段，避免数据冗余和同步问题
- 对无标记的形态 A 条目，返回空列表 `[]`（不影响现有响应结构）
