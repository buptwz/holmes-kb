# Contract: Skill Markers API

**Module**: `kb/holmes/kb/skill/markers.py`

---

## `extract_skill_markers(resolution_text: str) -> list[dict]`

解析 Resolution Markdown 文本，返回所有 skill 调用标记的列表。

### 输入

| 参数 | 类型 | 说明 |
|------|------|------|
| `resolution_text` | `str` | Resolution 章节完整 Markdown 文本（已去除 frontmatter） |

### 输出

`list[dict]`，每项包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `skill_name` | `str` | skill 名称，已验证合法格式 |
| `step_heading` | `str` | 最近的上级标题，或 `""` |
| `marker_type` | `"blockquote"` \| `"inline"` | 标记形式 |
| `line` | `int` | 行号（1-indexed） |

### 行为规范

1. **Blockquote 形式**：匹配独立行 `> skill: <name>`（行首，允许前导空格）
2. **Inline 形式**：匹配 `` `[skill:<name>]` ``（行内任意位置）
3. **合法性检查**：`skill_name` 需符合 `[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]{1,2}`，不合规则的标记**跳过**（不抛异常）
4. **重复处理**：同一 `skill_name` 多次出现时，**全部返回**（调用方负责去重）
5. **无标记时**：返回空列表 `[]`
6. **step_heading 提取**：向上扫描，取最近一行以 `## ` 或 `### ` 开头的标题文本

### 示例

输入：
```markdown
### Step 3：执行固件升级

> skill: e810-firmware-upgrade

此步骤通过 skill 执行完整的固件升级流程。

### Step 5：驱动调参

3. 执行驱动调参 → `[skill:e810-driver-tuning]`
```

输出：
```python
[
  {
    "skill_name": "e810-firmware-upgrade",
    "step_heading": "### Step 3：执行固件升级",
    "marker_type": "blockquote",
    "line": 3,
  },
  {
    "skill_name": "e810-driver-tuning",
    "step_heading": "### Step 5：驱动调参",
    "marker_type": "inline",
    "line": 9,
  }
]
```
