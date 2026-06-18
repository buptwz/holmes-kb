# Research: 修复 Holmes KB v7 报告问题

## US1 — detect_commands() backtick 过滤规则

**Decision**: 在 `manager.py` 的 `detect_commands()` 函数中，CMD_PATTERN 循环的 backtick 路径（`m.group(2) is not None`）补充 4 条过滤规则。

**Current code** (`kb/holmes/kb/skill/manager.py` ~line 472):
```python
if m.group(2) is not None and ("=" in cmd_line or ":" in cmd_line):
    continue
```

**New rules to add** (after the existing check):
```python
if m.group(2) is not None:
    if ("=" in cmd_line or ":" in cmd_line):
        continue
    if cmd_line.startswith("-X"):          # JVM 参数: -Xmx4g, -Xms4g
        continue
    if re.match(r'^\w[\w.]*\.\w[\w]*$', cmd_line):  # 配置键: session.timeout.ms
        continue
    if cmd_line[0:1].isalpha() and "(" in cmd_line:  # 方法调用: emitter.on()
        continue
    if cmd_line.endswith("{"):             # 配置块开头: upstream backend {
        continue
```

**Rationale**:
- FR-001: `-X` prefix covers all JVM startup flags (`-Xmx`, `-Xms`, `-XX:`)
- FR-002: `^\w[\w.]*\.\w[\w]*$` matches dot-separated config keys without spaces (must contain `.`)
- FR-003: `[0].isalpha() and "(" in cmd_line` matches method calls like `emitter.on()`, `func(arg)`
- FR-004: `endswith("{")` matches Nginx-style config block starters

**Alternatives considered**:
- Using `re` module for all filters: more consistent but adds import (already imported in manager.py)
- Single combined regex: harder to read and maintain; separate conditions are clearer

## US2 — amend-pending 命令

**Decision**: 新增 `@kb.command("amend-pending")` 命令，读取现有 pending 文件，替换 content 和 user-provided frontmatter，保留 pending 系统元字段。

**Metadata preservation strategy**:
- Keep from original: `id`, `pending_since`, `source`, `source_session`, `pending` (bool), `suggested_type`, `suggested_category`
- Replace from new content: everything else (title, type, category, maturity, resolution, etc.)

**Implementation**:
```python
@kb.command("amend-pending")
@click.argument("pending_id")
@click.option("--content", default=None, help="New Markdown content with frontmatter.")
@click.option("--file", "file_path", default=None, type=click.Path(exists=True), help="File path to read content from.")
@click.pass_context
def kb_amend_pending(ctx, pending_id, content, file_path):
    # Load original, parse new content, preserve metadata, write back
```

## US3 — write-pending --file 选项

**Decision**: `write-pending` 的 `--content` 改为可选（`required=False`），新增 `--file` 选项。两者互斥，必须提供其一。

**Mutual exclusion**: 在函数体内检查，而非用 click.option 的 `required`，因为 click 不原生支持 XOR 互斥。

## US4 — archive-orphans --dry-run

**Decision**: 新增 `--dry-run` is_flag，当为 True 时只打印将被归档的 ID，不调用 `archive_orphan()`。

**Output format** (consistent with reject --stale-days --dry-run):
```
<entry_id>
<entry_id>
Archived 2 orphan draft(s) (dry run)
```

JSON mode with dry-run: `{"archived": [...], "errors": [], "dry_run": true}`

## US5 — reject 单条 --dry-run

**Decision**: 移除 `if dry_run and stale_days is None: error` 检查。在 single-entry 模式中，dry-run 打印条目 ID 和 `(dry run)` 标记，不删除文件。

**Output** (single-entry dry-run):
```
<pending_id>
✓ Rejected: <pending_id> (dry run)
```

## US6 — pending 表格 CREATED 列

**Decision**: 将 `kb_pending()` 表格的 CREATED 列从 `e['created_at'][:10]` 改为 `e['pending_since'][:10]`。

`list_pending()` 已经通过 `pending_since_source` 逻辑保证 `pending_since` 始终非空（field → created_at → mtime 三级兜底），因此无需额外 null 检查。
