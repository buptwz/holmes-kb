# Research: 修复 Holmes KB v5 报告问题

## US1: SQL 从句关键字补全

**Decision**: 在 `_SQL_KEYWORDS` frozenset 中追加 `"where", "from", "group", "having", "order", "limit", "join", "on"`

**Rationale**: 现有列表只包含 SQL 主句（`select/insert/update/delete/...`），多行 SQL 语句的从句行（`WHERE state = 'idle'`）以从句关键字开头，同样不是 shell 命令。大小写不敏感匹配已由 `.lower()` 处理，无需额外改动。

**Alternatives considered**: 正则表达式检测 SQL 语法 — 过于复杂，关键字列表已经足够且性能更好。

---

## US2: backtick 误报过滤

**Decision**: 在 `detect_commands()` 的 CMD_PATTERN loop 中，对 backtick 匹配路径（`m.group(2)` 非空时）额外检查：若 `cmd_line` 含 `=` 或 `:` 则跳过

**Rationale**:
- 含 `=` 的 backtick 内容：配置赋值（`` `max_connections = 300` ``）
- 含 `:` 的 backtick 内容：错误消息（`` `FATAL: remaining...` ``）、字典格式值
- 真正的 shell 命令（`` `redis-cli info` ``）通常不含 `=` 或 `:`
- 纯名词引用（`` `pg_stat_activity` ``）不含 `=`/`:` 但也不是命令 — 通过检查 `first_word not in known CLI tools` 也可过滤，但会增加复杂度；合理取舍是接受少量名词引用的误报，因为比 `=`/`:` 误报更少见

**实现**：在 loop 中，当 `m.group(2)` 非空（backtick 路径）时，追加过滤：
```
if m.group(2) is not None and ("=" in cmd_line or ":" in cmd_line):
    continue
```

**Alternatives considered**: 白名单 CLI 工具 — 维护成本高；只过滤大写开头 — 漏掉 `max_connections = 300` 这类误报。

---

## US3: run.sh SKILL_PARAM 注释模板

**Decision**: 在 `auto_create_skill()` 的 `run_sh_content` f-string 模板中，在 `set -euo pipefail` 之后添加一个固定注释块，说明 `SKILL_PARAM_*` 变量的用法

**Rationale**: 用户用 `$VAR` 语法写命令是自然习惯，生成的脚本应立即告诉用户"如果你想接受外部参数，用这种方式"。注释不影响脚本执行，向后完全兼容。

**注释内容**：
```bash
# To accept parameters via --param KEY=VALUE, use SKILL_PARAM_* variables:
# Example: HOST="${SKILL_PARAM_HOST:-localhost}"
#          PORT="${SKILL_PARAM_PORT:-5432}"
# Then use $HOST, $PORT in your command below.
```

**Alternatives considered**: 自动检测 `$VAR` 并生成映射行 — 需要 shell 变量名解析，复杂度高；注释方式足够且更安全。

---

## US4: pending 批量 reject

**Decision**: 在 `kb_reject()` 的 Click decorator 上新增 `@click.option("--stale-days", "stale_days", default=None, type=int)`；若传入该选项，遍历 `list_pending()` 结果，比较 `pending_since`/`created_at` 与截止时间，批量调用 `delete_pending()`

**Rationale**: 最小化实现——复用 `list_pending()` 和 `delete_pending()` 已有函数。`pending_id` 参数改为 `required=False`，传入时走单条路径，不传时走批量路径（但必须有 `--stale-days`）。

**边界条件**：`--stale-days 0` 删除所有条目（截止时间 = now，所有 pending_since <= now）；负数报错。

**Alternatives considered**: 新增 `reject-stale` 子命令 — 层级过深；扩展现有 reject 更一致。

---

## US5: pending mtime 兜底

**Decision**: 在 `list_pending()` 的 `results.append({...})` 中，`pending_since` 字段的值改为三阶段逻辑：
1. 优先使用 `post.metadata.get("pending_since")` 非空值
2. 否则用 `post.metadata.get("created_at")` 非空值
3. 否则用 `path.stat().st_mtime` 转 ISO 格式字符串

**Rationale**: 对老数据（pre-v4）的最佳兜底，不修改文件，只在读取时动态补充。

**Alternatives considered**: 写回文件 — 有副作用，不符合读取函数的职责。

---

## US6: search --type 过滤

**Decision**: 在 `kb_search()` decorator 上新增 `@click.option("--type", "kb_type", default=None)`；若传入，在 `search()` 返回结果后用列表推导过滤 `r.kb_type.lower() == kb_type.lower()`

**Rationale**: 最简单的后过滤方案——`search()` 函数无需修改，CLI 层过滤结果。limit 仍作用于搜索阶段，后过滤可能返回更少结果（可接受，文档化）。

**Alternatives considered**: 修改 `search()` 函数加 type 参数 — 需要改动更深层，后过滤足够。

---

## US7: show --with-evidence 位置调整

**Decision**: 在 `kb_show()` 中，将 Evidence 输出块从函数末尾（skill refs 之后）移动到 `click.echo(content)` 之前

**Rationale**: Evidence 汇总在 frontmatter 展示后、正文前，用户第一眼就能看到 maturity 来源。移动不影响功能，只影响输出顺序。

**Alternatives considered**: 在 frontmatter 内部插入 `evidence_summary:` 字段 — 改变了条目格式，容易引起混乱。

---

## US8: history --show 过滤内部字段

**Decision**: 在 `kb_history()` 的 `--show` 路径中，读取快照文件后用 `fm.loads()` 解析，pop `replaced_at/replaced_by/snapshot_reason`，再用 `fm.dumps()` 重新序列化后输出

**Rationale**: 与 Gate 3 预览的内部字段剥离逻辑完全一致（v4 已有先例），用相同方式处理快照的系统字段。

**Alternatives considered**: 直接字符串过滤 — 不可靠；fm.loads/pop/dumps 方式已经验证可行。

---

## US9: holmes --version

**Decision**: 在 `@cli.group(invoke_without_command=True)` 上方添加 `@click.version_option(version="0.1.0", prog_name="holmes")`；版本号从 `importlib.metadata` 读取，fallback 到硬编码 `"0.1.0"`

**Rationale**: Click 内置 `version_option` 是标准方式，自动支持 `--version` 和 `-v`（通过 `version_option` 的默认行为）。

**实现**：
```python
import importlib.metadata
_VERSION = importlib.metadata.version("holmes-kb") if importlib.metadata else "0.1.0"
```
然后 `@click.version_option(version=_VERSION, prog_name="holmes")`

**Alternatives considered**: 手动实现 `--version` 命令 — 不如内置 `version_option` 标准。
