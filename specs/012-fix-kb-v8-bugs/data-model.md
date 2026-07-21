# Data Model: 修复 Holmes KB v8 报告问题

## Affected Entities

### PendingEntry (US1, US3)

**amend-pending 现在系统注入的字段**：
- `updated_at`: 总是设为当前 UTC 时间（amend 操作时刻）
- `created_at`: setdefault 保留原始值；若原始 pending 无该字段则设为空字符串

**write-pending 新增前置校验**：
- 内容必须以 `---` 开头（frontmatter 格式），否则拒绝写入

### CommandCandidate (US2)

**新常量**：
```python
_SHELL_LANGS = frozenset({"", "bash", "sh", "shell", "zsh"})
```

**_CODE_BLOCK_RE 变更**：
- 旧: `r"```[a-z]*\n(.*?)```"` — 1 个捕获组（内容）
- 新: `r"```([a-z]*)\n(.*?)```"` — 2 个捕获组（语言标签 + 内容）

**_extract_code_block_lines() 变更**：
- `m.group(1)` → 语言标签（旧代码的 group 需要整体 +1）
- 新增：`if lang not in _SHELL_LANGS: continue`

### EntryListFilter (US6)

**list 命令新增过滤维度**：

| 选项 | 类型 | 有效值 | 行为 |
|------|------|--------|------|
| `--maturity` | string | draft / verified / proven | 内存过滤，大小写不敏感 |

无效值：stderr 警告，返回空列表，exit 0（与 `--type` 无效值行为一致）
