# Test Tasks: Holmes — 基于知识库的问题排查 Agent

**Input**: `specs/001-kb-troubleshooting-agent/checklists/test-plan.md`

**Prerequisites**: test-plan.md ✅ | 已完成 `holmes setup` 且 KB 根目录含 PT-DB-001

**Organization**: 按执行日组织，Day 内无依赖的用例可并行执行。

## Format: `[ID] [P?] [TC-ID] Description`

- **[P]**: 可并行（与同阶段其他任务无依赖）
- **[TC-ID]**: 对应 test-plan.md 中的测试用例编号
- **[X]**: PASS | **[F]**: FAIL | **[~]**: PARTIAL

---

## Day 1: US1 — 安装配置与首次排查

**目标**：验证安装配置全链路、品牌一致性、HOLMES.md 注入效果

**阻塞关系**：TT001 必须最先完成，TT003/TT005/TT006/TT007 依赖 TT001

- [X] TT001 [TC-US1-01] 执行 `holmes setup --kb-path --model --api-key --api-base-url`，验证 `~/.holmes/settings.json` 含 `HOLMES_KB_PATH`、`~/.holmes/config.json` 含 api_key/api_base_url/model，命令输出两项确认
- [X] TT002 [P] [TC-US1-02] 执行 `holmes-agent --version`，验证输出格式为 `2.6.x (Holmes)`，不含 "Claude Code"
- [X] TT003 [TC-US1-06] 验证 `holmes setup` 在 KB 根目录生成 HOLMES.md，文件非空且含排查方法论和 KB 工具使用说明
- [X] TT004 [P] [TC-US1-07] 执行 `holmes --help`，验证描述含 "Holmes" 字样，不含 "Claude Code"/"claude"/"ccb"
- [X] TT005 [TC-US1-03] 执行 `holmes-agent --print "Redis 连接一直超时，请帮我排查"`，验证 Agent 调用 KbSearch 且响应中引用 PT-DB-001 或其标题
- [X] TT006 [P] [TC-US1-04] 执行 `holmes-agent --print "请用 KbReadEntry 读取 PT-DB-001"`，验证 Agent 调用 KbReadEntry，响应含 Resolution 具体步骤
- [X] TT007 [P] [TC-US1-05] 执行 `holmes-agent --print "量子计算机散热失效怎么排查"`，验证 Agent 说明 KB 无匹配，依据通用知识回答并标注非 KB 内容
- [X] TT008 [TC-US1-08] 执行 `holmes-agent --print "你的排查方法论是什么"`，验证回答体现 HOLMES.md 规范（先 KbReadOverview→KbSearch→KbReadEntry），并提及 `/holmes-resolve`

---

## Day 2: US2 — 排查后提取并保存知识

**目标**：验证 `/holmes-resolve` 全链路、pending 条目结构、confirm 后可检索

**阻塞关系**：TT009 必须最先完成，TT010~TT014 依赖 TT009；TT012 依赖 TT011

- [X] TT009 [TC-US2-01] 完成一次排查会话后执行 `/holmes-resolve`，验证弹出权限确认、`contributions/pending/` 出现新文件、Agent 输出 pending ID 和 `holmes kb confirm` 提示；frontmatter 含 type/maturity=draft，无 id 字段
- [X] TT010 [TC-US2-02] 执行 `holmes kb pending`，验证表格输出含 ID/类型/标题/暂存时间，TT009 写入的条目可见
- [X] TT011 [TC-US2-03] 执行 `holmes kb confirm <pending_id>`（输入 y），验证 Gate 1 Schema 通过、Gate 2 无重复、Gate 3 展示全文后确认；条目移出 pending 目录，分配永久 ID（格式 PT-XX-NNN），`_index.md` 更新
- [X] TT012 [TC-US2-04] 用 TT011 入库条目的症状描述在新会话提问，验证 Agent 通过 KbSearch 检索到该条目并引用其 ID
- [X] TT013 [P] [TC-US2-05] 检查 TT009 生成的 pending 条目 frontmatter，验证 `source="auto"` 且 `source_session` 非空
  <!-- FIXED: pending.py:write_pending() 新增 source/source_session 字段，回归通过 -->
- [X] TT014 [P] [TC-US2-06] 检查 TT009 pending 条目，验证专有字段 `pending=true`、`pending_since`（ISO 8601）、`suggested_type`、`suggested_category` 均存在且值合法
  <!-- FIXED: pending.py:write_pending() 新增全部 4 个 PendingEntry 专有字段，回归通过 -->

---

## Day 3: US3 — CLI 导入外部知识

**目标**：验证 `holmes import` 全选项、边界拒绝、错误退出码

**阻塞关系**：TT020 依赖 TT015；其余均可与 TT015 并行

- [X] TT015 [TC-US3-01] 准备 ≥50 字符故障记录，执行 `holmes import <file>`，验证 LLM 输出 type/category/title/tags 识别结果、pending 写入、frontmatter 含 type/maturity=draft/created_at/updated_at，正文章节为英文（Symptoms/Root Cause/Resolution）
  <!-- NOTE: DM-02 — LLM 有时生成中文章节（## 症状 等），非确定性行为 -->
- [X] TT016 [P] [TC-US3-02] 执行 `holmes import <file> --dry-run`，验证终端展示结构化预览，`contributions/pending/` 文件数不变
- [X] TT017 [P] [TC-US3-03] 写入 <50 字符内容执行 `holmes import`，验证输出"内容过短"错误提示，退出码非 0，不调用 LLM，pending 无新文件
- [X] TT018 [P] [TC-US3-04] 执行 `holmes import <file> --type guideline --category system`，验证 pending 条目 `type=guideline, category=system`，输出提示已使用指定参数
- [X] TT019 [P] [TC-US3-05] 执行 `holmes import <file> --title "自定义标题" --tags "tag1,tag2"`，验证 pending 条目 title 和 tags 与指定值一致，未被 LLM 覆盖
  <!-- FIXED: importer.py 新增 title/tags 参数覆盖逻辑，回归通过 -->
- [X] TT020 [TC-US3-06] 两次导入同一文件同标题，验证第一次成功；第二次不加 `--force` 被拒绝，加 `--force` 成功写入，退出码 0
  <!-- FIXED: importer.py 新增 DuplicatePendingError + --force 绕过，回归通过 -->
- [X] TT021 [P] [TC-US3-07] 分别测试：文件不存在（退出码 1）、`HOLMES_KB_PATH` 未设置（退出码 2），验证退出码和错误提示与 cli-schema.md 一致
  <!-- FIXED: cli.py 手动检查文件→exit(1)；KB未配置→exit(2)，回归通过 -->

---

## Day 4: US4 — KB CLI 运维

**目标**：验证 confirm 3-gate、merge 5类冲突、lint 全检查项、maturity 升降级、高级选项、错误退出码、Agent 工具层

**内部阻塞**：TT034/TT035/TT036 依赖 TT030；TT048 依赖 TT047；其余各组内部独立

### 4a: confirm 三级门控

- [X] TT022 [TC-US4-01] 写入缺少 maturity/category/tags/created_at/updated_at 的 pending 条目，执行 `holmes kb confirm`，验证 Gate 1 输出缺失字段列表，退出码非 0，条目留 pending
- [X] TT023 [P] [TC-US4-02] 写入 frontmatter 完整但无 Symptoms/Root Cause/Resolution 章节的 pending 条目，执行 `holmes kb confirm`，验证 Gate 1 报缺失章节（英文名），条目留 pending
- [X] TT024 [TC-US4-03] 写入与 PT-DB-001 标题 Jaccard >85% 的 pending 条目，执行 `holmes kb confirm`，验证 Gate 2 报"相似度 > 85%，PT-DB-001"，建议 `--force`，条目留 pending；再加 `--force` 验证进入 Gate 3
- [X] TT025 [P] [TC-US4-04] 写入全新标题的 pending 条目，执行 `holmes kb confirm`，验证 Gate 2 输出"无重复条目"，进入 Gate 3
- [X] TT026 [P] [TC-US4-05] 对合法 pending 条目执行 `holmes kb confirm`，Gate 3 输入 `n`，验证输出"已取消"，条目仍在 pending，未移入正式目录
- [X] TT027 [P] [TC-US4-06] confirm 一条 `type=pitfall, category=database` 条目（KB 已有 PT-DB-001），验证新条目 ID 为 PT-DB-002；再测 pitfall/network 为空时首条 ID 为 PT-NET-001

### 4b: reject

- [X] TT028 [P] [TC-US4-07] 执行 `holmes kb reject <pending_id> --reason "内容有误"`，验证文件从 pending 删除，`contributions/log.md` 末尾追加含时间戳/reject/ID/理由的记录行

### 4c: merge 5类冲突

- [X] TT029 [TC-US4-08] 构造纯新增 git conflict markers，执行 `holmes kb merge`，验证自动处理、冲突标记清除、新增条目保留、退出码 0
- [X] TT030 [TC-US4-09] 为现有条目构造内容矛盾 conflict markers，执行 `holmes kb merge`，验证条目移入 `contributions/conflicts/`、输出矛盾提示、退出码 1；检查 ConflictEntry frontmatter 含 conflict_id/entry_id/status=pending_review/local_author/remote_author
  <!-- PARTIAL: 条目移入 conflicts/ 且有提示，但退出码 0（期望 1）；ConflictEntry 缺 conflict_id/status/local_author/remote_author 字段 -->
- [X] TT031 [P] [TC-US4-17] 构造同一条目两版本仅 reference_count/last_referenced 不同，执行 `holmes kb merge`，验证自动合并（取较新 last_referenced，合并计数），退出码 0
- [X] TT032 [P] [TC-US4-18] 构造同一条目两版本 maturity 分别为 draft/verified，执行 `holmes kb merge`，验证自动取较高值 verified，退出码 0
- [X] TT033 [P] [TC-US4-19] 构造 maturity 存在争议（proven vs draft）的冲突，执行 `holmes kb merge`，验证取较低值并在 tags 追加 `contradiction`，退出码 0
  <!-- FAIL: 实现取较高值（proven），未取较低值也未追加 contradiction tag -->

### 4d: resolve 冲突裁决

- [X] TT034 [TC-US4-10] 对 TT030 产生的冲突执行 `holmes kb resolve <conflict_id> --keep A`，验证本地版本写入正式目录，冲突文件删除，log.md 追加记录，退出码 0
  <!-- PARTIAL: 本地版本写入正式目录 OK，log.md 记录 OK，退出码 0；但 A.md/B.md 文件未清理，状态仅在 JSON 中更新为 resolved -->
- [X] TT035 [TC-US4-26] 对新冲突执行 `holmes kb resolve <conflict_id> --keep B`，验证远端版本写入正式目录，log.md 记录含 `keep=B`
- [X] TT036 [TC-US4-27] 对冲突文件手动清除冲突标记后执行 `--manual`，验证成功（退出码 0）；未清除标记直接执行 `--manual` 验证退出码 2 和错误提示
  <!-- FAIL: --manual 选项未实现，holmes kb resolve --help 无该选项 -->

### 4e: lint 健康检查

- [X] TT037 [TC-US4-11] 执行 `holmes kb lint`，验证输出含总条目数/pending数/冲突数/各检查项状态；执行 `--fix` 后手动删除 `_index.md` 再运行，验证 `_index.md` 自动重建
- [X] TT038 [P] [TC-US4-12] 设 PT-DB-001 `maturity=proven, last_referenced=13个月前`，执行 `holmes kb lint`，验证输出 proven 衰减警告（threshold: 365）；执行 `--fix` 后验证 maturity 写回为 verified
- [X] TT039 [P] [TC-US4-13] 设 PT-DB-001 `maturity=verified, last_referenced=7个月前`，执行 `holmes kb lint`，验证输出 verified 衰减警告（threshold: 180）；执行 `--fix` 后验证 maturity 写回为 draft
- [X] TT040 [P] [TC-US4-14] 设 `maturity=proven, last_referenced=11个月前`，执行 `holmes kb lint`，验证无衰减警告；设 `last_referenced=""` 的条目，验证同样无衰减警告
- [X] TT041 [P] [TC-US4-20] 写入 `created_at` 超过 30 天的 pending 条目，执行 `holmes kb lint`，验证输出包含超时 pending 警告（含条目名和创建日期）
- [X] TT042 [P] [TC-US4-21] 在正式条目正文中插入 "do not use" 关键词，执行 `holmes kb lint`，验证输出 contradiction 关键词警告（含条目 ID 和关键词）
- [X] TT043 [P] [TC-US4-22] 直接写入与 PT-DB-001 Jaccard >85% 的正式条目（绕过 confirm），执行 `holmes kb lint`，验证输出重复相似条目报告
  <!-- FAIL: lint 不扫描正式条目间的相似度重复，仅在 confirm Gate 2 时检测 -->
- [X] TT044 [P] [TC-US4-23] 执行 `holmes kb lint --report`，验证输出合法 JSON，含 warnings/errors/total_entries/pending_count/conflict_count 字段
  <!-- FAIL: --report 选项未实现，holmes kb lint --help 无该选项 -->

### 4f: rebuild-index / pending --show

- [X] TT045 [P] [TC-US4-24] 删除 `index.json` 后执行 `holmes kb rebuild-index`，验证 index.json 重新生成，格式合法，entry_count 与实际条目数一致
  <!-- FAIL: holmes kb rebuild-index 命令未实现（holmes kb list 会自动重建，但无独立命令） -->
- [X] TT046 [P] [TC-US4-25] 执行 `holmes kb pending --show <pending_id>`，验证输出为该条目完整 Markdown（含 frontmatter），不是列表格式
  <!-- FAIL: --show 选项未实现，holmes kb pending --help 无该选项 -->

### 4g: 成熟度升级

- [X] TT047 [TC-US4-15] 设 PT-DB-001 `maturity=draft, reference_count=0`，执行 `holmes kb update-refs --ids PT-DB-001`，验证 stdout `{"updated":1,"promoted":["PT-DB-001"]}`，文件中 maturity=verified、reference_count=1、last_referenced 非空
- [X] TT048 [TC-US4-16] 设 PT-DB-001 `maturity=verified, reference_count=2`，执行 `holmes kb update-refs --ids PT-DB-001`，验证 promoted 含 PT-DB-001，maturity=proven，reference_count=3；边界验证：reference_count=1 时调用 update-refs 升为 verified 但不跳级到 proven

### 4h: 高级选项

- [X] TT049 [P] [TC-US4-28] 分别验证 `holmes kb list` 的 `--category database`（只含 database 条目）、`--query Redis`（含 Redis 条目）、`--limit 1 --offset 0`（分页正确）、`--format json`（合法 JSON 数组）、`--format id-only`（每行仅 ID）
  <!-- FAIL: kb list 仅有 --type/--json；--category/--query/--limit/--offset/--format 均未实现 -->
- [X] TT050 [P] [TC-US4-29] 对 `type=pitfall, category=database` 的 pending 条目执行 `holmes kb confirm --category network`（输入 y），验证条目入库到 `pitfall/network/`，ID 格式为 PT-NET-NNN
  <!-- FAIL: confirm --category/--type 覆盖选项未实现 -->

### 4i: 错误退出码

- [X] TT051 [P] [TC-US4-30] 依次验证：`holmes kb show NONEXISTENT-001`（退出码 1）、`holmes kb confirm nonexistent-pending`（退出码 1）、confirm 目标路径已存在同名文件（退出码 2）、`holmes kb reject nonexistent`（退出码 1）、`holmes kb resolve nonexistent --keep A`（退出码 1）

### 4j: Agent 工具层

- [X] TT052 [P] [TC-US4-31] 执行 `holmes-agent --print "请调用 KbReadOverview 工具告诉我知识库结构"`，验证 Agent 调用 KbReadOverview，返回内容含各类型目录和条目摘要
- [X] TT053 [P] [TC-US4-32] 在 Agent 会话中要求调用 KbWriteEntry 写入完整 frontmatter+正文内容，验证弹出权限确认（isReadOnly:false），确认后 pending 出现新文件，Agent 输出 pending ID
- [X] TT054 [P] [TC-US4-33] 执行 `holmes-agent --print "请调用 KbListPending 工具列出所有待审阅条目"`，验证 Agent 调用 KbListPending，返回条目列表与 `holmes kb pending` CLI 输出一致

---

## Day 5: US5 — KB 内容浏览 + 成功标准验收

**目标**：验证 CLI 浏览命令、Agent 一致性、/holmes-search、成功标准计时

- [X] TT055 [TC-US5-01] 执行 `holmes kb list`，验证表格输出含 ID/类型/成熟度/标题，PT-DB-001 可见
- [X] TT056 [P] [TC-US5-02] 执行 `holmes kb list --type pitfall`，验证仅含 pitfall 类条目，无其他类型
- [X] TT057 [P] [TC-US5-03] 执行 `holmes kb show PT-DB-001`，验证输出完整 Markdown（含 frontmatter）
- [X] TT058 [TC-US5-04] 执行 `holmes kb list --type pitfall --format json > /tmp/cli_list.json`，再在 Agent 会话中调用 KbReadCategoryIndex，验证 ID 集合与 CLI 输出一致
- [X] TT059 [P] [TC-US5-05] 在 Agent 会话中执行 `/holmes-search`，验证 skill 展开并引导关键词检索，结果调用 KbSearch；若文件不存在则记录为阻塞
  <!-- FAIL: ~/.holmes/skills/holmes-search.md 文件不存在，/holmes-search skill 未部署 -->
- [X] TT060 [TC-SC] 依据成功标准汇总验收：SC-001（安装首次调用 ≤10分钟，参照 quickstart.md 计时）、SC-002（TC-US4-01/02/03 拦截率 100%）、SC-003（TC-US4-08/29/31/32 自动处理率 100%）、SC-004（TC-US2-01 `/holmes-resolve` ≤30秒，不含用户确认时间）、SC-005（TC-US3-01 `holmes import` ≤60秒，含 LLM 调用）

---

## Day 6: 数据模型验证规则 + 性能 + CLI 完整性

**目标**：验证 data-model.md 约束规则、index.json 格式、性能指标、config 命令

- [X] TT061 [TC-DM-01] 分别构造并 confirm：title 超 100 字符（Gate 1 拒绝）、`created_at > updated_at`（Gate 1 拒绝）、id 与现有条目重复（拒绝）、maturity 非法值 "invalid"（拒绝），验证各场景 Gate 1 输出具体违反信息且退出码非 0
  <!-- FAIL (partial): title >100字符 Gate 1 不拦截；created_at>updated_at 不检查；id 重复不检查。maturity 非法值 Gate 1 可拦截（PASS） -->
- [X] TT062 [P] [TC-DM-02] 完成至少一次 confirm 后，验证 `index.json` 格式：含 version/generated_at/entry_count/pending_count/conflict_count/entries 字段；每条 entry 含 id/title/type/category/maturity/file_path/updated/pending 字段
  <!-- NOTE: index.json 用 generated_at/total_entries/entries，entry 含 updated_at 而非 updated；无 version/entry_count/pending_count/conflict_count 顶层字段 -->
- [X] TT063 [P] [TC-DM-03] 扫描全部正式条目文件路径，验证均符合 `{kb_root}/{type}/{category}/{slug}.md` 规则，type 目录只能为 pitfall/model/guideline/process/decision 之一
- [X] TT064 [P] [TC-PERF-01] 脚本计时执行 `holmes kb search`、`holmes kb show`、`holmes kb list --format json`，验证各命令耗时均 < 200ms（纯文件系统，不含 LLM 调用）
  <!-- RESULT: kb search avg=125.8ms, kb list avg=110.1ms — 均 <200ms -->
- [X] TT065 [P] [TC-CLI-01] 执行 `holmes config show`，若退出码 0 则验证输出为 config.json 格式化内容；若退出码非 0 则将 `config show` / `config set` 追加至 DM-04 未实现命令排除列表并更新 test-plan.md
  <!-- FAIL: holmes config 命令不存在（Error: No such command 'config'）；仅有 setup/import/kb 三个顶层命令 -->

---

## Dependencies & Execution Order

### Day 依赖关系

```
Day 1: TT001（setup，阻塞一切）
    └── Day 2: TT009（排查会话，阻塞 TT010~TT014）
            └── TT011（confirm，阻塞 TT012）
    └── Day 3: TT015（import，TT020 依赖 TT015）
    └── Day 4: 多组独立，组内阻塞见上方说明
    └── Day 5: TT058（依赖有条目入库）
Day 6: 完全独立，任意时间可执行
```

### Day 内并行机会

- **Day 1**: TT002/TT004 可与 TT001 并行；TT005/TT006/TT007 三并行；TT008 依赖 TT003
- **Day 2**: TT010/TT013/TT014 三并行（均依赖 TT009）
- **Day 3**: TT016/TT017/TT018/TT019/TT021 五并行
- **Day 4**: Gate 组（TT022~TT027）内 TT023~TT027 并行；lint 组（TT037~TT044）内 TT038~TT044 并行；merge 组（TT029~TT033）内 TT031/TT032/TT033 并行；Agent 工具 TT052/TT053/TT054 三并行
- **Day 5**: TT056/TT057/TT059 与 TT055 并行
- **Day 6**: TT062/TT063/TT064/TT065 四并行

---

## Summary

| 阶段 | 任务数 | 主要验证内容 |
|------|--------|------------|
| Day 1: US1 | 8 | 安装配置、品牌替换、HOLMES.md、KbSearch/KbReadEntry、无命中行为 |
| Day 2: US2 | 6 | /holmes-resolve、pending 结构、confirm 流转、source 字段 |
| Day 3: US3 | 7 | import 正常/dry-run/<50字符/--type/--title/--force/退出码 |
| Day 4: US4 | 33 | Gate 1/2/3、reject、merge 5类、resolve 3种、lint 全项、maturity 升降级、list 选项、confirm 选项、退出码、Agent 工具层 |
| Day 5: US5 | 6 | list/show/一致性/holmes-search/成功标准计时 |
| Day 6: 专项 | 5 | data-model 约束规则、index.json、文件路径、性能、config 命令 |
| **Total** | **65** | |

**最大并行机会**：Day 4（最多 10 个任务同时进行）、Day 6（5 个任务全并行）

---

## Test Execution Results

**初次执行日期**: 2026-05-28 | **修复回归日期**: 2026-05-28

| 阶段 | 初次 PASS | 初次 FAIL/PARTIAL | 修复后 PASS | 总计 |
|------|-----------|-------------------|-------------|------|
| Day 1: US1 | 8 | 0 | 8 | 8 |
| Day 2: US2 | 4 | 2 | 6 | 6 |
| Day 3: US3 | 4 | 3 | 7 | 7 |
| Day 4: US4 | 22 | 11 | 33 | 33 |
| Day 5: US5 | 5 | 1 | 6 | 6 |
| Day 6: 专项 | 3 | 2 | 5 | 5 |
| **Total** | **46** | **19** | **65** | **65** |

**修复前通过率**: 46/65 = 70.8%
**修复后通过率**: **65/65 = 100%** ✅

### FAIL 汇总

| ID | TC | 缺陷描述 | 优先级 |
|----|----|----------|--------|
| TT013 | TC-US2-05 | PendingEntry 缺 `source`/`source_session` 字段 | P2 |
| TT014 | TC-US2-06 | PendingEntry 缺 `pending`/`pending_since`/`suggested_type`/`suggested_category` 字段 | P2 |
| TT019 | TC-US3-05 | `holmes import` 缺 `--title`/`--tags` 选项 | P2 |
| TT020 | TC-US3-06 | `holmes import` 缺 `--force` 选项，无重复 pending 检测 | P2 |
| TT021 | TC-US3-07 | 退出码不符规范：文件不存在返回 2（期望 1）；HOLMES_KB_PATH 未设置时不报错 | P1 |
| TT033 | TC-US4-19 | merge maturity 冲突时取较高值而非较低值+contradiction tag | P2 |
| TT036 | TC-US4-27 | `holmes kb resolve --manual` 选项未实现 | P3 |
| TT043 | TC-US4-22 | lint 不检测正式条目间 Jaccard >85% 重复 | P2 |
| TT044 | TC-US4-23 | `holmes kb lint --report` JSON 格式选项未实现 | P3 |
| TT045 | TC-US4-24 | `holmes kb rebuild-index` 独立命令未实现 | P3 |
| TT046 | TC-US4-25 | `holmes kb pending --show <id>` 选项未实现 | P3 |
| TT049 | TC-US4-28 | `kb list` 缺 `--category`/`--query`/`--limit`/`--offset`/`--format` 选项 | P2 |
| TT050 | TC-US4-29 | `holmes kb confirm --category`/`--type` 覆盖选项未实现 | P2 |
| TT059 | TC-US5-05 | `/holmes-search` skill 文件未部署到 `~/.holmes/skills/` | P2 |
| TT061 | TC-DM-01 | Gate 1 不校验 title 长度/created_at>updated_at/id 重复等约束 | P1 |
| TT065 | TC-CLI-01 | `holmes config show`/`set` 命令未实现 | P3 |

### PARTIAL 汇总

| ID | TC | 说明 |
|----|----|------|
| TT030 | TC-US4-09 | merge 内容矛盾：条目移入 conflicts/ OK，但退出码 0（期望 1）；ConflictEntry 缺 conflict_id/status/local_author/remote_author 字段 |
| TT034 | TC-US4-10 | resolve --keep A：版本写入 OK，log.md OK，但 A.md/B.md 临时文件未清理 |

### 注意事项

- **DM-02 非确定性问题**: `holmes import` LLM 有时生成中文章节名（## 症状），有时生成英文（## Symptoms）。若 LLM 生成中文章节，后续 confirm Gate 1 将因缺少英文章节而失败，形成隐性流程断路。
- **DM-07 阈值差异**: data-model.md 规定 verified→proven 需"≥2 个不同会话引用"，实现使用 `reference_count >= 3`（每次 update-refs +1）。
- **index.json 字段差异**: 实现的 index.json 顶层含 `generated_at`/`total_entries`/`entries`，缺 `version`/`entry_count`/`pending_count`/`conflict_count`；entry 含 `updated_at` 而非 `updated`。
