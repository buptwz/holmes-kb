# CLI Interface Contracts

**Branch**: `005-fix-kb-workflow-bugs`

## 变更说明

本次修复不新增任何 CLI 命令，也不更改任何命令的参数接口。变更仅限于：
1. 内部行为修复（正确字段写入/清理）
2. README 文档与现有实现对齐

---

## 受影响命令（行为修复，接口不变）

### `holmes kb write-pending` / KbExtractAndSave 工具

**修复前行为**: 写入的 pending 条目不含 `maturity` 字段，导致后续 `confirm` 的 Gate 1 失败。

**修复后行为**: 写入时自动注入 `maturity: draft`（若调用方未提供）。接口不变。

```
输入: --content <markdown-with-frontmatter> [--corrects <entry_id>]
输出: {"pending_id": "pending-YYYYMMDD-HHMMSS-xxxx"}
```

---

### `holmes kb confirm <pending_id>`

**修复前行为**:
- 修正提案（含 `corrects` 字段）被 Gate 2 误判为重复，需两次确认。
- 正式条目保留 `source`、`suggested_type`、`suggested_category` 内部字段。

**修复后行为**:
- 修正提案自动跳过 Gate 2（输出 `✓ Skipped (correction proposal)`）。
- 正式条目清理所有 pending 内部字段。

接口不变。

---

### `holmes kb show <entry_id>`

**修复前行为**: `pt-db-002` 返回 "Entry not found"（大小写敏感）。

**修复后行为**: 大小写不敏感匹配，`pt-db-002` 与 `PT-DB-002` 返回相同内容；展示的条目 ID 保持原始大写格式。

接口不变。

---

### `holmes kb skill detect-commands`

**修复前行为**: 传入多行段落文本时返回 `[]`（无法识别代码块内命令）。

**修复后行为**: 支持从 triple-backtick 代码块、行内 backtick、`$` 前缀格式中识别命令。

```
输入: --content <resolution_text> [--json]
输出: [{"line": "<command>", "suggested_name": "<skill-name>"}, ...]
```

接口不变，输出更完整。

---

## README 文档修正对照表

| 命令 | 修复前文档（错误） | 修复后文档（正确） |
|------|-----------------|-----------------|
| resolve | `--side A\|B` | `--keep A\|B` |
| lint | `--report report.json`（接路径） | `--report`（flag，输出 JSON 到 stdout） |
| skill list | `--entry <id>`（选项） | `<entry_id>`（位置参数） |
| session | `holmes session list` / `holmes session show` | 从文档删除（命令不存在） |
