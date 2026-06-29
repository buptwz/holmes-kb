# Research: M2-dedup Step 0

## Decision 1: 新函数放在 store.py 还是 tools.py？

**Decision**: 放在 `store.py`

**Rationale**: `store.py` 负责所有 KB 文件系统 CRUD 操作；`tools.py` 已有 `_find_all_entries_by_hash`（私有函数，供 Phase 3 LLM agent 使用）。公开的去重查询函数属于 store 层职责，不应放在 agent tools 层。

**Alternatives considered**:
- 放在 `tools.py`：违反单一职责（tools.py 面向 agent tool-use loop，不是通用查询层）
- 新建 `dedup.py`：过度抽象，M2 只有两个简单函数

---

## Decision 2: 是否复用 tools.py 的 `_find_all_entries_by_hash`？

**Decision**: 不复用；store.py 中独立实现

**Rationale**: `_find_all_entries_by_hash` 是私有函数，直接依赖 `list_entries()` + 手动 frontmatter 读取。store.py 的新函数需要返回 `EntryMeta`（含 `source_hash`/`source_file` 字段），而工具函数返回 `(entry_id, file_path)` 元组。两者接口不同，合并会增加耦合。

---

## Decision 3: EntryMeta 是否新增字段？

**Decision**: 是，新增 `source_hash: str = ""` 和 `source_file: str = ""`

**Rationale**: 这样 `find_entries_by_source_hash` 可以直接从 `list_entries()` 返回完整 EntryMeta，调用方无需二次读文件。向后兼容：默认值为空字符串，legacy entries 不受影响。

---

## Decision 4: `list_entries()` 是否填充新字段？

**Decision**: 是，在现有 `list_entries()` 中从 frontmatter 读取 `source_hash` 和 `source_file`

**Rationale**: `list_entries()` 已经读取所有 frontmatter 字段，加两行赋值无额外 I/O 开销。无需修改 `list_entries()` 的签名或参数。

---

## Decision 5: Step 0 应该替换还是补充现有 hash-dedup？

**Decision**: Step 0 **替换** pipeline.py 现有的 hash-dedup（lines 114-150）

**Rationale**: 现有逻辑只处理 hash 匹配（包括 pending matches 的 --force 清理）。Step 0 的 source_file 检测是新能力。为避免重复代码，Step 0 实现后需整合现有逻辑：

| 现有行为 | Step 0 后行为 |
|----------|---------------|
| confirmed hash match → skip | 保留（Step 0a） |
| pending hash match + !force → warn + return | 保留（Step 0a，改为统一 skip 处理） |
| pending hash match + force → delete + continue | 保留（--force bypass Step 0） |
| source_file match → 无处理 | 新增（Step 0b） |

具体实现：Step 0 **在** `if not self.dry_run:` 块前运行（Step 0 本身不写文件），并复用 `delete_pending()`。

---

## Decision 6: dry_run 下 Step 0 的行为？

**Decision**: dry_run 时：
- hash 匹配 → 仍然跳过（无写操作，但告知用户重复）
- source_file 匹配 → 打印更新提示，但不删除旧 pending（dry_run 不写文件）

**Rationale**: dry_run 的语义是"不修改状态"，因此跳过通知合理，但删除 pending 是副作用，不执行。
