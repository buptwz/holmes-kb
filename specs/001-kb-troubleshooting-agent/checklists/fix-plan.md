# Holmes KB — 缺陷修复计划

**来源**: test-task.md 执行结果（2026-05-28）
**失败**: 17 FAIL + 2 PARTIAL = 19 项
**通过率**: 46/65 = 70.8%

---

## 根因分类与优先级

| 优先级 | 失败项 | 根因类别 |
|--------|--------|----------|
| P1 | TT021, TT061 | 退出码规范错误 / Gate 1 约束缺失 |
| P2 | TT013/14, TT019/20, TT030, TT033, TT043, TT049, TT050, TT059 | 功能缺失或行为偏差 |
| P3 | TT036, TT044, TT045, TT046, TT065 | 次要 CLI 选项未实现 |

---

## 根因详细分析

### A — 退出码规范不符（TT021）

**失败现象**:
- 文件不存在 → 退出码 2（期望 1）
- `HOLMES_KB_PATH` 未设置 → 无报错，静默继续

**根因**:
`cli.py:import_cmd` 使用 `click.Path(exists=True)`，该参数不存在时 Click 自动触发 Usage Error（退出码 2）。
`HOLMES_KB_PATH` 未设置时，`kb_root` 为空字符串，`kb_root.exists()` 返回 False 后才报错，但此检查在 `cfg = load_config()` 之后，路径也没有早期验证。

**定位**:
- `cli.py:179` — `@click.argument("file", type=click.Path(exists=True, path_type=Path))`
- `cli.py:188-191` — KB path 检查逻辑

---

### B — Gate 1 约束缺失（TT061）

**失败现象**:
- title 超 100 字符 → Gate 1 不拦截（PASS 应为 FAIL）
- `created_at > updated_at` → 不检查
- id 与现有条目重复 → 不检查

**根因**:
`schema.py:validate_entry()` 只检查字段存在性、type/maturity 枚举合法性、section 存在性。
未实现数据约束规则：title 长度上限、时间逻辑顺序、id 唯一性。

**定位**:
- `schema.py:46-97` — `validate_entry()` 函数，缺少以下检查：
  1. `len(title) > 100` → error
  2. `created_at > updated_at` → error
  3. id 重复检查（需要 kb_root 作为参数，需在 validator 层传入）

---

### C — PendingEntry 缺少数据模型字段（TT013, TT014）

**失败现象**:
pending 条目 frontmatter 中无 `source`、`source_session`、`pending`、`pending_since`、`suggested_type`、`suggested_category`

**根因**:
`pending.py:write_pending()` 只写 `id`、`created_at`、`updated_at`，完全未实现 data-model.md §1.5 的 PendingEntry 专有字段。

**定位**:
- `pending.py:31-60` — `write_pending()` 函数，缺少以下字段注入：
  - `source="auto"` (import 来源) / `source="agent"` (KbExtractAndSave 来源)
  - `source_session` — 调用者会话标识（可用时间戳替代）
  - `pending=true`
  - `pending_since` — ISO 8601，同 created_at
  - `suggested_type` — 从 frontmatter `type` 字段读取
  - `suggested_category` — 从 frontmatter `category` 字段读取

---

### D — import 缺少 --title/--tags/--force 选项（TT019, TT020）

**失败现象**:
- `--title`/`--tags` 选项不存在
- `--force` 不存在；每次 import 都写新 pending 条目，无重复检测

**根因**:
`cli.py:import_cmd` 签名仅含 `--type`、`--category`、`--dry-run`。
`importer.py:import_document()` 也无 `title`/`tags` 参数。
LLM 响应后未提供覆盖机制，pending 区亦无标题重复检测。

**定位**:
- `cli.py:173-221` — `import_cmd` 缺 3 个选项
- `importer.py:65-188` — `import_document()` 缺 `title`/`tags` 参数及覆盖逻辑
- `pending.py` — 缺少"检查同标题 pending 是否已存在"的函数

---

### E — merge maturity 冲突策略错误（TT033）

**失败现象**:
proven vs draft 冲突 → 取 proven（高值），期望取 draft（低值）+ tags 追加 `contradiction`

**根因**:
`merger.py:_merge_maturity()` 逻辑无条件取高值（`if maturity_rank[remote] > maturity_rank[local]`）。
规范要求：若 remote 的 maturity **低于** local（即发生降级争议），应取低值并标记 `contradiction`；只有同向升级（如 draft→verified）才取高值。

**定位**:
- `merger.py:229-244` — `_merge_maturity()` 函数

---

### F — merge content_contradiction 退出码错误（TT030 PARTIAL）

**失败现象**:
内容矛盾冲突被隔离后 → 退出码 0（期望 1）

**根因**:
`cli.py:kb_merge()` 执行结束后无条件退出码 0；即使有 `isolated_count > 0`（需人工介入）也不通知调用者。

**定位**:
- `cli.py:514-537` — `kb_merge()` 末尾，缺 `if isolated_count > 0: sys.exit(1)`

---

### G — ConflictEntry 缺少 schema 字段（TT030 PARTIAL）

**失败现象**:
`contributions/conflicts/{id}.json` 无 `local_author`、`remote_author` 字段；`status` 值不符（实现为 "open"，data-model 期望 "pending_review"）

**根因**:
`conflict.py:write_conflict_entry()` 的 `entry_data` dict 固定 `status="open"`，且无 author 字段。
`ConflictEntry` dataclass 也未定义 author 字段。
Git conflict markers 格式 `<<<<<<< HEAD` 和 `>>>>>>> branch-name` 中 branch 名可作为 remote_author。

**定位**:
- `conflict.py:55-69` — `write_conflict_entry()` entry_data 构造
- `conflict.py:27-36` — `ConflictEntry` dataclass 定义

---

### H — resolve 后临时文件未清理（TT034 PARTIAL）

**失败现象**:
`holmes kb resolve <id> --keep A` 执行后，`{id}-A.md` 和 `{id}-B.md` 仍留在 `conflicts/` 目录

**根因**:
`conflict.py:resolve_conflict()` 只更新 JSON 状态为 "resolved"，未删除 A/B 侧文件。

**定位**:
- `conflict.py:112-151` — `resolve_conflict()` 函数末尾，缺少 A/B 文件的 `unlink()` 调用

---

### I — lint 缺少官方条目间重复检测（TT043）

**失败现象**:
将 Jaccard >85% 相似条目直接写入正式 KB（绕过 confirm）→ lint 无警告

**根因**:
`linter.py:lint()` 只做：index 一致性、stale pending、maturity decay、contradiction 关键词扫描。
Jaccard 相似度检测只在 `validator.py:check_duplicate()` 里实现，且仅在 confirm 时调用。

**定位**:
- `linter.py:41-87` — `lint()` 函数，缺少对所有官方条目的成对相似度扫描

---

### J — resolve --manual 未实现（TT036）

**失败现象**:
`holmes kb resolve <id> --manual` 选项不存在

**根因**:
`cli.py:kb_resolve_conflict()` 只有 `--keep A|B`，无 `--manual` 处理路径（读取用户手动编辑后的文件，检查冲突标记残留）。

**定位**:
- `cli.py:548-562` — `kb_resolve_conflict()` 函数

---

### K — lint --report JSON 未实现（TT044）

**失败现象**:
`holmes kb lint --report` 选项不存在

**根因**:
`cli.py:kb_lint()` 只有 `--fix` flag；`LintReport` dataclass 无 JSON 序列化逻辑。

**定位**:
- `cli.py:570-592` — `kb_lint()` 函数

---

### L — rebuild-index / pending --show 未实现（TT045, TT046）

**失败现象**:
- `holmes kb rebuild-index` 命令不存在
- `holmes kb pending --show <id>` 选项不存在

**根因**:
`cli.py` 无对应命令/选项注册。逻辑已在 `store.py:rebuild_index_files()` 和 `pending.py:get_pending()` 中实现，只差 CLI 入口。

**定位**:
- `cli.py` — 缺 `rebuild-index` 子命令；`kb_pending()` 缺 `--show` 选项

---

### M — kb list 缺高级过滤选项（TT049）

**失败现象**:
`--category`、`--query`、`--limit`、`--offset`、`--format id-only` 均不存在

**根因**:
`cli.py:kb_list()` 只有 `--type` 和 `--json`。
`store.py:list_entries()` 可能也不接受 category/query/limit/offset 参数。

**定位**:
- `cli.py:600-633` — `kb_list()` 函数
- `store.py:list_entries()` — 需检查现有参数支持

---

### N — confirm --category/--type 覆盖选项未实现（TT050）

**失败现象**:
`holmes kb confirm <id> --category network` 无法覆盖 pending 条目的 category

**根因**:
`cli.py:kb_confirm()` 只有 `--force` 选项，无 `--category`/`--type` 覆盖。
assign ID 和 target_path 计算均从 pending frontmatter 读取，无覆盖入口。

**定位**:
- `cli.py:422-487` — `kb_confirm()` 函数

---

### O — /holmes-search skill 未部署（TT059）

**失败现象**:
`~/.holmes/skills/holmes-search.md` 不存在

**根因**:
`cli.py:setup_cmd` 只写 CLAUDE.md，未部署任何 skill 文件到 `~/.holmes/skills/`。
`/holmes-resolve` skill 已作为 claude-code 的 skill 独立存在，但 `/holmes-search` 未创建。

**定位**:
- `cli.py:62-123` — `setup_cmd`，缺少 skills 目录创建和 skill 文件写入

---

### P — DM-02：importer 生成中文章节名（TT015 注）

**失败现象**:
`holmes import` 对中文文档有时生成 `## 症状`/`## 根本原因`/`## 解决方案` 而非英文节名，导致后续 confirm Gate 1 失败

**根因**:
`importer.py:_CLASSIFY_SYSTEM` 含 `"Preserve the original language of the document."` 指令，导致 LLM 使用文档语言写节标题。
但 `schema.py:TYPE_REQUIRED_SECTIONS` 硬编码英文节名（`## Symptoms` 等），形成隐式不兼容。

**定位**:
- `importer.py:25-50` — `_CLASSIFY_SYSTEM` 提示词

---

### Q — config 命令未实现（TT065）

**失败现象**:
`holmes config show`/`set` 命令不存在

**根因**:
`cli.py` 无 `config` 命令组。配置逻辑散落在 `config.py:load_config/save_config`，但无 CLI 入口。

**定位**:
- `cli.py` — 缺少 `@cli.group("config")` 及 `show`/`set` 子命令

---

## 修复计划

### Sprint 1 — P1 高危缺陷（1天）

#### Fix-1：退出码规范（`cli.py`）

**范围**: TT021
**文件**: `holmes/kb/holmes/cli.py`

```
修改点:
1. import_cmd 参数:
   - 改 click.Path(exists=True) 为 click.Path(exists=False)
   - 函数体内手动检查 file.exists()，不存在则 sys.exit(1)
   - 在 kb_root 检查前先验证 HOLMES_KB_PATH:
     kb_root = ctx.obj.get("kb_path") or cfg.kb_path
     if not kb_root:
         click.echo("HOLMES_KB_PATH not set. Run: holmes setup ...", err=True)
         sys.exit(2)
```

#### Fix-2：Gate 1 数据约束（`schema.py`）

**范围**: TT061
**文件**: `holmes/kb/holmes/kb/schema.py`

```
在 validate_entry() 中追加检查:
1. title 长度: if len(title) > 100 → error
2. 时间逻辑: 解析 created_at/updated_at，若 created_at > updated_at → error
3. id 重复: schema.py 只做格式验证；id 唯一性检查在 validator.py:validate_schema()
   中追加（需传入 kb_root），或作为 kb_confirm 中 Gate 1 的额外步骤
```

---

### Sprint 2 — P2 功能缺失（2-3天）

#### Fix-3：PendingEntry 专有字段（`pending.py`）

**范围**: TT013, TT014
**文件**: `holmes/kb/holmes/kb/pending.py`

```python
# write_pending() 中追加：
post.metadata["pending"] = True
post.metadata["pending_since"] = now_iso          # 同 created_at
post.metadata["source"] = source                   # 新增 source 参数，默认 "auto"
post.metadata["source_session"] = source_session   # 新增参数，默认 ""
post.metadata["suggested_type"] = post.metadata.get("type", "pitfall")
post.metadata["suggested_category"] = post.metadata.get("category", "")

# write_pending 签名修改:
def write_pending(kb_root, content, source="auto", source_session="") -> str:
```

同步更新 `KbExtractAndSave.ts` 和 `importer.py` 调用处，传入对应 source 值。

#### Fix-4：import --title/--tags/--force（`cli.py`, `importer.py`）

**范围**: TT019, TT020
**文件**: `cli.py`, `importer.py`

```
cli.py:import_cmd 添加:
  @click.option("--title", default=None, help="Override LLM-generated title.")
  @click.option("--tags", default=None, help="Comma-separated tags, override LLM.")
  @click.option("--force", is_flag=True, help="Skip duplicate pending check.")

importer.py:import_document() 添加:
  title_override: Optional[str] = None
  tags_override: Optional[str] = None
  force: bool = False

  # 在 LLM 响应解析后覆盖:
  if title_override:
      post.metadata["title"] = title_override
  if tags_override:
      post.metadata["tags"] = [t.strip() for t in tags_override.split(",")]

  # --force=False 时检查同标题 pending 是否已存在:
  if not force:
      existing = [p for p in list_pending(kb_root) if p["title"] == result_title]
      if existing:
          raise DuplicatePendingError(existing[0]["id"])
```

#### Fix-5：merge maturity 冲突策略（`merger.py`）

**范围**: TT033
**文件**: `holmes/kb/holmes/kb/merger.py`

```python
def _merge_maturity(local: str, remote: str) -> str:
    maturity_rank = {"draft": 0, "verified": 1, "proven": 2, "deprecated": -1}
    local_post = frontmatter.loads(local)
    remote_post = frontmatter.loads(remote)
    local_m = str(local_post.metadata.get("maturity", "draft"))
    remote_m = str(remote_post.metadata.get("maturity", "draft"))
    local_r = maturity_rank.get(local_m, 0)
    remote_r = maturity_rank.get(remote_m, 0)

    if remote_r > local_r:
        # 同向升级 → 取高值
        local_post.metadata["maturity"] = remote_m
    elif remote_r < local_r:
        # 降级争议 → 取低值 + contradiction tag
        local_post.metadata["maturity"] = remote_m
        tags = list(local_post.metadata.get("tags", []))
        if "contradiction" not in tags:
            tags.append("contradiction")
        local_post.metadata["tags"] = tags
    # else: 相同，不变

    return frontmatter.dumps(local_post)
```

#### Fix-6：merge content_contradiction 退出码（`cli.py`）

**范围**: TT030 PARTIAL
**文件**: `holmes/kb/holmes/cli.py`

```python
# kb_merge() 末尾:
click.echo(f"✓ Resolved: {auto_count} auto, {isolated_count} isolated to contributions/conflicts/")
if isolated_count > 0:
    sys.exit(1)
```

#### Fix-7：ConflictEntry 字段补全（`conflict.py`）

**范围**: TT030 PARTIAL
**文件**: `holmes/kb/holmes/kb/conflict.py`

```python
# write_conflict_entry() — entry_data 中:
entry_data = {
    "conflict_id": conflict_id,
    "original_path": str(cf.path),
    "status": "pending_review",   # 改 "open" → "pending_review"
    "created_at": now.isoformat(),
    "local_author": _extract_author(cf.local_content, side="local"),
    "remote_author": _extract_author(cf.remote_content, side="remote"),
}

# 新增辅助函数，从 conflict marker 行提取 branch 名:
def _extract_author(content: str, side: str) -> str:
    # git conflict markers 格式: "<<<<<<< HEAD" / ">>>>>>> feature-branch"
    # 已在 parse_conflicts 阶段分割，可从 ConflictFile.path 的上下文推断
    return ""  # 无 git 上下文时返回空字符串

# ConflictEntry dataclass 增加字段:
@dataclass
class ConflictEntry:
    conflict_id: str
    original_path: str
    side_a: str
    side_b: str
    status: Literal["pending_review", "resolved"]
    created_at: str
    local_author: str = ""
    remote_author: str = ""
```

#### Fix-8：resolve 后清理 A/B 文件（`conflict.py`）

**范围**: TT034 PARTIAL
**文件**: `holmes/kb/holmes/kb/conflict.py`

```python
# resolve_conflict() 末尾，在更新 JSON 状态后:
(conflicts_dir / f"{conflict_id}-A.md").unlink(missing_ok=True)
(conflicts_dir / f"{conflict_id}-B.md").unlink(missing_ok=True)
```

#### Fix-9：lint 增加官方条目重复检测（`linter.py`）

**范围**: TT043
**文件**: `holmes/kb/holmes/kb/linter.py`

```python
def _check_duplicate_entries(entries, report: LintReport) -> None:
    """Warn when two official entries have Jaccard title similarity >85%."""
    from holmes.kb.validator import _jaccard_similarity
    seen: list = []
    for entry in entries:
        for prev in seen:
            if entry.type != prev.type:
                continue  # 仅同类型比较
            sim = _jaccard_similarity(entry.title, prev.title)
            if sim >= 0.85:
                report.warnings.append(
                    f"Possible duplicate: [{entry.id}] vs [{prev.id}] "
                    f"(Jaccard={sim:.0%})"
                )
        seen.append(entry)

# 在 lint() 中调用:
_check_duplicate_entries(all_entries, report)
```

注意：`_jaccard_similarity` 当前为模块私有函数，需改为 `jaccard_similarity`（去掉前导 `_`）并在 `__all__` 中导出，或直接在 linter 中内联实现。

#### Fix-10：kb list 高级过滤选项（`cli.py`, `store.py`）

**范围**: TT049
**文件**: `cli.py`, `holmes/kb/holmes/kb/store.py`

```
cli.py:kb_list() 添加:
  --category TEXT
  --query TEXT
  --limit INT (default=0, 0=无限制)
  --offset INT (default=0)
  --format [table|json|id-only] (default=table)

store.py:list_entries() 添加参数:
  category: Optional[str] = None
  query: Optional[str] = None   # 在 title/tags 中搜索
  limit: int = 0
  offset: int = 0

  # 过滤逻辑:
  if category:
      entries = [e for e in entries if e.category == category]
  if query:
      q = query.lower()
      entries = [e for e in entries if q in e.title.lower()
                 or any(q in t.lower() for t in e.tags)]
  if offset:
      entries = entries[offset:]
  if limit:
      entries = entries[:limit]
```

#### Fix-11：confirm --category/--type 覆盖（`cli.py`）

**范围**: TT050
**文件**: `holmes/kb/holmes/cli.py`

```
kb_confirm() 添加:
  --category TEXT  (覆盖 pending 条目的 category)
  --type TEXT      (覆盖 pending 条目的 type)

在 Gate 3 通过后、assign ID 之前，应用覆盖:
  if category_override:
      post.metadata["category"] = category_override
  if type_override:
      post.metadata["type"] = type_override

  # 重新读取用于 generate_id:
  kb_type = str(post.metadata.get("type", "pitfall"))
  category = post.metadata.get("category")
```

#### Fix-12：/holmes-search skill 部署（`cli.py`）

**范围**: TT059
**文件**: `holmes/kb/holmes/cli.py`（`setup_cmd`）

```python
# setup_cmd 末尾，在写 CLAUDE.md 之后:
skills_dir = home / "skills"
skills_dir.mkdir(exist_ok=True)
search_skill = skills_dir / "holmes-search.md"
if not search_skill.exists():
    search_skill.write_text(_HOLMES_SEARCH_SKILL, encoding="utf-8")
    click.echo(f"✓ /holmes-search skill deployed to {search_skill}")

_HOLMES_SEARCH_SKILL = """\
# /holmes-search

Use this skill to perform a targeted knowledge base search.

## Execution Steps

1. Ask the user for search keywords if not already provided.
2. Call **KbSearch** with the provided keywords.
3. For each result, display: ID, title, type, category, maturity, snippet.
4. If results found, ask the user if they want to read the full content of any entry.
5. If the user selects an entry, call **KbReadEntry** with that ID.
6. If no results found, suggest alternative keywords or inform the user the KB has no matching entry.
"""
```

#### Fix-13：DM-02 importer 中文章节名（`importer.py`）

**范围**: TT015 注（非确定性隐性断路）
**文件**: `holmes/kb/holmes/kb/importer.py`

```python
# _CLASSIFY_SYSTEM 修改:
# 将:
"- Preserve the original language of the document. Do NOT translate content."
# 改为:
"- Translate content to English if needed, but section headings MUST always be in English."
# 或更精确:
"- The section headings (e.g. ## Symptoms, ## Root Cause, ## Resolution) MUST be in English."
"- The section body text may be in the original document language."
```

---

### Sprint 3 — P3 次要 CLI 选项（1天）

#### Fix-14：resolve --manual（`cli.py`）

**范围**: TT036
**文件**: `holmes/kb/holmes/cli.py`

```python
@kb.command("resolve")
@click.argument("conflict_id")
@click.option("--keep", type=click.Choice(["A", "B"]), default=None)
@click.option("--manual", is_flag=True, help="Use manually edited conflict file.")
def kb_resolve_conflict(ctx, conflict_id, keep, manual):
    if not keep and not manual:
        click.echo("Either --keep A|B or --manual is required.", err=True)
        sys.exit(2)

    if manual:
        # 读取原始冲突路径，检查是否还有冲突标记
        import re
        data = json.loads(meta_path.read_text())
        orig = Path(data["original_path"])
        text = orig.read_text(encoding="utf-8")
        if re.search(r"^<{7} ", text, re.MULTILINE):
            click.echo("Conflict markers still present. Resolve manually first.", err=True)
            sys.exit(2)
        # 文件已手动清理，直接写入正式 KB（路径已是 original_path）
        append_conflict_log(kb_root, conflict_id, "manual")
        # 更新 JSON 状态
        data["status"] = "resolved"
        meta_path.write_text(json.dumps(data, indent=2))
        click.echo(f"✓ Conflict {conflict_id} resolved manually")
        return

    # 原 --keep A|B 逻辑不变
    ...
```

#### Fix-15：lint --report JSON（`cli.py`）

**范围**: TT044
**文件**: `holmes/kb/holmes/cli.py`

```python
@kb.command("lint")
@click.option("--fix", is_flag=True)
@click.option("--report", "as_report", is_flag=True, help="Output JSON report.")
def kb_lint(ctx, fix, as_report):
    report = lint(kb_root, fix=fix)
    if as_report:
        import dataclasses
        click.echo(json.dumps({
            "total_entries": report.total_entries,
            "pending_count": report.pending_count,
            "conflict_count": report.conflict_count,
            "warnings": report.warnings,
            "errors": report.errors,
            "fixes_applied": report.fixes_applied,
        }, ensure_ascii=False))
        return
    # 原来的文字输出不变
```

#### Fix-16：rebuild-index 子命令（`cli.py`）

**范围**: TT045
**文件**: `holmes/kb/holmes/cli.py`

```python
@kb.command("rebuild-index")
@click.pass_context
def kb_rebuild_index(ctx):
    """Rebuild index.json and all _index.md files."""
    from holmes.kb.store import rebuild_index_files
    kb_root = _require_kb_root(ctx)
    rebuild_index_files(kb_root)
    index_path = kb_root / "index.json"
    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    count = index_data.get("total_entries", 0)
    click.echo(f"✓ Index rebuilt: {count} entries")
```

#### Fix-17：pending --show 选项（`cli.py`）

**范围**: TT046
**文件**: `holmes/kb/holmes/cli.py`

```python
@kb.command("pending")
@click.option("--json", "as_json", is_flag=True)
@click.option("--show", "show_id", default=None, help="Show full content of a pending entry.")
def kb_pending(ctx, as_json, show_id):
    if show_id:
        from holmes.kb.pending import get_pending
        raw = get_pending(kb_root, show_id)
        if raw is None:
            click.echo(f"Pending entry not found: {show_id}", err=True)
            sys.exit(1)
        click.echo(raw)
        return
    # 原列表逻辑不变
```

#### Fix-18：config show/set 命令（`cli.py`）

**范围**: TT065
**文件**: `holmes/kb/holmes/cli.py`

```python
@cli.group("config")
def config_group():
    """View and update Holmes configuration."""
    pass

@config_group.command("show")
def config_show():
    """Display current configuration."""
    from holmes.config import load_config, _holmes_home
    cfg = load_config()
    home = _holmes_home()
    click.echo(json.dumps({
        "kb_path": cfg.kb_path,
        "model": cfg.model,
        "api_base_url": cfg.api_base_url,
        "config_file": str(home / "config.json"),
        "settings_file": str(home / "settings.json"),
    }, indent=2, ensure_ascii=False))

@config_group.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a configuration value (kb_path, model, api_key, api_base_url)."""
    from holmes.config import HolmesConfig, load_config, save_config
    cfg = load_config()
    if not hasattr(cfg, key):
        click.echo(f"Unknown config key: {key}", err=True)
        sys.exit(1)
    setattr(cfg, key, value)
    save_config(cfg)
    click.echo(f"✓ {key} = {value}")
```

---

## 修复文件索引

| 文件 | 涉及 Fix | 变更规模 |
|------|----------|---------|
| `holmes/kb/holmes/cli.py` | Fix-1,4,6,10,11,12,14,15,16,17,18 | 大（11处） |
| `holmes/kb/holmes/kb/schema.py` | Fix-2 | 小（+10行） |
| `holmes/kb/holmes/kb/pending.py` | Fix-3 | 小（+8行） |
| `holmes/kb/holmes/kb/importer.py` | Fix-4,13 | 中（参数+提示词） |
| `holmes/kb/holmes/kb/merger.py` | Fix-5 | 小（_merge_maturity 重写） |
| `holmes/kb/holmes/kb/conflict.py` | Fix-7,8 | 小（+字段+unlink） |
| `holmes/kb/holmes/kb/linter.py` | Fix-9 | 小（+_check_duplicate_entries） |
| `holmes/kb/holmes/kb/store.py` | Fix-10 | 中（list_entries 增参数） |
| `holmes/kb/holmes/kb/validator.py` | Fix-9 | 极小（_jaccard_similarity 改名） |

---

## 测试验证矩阵

修复完成后，重新执行以下测试用例验证：

| Fix | 验证用例 | 期望结果 |
|-----|----------|---------|
| Fix-1 | TT021 | 文件不存在→退出码 1；KB 未配置→退出码 2 |
| Fix-2 | TT061 | title >100 → Gate 1 error；created_at>updated_at → error |
| Fix-3 | TT013, TT014 | pending 含 source/pending_since/suggested_type 等字段 |
| Fix-4 | TT019, TT020 | --title/--tags 覆盖生效；--force 绕过重复检测 |
| Fix-5 | TT033 | proven vs draft → 取 draft + tags=[contradiction] |
| Fix-6 | TT030 | isolated_count>0 → 退出码 1 |
| Fix-7 | TT030 | conflict JSON 含 status=pending_review/local_author/remote_author |
| Fix-8 | TT034 | resolve 后 A.md/B.md 被删除 |
| Fix-9 | TT043 | lint 输出相似条目警告 |
| Fix-10 | TT049 | kb list --category/--query/--limit/--offset/--format 均生效 |
| Fix-11 | TT050 | confirm --category network → 写入 pitfall/network/ |
| Fix-12 | TT059 | ~.holmes/skills/holmes-search.md 存在，/holmes-search 可执行 |
| Fix-13 | TT015 | import 中文文档 → 章节名始终为英文 |
| Fix-14 | TT036 | --manual 已清除标记→成功；未清除→退出码 2 |
| Fix-15 | TT044 | lint --report → 合法 JSON |
| Fix-16 | TT045 | rebuild-index → index.json 重建，entry_count 正确 |
| Fix-17 | TT046 | pending --show <id> → 完整 Markdown 输出 |
| Fix-18 | TT065 | config show/set → 读写 config.json |

预期修复后通过率：**63+/65 ≥ 96.9%**（TT030 ConflictEntry author 字段若无 git 上下文可能仍为空）
