# Tasks: KB 系统加固与 NPI 场景适配（043）

**Input**: `specs/043-kb-hardening/spec.md`

**Organization**: 按 M1→M2→M3→M3.5 分 phase，每个 phase 有 Independent Test 和 Checkpoint。原则上 phase 内有序、phase 间串行（M1 是后续一切的安全网）。

## Format: `[ID] [P?] Description`

- **[P]**: 可并行（不同文件、无依赖）
- 所有任务对应 spec.md 的决策编号（D1–D8）与问题编号（P1–P13）

---

## Phase 1: Setup

**Purpose**: 建立基线，确认现状可复现。

- [X] T001 跑基线测试：`cd kb && python -m pytest -q 2>&1 | tail -3`，记录通过数（后续每个 phase 结束都不得回退）
- [X] T002 确认 editable 安装状态下 `holmes --help` 的当前行为，记录顶层命令清单（预期：只有 config/import/kb/log/setup/start，即 P3 的现场）

---

## Phase 2 (M1): 闭环修复 + 收敛（P1/P2/P3，D1/D8）

**Goal**: import→approve→read→confirm→maturity 提升全环第一次真实走通；代码=文档=行为。

**Independent Test**: `test_golden_loop.py` 全环绿；三个复现测试从红变绿。

### 复现测试先行（红）

- [X] T003 [P] 新建 `kb/tests/test_repro_043.py`：`test_import_then_approve_finds_entry`——tmp KB 里用 `holmes.kb.pending.write_pending` 写一条 pending（模拟 import 产物），再调 approve 的查找路径 `store._find_pending_entry`，断言能找到（当前预期失败：P2）
- [X] T004 [P] 同文件：`test_top_level_commands_exist`——用 click CliRunner 调 `holmes approve --help` / `holmes pending --help` / `holmes search --help`，断言命令存在（当前预期失败：P3）
- [X] T005 [P] 同文件：`test_read_full_then_confirm_not_duplicate`——tmp KB 放一条正式条目，先 `handle_kb_read(detail="full", session_id=X)`，再 `handle_kb_confirm(session_id=X, outcome="solved")`，断言 `ok=True` 且 maturity 提升（当前预期失败：P1）
- [X] T006 运行 `pytest kb/tests/test_repro_043.py`，确认三个测试全红，截图/记录输出

### D1 证据模型事件溯源化

- [X] T007 改 `kb/holmes/kb/store.py` `append_evidence()`：同 session 已有记录时的语义从"一律拒绝"改为状态机——允许 `referenced → solved/not_solved`、`not_solved → solved` 升级（覆写自己的 `<session>.json` sidecar，用 `atomic_write` 替换 `store.py:434` 的裸 `write_text`）；`solved → solved` 与 `solved → not_solved` 仍判 duplicate 返回 False
- [X] T008 改 `kb/holmes/mcp/tools.py` `handle_kb_confirm()`：append 返回 False 时区分"真重复"与"升级已发生"；确认 T005 变绿
- [X] T009 `kb/holmes/kb/store.py` 新增 `derive_entry_maturity(kb_root, entry_id) -> str`：从 frontmatter+sidecar 全量证据实时推导；`handle_kb_browse`/`handle_kb_read` 返回的 maturity 改用推导值（frontmatter 字段降级为缓存，读取以推导为准）
- [X] T010 `rebuild_index_files()`（`store.py:853`）顺带用推导值校准各条目 frontmatter 的 maturity 缓存；`_index.md`/`index.json` 的 maturity 列也用推导值
- [X] T011 补测试 `kb/tests/test_store.py`：状态机全转移表（referenced→solved ✓、referenced→not_solved ✓、not_solved→solved ✓、solved→solved duplicate、solved→not_solved duplicate）；proven 推导（2 session × 2 contributor）；`cd kb && pytest tests/test_store.py tests/test_repro_043.py` 绿

### D8 收敛

- [X] T012 approve 链路指向 `contributions/pending/`：改 `cli/pending.py` approve 的查找逻辑（用 `pending.py` 的 PENDING_DIR，或让 `_find_pending_entry` 扫 `contributions/pending/`），T003 变绿；`approve_entry` 的搬运目标/状态字段相应对齐
- [X] T013 删除 `_pending/<type>/<category>/` 那套：`store.write_pending`（`store.py:580`）及其全部引用；确认生产代码无 `_pending` 写入路径后，读取侧兼容保留一个版本周期（只读）
- [X] T014 CLI 顶层化：`browse.py/pending.py/confirm.py/governance.py` 的命令同时注册到顶层 `cli`（`holmes approve` 等），`kb` 组保留 hidden 别名；T004 变绿
- [X] T015 [P] 删死代码：`merger.py` 的 `merge_pending_entry`、`store.py` 的 `resolve_maturity_conflict`（生产零调用，逻辑由 D1 取代）、`agent/src/tools/kb/*.ts`；CHANGELOG 自动追加的模板注释修正
- [X] T016 新建 `kb/tests/test_golden_loop.py`：合成一篇小文档走全环——import（mock LLM provider）→ pending → approve → browse 可见 → read(full) → confirm(solved) → 断言 verified → 换 contributor 再 confirm → 断言 proven → 跑 decay（时间 mock）断言衰减规则触发
- [X] T017 全量回归 `cd kb && python -m pytest -q` 绿；根 `tests/` e2e 脚本涉及路径逐个核对（agent/ 包内副本暂不动，记录差异）

**Checkpoint**: M1 完成——核心闭环有 golden loop 背书，文档命令可用，import→approve 通畅。

---

## Phase 3 (M2): 两种部署形态（P4–P10，D2–D5）

**Goal**: 分布式 git 协作低冲突、无撞号；集中式身份可归因、有基本防护。

**Independent Test**: 双客户端模拟（两个 tmp clone 各自 approve+push+pull）无人工干预合并成功；集中式模式下两条不同 contributor 的 confirm 使条目达 proven。

### D1 收尾：decay 事件化（M1 golden loop 发现的设计裂缝）

- [X] T017a decay 触发时写系统证据 sidecar（`contributor: "system"`、`outcome: "decayed"`、记录目标等级与原因），不再只改 frontmatter 缓存；`derive_maturity`/`derive_entry_maturity` 规则改为"最新 decayed 事件之后的 solved 证据才重新计数"（decay 后的等级作为推导上限，直到有新 solved）；decay 快照（`.history/`）行为保留；补测试：decay→推导不回弹、decay 后新 solved→重新升级

### D5 派生文件出 git

- [X] T018 `kb-template/` 新增 `.gitignore`（`index.json`、`**/_index.md`）与 `.gitattributes`（`contributions/log.md merge=union`）；从模板 git 历史中清理已跟踪的这两个文件（`git rm --cached`，模板侧操作）
- [X] T019 `rebuild_index_files()` 的 `file_path` 改存相对路径（`store.py:894`）；`find_entry`（`store.py:98-102`）加 `is_relative_to(kb_root)` 校验，越界即忽略并落 rglob 兜底（同时覆盖待核实项）
- [X] T020 `cli/confirm.py` `kb merge`：`_isolate_conflict` 排除 `log.md`/`_index.md`/`index.json`——log.md 交给 union driver，索引类冲突提示并自动执行 rebuild；`_index.md` 冲突时直接取任一边+rebuild

### D2 UUID ID + 语义查重门控（P9/P13）

- [x] T021 `validator.py` `generate_id()` 改为 `{PREFIX}-{CAT}-{6位hex}` 随机生成 + 存在性重试（最多 5 次）；更新全部依赖顺序号的测试与文档示例
- [x] T022 approve 门控接入查重：`SemanticDeduplicator` 接线到 approve 流程（疑似重复时展示候选条目、要求人工确认或 `--force`）；approve 帮助文档注明；删除原死代码路径中不再用的部分

### D3 身份声明（P4/P7）

- [X] T023 `kb_browse`/`kb_confirm` 增加 `contributor` 参数（可选）：server 侧优先用传入值，local 模式回退 `_get_contributor`；`_record_reference` 取消硬编码 `"agent"`（`tools.py:396`）；`config.py` 的 `username` 字段接入 agent 侧默认
- [X] T024 session_id 完整 uuid（取消 `[:8]` 截断，`tools.py:163-164`）；`kb_confirm` 空 sid 一律拒绝并 hint（引导先调 `kb_browse` 获取 session）——已拍板，无匿名桶
- [X] T025 [P] 测试：两个不同 contributor 经 MCP 连续 confirm → proven 达成（此前数学不可达，P4 的反向证明）

### D4 部署模式（P5/P6）

- [X] T026 `cli/server.py` `holmes start` 加 `--mode local|central`（默认 local）、`--host`（默认 127.0.0.1）；central 模式：强制 contributor 非空、启用静态 token 认证（FastMCP auth 或 ASGI middleware，token 存 config）
- [X] T027 低频人工写（approve/decay/deprecate）加进程内 per-entry 锁；`decay.py:254`、`store.py:470` 的裸写改 `atomic_write`（覆盖待核实项）
- [X] T028 双客户端集成测试：两个 tmp clone 各自 import+approve+push/pull（同分类、同时点），验证无撞号（D2）、log.md 自动合并且不丢行、索引类冲突自动 rebuild

**Checkpoint**: M2 完成——分布式协作低摩擦，集中式身份/防护成立。

---

## Phase 4 (M3): import 质量 + applies_to（P11–P13，D6/D7）

**Goal**: NPI 长文档的分支结构、物理/远程步骤结构化存活且可校验；条目携带适用性元数据。

**Independent Test**: 合成评测集全量通过：步骤提取完整率、fidelity 通过率、applies_to 提取准确率达标（阈值实现时定并写入测试）。

### D7 IR 扩展与长文档不变量

- [x] T021b （M2 缺口补齐）`approve_entry` 也走 `generate_id` 铸永久 UUID ID：当前 approve 保留 `pending-*` 临时 ID 作正式 ID，与 confirm 路径的 PT-XX-6hex 分裂。approve 时铸新 ID 并连带处理：文件名、frontmatter id、evidence sidecar 目录迁移、正文/frontmatter 中对旧 ID 的引用（corrects/decision_map）；更新 approve 相关测试

- [x] T029 Summarizer 输出 schema 加 `steps: [{action, actor: human|agent|remote, command?, expected?}]`（`summarizer.py:9-16` docstring + `_normalize_summary`）；各类型 prompt（`prompts/summarizer_prompts.py`）增加 actor 提取要求
- [x] T030 Generator 的行为标签（`[physical]/[api:*]/[remote]/[decide]/[verify]`）改为从 `steps[].actor` 机械生成（`generator.py:258-263` 的命令渲染逻辑扩展），不再依赖 LLM 自觉
- [x] T031 `fidelity.py` 增加步骤保真检查：steps 丢失率 >30% 为 error；物理步骤（actor=human）单独统计，丢失即 error
- [x] T032 Classifier 对全文取 outline（不再只读前 8K，`classifier.py:223`）；修多主题偏移基于截断片段切全文的错误（`pipeline.py:453-464`）
- [x] T033 阅读覆盖硬不变量：pipeline 结束前排核"outline 每个 section 均被 read_document_range 覆盖"，未覆盖强制 `_supplement_extraction`，杜绝 15 轮上限静默截断（`summarizer.py:44,384`）
- [x] T034 [P] 合成评测集：`kb/tests/fixtures/eval/` 造 6-10 篇 NPI 特征文档（超长多分支排查树/物理量测混排/密集无结构纯文本/多主题混合/中英混杂），接入 `test_eval_regression.py`，记录基线指标
- [x] T035 [P] 核实并处理 Anthropic provider compact 失效（`compact.py:194` 只认 OpenAI 格式）：属实则修，证伪则删此任务并回写 spec 3.5

### D6 applies_to

- [x] T036 键已拍板（product_line/test_stage/firmware）：`schema.py` 加可选 `applies_to` 字段及校验（slug、版本约束存字符串）；`kb-config.yml` 支持 `vocabulary:` 词表段（或从现有条目聚合），作为 import 注入与 doctor lint 的数据源
- [x] T037 `handle_kb_browse` 加适用性过滤参数（未写 applies_to 的通用条目始终返回；写了的按匹配排序/过滤）
- [x] T038 `holmes doctor`（`governance.py`）加适用性过期检查：`kb-config.yml` 支持 `current_context:`，约束不符的条目仅报告不自动处理
- [x] T039 import 提取 applies_to：Summarizer prompt 注入当前词表（优先复用已有取值）+ schema 字段透传 + approve 预览中展示可改；approve 通过的新取值沉淀进词表；doctor 对词表外取值报"疑似笔误"
- [x] T040 [P] 测试：browse 过滤、doctor 报告、import 提取的端到端用例；`cd kb && pytest -q` 全绿

**Checkpoint**: M3 完成——评测集量化达标，条目携带适用性元数据。

---

## Phase 5 (M3.5): 可交付

**Goal**: 一条命令装对、agent 会用、人看得懂。

- [x] T041 打包收敛：确定 `holmes` 入口唯一指向（kb 包新版 CLI），处理根包旧 CLI 与 `agent/` 包的 entry point 冲突；验证干净环境 `pip install -e .` 后 `holmes approve --help` 等行为正确
- [x] T042 MCP 内嵌引导打磨：4 个工具的 description + `kb_browse` 首页 `guide` 字段重写（排查方法论：browse→read 摘要→按需 branch→解决后 confirm→没有则 draft；含 contributor/session_id 使用约定）
- [x] T043 文档重写：README、OPERATIONS.md、docs/（quickstart/user-guide/reference/mcp-integration/kb-management）按新命令与新行为全面更新；`kb-template/README.md` 同步
- [~] T044 telemetry 接线评估：**挂起**（按 spec 约定：集中式试点启动前再接 `emit_event()`；届时注意 telemetry/ 文档里的 `holmes kb health-export` 命令不存在，需一并设计）

---

## Phase 6: E2E 修复（真实 LLM 验证发现，2026-07-20）

- [X] T045 写操作标签根因修复：risk 分类不能依赖 LLM 自觉——Normalizer/生成层加确定性动词推断（i2cset/setpci/set/save/update/flash/load-cfg 等写动词 → 不得为 read），LLM 标注只能升级风险等级、不能降级；firmware update 类 → danger
- [ ] T046 approve "Failed to deprecate <pending-id>" 根因修复：先复现定位（同源旧条目检测是否把被审批条目自身纳入 deprecate 清单），修流程而非吞异常
- [X] T047 applies_to 噪声值根因修复：normalize 层对可选字段过滤占位噪声（unknown/n/a/na/none/未知/无，大小写不敏感）——信息缺失=字段缺省，而不是字面值；prompt 同步说明
- [X] T049 段长提速与可配置化：READ_CHUNK_CHARS 默认 20000（原 8000，常量化于 doc_access.py）；`holmes config set read_chunk_chars|direct_mode_char_limit` 写入 ~/.holmes/config.json 可覆盖（0=默认）；summarizer_prompts 消除硬编码数字；补 test_043_import_config.py 7 例
- [X] T050 doctor 条目卫生检查 + not_solved 反馈（替代原 re-tag 独立命令方案，owner 拍板并入 doctor）：行为标签误标检测（infer_command_risk 为下限）+ applies_to 占位噪声，--fix 机械修复；not_solved 证据浮出提醒人工复核；placeholder 定义收拢到 schema.py；test_043_doctor_hygiene.py 7 例；真实 KB 实战修复 PLL 7 处/BMC 3 处误标
- [X] T051 纠错场景文档：OPERATIONS.md §4.6（--corrects 纠错流程）+ §8.1（doctor 新检查项）、docs/reference.md、README.md
- [X] T052 Generator 空 draft 根因修复（评测集实测发现）：_extract_draft 跳过空 assistant 轮（OpenAI null content / Anthropic 空 block 双形态）、生成循环空响应追问×2、管线层全新重试一次；真实来源是 deepseek 系网关返回空 content
- [X] T053 类型覆盖门控（评测集实测 guideline→decision 误判）：infer_type_from_summary 仅在 Classifier 失败兜底或强 pitfall 信号时才允许覆盖，置信分类不被关键词翻转；诊断证明 Classifier 判得对、是启发式推翻
- [X] T054 doctor 进度反馈：17 步检查实时输出（progress 回调 + CLI 接线）；import 文件不存在/非 UTF-8 改干净报错
- [X] T055 交付前全量扫描一次修（产品/用户视角）：T046 证伪（已被 T022 修复）；重试反馈为空修复（attempt_report）；schema 必填字段入反馈环；stdin/内联文本实现；T048 类目缩写程序化派生；source_file 相对路径；git add -A → 只提交 contributions/；kb_read not-found hint；CLI help 指引 scenarios.md；test_043_final_sweep.py 17 例
- [ ] T048 类目缩写根因修复（已由 T055 完成，留档）：PITFALL_CAT_PREFIXES 是封闭映射无法覆盖开放类目（serdes/pll、memory 等）——未命中时从类目 slug 程序化派生缩写（取各段首字母大写，如 serdes/pll→SP、memory→MEM），派生冲突时回退 GEN；补测试

---

## Dependencies & Notes

- T003–T006（红测试）必须先于 T007–T017；T016 golden loop 依赖 T007–T015
- M2 的 T022（语义查重门控）依赖 M1 的 T012（approve 链路收敛后才有唯一挂载点）
- T036 键集合已拍板（product_line/test_stage/firmware，词表自积累）；"proven 场景维度"是否启用待 owner 定
- 每个 phase 结束跑 `cd kb && python -m pytest -q`，通过数不得回退
- 待核实项（spec 3.5）分别挂在 T019/T027/T035 顺手处理，证伪即回写 spec
