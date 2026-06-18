# Implementation Plan: 步骤级 Skill 模型

**Branch**: `033-step-level-skill-model` | **Date**: 2026-06-17 | **Spec**: [spec.md](spec.md)

## Summary

在现有 Skill 执行层基础上实现三组改进：

1. **Bug-1 + FR-4**：修复 `_extract_resolution_section()` 的正则截断问题，使 Resolution 内的 `###` 子章节不再被截断
2. **Bug-3**：扩展 `_compute_linked_entries()` 扫描 pending 目录；修复 `_read_entry()` / `read_entry()` 支持 pending 条目读取
3. **FR-1 + FR-2 + FR-3**：实现 skill 调用标记语法解析器，SkillAdvisor 支持形态 A / 形态 B 双模式，Import Pipeline 按标记或自动拆分生成多个 skill
4. **FR-5**：`kb_read(entry_id)` 响应新增 `skill_invocations` 字段

---

## Technical Context

**Language/Version**: Python 3.11+

**Primary Files**:
- `kb/holmes/kb/agent/runner.py` — Bug-1 根因：`_extract_resolution_section()` L536，`_extract_section()` L565
- `kb/holmes/mcp/tools.py` — Bug-3：`_compute_linked_entries()` L342，`_read_entry()` L222，FR-5：`skill_invocations`
- `kb/holmes/kb/store.py` — Bug-3：`read_entry()` L33 未使用 `include_pending=True`
- `kb/holmes/kb/agent/skill_advisor.py` — FR-3：SkillAdvisor 双模式
- `kb/holmes/kb/agent/pipeline.py` — FR-2：步骤级 skill 生成触发

**Testing**: pytest，现有 `kb/tests/`

**Constraints**:
- 不破坏现有形态 A 行为（线性 Resolution + 整体封装）
- 不修改 KB 文件系统布局
- 所有现有 KB 测试无回归

---

## Constitution Check

- [x] 复用现有模块（`runner.py`、`skill_advisor.py`、`tools.py`），不重复实现
- [x] 每个变更有对应测试覆盖
- [x] 不修改 KB 文件格式（向后兼容）
- [x] Bug-1 修复只改正则模式，不影响 API 签名

---

## Root Cause Analysis

### Bug-1：SKILL.md 内容截断

**根因**（`runner.py:558-562`）：

```python
m = re.search(
    rf"{re.escape(header)}\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL
)
```

正则 `(?=\n##|\Z)` 匹配 `\n##` 时同时匹配 `### 阶段二`（三个 `#` 也以 `##` 开头），导致 Resolution 提取在遇到第一个 `###` 子章节时截断。

**修复**：将 `\n##` 改为 `\n## `（两个 `#` + 空格），只在 H2 级别 (`## `) 处停止，允许 H3 子章节（`### `）包含在提取内容中。

```python
m = re.search(
    rf"{re.escape(header)}\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL
)
```

同样适用于 `_extract_section()`（L565）。

### Bug-3：pending 条目不可见

**根因 A**（`tools.py:342-362`）：`_compute_linked_entries()` 只扫描 `pitfall/model/guideline/process/decision` 五个已确认目录，未扫描 `contributions/pending/`。

**修复 A**：在循环结束后，额外扫描 `kb_root / "contributions" / "pending"` 目录，pending 条目返回 `{id: "pending-xxx", pending: True}`。

**根因 B**（`store.py:33-48`）：`read_entry()` 调用 `list_entries(kb_root)` 时未传 `include_pending=True`，导致 pending 条目 ID 无法匹配。

**修复 B**：在 `_read_entry()` 中（或在 `store.read_entry()` 中）改为调用 `list_entries(kb_root, include_pending=True)`；响应中新增 `pending: true` 字段。

---

## Project Structure

### Documentation (this feature)

```text
specs/033-step-level-skill-model/
├── plan.md          ← 本文件
├── spec.md          ← 需求规格
├── research.md      ← 技术调研结论
├── data-model.md    ← 数据结构变更
├── contracts/
│   └── skill-markers.md   ← extract_skill_markers() 接口契约
├── checklists/
│   └── requirements.md
└── tasks.md         ← 由 /speckit-tasks 生成
```

### Source Code (impacted files)

```text
kb/holmes/kb/agent/runner.py          ← Bug-1: _extract_resolution_section(), _extract_section()
                                      ← FR-3: _finalize_skill_generation() 形态 B 路径
kb/holmes/kb/agent/pipeline.py        ← FR-2: 步骤级 skill 生成触发（Pipeline 调用路径）
kb/holmes/kb/agent/skill_advisor.py   ← FR-3: SkillAdvisor.advise() 双模式扩展
kb/holmes/kb/skill/markers.py         ← FR-1: 新文件 — extract_skill_markers()
kb/holmes/kb/store.py                 ← Bug-3B: read_entry() include_pending 参数
kb/holmes/mcp/tools.py                ← Bug-3A: _compute_linked_entries() 扫描 pending
                                      ← Bug-3B: _read_entry() pending 支持
                                      ← FR-5: _read_entry() 新增 skill_invocations
kb/tests/                             ← 新增/更新测试
```

---

## Phase 0: Research

### R-1：Bug-1 修复边界验证

**结论**：修复 `\n##` → `\n## ` 不影响 `## Resolution` → `## 下一章节` 的停止行为（因为 `## ` 仍然匹配），但允许 `### 子章节` 包含在提取内容中。

需额外验证：
- KB 条目无 `## ` 后缀章节时（Resolution 是最后一章），`\Z` 仍能正确终止 ✓
- 中文章节标题（`## 解决方案`）同样需要修复 ✓（同一正则，同一修复）

### R-2：FR-1 标记语法最终设计

两种格式同时支持，解析器通过独立正则处理：

| 形式 | 语法 | 正则 |
|------|------|------|
| Blockquote | `> skill: skill-name` | `^>\s*skill:\s*([a-z0-9][a-z0-9-]*)` |
| Inline | `` `[skill:skill-name]` `` | `` `\[skill:([a-z0-9][a-z0-9-]*)\]` `` |

skill name 合法性：`[a-z0-9][a-z0-9-]*[a-z0-9]` 或单字符 `[a-z0-9]`（与 `schema.py` 中 `skill_name_re` 保持一致）。

### R-3：FR-3 形态 B 触发条件

基于纯文本结构规则，不依赖 LLM：

| 条件 | 形态 |
|------|------|
| Resolution 含 skill 标记 | 强制形态 B |
| Resolution 步骤 > 10 且有 ≥ 3 个并列操作路径（以 `Step XA/XB`、`分支X`、`若...则...` 识别） | 自动形态 B |
| 其他（线性，≤10 步，无标记） | 形态 A（现有行为） |

形态 B 下，每个被标记步骤（或每个自动识别的分支）独立调用 `create_skill`，skill name 来自标记或自动生成（`entry_slug-branch-N`）。

---

## Phase 1: Design & Contracts

### Data Model Changes

**`linked_entries` 响应格式扩展**（`_compute_linked_entries` 返回值）

```python
# 原来
linked: list[str] = ["PT-DB-001", "GD-SYS-002"]

# 新格式 — 区分 confirmed 和 pending
linked: list[dict] = [
    {"id": "PT-DB-001", "pending": False},
    {"id": "pending-20260617-123456-ab12", "pending": True},
]
```

**`kb_read(entry_id)` 响应新增字段**

```json
{
  "id": "PT-NW-001",
  "type": "pitfall",
  "maturity": "draft",
  "content": "...",
  "skill_refs": ["e810-firmware-upgrade", "e810-driver-tuning"],
  "skill_invocations": [
    {"step": "### Step 3：执行固件升级", "skill": "e810-firmware-upgrade"},
    {"step": "### Step 5：驱动调参",     "skill": "e810-driver-tuning"}
  ]
}
```

`skill_invocations` 从 Resolution 文本实时解析（`extract_skill_markers()`），无需额外存储。

**`kb_read(pending_id)` 响应新增字段**

```json
{
  "id": "pending-20260617-123456-ab12",
  "type": "pitfall",
  "maturity": "draft",
  "content": "...",
  "skill_refs": ["e810-firmware-upgrade"],
  "pending": true
}
```

**`SkillAdvisor.advise()` 返回值扩展**

```python
@dataclass
class SkillAdvice:
    recommendation: Recommendation        # 不变
    suggested_name: str = ""              # 不变
    reason: str = ""                      # 不变
    existing_skill: Optional[str] = None  # 不变
    form: str = "A"                       # NEW: "A" | "B"
    step_skills: list[dict] = field(default_factory=list)
    # NEW: 形态 B 时为 [{"step_heading": "...", "skill_name": "...", "content": "..."}]
```

### Interface Contracts

**`extract_skill_markers(resolution_text: str) -> list[dict]`**

```python
# 输入
resolution_text: str  # Resolution 章节完整 Markdown 文本

# 输出
[
  {
    "skill_name": "e810-firmware-upgrade",   # str，合法 kebab-case
    "step_heading": "### Step 3：执行固件升级",  # str，最近的上级标题，或 ""
    "marker_type": "blockquote",             # "blockquote" | "inline"
    "line": 15,                              # int，标记所在行号（1-indexed）
  },
  ...
]
```

- skill_name 不符合规则时，跳过并记录警告（不抛异常）
- 同一 skill_name 多次出现时全部返回（调用方去重）
- 无标记时返回空列表

---

## Implementation Approach

### 实现顺序（依赖关系）

```
Step 1: Bug-1 修复（runner.py 正则）        — 独立，无依赖
Step 2: Bug-3A 修复（_compute_linked_entries）— 独立，无依赖
Step 3: Bug-3B 修复（read_entry + _read_entry）— 独立，无依赖
Step 4: FR-1 实现（markers.py）             — 独立，被 FR-3/FR-5 依赖
Step 5: FR-5 实现（skill_invocations）      — 依赖 Step 4
Step 6: FR-3 实现（SkillAdvisor 双模式）    — 依赖 Step 4
Step 7: FR-2 实现（Pipeline 步骤级生成）    — 依赖 Step 4 + Step 6
Step 8: 测试                               — 全部 Steps 完成后
```

### 各步骤要点

**Step 1 — Bug-1（runner.py）**：
- `_extract_resolution_section()` L558：`\n##` → `\n## `
- `_extract_section()` L568：同上
- 验证：5 个 `###` 子章节的 Resolution 可完整提取

**Step 2 — Bug-3A（tools.py）**：
- `_compute_linked_entries()` 末尾添加：扫描 `kb_root / "contributions" / "pending"` 目录
- 返回格式改为 `list[dict]`（含 `pending` 标志）
- 同步更新 `_read_skill()` 中 `linked_entries` 字段的使用

**Step 3 — Bug-3B（store.py + tools.py）**：
- `store.read_entry()` 改为 `list_entries(kb_root, include_pending=True)` 传参
- `_read_entry()` 检测 pending 条目时，响应新增 `"pending": True`
- `handle_kb_read()` 路由：pending ID 格式 (`pending-YYYYMMDD-...`) 不匹配 `_is_entry_id()`，走 skill 分支；需在 skill 分支前新增 pending ID 检测，路由到 `_read_entry()`

**Step 4 — FR-1（新建 markers.py）**：
- `extract_skill_markers(resolution_text)` 纯文本解析
- Blockquote 正则：`^>\s*skill:\s*([a-z0-9][a-z0-9-]*)$`（多行模式）
- Inline 正则：`` `\[skill:([a-z0-9][a-z0-9-]*)\]` ``
- 每个 marker 关联最近的 `##` 或 `###` 上级标题

**Step 5 — FR-5（tools.py）**：
- `_read_entry()` 末尾：解析 content 中的 Resolution 章节，调用 `extract_skill_markers()`，写入 `skill_invocations`

**Step 6 — FR-3（skill_advisor.py）**：
- `advise()` 新增形态判断：先调用 `extract_skill_markers(resolution_text)`
  - 有标记 → 形态 B，`step_skills` 按标记填充
  - 无标记但满足自动拆分条件 → 形态 B，自动识别分支
  - 否则 → 形态 A（现有逻辑）

**Step 7 — FR-2（runner.py `_run_skill_and_curation()`）**：
- 当 `SkillAdvice.form == "B"` 时，对 `step_skills` 中每个步骤分别调用 `create_skill()`
- 将所有生成的 skill name 写入条目 `skill_refs`

---

## Success Criteria Mapping

| SC | 验证方式 | 关联实现步骤 |
|----|---------|------------|
| SC-001 内容完整性 | 测试：导入含 5 个 `###` 的文档，验证 SKILL.md 行数 | Step 1 |
| SC-002 步骤级 skill | 测试：含 `> skill: xxx` 标记的文档，验证生成多个 SKILL.md | Step 4 + 7 |
| SC-003 自动拆分 | 测试：>10 步 ≥3 分支文档，验证自动生成多个 skill | Step 6 + 7 |
| SC-004 pending 可见性 | 测试：导入后立即 `kb_read(skill_name)` 和 `kb_read(pending_id)` | Step 2 + 3 |
| SC-005 skill_invocations | 测试：`kb_read(entry_id)` 响应含正确 `skill_invocations` | Step 5 |
| SC-006 回归 | `pytest kb/tests/` 全部通过 | 全部 Steps |
