# Research: 修复 Holmes KB v3 报告缺陷

## US1: 数字 tag 崩溃

**Decision**: 在 `any(q in t.lower() for t in e.tags)` 中改为 `str(t).lower()`

**Rationale**: YAML 规范中纯数字值（如 `- 502`）会被解析为 Python `int`，`int` 对象没有 `.lower()` 方法。用 `str(t)` 显式转换可兼容任何 tag 类型。

**Alternatives considered**:
- 在写入时校验 tag 类型 — 修复点远离 bug，且会破坏现有数据
- 使用 `isinstance` 检查后跳过数字 tag — 数字 tag 不参与搜索，用户体验更差

---

## US2: dry-run 跳过 LLM

**Decision**: 在 `importer.py` 的 `import_document()` 中，若 `dry_run=True` 且文件没有已有 KB frontmatter，跳过 LLM 调用，直接将原文内容作为 `structured_content`

**Rationale**: dry-run 的语义是"无副作用预览"，不应依赖外部 API。若文件本身已有 frontmatter（`type` + `title`），现有代码已能跳过 LLM；针对无 frontmatter 的文件，dry-run 时展示原文预览已足够满足需求。

**Alternatives considered**:
- dry-run 仍调用 LLM 但不写文件 — 违背 dry-run 语义，且在无 API Key 环境无法使用
- 提供 mock 分类结果 — 过度实现，用户只需要看到文件内容

---

## US3: created_at 继承

**Decision**: 在纠错路径中，继承 `orig_post.metadata.get("created_at")` 到新条目

**Rationale**: `created_at` 记录知识首次入库时间，属于不可变历史字段，纠错操作只更新内容，不改变知识首次被记录的时间。现有代码已正确继承 `evidence` 和 `contributors`，`created_at` 漏掉属于遗漏。

**Alternatives considered**: 无合理替代方案

---

## US4: contributor 追加

**Decision**: 在纠错路径中，若 `contributor` 参数非空，将其追加到 `contributors` 列表（去重后写入）

**Rationale**: 纠错本身是一种贡献行为，贡献者应被记录。现有代码只复制原始列表，未追加新贡献者。去重使用 `list(dict.fromkeys(...))` 保持顺序且不重复。

**Alternatives considered**: 使用 `set` 去重 — 不保持顺序，不符合现有 contributors 字段的列表语义

---

## US5: Gate 3 截断替换

**Decision**: 将 `click.echo(raw[:800])` 及后续截断提示替换为：若 `len(raw) > 800` 则输出 `holmes kb pending --show <id>` 引导命令；否则输出完整内容

**Rationale**: 800 字符对于包含诊断步骤的 KB 条目远远不足，截断后的预览无法让用户做出有效判断。引导用户使用 `pending --show` 是更好的 UX — 用户可以在单独步骤中审阅完整内容。

**Alternatives considered**:
- 增加截断长度（如 2000 字符）— 治标不治本，仍有截断风险
- 直接输出全文 — 长条目会污染 confirm 交互流程

---

## US6: 空 ID 显示

**Decision**: 在 `kb_pending()` 的列表输出中，将 `e['id']` 替换为 `e['id'] or e.get('_stem', e['id'])` 的模式；需要 `list_pending()` 在返回数据中包含文件名 stem

**Rationale**: 从 `store.py` 的 `list_pending()` 可以看到，当 frontmatter `id` 为空字符串时返回 `path.stem` — 但 CLI 显示时直接使用 `e['id']`，若 `id` 为空字符串则显示空白。应在显示时 fallback 到文件名 stem。

**Alternatives considered**: 修复 `write_pending()` 强制写入非空 id — 影响范围更大，且无法修复历史数据

---

## US7: maturity 降级警告

**Decision**: 在纠错 confirm 完成后，输出一行 maturity 变更提示：`  maturity: {old_maturity} → {new_maturity}`

**Rationale**: 用户在 confirm 前无法从 pending 条目中看出 maturity 将如何变化，添加显式提示符合"所有操作都有明细提示和指引"的质量标准（Constitution）。

**Alternatives considered**: 在 Gate 3 预览中显示 — 与 Gate 3 截断修复（US5）冲突，单独输出更清晰
