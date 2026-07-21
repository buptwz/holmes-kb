# Research: 修复 Holmes KB v6 报告问题

## US1: auto-create {{placeholder}} 注释修复

**Decision**: 将 run.sh 注释中的 `{{placeholder}}` 改为 `{placeholder}`。

**Rationale**: `auto_create_skill()` 在 f-string 模板中用 `{{` 转义单个 `{`（Python f-string 规则），但注释文本的意图是展示给用户的语法示例，应显示单花括号。当前代码中 `{{placeholder}}` 在 f-string 求值后输出 `{placeholder}`——问题在 "No parameters defined via {{placeholder}} syntax" 这一行是非 f-string 上下文还是 f-string，需确认。

**Confirmed**: 查看 manager.py line 572，整个 `run_sh_content` 是 f-string，`{{placeholder}}` 在 f-string 中渲染为 `{placeholder}`——但同行其他地方也有 `{{` 渲染为 `{`。实际问题是用户看到的提示行（comment）显示的是 `{placeholder}` 单花括号，但 Example 注释行 `HOST="${{SKILL_PARAM_HOST:-localhost}}"` 在 f-string 求值后显示 `HOST="${SKILL_PARAM_HOST:-localhost}"` 是正确的 bash 语法。

**Root cause**: "No parameters defined via {{placeholder}} syntax" 这行在 f-string 里 `{{` 和 `}}` 各渲染为 `{` 和 `}`，所以用户实际看到的是 `{placeholder}` 单花括号——这是正确的！但 v6 报告说注释显示双花括号，说明实际代码用的是字面 `{{placeholder}}`（不在 f-string 内），或者该行已被修改。**需要在实现阶段读取实际代码确认**。无论如何，修复目标是确保用户看到的注释示例与 `detect {placeholder}` 实现一致。

## US2: reject --dry-run

**Decision**: 添加 `--dry-run` 选项，打印待删条目但不删除。

**Rationale**: Click 的 `is_flag=True` 选项是最简单实现。dry-run 模式只需在删除前返回。输出格式：每行一个 ID，末尾 `Rejected: N stale entries (dry run)`。

**Alternatives considered**: 交互式 `y/N` 确认——被拒绝，因为不支持非交互式脚本使用。

## US3: detect-commands 文档约束

**Decision**: 在 `CLAUDE.md` 添加 detect-commands 使用约束说明。

**Rationale**: 单词标识符（`pg_stat_activity`）本身不含任何可通过负向过滤排除的特征。限制输入范围（只传 Resolution 段落）是零代码成本的根治方案。

**Location**: CLAUDE.md 中 `kb skill detect-commands` 相关章节，或在 KB 工具使用说明中新增一条约束。

## US4: --type 无效值警告

**Decision**: 在 `kb_search()` 和 `kb_list()` 中，当 `kb_type` 不在 KB 根目录有效类型列表时输出 stderr 警告。

**Valid types detection**: `[d.name for d in kb_root.iterdir() if d.is_dir() and not d.name.startswith('.') and d.name not in ('contributions', 'skills')]`。这样不需要硬编码类型列表，KB 扩展新类型时自动生效。

**Warning format**: `Warning: unknown type '{kb_type}'. Valid types: {', '.join(sorted(valid_types))}`，输出到 stderr（`click.echo(..., err=True)`）。

**--json mode**: stderr warning + stdout `[]` — JSON consumer 不受影响。

## US5: pending_since_source 字段

**Decision**: 在 `list_pending()` 的返回 dict 中加 `pending_since_source` 字段（内存值，不写盘）。

**Values**: `"field"` / `"created_at"` / `"mtime"`，与 `list_pending()` 中的三个 fallback 分支一一对应。

**Rationale**: 自动化工具可用此字段区分可靠时间戳（`"field"`）和不可靠时间戳（`"mtime"`），在 git clone 场景下正确处理。
