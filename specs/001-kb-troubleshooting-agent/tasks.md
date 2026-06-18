# Tasks: Holmes — 基于知识库的问题排查 Agent

**Input**: `specs/001-kb-troubleshooting-agent/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | data-model.md ✅

**Organization**: 按用户故事组织，各故事可独立实现与验收。

## Format: `[ID] [P?] [Story?] Description with file path`

- **[P]**: 可并行（不同文件，无未完成依赖）
- **[Story]**: 对应用户故事编号（US1–US5）
- Setup/Foundational/Polish 阶段无 Story 标签

---

## Phase 1: Setup（项目脚手架）

**目标**：建立两个子项目的目录结构和基础配置

- [X] T001 创建 `kb/` Python 包完整骨架：`kb/holmes/__init__.py`、`kb/holmes/kb/__init__.py`、`kb/pyproject.toml`（含 click/python-frontmatter/openai/pydantic 依赖）、`kb/ruff.toml`（Google style）
- [X] T002 [P] 创建 `agent/` 新增文件目录结构：`agent/src/tools/kb/`、`agent/skills/`，以及 `agent/HOLMES.md` 占位文件
- [X] T003 [P] 创建 `kb-template/` 完整目录骨架：`pitfall/{network,system,application,database}/`、`model/`、`guideline/`、`process/`、`decision/`、`contributions/{pending,conflicts}/`（含 `.gitkeep`）、`contributions/log.md`

---

## Phase 2: Foundational（核心基础，阻塞所有用户故事）

**目标**：KB 数据层与 Python CLI 骨架就绪，TypeScript 工具才能通过 subprocess 调用

**⚠️ CRITICAL**: 所有用户故事均依赖本阶段完成

- [X] T004 实现 `kb/holmes/kb/schema.py`：定义5种条目类型的 frontmatter 必填字段规则、各类型必需正文章节映射（pitfall→问题描述+解决步骤，model→概述，guideline→推荐/禁止做法，process→步骤，decision→决策内容+背景）、暴露 `validate_entry(content: str) -> ValidationResult`
- [X] T005 实现 `kb/holmes/kb/store.py`：`read_entry(kb_root, entry_id) -> str`、`list_entries(kb_root, type=None, category=None) -> list[EntryMeta]`、`write_entry(path, content)`、`rebuild_index_files(kb_root)`（重建各类型 `_index.md` 表格）
- [X] T006 实现 `kb/holmes/kb/search.py`：定义 `SearchBackend` 抽象接口（预留索引扩展点，方法 `search(query, limit) -> list[SearchResult]`）、实现 `LinearScanBackend`（遍历全部 .md 文件全文匹配）、暴露模块级 `search(kb_root, query, limit=5) -> list[SearchResult]`
- [X] T007 [P] 实现 `kb/holmes/config.py`：`HolmesConfig` dataclass（kb_path/api_key/api_base_url/model 字段）、`load_config(holmes_home=None) -> HolmesConfig`、`save_config(config, holmes_home=None)`，读写 `~/.holmes/config.json`
- [X] T008 [P] 搭建 `kb/holmes/cli.py` Click 命令组骨架：`holmes` 主组 + `kb` 子组，配置全局 `--kb-path` 选项，注册所有子命令占位
- [X] T009 在 `kb/holmes/cli.py` 实现4个 KB 内部读取命令（供 TypeScript 工具 subprocess 调用，均支持 `--json` 输出）：`holmes kb overview --kb-path <path>`（读 README.md + 各 _index.md）、`holmes kb search <query> --kb-path <path> [--limit N]`、`holmes kb show <id> --kb-path <path>`（输出条目全文）、`holmes kb read-category <type> --kb-path <path>`（读 `{type}/_index.md`）
- [X] T010 [P] 初始化 `kb-template/` 内容文件：`README.md`（全景目录模板，含5类条目说明和贡献流程）、各类型 `_index.md`（含表头 ID/标题/分类/成熟度/更新日期）、`CHANGELOG.md` 占位

**Checkpoint**: Python CLI 读取命令可用，TypeScript 工具可开始实现 US1

---

## Phase 3: US1 — 安装配置与首次排查（优先级：P1）🎯 MVP

**目标**：用户执行 `holmes setup` 后，运行 `holmes` 即可使用 KB 工具进行排查

**独立验收**：`holmes setup --kb-path <path>` 完成后，运行 `holmes`，提问"Redis 连接超时"，Holmes Agent 调用 `KbSearch` 并在响应中引用 KB 条目

- [X] T011 [US1] 修改 `agent/package.json`：`bin` 字段改为 `{ "holmes": "dist/cli-node.js" }`，更新 `name`、`description`（BR-001）— 见 agent/FORK_CHANGES.md
- [X] T012 [US1] 修改 `agent/src/utils/envUtils.ts`：`getClaudeConfigHomeDir` 默认路径从 `~/.claude` 改为 `~/.holmes`，保持 `CLAUDE_CONFIG_DIR` 环境变量兼容（BR-004）— 见 agent/FORK_CHANGES.md
- [X] T013 [US1] 修改 `agent/src/main.tsx`：`.name('holmes')`、描述改为 `Holmes - AI-powered knowledge-based troubleshooting assistant`、版本字符串 `(Holmes)`、全部用户可见的 "Claude Code" 文字替换为 "Holmes"（BR-002/003）— 见 agent/FORK_CHANGES.md
- [X] T014 [US1] 修改 `agent/src/entrypoints/cli.tsx`：在最早期（performanceShim import 之后、任何模块加载之前）读取 `$HOLMES_HOME/config.json`，将 `api_key→OPENAI_API_KEY`、`api_base_url→OPENAI_BASE_URL`、`model→OPENAI_MODEL` 注入 `process.env`（仅在对应 env 未设置时），若任一存在则设 `CLAUDE_CODE_USE_OPENAI=1`（MC-001）— 见 agent/FORK_CHANGES.md
- [X] T015 [US1] 在 `kb/holmes/cli.py` 实现 `holmes setup` 命令：参数 `--kb-path`、`--model`、`--api-key`、`--api-base-url`；将 `HOLMES_KB_PATH=<path>` 写入 `~/.holmes/settings.json` 的 `env` 字段；将模型配置写入 `~/.holmes/config.json`；在 `<kb-path>/HOLMES.md` 生成系统提示模板；输出两项操作的确认信息（FR-001，MC-002）
- [X] T016 [P] [US1] 编写 `agent/HOLMES.md` 排查系统提示模板：排查方法论（先 KbReadOverview→KbSearch→KbReadEntry 渐进式导航）、KB 工具使用说明、排查成功后执行 `/holmes-resolve` 的触发时机
- [X] T017 [P] [US1] 实现 `agent/src/tools/kb/KbReadOverview.ts`：`buildTool`/`ToolDef` 模式，`isReadOnly: true`，无参数，通过 `execa('holmes', ['kb', 'overview', '--kb-path', kbPath, '--json'])` 获取知识库全景
- [X] T018 [P] [US1] 实现 `agent/src/tools/kb/KbSearch.ts`：`isReadOnly: true`，参数 `{ query: string, limit?: number }`，subprocess 调用 `holmes kb search <query> --kb-path <path> --json --limit <n>`，返回匹配条目摘要列表
- [X] T019 [P] [US1] 实现 `agent/src/tools/kb/KbReadCategoryIndex.ts`：`isReadOnly: true`，参数 `{ type: string }`，subprocess 调用 `holmes kb read-category <type> --kb-path <path> --json`，返回该类型 _index.md 内容
- [X] T020 [P] [US1] 实现 `agent/src/tools/kb/KbReadEntry.ts`：`isReadOnly: true`，参数 `{ entry_id: string }`，subprocess 调用 `holmes kb show <id> --kb-path <path>`，返回条目全文 Markdown
- [X] T021 [US1] 创建 `agent/src/tools/kb/index.ts` 导出全部 KB 工具；在 `agent/src/tools.ts` 中导入并注册4个只读工具（KbReadOverview、KbSearch、KbReadCategoryIndex、KbReadEntry）

**Checkpoint**: US1 可独立验收——`holmes setup` + `holmes` + KB 工具调用全链路可通

---

## Phase 4: US2 — 排查成功后提取并保存知识（优先级：P1）

**目标**：用户执行 `/holmes-resolve`，Holmes Agent 调用 `KbExtractAndSave` 写入 pending 区

**独立验收**：完成排查会话，执行 `/holmes-resolve`，`contributions/pending/` 出现结构化新条目；`holmes kb pending` 可显示该条目

- [X] T022 [US2] 实现 `kb/holmes/kb/pending.py`：`write_pending(kb_root, content) -> pending_id`（文件名格式 `{date}-{slug}.md`）、`list_pending(kb_root) -> list[PendingEntry]`、`get_pending(kb_root, pending_id) -> str`、`delete_pending(kb_root, pending_id)`
- [X] T023 [US2] 在 `kb/holmes/cli.py` 实现 `holmes kb pending [--json]` 命令：表格输出 ID、类型、标题、暂存时间；支持 `--json` 供脚本/工具调用
- [X] T024 [P] [US2] 实现 `agent/src/tools/kb/KbExtractAndSave.ts`：`isReadOnly: false`（触发 Holmes Agent 原生权限确认），参数 `{ summary: string, type?: string, category?: string }`，subprocess 调用内部 `holmes kb write-pending` 命令，返回 pending_id
- [X] T025 [P] [US2] 实现 `agent/src/tools/kb/KbWriteEntry.ts`：`isReadOnly: false`，参数 `{ content: string }`（完整 frontmatter + 正文），subprocess 写入 pending 区，返回 pending_id
- [X] T026 [P] [US2] 实现 `agent/src/tools/kb/KbListPending.ts`：`isReadOnly: true`，subprocess 调用 `holmes kb pending --kb-path <path> --json`，返回 pending 条目列表
- [X] T027 [US2] 在 `kb/holmes/cli.py` 添加内部写入命令 `holmes kb write-pending --content <str> --kb-path <path>`（供 TypeScript 工具调用）；在 `agent/src/tools.ts` 补充注册 KbExtractAndSave、KbWriteEntry、KbListPending
- [X] T028 [US2] 创建 `agent/skills/holmes-resolve.md`：定义 `/holmes-resolve` skill 执行步骤——总结会话 Symptoms/Root Cause/Resolution → 调用 `KbExtractAndSave` → 输出 pending_id 和 `holmes kb confirm <ID>` 提示
- [X] T029 [P] [US2] 创建 `agent/skills/holmes-search.md`：定义 `/holmes-search` skill——接受用户关键词，调用 `KbSearch`，格式化返回结果

**Checkpoint**: US2 可独立验收——`/holmes-resolve` 写入 pending，`holmes kb pending` 可见

---

## Phase 5: US3 — CLI 导入外部知识（优先级：P1）

**目标**：`holmes import <file>` 将任意文档 LLM 结构化后写入 pending 区

**独立验收**：提供 ≥50字符非结构化故障记录，`holmes import` 写入 pending；对 <50字符内容直接拒绝不调用 LLM

- [X] T030 [US3] 实现 `kb/holmes/kb/importer.py`：`import_document(kb_root, source_path, model, api_key, api_base_url, type=None, category=None, dry_run=False) -> ImportResult`；内容 <50字符时抛 `ContentTooShortError` 不调用 LLM；构造分类 prompt 调用 LLM 返回结构化 Markdown；dry_run 时返回预览不写文件；写入时调用 `write_pending()`
- [X] T031 [US3] 在 `kb/holmes/cli.py` 实现 `holmes import <file>` 命令：支持 `--type`、`--category`（覆盖 LLM 推断）、`--dry-run`；对 <50字符输出 "内容过短，至少需要50字符" 后退出；成功时输出 pending_id 和内容预览（前500字符）

**Checkpoint**: US3 可独立验收——`holmes import` 全流程（LLM 分类 + pending 写入 + dry-run）

---

## Phase 6: US4 — 知识库 CLI 运维（优先级：P1）

**目标**：`holmes kb` 子命令集完整支持 pending→confirm 流转、冲突处理、健康检查

**独立验收**：残缺条目和 >85% 相似度条目被 confirm 拦截；`holmes kb merge` 处理 git conflict markers；`holmes kb lint` 输出健康报告

### 6a: confirm 三级门控

- [X] T032 [US4] 实现 `kb/holmes/kb/validator.py` Gate 1：`validate_schema(content: str) -> SchemaResult`，检查必填 frontmatter 字段（id/title/type/category/tags/maturity/created/updated）及各类型必需章节是否完整，返回缺失项列表
- [X] T033 [US4] 实现 `kb/holmes/kb/validator.py` Gate 2：`check_duplicate(kb_root, content, threshold=0.85) -> DuplicateResult`，对全部正式条目标题计算 Jaccard 词集相似度，>threshold 时返回相似条目列表
- [X] T034 [US4] 实现 `kb/holmes/kb/validator.py` ID 自动生成：`generate_id(kb_root, type, category) -> str`，扫描 `{type}/{category}/` 目录下所有条目 frontmatter id 字段取最大序号+1，格式 `{PREFIX}-{CAT_ABBR}-{NNN}`（如 PT-DB-001）
- [X] T035 [US4] 在 `kb/holmes/cli.py` 实现 `holmes kb confirm <pending_id> [--force]` 命令：串行执行 Gate1（Schema）→Gate2（重复检测，>85% 无 --force 时拒绝）→Gate3（打印全文等待 y/n）→通过后 `generate_id` 分配永久 ID、移入 `{type}/{category}/` 正式目录、更新 `{type}/_index.md`

### 6b: reject

- [X] T036 [US4] 在 `kb/holmes/cli.py` 实现 `holmes kb reject <pending_id> [--reason <text>]` 命令：调用 `delete_pending()`，追加操作记录到 `contributions/log.md`（格式：时间戳 | 操作 | ID | reason）

### 6c: merge（git 冲突处理）

- [X] T037 [US4] 实现 `kb/holmes/kb/merger.py`：`parse_conflicts(kb_root) -> list[ConflictFile]`，扫描 KB 目录中含 git conflict markers（`<<<<<<<`/`=======`/`>>>>>>>`）的 .md 文件，提取 local/remote 两个版本
- [X] T038 [US4] 在 `kb/holmes/kb/merger.py` 实现5类冲突分类：`classify_conflict(local_content, remote_content) -> ConflictType`（pure_new / evidence_append / maturity_change / field_update / content_contradiction）
- [X] T039 [US4] 在 `kb/holmes/kb/merger.py` 实现自动解决：`auto_resolve(conflict_file) -> str | None`，对前4类返回合并后内容，content_contradiction 返回 None
- [X] T040 [US4] 在 `kb/holmes/cli.py` 实现 `holmes kb merge [--kb-path <path>]` 命令：调用 `parse_conflicts`→分类→`auto_resolve`（覆盖原文件并 `git add`）→content_contradiction 生成 ConflictEntry 移入 `contributions/conflicts/`；输出摘要（自动处理 N 条，隔离 M 条）

### 6d: resolve（冲突裁决）

- [X] T041 [US4] 实现 `kb/holmes/kb/conflict.py`：`list_conflicts(kb_root) -> list[ConflictEntry]`（读 contributions/conflicts/）、`resolve_conflict(kb_root, conflict_id, keep: Literal['A','B']) -> str`（将选定版本移入正式目录，更新 ConflictEntry status=resolved）
- [X] T042 [US4] 在 `kb/holmes/cli.py` 实现 `holmes kb resolve <conflict_id> --keep A|B` 命令：调用 `resolve_conflict`，删除冲突文件，追加 `contributions/log.md`

### 6e: lint（健康检查）

- [X] T043 [US4] 实现 `kb/holmes/kb/linter.py`：检查项—`_index.md` 与实际文件不一致（孤儿/幽灵条目）、maturity 衰减（proven>12月/verified>6月未引用自动降级）、contradiction 关键词扫描、pending 超30天未处理告警；返回 `LintReport`（总条目数/pending数/冲突数/警告列表/错误列表）
- [X] T044 [US4] 在 `kb/holmes/cli.py` 实现 `holmes kb lint [--fix] [--kb-path <path>]` 命令：输出 LintReport；`--fix` 时自动重建 _index.md（调用 `rebuild_index_files`）并写入 maturity 衰减修正

**Checkpoint**: US4 可独立验收——confirm 3-gate / merge 5场景 / lint 报告全链路可通

---

## Phase 7: US5 — 知识库内容浏览（优先级：P2）

**目标**：用户通过 CLI 浏览 KB 全量内容，结果与 Agent 会话检索一致

**独立验收**：`holmes kb list --type pitfall` 输出条目与 KbSearch 返回结果覆盖一致

- [X] T045 [US5] 在 `kb/holmes/kb/store.py` 实现 `IndexBuilder.rebuild(kb_root) -> KnowledgeIndex`：扫描全部 `.md` 条目（含 pending）生成 `index.json`（字段：id/title/type/category/tags/maturity/file_path/updated/pending）
- [X] T046 [US5] 在 `kb/holmes/cli.py` 实现 `holmes kb list [--type <type>] [--json]` 命令：读取 `index.json`（若不存在则先 rebuild），表格输出 ID/类型/成熟度/标题；`--json` 供脚本调用

**Checkpoint**: US1–US5 全部可独立验收

---

## Phase N: Polish & Cross-Cutting Concerns

**目标**：文档完善、测试覆盖、代码风格合规

- [X] T047 编写 `docs/quickstart.md`：安装 holmes-kb → `holmes setup` → 首次排查 → `/holmes-resolve` → `holmes kb confirm` 完整走通步骤（对应 SC-001：10分钟内完成）
- [X] T048 [P] 编写 `docs/developer-guide.md`：holmes-agent fork 4处改动清单、KB 工具开发指南（buildTool 模式示例代码）、Python 包开发环境搭建、ruff/biome 配置说明
- [X] T049 [P] 完善 `kb-template/README.md`：KB 结构说明、5种条目类型用法示例、贡献流程（import→pending→confirm→push→merge）
- [X] T050 [P] 编写 `kb/tests/test_schema.py` 和 `kb/tests/test_store.py`：schema 必填字段验证用例（各类型正反向各3例）、store CRUD 操作验证
- [X] T051 [P] 编写 `kb/tests/test_validator.py`：confirm 3-gate 各场景——残缺 frontmatter 拦截、缺少必需章节拦截、Jaccard >85% 拦截（含 --force 覆盖）、ID 递增生成正确性
- [X] T052 [P] 编写 `kb/tests/test_merger.py`：5类冲突场景各2用例（pure_new/evidence_append/maturity_change/field_update 自动解决，content_contradiction 隔离）
- [X] T053 [P] 编写 `kb/tests/test_importer.py`：<50字符内容拒绝、dry-run 不写文件、LLM mock 返回结构化条目、--type/--category 覆盖推断
- [X] T054 编写 `kb/tests/test_integration.py`：全链路集成测试（mock LLM）——`holmes setup` → `holmes kb search` → `holmes import` → `holmes kb confirm`
- [X] T055 运行 `ruff check kb/ --fix` 修复全部 Python lint 问题；运行 `bun run lint` 修复 TypeScript lint 问题

---

## Dependencies & Execution Order

### Phase 依赖

```
Phase 1: Setup
    └── Phase 2: Foundational（BLOCKS ALL）
            ├── Phase 3: US1（MVP，仅依赖 Phase 2）
            │       └── Phase 4: US2（依赖 T021 工具注册完成）
            ├── Phase 5: US3（独立，可与 US2 并行启动）
            ├── Phase 6: US4（依赖 T022 pending.py 完成）
            └── Phase 7: US5（依赖 T005 store.py 完成）
```

### 用户故事依赖关系

- **US1 (P1)**: 仅依赖 Phase 2，是 MVP
- **US2 (P1)**: 依赖 T021（工具注册到 tools.ts），需 US1 完成后启动
- **US3 (P1)**: 仅依赖 Phase 2，可与 US2 并行
- **US4 (P1)**: 依赖 T022（pending.py），可在 US2 的 T022 完成后启动
- **US5 (P2)**: 仅依赖 Phase 2，可在任意阶段并行启动

### 故事内并行机会

- **US1**: T016~T020（5个文件，全并行）
- **US2**: T024~T026（3个 TS 工具文件，全并行）
- **US4 validator**: T032~T034（同文件不同函数，可分工并行）
- **US4 merger**: T037~T039（递进实现，T038 依赖 T037）
- **Polish tests**: T050~T053（4个独立测试文件，全并行）

---

## Parallel Execution Examples

### US1 TypeScript 工具（并行）

```
同时开始（各自独立文件）:
├── T016: agent/HOLMES.md
├── T017: agent/src/tools/kb/KbReadOverview.ts
├── T018: agent/src/tools/kb/KbSearch.ts
├── T019: agent/src/tools/kb/KbReadCategoryIndex.ts
└── T020: agent/src/tools/kb/KbReadEntry.ts
→ 全部完成后执行 T021（注册到 tools.ts）
```

### US4 Validator（并行）

```
同时开始（不同函数）:
├── T032: validate_schema()
├── T033: check_duplicate()
└── T034: generate_id()
→ 全部完成后执行 T035（confirm 命令串联三关）
```

---

## Implementation Strategy

### MVP（仅 US1，21 tasks）

1. Phase 1: Setup（T001~T003）
2. Phase 2: Foundational（T004~T010）
3. Phase 3: US1（T011~T021）
4. **验收**：`holmes setup` + `holmes` + KB 工具调用通路
5. 可交付演示

### 增量交付

```
Phase 1+2 → Foundation ready（T001~T010）
Phase 3   → MVP：用户可用 Holmes Agent 排查并查阅 KB
Phase 4   → 知识提取闭环：排查经验自动沉淀到 pending
Phase 5   → 知识导入：外部文档批量入库
Phase 6   → 运维完整：KB 质量管理全链路（confirm/merge/lint）
Phase 7   → 体验完善：KB 内容可视化浏览
Phase N   → 生产就绪：文档 + 测试 + lint
```

---

## Summary

| 阶段 | 任务数 | 主要产物 |
|------|--------|---------|
| Phase 1: Setup | 3 | 目录结构、package 配置 |
| Phase 2: Foundational | 7 | schema / store / search / CLI骨架 / kb-template |
| Phase 3: US1 | 11 | 品牌 fork + `holmes setup` + 4个只读 KB 工具 + HOLMES.md |
| Phase 4: US2 | 8 | pending.py + 3个写入工具 + `/holmes-resolve` skill |
| Phase 5: US3 | 2 | importer.py + `holmes import` 命令 |
| Phase 6: US4 | 13 | validator / merger / conflict / linter + 7个 CLI 命令 |
| Phase 7: US5 | 2 | IndexBuilder + `holmes kb list` 命令 |
| Phase N: Polish | 9 | 文档 + 单元/集成测试 + lint |
| **Total** | **55** | |

**MVP Scope**: Phase 1 + Phase 2 + Phase 3（US1）= **21 tasks**

**最大并行机会**: T002/T003（Phase 1）、T007/T008/T010（Phase 2）、T016~T020（US1）、T024~T026（US2）、T050~T053（Polish）
