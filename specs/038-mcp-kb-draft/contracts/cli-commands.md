# CLI Command Contracts: M9

## 新增: holmes kb drafts

**用法**: `holmes kb drafts`

**行为**:
- 读取 `<kb_root>/_drafts/` 下所有 `.md` 文件（不含 `_imported/` 子目录）
- 读取每个文件的 frontmatter，提取 `saved_at` 和 `source`
- 按 `saved_at` 倒序排列（最新在前）
- `_drafts/` 不存在或无 `.md` 文件：打印 "暂无待 import 的草稿"

**输出示例**:
```
_drafts/ (2 pending)
  redis-oom-2026-06-23.md        2026-06-23  [via mcp.draft]
  nginx-timeout-2026-06-20.md    2026-06-20  [via mcp.draft]

运行 holmes import _drafts/<file> 正式导入。
```

**无草稿输出**:
```
暂无待 import 的草稿
```

---

## 更新: holmes import（草稿归档联动）

**新增逻辑**（在 `_print_report` 之后，仅单文件模式）:

```
if source_path 在 _drafts/ 下（不在 _imported/ 中）
  且 非 dry_run
  且 report 无 errors（import 成功）
then
  _drafts/_imported/ 目录不存在则创建
  shutil.move(source_path, _imported/<filename>)
```

**目录批量模式（--dir）**：不做草稿移动（`--dir` 不应指向 `_drafts/`，通常是文档目录）。
