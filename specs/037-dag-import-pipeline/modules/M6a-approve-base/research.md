# Research: M6a — Pending/Approve 基础流程

## Decision 1: _pending/ 新目录结构与旧 contributions/pending/ 并存策略

**Decision**: 新格式使用 `_pending/<category>/<entry_id>.md`；旧格式 `contributions/pending/` 保持不变，两套并存。

**Rationale**:
- 新格式按 category 分级，方便审核员按业务领域批量 approve
- `_` 前缀目录与现有 `find_entry()` 的 `_` 文件过滤逻辑一致（不会被误检索）
- 向后兼容：旧 pending 流程（`holmes kb confirm`）不受影响

**Alternatives considered**:
- 统一迁移到新格式：破坏现有 confirm workflow，风险过高
- 扁平 `_pending/*.md`：无法按 category 分组，不满足需求

---

## Decision 2: approve_entry 的原子性实现

**Decision**: 先 `atomic_write` 到目标路径，成功后再 `unlink` 源文件；任一步失败记录日志。

**Rationale**:
- 先写新文件确保即使删除失败，entry 不丢失（_pending/ 留孤文件，可手动清理）
- `atomic_write`（tmp + os.replace）已有实现，直接复用
- 与 blueprint §Step 4 "先写新文件，再删旧文件" 要求一致

**Alternatives considered**:
- `shutil.move`：不原子，中间状态可见
- 数据库事务：过度设计，项目使用文件系统存储

---

## Decision 3: find_entries_by_source_file 扫描范围

**Decision**: 扫描 `_pending/<category>/` 所有子目录 + 所有 confirmed 类型目录（pitfall/model/guideline/process/decision）；旧格式 `contributions/pending/` 也扫。

**Rationale**:
- 冲突检测需要覆盖所有可能存放 entries 的位置
- `source_file` 字段为精确路径比对（规范化后比较），不走 glob
- 与 `list_entries` 的扫描范围对齐，减少遗漏

**Alternatives considered**:
- 只扫 _pending/ 和 pitfall/：漏掉其他类型 entries
- 复用 list_entries(kb_status=None)：需要同时处理新旧格式，独立实现更清晰

---

## Decision 4: category index 更新策略

**Decision**: approve 后若 `<category>/_index.md` 存在，调用现有 `rebuild_index_files(kb_root)`。

**Rationale**:
- `rebuild_index_files` 已在 store.py 实现，功能完整
- 增量更新复杂度高、收益有限（KB 数百条目，全量重建 < 100ms）

**Alternatives considered**:
- 增量更新（追加一行）：实现简单但易出错（格式不一致、ID 重复）
- 不更新 index：approve 后 `holmes kb list` 需依赖 index 文件时会失效

---

## Decision 5: deprecate_entry 不移动文件

**Decision**: in-place 修改 frontmatter `kb_status = "deprecated"`，不移动到 `_trash/`。

**Rationale**:
- blueprint 明确要求：deprecate 只修改字段，不移动文件，方便 git 追踪历史
- 移动文件会破坏 git blame / log
- `_trash/` 移动由 `holmes kb delete` 命令负责（M7 实现）

---

## Decision 6: holmes kb pending 分组展示格式

**Decision**: 新格式按 category 为标题分组；旧格式追加在末尾（标记 `[legacy]` 或单独区块）。

**Rationale**:
- 新格式是主要工作流，优先展示
- 旧格式可能被历史遗留，单独标记避免混淆
- M6b 在此基础上增加树形展示，不影响本模块平铺实现
