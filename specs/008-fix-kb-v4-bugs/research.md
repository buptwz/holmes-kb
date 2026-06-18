# Research: 修复 Holmes KB v4 报告问题

## US1: merge exit 码

**Decision**: 移除 `cli.py:808` 的 `sys.exit(1)`，改为 `click.echo("Run 'holmes kb resolve <id> --keep [A|B]' to resolve.")`

**Rationale**: 冲突被成功隔离是正常结果，不是失败。`exit 1` 是 Unix 惯例中的"错误"信号，用在此处会让 CI/CD 脚本误判。

**Alternatives considered**: 用 `exit 2` 表示"警告"— 不标准，不如 0。

---

## US2: Gate 3 内部字段剥离

**Decision**: 在 Gate 3 展示前，对 `raw` 内容重新解析，用 `fm.loads(raw)` 获取 `post`，pop 掉内部字段（`pending`, `pending_since`, `source`, `source_session`, `suggested_type`, `suggested_category`），再用 `fm.dumps(post)` 重新序列化为展示文本

**Rationale**: 这与 confirm 路径中的字段清理逻辑一致，用相同方式预览。用户看到的预览应与实际写入 KB 的内容一致。

**Alternatives considered**: 只在展示时隐藏字段（不 pop）— 可能遗漏其他内部字段，不如 pop 方式彻底。

---

## US3: pending_since 暴露

**Decision**: 在 `pending.py` `list_pending()` 的结果 dict 中追加 `"pending_since": str(post.metadata.get("pending_since", ""))`

**Rationale**: `pending_since` 已在 `write_pending()` 中写入 frontmatter，只是 `list_pending()` 没有提取它。一行修改。

**Alternatives considered**: 无合理替代方案。

---

## US4: CMD_PATTERN 误报

**Decision**:
1. 在 `detect_commands()` 入口处，若文本以 `---\n` 开头（YAML frontmatter），剥离第一个 `---...---` 块
2. 在 `CMD_PATTERN.finditer` 的结果处理中，对每个候选命令应用 SQL 关键字过滤（复用已有 `_SQL_KEYWORDS`）

**Rationale**:
- YAML frontmatter 的 `key: value` 格式不会触发 `$` 或 backtick 模式，但可能触发 `known CLI tool at line start` 模式（如 `grep`, `find` 作为字段值）
- `CMD_PATTERN` 的 `$\s+...` 模式会匹配类似 `$ FATAL: ...` 的文本（错误消息以 `$` 开头很少见，但 backtick 路径可能匹配 SQL）
- SQL 过滤复用 v2 修复中已有的 `_SQL_KEYWORDS` frozenset

**Alternatives considered**: 只剥离 frontmatter，不过滤 SQL — 不完整，backtick 路径仍有误报。

---

## US5: show --with-evidence

**Decision**: 在 `kb_show()` 添加 `@click.option("--with-evidence", is_flag=True)` 参数；若传入该选项，调用 `load_evidence(kb_root, entry_id, [])` 读取 sidecar，输出汇总行：`Evidence: N sessions (<contributors>) — last: <date>`

**Rationale**: `load_evidence()` 已在 `store.py` 中实现，直接复用。汇总显示（不是完整列表）避免输出过多。

**Alternatives considered**: 直接在默认 show 中显示 evidence — 改变现有行为，破坏向后兼容。

---

## US6: history --show

**Decision**: 在 `kb_history()` 添加 `@click.option("--show", "show_snapshot", default=None)` 参数；若传入，在 `.history/<entry_id>/` 目录下找到对应文件，输出完整内容。安全检查：只允许纯文件名（`Path(name).name == name`），防止路径遍历。

**Rationale**: 快照文件已存在于 `.history/` 目录，只需一个读取路径。安全校验防止 `../../etc/passwd` 类攻击。

**Alternatives considered**: 另起 `snapshot show` 子命令 — 层级过深，不如 `--show` 选项直接。

---

## US7: import --dry-run 无参数提示

**Decision**: 在 `import_cmd()` 中，dry-run 执行前检查：若 `api_key` 为空（或未配置）且 `kb_type/category/title/tags` 均为 None，在输出结果后追加一行提示：`Tip: LLM not configured. Use --type/--category/--title/--tags to preview with manual classification.`

**Rationale**: 只在真正"无意义"场景（无 LLM + 无手动参数）给出提示，避免误报。

**Alternatives considered**: 直接 abort — 过于强硬，用户可能只是想看原始文件内容。
