# Feature Specification: M2-dedup — Step 0 去重与更新检测

**Feature Branch**: `dev-M2`

**Created**: 2026-06-23

**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 完全重复文档跳过 (Priority: P1)

工程师对同一份文档运行两次 `holmes import`。第二次运行时，系统识别出内容完全相同（SHA-256 hash 匹配），打印提示并立即退出，不启动 LLM pipeline。

**Why this priority**: 防止重复条目生成，节省 LLM API 调用开销，是去重检测的核心能力。

**Independent Test**: 可独立测试——向已导入文档运行 import 并验证不生成新 pending 条目。

**Acceptance Scenarios**:

1. **Given** KB 中存在 source_hash=`abc123` 的 confirmed entry，**When** 用户导入内容相同的文档（source_hash=`abc123`），**Then** 系统打印"已存在完全相同的文档，跳过导入"并返回，不启动 pipeline
2. **Given** KB 中存在 source_hash=`abc123` 的 pending entry，**When** 用户导入内容相同的文档，**Then** 系统识别 pending 空间中的 hash 匹配并跳过
3. **Given** entry 的 source_hash 字段为空（旧格式 entry），**When** 用户导入任意文档，**Then** 空字段不被误判为 hash 匹配

---

### User Story 2 - 文档更新检测 (Priority: P1)

工程师修改了一份已导入的文档并重新运行 import。系统识别出相同路径但不同内容（source_file 匹配、hash 不同），打印"文档有更新"提示，然后继续走 import 流程。

**Why this priority**: 文档会随着排查经验积累而更新，必须支持更新导入，否则 KB 内容会过时。

**Independent Test**: 修改已导入文档内容后重新 import，验证系统打印更新提示且 pipeline 继续执行。

**Acceptance Scenarios**:

1. **Given** KB 有 source_file=`docs/gpu.md` 的 entry（hash=`old123`），**When** 用户导入内容已变更的 `docs/gpu.md`（hash=`new456`），**Then** 系统打印"文档有更新"提示并继续走 import 流程
2. **Given** 更新文档时 pending 空间有旧版本 entries，**When** 检测到 source_file 匹配，**Then** 系统显示旧 pending 列表并询问 `是否取消旧 pending？[Y/n]`
3. **Given** 用户回答 Y，**Then** 旧 pending entries 从 `contributions/pending/` 删除（直接删除，不走 trash）
4. **Given** 用户回答 n，**Then** 新旧 pending 并存，继续 import

---

### User Story 3 - 全新文档正常导入 (Priority: P2)

工程师导入一份从未入库的文档。系统检测 hash 和 source_file 均无匹配，直接进入 import 流程，无任何额外提示。

**Why this priority**: 这是最常见的使用场景，必须零干扰。

**Independent Test**: 导入全新文档验证无额外输出、pipeline 正常启动。

**Acceptance Scenarios**:

1. **Given** KB 中不存在 source_hash 或 source_file 匹配，**When** 用户运行 import，**Then** 无去重提示，直接进入 pipeline
2. **Given** 任意全新文档，**When** 运行 import，**Then** source_file 相对路径被正确记录（如 `docs/hardware/gpu.md`）

---

### User Story 4 - --force 跳过去重 (Priority: P2)

工程师使用 `--force` 标志强制重新导入，无论是否存在重复或更新。

**Why this priority**: 修复损坏的 import 状态或强制刷新时必须能绕过所有检测。

**Independent Test**: 对已导入文档使用 `--force` 并验证 pipeline 正常启动（不跳过）。

**Acceptance Scenarios**:

1. **Given** KB 中存在完全相同 hash 的 entry，**When** 用户运行 `holmes import --force`，**Then** Step 0 所有检测被跳过，pipeline 正常执行
2. **Given** 文档有更新且有旧 pending，**When** 用户运行 `--force`，**Then** 不询问 pending 清理，直接继续

---

### Edge Cases

- source_file 字段仅在 `file_path` 位于 `kb_root` 内部时才能计算；若文档在 kb_root 之外则 source_file 留空，仅做 hash 检测
- legacy entries（无 `source_hash` 字段）：空字符串不等于任意有效 hash，不被误判
- `no_interactive=True`（批量导入模式）：自动选 n（新旧 pending 并存），不询问用户
- 同一 source_file 有多个旧 pending entries 时，列出所有条目供用户确认

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `store.py` 必须提供 `find_entries_by_source_hash(kb_root, source_hash) -> list[EntryMeta]`，同时搜索 confirmed 空间（类型目录）和 pending 空间（`contributions/pending/`）
- **FR-002**: `store.py` 必须提供 `find_entries_by_source_file(kb_root, source_file) -> list[EntryMeta]`，在同样两个空间中按相对路径搜索
- **FR-003**: `EntryMeta` 必须新增 `source_hash: str = ""` 和 `source_file: str = ""` 字段，并由 `list_entries()` 从 frontmatter 中读取填充
- **FR-004**: `pipeline.py` `run()` 方法必须在 `self.force=True` 时完全跳过 Step 0
- **FR-005**: `pipeline.py` 必须在 source_hash 匹配时打印跳过提示，写入 `report.warnings`，立即返回
- **FR-006**: `pipeline.py` 必须在 source_file 匹配（hash 不同）时打印更新提示，检测 pending 旧版本
- **FR-007**: 检测到旧 pending entries 时，系统必须展示列表，并在 interactive 模式下询问 `[Y/n]`
- **FR-008**: 用户选 Y 时，删除旧 pending entries（调用 `delete_pending()`），不走 trash
- **FR-009**: `no_interactive=True` 时不询问，自动保留旧 pending（n 行为）
- **FR-010**: source_file 仅存储相对于 kb_root 的路径（如 `docs/hardware/gpu.md`）
- **FR-011**: source_hash 使用 SHA-256 前 16 位 hex（复用现有 `compute_source_hash()`）

### Key Entities

- **EntryMeta**: 轻量元数据对象，新增 `source_hash` 和 `source_file` 字段
- **ImportReport**: 包含 `warnings`、`skipped` 列表，Step 0 的跳过和提示写入此处

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 对已导入文档二次运行 import 时，100% 的情况下不启动 LLM pipeline（无 API 调用）
- **SC-002**: 对更新后的文档运行 import，100% 的情况下系统打印更新提示且 pipeline 继续执行
- **SC-003**: `--force` 标志能在 100% 的情况下绕过所有 Step 0 检测
- **SC-004**: 所有验收条件的单元测试通过率 100%
- **SC-005**: legacy entries（无 source_hash 字段）在所有 import 场景下零误判

## Assumptions

- M1 已完成：entry frontmatter 已有 `source_file` 和 `source_hash` 字段，`store.py` 的 `list_entries` 已支持 `kb_status` 过滤
- `contributions/pending/` 为唯一 pending 目录（不存在 `_pending/<category>/` 子结构）
- `--force` 标志已存在于 `holmes import` CLI，无需修改 `cli.py`
- `no_interactive` 模式（批量导入）下所有交互提示自动采用默认值（n = 并存）
- 旧 pending 条目的识别方式：文件位于 `contributions/pending/` 目录，且 `source_file` 与本次导入一致
