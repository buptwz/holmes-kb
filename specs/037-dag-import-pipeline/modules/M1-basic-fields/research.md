# Research: M1 — 基础字段与过滤

**Date**: 2026-06-23

## Decision 1: `kb_status` 缺省值处理方式

**Decision**: 缺省 `kb_status` 字段的 entry 视为 `active`（在 `list_entries()` 过滤逻辑中用 `meta.get("kb_status", "active")` 取值）。

**Rationale**: 旧 entry 均无此字段，若缺省视为 non-active 则会导致全量旧数据消失，破坏向后兼容性。视为 active 是最保守的安全默认。

**Alternatives considered**:
- 缺省视为 `deprecated`：会立即隐藏所有旧条目，破坏性变更，不可接受。
- 缺省视为 `pending`：语义不符（旧条目已经是有效的 confirmed entries），不可接受。

---

## Decision 2: `list_entries()` 如何传入"显示全部状态"

**Decision**: 使用 `kb_status: Optional[str] = "active"`，传入 `None` 时跳过状态过滤。`--all` flag 传 `None`，`--all` 语义为"active + deprecated（但仍排除 pending）"。

**Rationale**:
- `None` 是 Python 中"无过滤"的惯用表示
- `--all` 语义对应"不过滤 deprecated"，而非"包含 pending"（pending 条目在 `contributions/pending/` 有单独的 `include_pending` 参数控制）

**Alternatives considered**:
- 使用特殊字符串 `"*"` 表示全部：不如 `None` 直观，且需要文档说明。
- 拆分为 `include_deprecated: bool` 参数：与现有 `include_pending` 参数命名风格一致，但字段增多复杂度高，不如 `kb_status=None` 简洁。

---

## Decision 3: `find_entry()` 文件系统扫描策略

**Decision**: 在 `store.py` 新增 `find_entry(kb_root, entry_id)` 函数，使用 `kb_root.rglob("*.md")` 扫描所有目录（含 pending），读取每个文件的 frontmatter `id` 字段进行大小写不敏感匹配。若 `id` 字段缺失，退化为文件名 stem 匹配。

**Rationale**:
- 文件系统扫描天然支持任意 ID 格式（不依赖正则）
- 大小写不敏感匹配保持与现有 `read_entry()` 的行为兼容
- 扫描范围包含 pending 目录，保持与现有 `read_entry()` 的 `include_pending=True` 行为一致

**Alternatives considered**:
- 维护内存索引：需要失效机制，复杂度过高，KB 规模不需要。
- 仅匹配文件名 stem（不读 frontmatter）：对新格式 ID 有效，但旧格式 `PT-DB-001` 文件名也是 ID，实际两种格式均用文件名 stem，无需读 frontmatter；但保险起见仍读 frontmatter id 字段作为主键。

---

## Decision 4: `read_entry()` 附加 children 字段的格式

**Decision**: 在返回的 Markdown 内容末尾追加一个 `## Children` section，格式为：

```markdown
## Children

| ID | Title |
|----|-------|
| gpu-init-firmware-fix-001 | GPU 固件修复流程 |
| gpu-pcie-check-001 | PCIe 带宽不足排查步骤 |
```

**Rationale**:
- 以 Markdown section 追加，不破坏 frontmatter 结构
- 表格格式对 Agent 解析友好，也对人类可读
- 放在末尾，原始内容完整保留

**Alternatives considered**:
- 修改 frontmatter 追加 `children` YAML 列表：改变原始文件结构，且 `read_entry` 返回的是 raw string，不应修改 frontmatter。
- 返回 dict 结构体而非 str：需要修改所有调用方，破坏性变更。
- HTML 注释：对 Agent 不友好。

---

## Decision 5: `search.py` 过滤实现位置

**Decision**: 在 `LinearScanBackend.search()` 内部循环中，读取每个文件的 `meta.get("kb_status", "active")` 和 `parent_id` 字段，跳过 non-active 或 sub-entry 的文件。新增 `all_statuses: bool = False` 和 `exclude_sub_entries: bool = True` 参数到 `search()` 模块级函数和 `LinearScanBackend.search()`。

**Rationale**:
- 在 scan 循环内过滤，无需额外遍历，性能最优
- 参数透传到 `LinearScanBackend` 保持接口灵活性

**Alternatives considered**:
- 在 CLI 层 post-filter：search 返回结果后再过滤。会导致 limit 参数不准确（返回 5 条中 2 条被过滤，实际只得到 3 条）。
- 修改 `SearchBackend` 抽象接口：需要修改 ABC，影响所有实现。只修改 `LinearScanBackend` 更简洁。

---

## Decision 6: `holmes kb list --all` 的精确语义

**Decision**: `--all` = 不过滤 deprecated（等价于 `kb_status=None` 传入 `list_entries()`）。pending 目录的条目不受影响（仍由 `include_pending` 参数控制，默认 False）。

**Rationale**: 符合 brief.md 验收条件："`holmes kb list --all` 包含 deprecated entry"。pending 是草稿，通过 `holmes kb pending` 命令查看，不应混入 list。

---

## Decision 7: MCP `_is_entry_id()` 路由修复

**Decision**: 更新 `mcp/tools.py` 中的 `_ENTRY_ID_PATTERN`，改为使用 `find_entry()` 的结果来判断是否为 entry ID（而非硬编码正则）。具体实现：先调用 `find_entry(kb_root, entry_id)` 检查文件是否存在；存在则路由到 `_read_entry()`；不存在则尝试 `_read_skill()`。

```python
# 修改后的路由逻辑
def handle_kb_read(kb_root, entry_id, path=None):
    from holmes.kb.store import find_entry
    if find_entry(kb_root, entry_id) is not None:
        return _read_entry(kb_root, entry_id)
    if entry_id.startswith("pending-"):
        return _read_entry(kb_root, entry_id)
    return _read_skill(kb_root, entry_id, path)
```

**Rationale**:
- 正则 `^[A-Z]{2,3}-[A-Z]{2,3}-\d{3}$` 只匹配旧格式（`PT-DB-001`），新格式（`gpu-init-failure-root-001`）完全不匹配
- 使用 `find_entry()` 作为路由依据，天然支持所有 ID 格式，无需维护多个正则
- `find_entry()` 在 M1 中已实现，复用即可

**Alternatives considered**:
- 扩展正则匹配新格式：新格式过于多样（任意 kebab-case），维护正则代价高，且未来可能再次失效
- 保留双重检查（正则 OR find_entry）：不必要复杂，直接用 find_entry 更简洁

---

## Decision 8: `read_entry()` children 附加的具体格式

**Decision**: 在返回 Markdown 字符串末尾追加以下 section（基于 blueprint §KB Entry 可读性规范 > §3 关联结构注释）：

```markdown

## Children

| ID | Title |
|----|-------|
| gpu-init-failure-driver-check | 驱动版本检查流程 |
| gpu-init-failure-firmware-update | 固件升级流程 |
```

对于 MCP 的 `_read_entry()` dict 返回值，额外在 dict 中增加 `children` key：

```python
{
    "content": "...",
    "type": "pitfall",
    "maturity": "draft",
    "skill_refs": [],
    "children": [
        {"id": "gpu-init-failure-driver-check", "title": "驱动版本检查流程"},
        {"id": "gpu-init-failure-firmware-update", "title": "固件升级流程"},
    ],
    "pending": false,
}
```

**Rationale**: CLI 层返回 raw string，追加 Markdown section 对人类和 Agent 均可读；MCP 层返回 dict，直接在 dict 中加 `children` key 对 Agent 更易解析，两层各用最适合自己的格式。

---

## Decision 10: `kb show` sub-entry 标签位置

**Decision**: 在 `holmes kb show` 输出内容之前，打印 `[sub-entry of: <parent_id>]` 标签行（即 `click.echo(f"[sub-entry of: {parent_id}]")` 先于 `click.echo(content)`）。

**Rationale**: 标签在内容前，用户不需要滚动到末尾即可看到上下文信息。与现有 evidence summary 显示在内容前的惯例一致。
