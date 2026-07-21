# Research: 修复 Holmes KB v8 报告问题

## US1 — amend-pending updated_at 注入

**Decision**: 在 `kb_amend_pending()` 的 `new_post.metadata.update(preserved)` 之后添加两行：

```python
from datetime import datetime as _dt, timezone as _tz
new_post.metadata["updated_at"] = _dt.now(_tz.utc).isoformat()
new_post.metadata.setdefault("created_at", original.metadata.get("created_at", ""))
```

**Rationale**: Gate 1 的 `validate_schema()` 要求 `updated_at` 存在。`setdefault` 保留原有 `created_at`，若无则设为空字符串（不报 missing，Gate 1 只检查必填字段存在性而非非空）。

## US2 — detect-commands 代码块语言过滤

**Decision**: 修改 `_CODE_BLOCK_RE` 捕获语言标签，在 `_extract_code_block_lines()` 中只处理白名单语言：

```python
_CODE_BLOCK_RE = re.compile(r"```([a-z]*)\n(.*?)```", re.DOTALL)
_SHELL_LANGS = frozenset({"", "bash", "sh", "shell", "zsh"})

def _extract_code_block_lines(text: str) -> list[str]:
    lines = []
    for m in _CODE_BLOCK_RE.finditer(text):
        lang = m.group(1)
        if lang not in _SHELL_LANGS:
            continue  # skip nginx, yaml, python, etc.
        for line in m.group(2).splitlines():
            ...
```

**Rationale**: 只需改 group 编号（group(1) → lang, group(2) → content）。非 shell 代码块直接跳过，不影响已有的 SQL 过滤和行级过滤逻辑。

## US3 — write-pending frontmatter 校验

**Decision**: 在 `kb_write_pending()` 中，解析文件内容后（content 确定后）立即检查是否含有 frontmatter：

```python
if not content.strip().startswith("---"):
    click.echo('Error: content must include YAML frontmatter (starting with "---").', err=True)
    sys.exit(1)
```

**Rationale**: frontmatter 格式要求内容以 `---` 开头。简单字符串检查足够，不需要解析 YAML。

## US4 — Gate 3 长条目强制 yes

**Decision**: 在 `kb_confirm()` Gate 3 的长内容分支（`if len(_preview_raw) > 800:`）中，将 `click.confirm("Confirm this entry?", default=True)` 替换为：

```python
answer = click.prompt("Type 'yes' to confirm this entry")
if answer.lower() != "yes":
    click.echo("Aborted.")
    sys.exit(0)
```

**Rationale**: `click.prompt` 不设默认值，强制用户主动输入。接受大小写不敏感的 `yes`。≤800 字符路径保持 `click.confirm` 不变。

**Note**: Gate 3 的 confirm 代码在 `if len(_preview_raw) > 800:` 分支后——需确认当前代码结构。当前代码在长内容时先显示提示信息，然后走到共同的 `click.confirm`。需要将 confirm 调用拆分到两个分支。

## US5 — resolve 后自动重建 index

**Decision**: 在 `kb_resolve_conflict()` 的所有成功退出路径（`--keep` 和 `--manual`）之前/之后调用 `rebuild_index_files(kb_root)` 并输出提示：

```python
from holmes.kb.store import rebuild_index_files
rebuild_index_files(kb_root)
click.echo("✓ Index rebuilt.")
```

**Rationale**: `resolve_conflict()` 写入了 entry 文件，但不更新 index。直接在 resolve 命令末尾调用重建，与 `confirm` 的做法一致（line 863）。

## US6 — list --maturity 过滤

**Decision**: 在 `@kb.command("list")` 添加 `--maturity` 选项，在 `list_entries()` 返回后过滤：

```python
@click.option("--maturity", "kb_maturity", default=None, help="Filter by maturity level.")
```

在函数体中：
```python
if kb_maturity:
    valid_maturities = {"draft", "verified", "proven"}
    if kb_maturity.lower() not in valid_maturities:
        click.echo(f"Warning: unknown maturity '{kb_maturity}'. Valid values: {', '.join(sorted(valid_maturities))}", err=True)
    entries = [e for e in entries if e.maturity and e.maturity.lower() == kb_maturity.lower()]
```

**Rationale**: `list_entries()` 已返回包含 `maturity` 字段的对象，在内存中过滤足够，无需改动 `list_entries()` 函数签名。

## US7 — history exit 码

**Decision**: 在两个"未找到"分支添加 `sys.exit(1)`：

1. `--show` 分支：`snap_path.exists()` 为 False → 已有 `click.echo(...) return` → 改为 `sys.exit(1)`
2. `not snapshots` 分支：`click.echo("No snapshots found..."); return` → 添加 `sys.exit(1)` 或改 `return` 为 `sys.exit(1)`
