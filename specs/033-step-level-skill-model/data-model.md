# Data Model: 步骤级 Skill 模型

**Date**: 2026-06-17 | **Feature**: 033-step-level-skill-model

---

## 1. 新增数据结构

### 1.1 SkillMarker（FR-1）

`extract_skill_markers()` 返回的单个 skill 调用标记记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| `skill_name` | `str` | skill 名称，kebab-case，合法格式 `[a-z0-9][a-z0-9-]*` |
| `step_heading` | `str` | 最近的上级标题文本（`## ...` 或 `### ...`），若无则为空字符串 |
| `marker_type` | `str` | `"blockquote"` 或 `"inline"` |
| `line` | `int` | 标记所在行号（1-indexed） |

---

### 1.2 SkillAdvice 扩展（FR-3）

在现有 `SkillAdvice` dataclass 上新增两个字段：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `form` | `str` | `"A"` | 形态选择：`"A"`（整体封装）或 `"B"`（步骤级） |
| `step_skills` | `list[dict]` | `[]` | 形态 B 时的步骤 skill 列表，每项含 `step_heading`、`skill_name`、`content` |

`step_skills` 单项格式：
```python
{
    "step_heading": "### Step 3：执行固件升级",  # 步骤标题
    "skill_name": "e810-firmware-upgrade",       # 目标 skill name
    "content": "...",                             # 该步骤对应的 Markdown 内容
}
```

---

## 2. 变更数据结构

### 2.1 `kb_read(skill_name)` 响应 — `linked_entries` 格式变更（Bug-3）

**原格式**（`list[str]`）：
```json
{"linked_entries": ["PT-DB-001", "GD-SYS-002"]}
```

**新格式**（`list[dict]`，含 pending 标志）：
```json
{
  "linked_entries": [
    {"id": "PT-DB-001",                       "pending": false},
    {"id": "pending-20260617-123456-ab12",    "pending": true}
  ]
}
```

### 2.2 `kb_read(entry_id)` 响应 — 新增 `skill_invocations`（FR-5）

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

- 无 skill 标记时 `skill_invocations: []`
- 不改变 `skill_refs` 字段（保持原有行为）

### 2.3 `kb_read(pending_id)` 响应 — 新增 `pending` 字段（Bug-3）

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

---

## 3. 不变数据结构

- KB 条目文件格式（frontmatter + body）：**不变**
- `skill_refs` frontmatter 字段格式：**不变**（仍为 `list[str]`）
- SKILL.md 文件格式：**不变**
- pending 条目文件格式：**不变**
- `contributions/evidence/` sidecar 格式：**不变**

---

## 4. 新增文件

| 文件 | 用途 |
|------|------|
| `kb/holmes/kb/skill/markers.py` | `extract_skill_markers()` 函数，FR-1 skill 标记解析器 |
