# 测试计划：KB Access Control & Governance

**Feature**: 003-kb-governance
**Date**: 2026-06-02
**依据**: spec.md、contracts/cli-commands.md、FR-001~FR-016、SC-001~SC-006

---

## 测试范围与策略

| 层次 | 工具 | 覆盖目标 |
|------|------|---------|
| 单元测试 | pytest | governance.py、history.py、decay.py、store.py 各函数 |
| 集成测试 | pytest + CliRunner | CLI 命令端到端流程（无 LLM 依赖） |
| 契约测试 | 手动/脚本 | CLI 输入输出格式符合 contracts/cli-commands.md |
| 端到端验收 | quickstart.md 脚本 | 每个 US 的完整用户操作路径 |

**不在范围**：LLM 分类逻辑、技能执行、git 冲突解析（已有独立测试）。

---

## TC-US1：已确认知识只读保护

> 对应：FR-001、FR-002、FR-003、SC-001

### TC-US1-001 不存在 write-entry 命令
- **前置**: 任意 KB 路径
- **操作**: `holmes kb write-entry PT-DB-001 --content "..."`
- **预期**: 退出码 2，输出 `No such command 'write-entry'`

### TC-US1-002 write-pending 对 verified 条目标题重复时硬拒绝（FR-004）
- **前置**: KB 中存在 `maturity: verified` 的 PT-DB-001，title="Redis connection timeout"
- **操作**: `holmes kb write-pending --content` (title 同为 "Redis connection timeout")
- **预期**: 退出码 1，JSON 输出含 `"error"` 字段且包含 `"PT-DB-001"`

### TC-US1-003 write-pending 对 proven 条目标题重复时硬拒绝
- **前置**: KB 中存在 `maturity: proven` 的条目，标题相同
- **操作**: 同 TC-US1-002
- **预期**: 退出码 1，硬拒绝

### TC-US1-004 write-pending 对 draft 条目标题重复不拒绝
- **前置**: KB 中存在 `maturity: draft` 的条目，同名
- **操作**: `holmes kb write-pending --content` (同名 title)
- **预期**: 退出码 0，返回 `pending_id`

### TC-US1-005 读取 verified/proven 条目成功（FR-002）
- **操作**: `holmes kb show PT-DB-001`
- **预期**: 退出码 0，返回完整 Markdown 内容

### TC-US1-006 维护者直接写入文件系统不受约束
- **操作**: 直接 `cp /tmp/updated.md $KB/pitfall/database/PT-DB-001.md`
- **预期**: 文件写入成功，`holmes kb show PT-DB-001` 返回新内容

### TC-US1-007 write-pending 使用 --corrects 跳过标题重复检查
- **前置**: KB 中存在 verified PT-DB-001
- **操作**: `holmes kb write-pending --content <同名内容> --corrects PT-DB-001`
- **预期**: 退出码 0，返回 `pending_id`

### TC-US1-008 write-pending --corrects 指向不存在条目时失败
- **操作**: `--corrects PT-NONEXISTENT`
- **预期**: 退出码 1，JSON 错误信息含 "not found"

---

## TC-US2：Agent 沉淀新知识到 pending

> 对应：FR-004、FR-005、FR-006、SC-002

### TC-US2-001 write-pending 新知识进入 pending 目录（FR-004）
- **操作**: `holmes kb write-pending --content <新内容>`
- **预期**: 退出码 0；`contributions/pending/` 目录出现对应 `.md` 文件；公共区不受影响

### TC-US2-002 pending 条目默认 maturity=draft
- **前置**: TC-US2-001
- **操作**: `holmes kb pending --json`
- **预期**: 对应条目 `maturity: draft`

### TC-US2-003 confirm 将 pending 条目移入公共区（FR-005）
- **前置**: pending 中存在条目
- **操作**: `holmes kb confirm <pending_id>` (交互 y\ny\n)
- **预期**: 退出码 0；条目出现在对应 `type/category/` 目录；pending 中该文件消失

### TC-US2-004 confirm 向 evidence 追加第一条记录（FR-005）
- **前置**: TC-US2-003，使用 `--contributor alice`
- **操作**: confirm 完成后读取条目
- **预期**: `evidence` 数组长度 = 1；`evidence[0].contributor = "alice"`；`maturity = "verified"`

### TC-US2-005 confirm 更新 contributors 列表（FR-012）
- **前置**: TC-US2-003，使用 `--contributor alice`
- **预期**: `contributors` 字段含 `"alice"`

### TC-US2-006 confirm 时间 ≤5 分钟可完成（SC-002）
- **操作**: 人工计时，从 write-pending 到 confirm 完成
- **预期**: 纯命令操作 <5 分钟

### TC-US2-007 reject 从 pending 删除条目不影响公共区（FR-006）
- **前置**: pending 中存在条目
- **操作**: `holmes kb reject <pending_id>`
- **预期**: 退出码 0；pending 中文件消失；公共区无变化

### TC-US2-008 pending 列表显示所有待审条目
- **前置**: 创建 2 条 pending 条目
- **操作**: `holmes kb pending --json`
- **预期**: 返回数组长度 = 2

---

## TC-US5：Evidence 驱动的成熟度自动晋升

> 对应：FR-010、FR-011、FR-012、SC-006

### TC-US5-001 update-refs 向 evidence 数组追加记录（FR-010）
- **前置**: KB 中存在 verified 条目 PT-DB-001
- **操作**: `holmes kb update-refs --ids PT-DB-001 --session-id s1 --contributor alice`
- **预期**: 退出码 0；条目 `evidence` 数组长度 +1；记录含 `session_id="s1"`、`contributor="alice"`

### TC-US5-002 同一 session 多次调用 update-refs 去重（FR-010）
- **前置**: TC-US5-001
- **操作**: 用相同 `--session-id s1` 再次调用
- **预期**: 输出 `skipped_duplicate: ["PT-DB-001"]`；`evidence` 数组长度不变

### TC-US5-003 不同 session + 不同 contributor → 自动晋升为 proven（FR-011）
- **前置**: verified 条目 PT-DB-001（evidence 为空）
- **操作**: 先 `--session-id s1 --contributor alice`，再 `--session-id s2 --contributor bob`
- **预期**: 第二次调用后 `maturity = "proven"`；输出 `maturity_promoted: [{"id": "PT-DB-001", "old": "verified", "new": "proven"}]`

### TC-US5-004 两个 session 同一 contributor 不晋升（FR-011）
- **操作**: `--session-id s1 --contributor alice`，再 `--session-id s2 --contributor alice`
- **预期**: maturity 保持 `"verified"`

### TC-US5-005 两个 contributor 同一 session 不晋升（FR-011）
- **操作**: `--session-id s1 --contributor alice` + `--session-id s1 --contributor bob`（第二次被去重）
- **预期**: maturity 保持 `"verified"`（session 去重后实际只有 1 条）

### TC-US5-006 update-refs 自动更新 contributors 列表（FR-012）
- **前置**: TC-US5-001
- **预期**: 条目 `contributors` 含 `"alice"`

### TC-US5-007 update-refs 对不存在的 ID 报告 not_found（契约）
- **操作**: `--ids PT-NONEXISTENT --session-id s1 --contributor a`
- **预期**: 退出码 0；输出 `not_found: ["PT-NONEXISTENT"]`

### TC-US5-008 evidence 多人并发追加可 git 合并无冲突（SC-006）
- **实现**: evidence 记录存储为每 session 独立 sidecar 文件（`contributions/evidence/<id>/<session_id>.json`），文件新增操作天然无冲突
- **操作**: 两个分支各调用 `update-refs` 追加不同 session 的 evidence → `git merge`
- **预期**: 合并无冲突（exit code 0）；两个 sidecar 文件均存在；`load_evidence()` 返回两条记录；`derive_maturity()` 计算结果正确
- **验证**: 已通过手动脚本测试确认 ✓ PASS

---

## TC-US3：修正已确认知识的工作流

> 对应：FR-007、FR-008、FR-009、SC-002、SC-004

### TC-US3-001 write-pending --corrects 创建修正提案（FR-007）
- **前置**: verified PT-DB-001
- **操作**: `holmes kb write-pending --corrects PT-DB-001 --content <修正内容>`
- **预期**: 退出码 0；pending 文件 frontmatter 含 `corrects: PT-DB-001`；原条目内容不变

### TC-US3-002 confirm 修正提案替换原条目（FR-008）
- **前置**: TC-US3-001
- **操作**: `holmes kb confirm <correction_id>` (y\ny\n)
- **预期**: 退出码 0；原条目 PT-DB-001 内容更新为提案内容；`maturity = "verified"`；`updated_at` 更新

### TC-US3-003 confirm 修正保存 VersionSnapshot（FR-008、SC-004）
- **前置**: TC-US3-001
- **操作**: confirm 完成后
- **预期**: `.history/PT-DB-001-*.md` 存在；snapshot 含 `replaced_at`、`replaced_by`、`snapshot_reason: "correction"`；原始内容完整保留

### TC-US3-004 confirm 修正保留原 evidence 数组（FR-008）
- **前置**: PT-DB-001 已有 2 条 evidence 记录
- **操作**: 提交并 confirm 修正
- **预期**: 更新后条目的 `evidence` 数组条数不减少

### TC-US3-005 confirm 修正保留原 contributors 列表（FR-008）
- **前置**: PT-DB-001 `contributors: [alice, bob]`
- **预期**: 修正后 `contributors` 仍含 alice、bob

### TC-US3-006 reject 修正提案原条目不受影响（FR-006）
- **前置**: TC-US3-001
- **操作**: `holmes kb reject <correction_id>`
- **预期**: PT-DB-001 内容与 reject 前完全相同；`.history/` 无新快照

### TC-US3-007 holmes kb history <id> 列出历史快照（FR-009）
- **前置**: PT-DB-001 已被修正一次
- **操作**: `holmes kb history PT-DB-001`
- **预期**: 输出至少一行，包含快照文件名和 `replaced_at` 时间戳

### TC-US3-008 holmes kb history --json 格式符合契约
- **操作**: `holmes kb history PT-DB-001 --json`
- **预期**: JSON 数组，每项含 `file`、`replaced_at`、`replaced_by`、`snapshot_reason` 字段

### TC-US3-009 修正目标不存在时 confirm 失败并报错
- **前置**: pending 条目 `corrects: PT-NONEXISTENT`
- **操作**: confirm
- **预期**: 退出码 1，提示 correction target not found

---

## TC-US4：知识成熟度自动衰减与归档

> 对应：FR-013、FR-014、FR-015、SC-003、SC-004、SC-005

### TC-US4-001 proven 超 12 个月衰减为 verified（FR-013）
- **前置**: proven 条目，evidence 最后日期 = 13 个月前
- **操作**: `holmes kb decay --json`
- **预期**: `changes` 含 `{id, old_maturity: "proven", new_maturity: "verified"}`；条目 `maturity` 已改为 `"verified"`

### TC-US4-002 verified 超 6 个月衰减为 draft（FR-013）
- **前置**: verified 条目，evidence 最后日期 = 7 个月前
- **预期**: `new_maturity: "draft"`；条目已更新

### TC-US4-003 proven 在 12 个月内不衰减（SC-005）
- **前置**: proven 条目，evidence 最后日期 = 6 个月前
- **预期**: `changes = []`；条目 maturity 不变

### TC-US4-004 衰减时保存 VersionSnapshot（FR-013、SC-004）
- **前置**: TC-US4-001 条件
- **操作**: decay 后
- **预期**: `.history/<id>-*.md` 存在；snapshot `snapshot_reason = "decay"`

### TC-US4-005 衰减记录日志（FR-014）
- **前置**: TC-US4-001 条件
- **操作**: decay 后
- **预期**: `contributions/log.md` 含 `"decay"` 和对应 entry_id；摘要含 "unreferenced N months"

### TC-US4-006 --dry-run 不写入磁盘
- **操作**: `holmes kb decay --dry-run --json`
- **预期**: 退出码 0；条目文件内容不变；`.history/` 无新增文件；但输出含预期 changes

### TC-US4-007 decay 在 ≤1000 条时 <10 秒（SC-003）
- **前置**: 种入 100 条 KB 条目
- **操作**: `time holmes kb decay --dry-run`
- **预期**: 实际耗时 <10 秒

### TC-US4-008 evidence 数组为空时使用 updated_at 作为参考日期
- **前置**: proven 条目，无 evidence，`updated_at` = 13 个月前
- **预期**: 被识别为衰减候选

### TC-US4-009 漏检率为零（SC-005）
- **前置**: 10 条应衰减 + 10 条不应衰减的混合条目
- **操作**: `holmes kb decay --dry-run --json`
- **预期**: `changes` 精确包含 10 条，无多无少

### TC-US4-010 --type 过滤限定扫描范围
- **操作**: `holmes kb decay --type pitfall --json`
- **预期**: `scanned` 数量等于 KB 中 pitfall 条目数

### TC-US4-011 draft 孤儿条目被 archive-orphans 移入 archive（FR-015）
- **前置**: KB 中存在 `maturity: draft` + `evidence: []` 的条目 PT-DRAFT-001
- **操作**: `holmes kb archive-orphans`
- **预期**: 条目文件移至 `contributions/archive/PT-DRAFT-001.md`；公共目录中原文件消失；`log.md` 含 "archived"

### TC-US4-012 有 evidence 的 draft 不被归档
- **前置**: draft 条目但 `evidence` 数组非空
- **操作**: `holmes kb archive-orphans`
- **预期**: 该条目不在 archived 列表中

### TC-US4-013 update-refs 批量更新 session 引用（FR-010）
- **操作**: `holmes kb update-refs --ids PT-DB-001,PT-DB-002 --session-id sx --contributor u`
- **预期**: 两个条目均追加了本次 evidence；`updated = ["PT-DB-001", "PT-DB-002"]`

---

## TC-FR016：成熟度冲突处理

> 对应：FR-016

### TC-FR016-001 resolve_maturity_conflict 保留较低值
- **操作** (单元): `resolve_maturity_conflict("draft", "proven")`
- **预期**: `("draft", True)`

### TC-FR016-002 resolve_maturity_conflict 两个相同值
- **操作**: `resolve_maturity_conflict("verified", "verified")`
- **预期**: `("verified", True)` — contradiction 仍为 True

### TC-FR016-003 check-conflicts 列出 contradiction=true 的条目
- **前置**: 手动在条目中写入 `contradiction: true`
- **操作**: `holmes kb check-conflicts --json`
- **预期**: 该条目出现在输出数组中

---

## TC-SC：成功指标验证

| 指标 | 测试用例 | 验收标准 |
|------|---------|---------|
| SC-001: 100% 拦截 | TC-US1-001、TC-US1-002、TC-US1-003 | 所有直接写入尝试退出码 = 1 |
| SC-002: ≤5 分钟 | TC-US2-006 | 计时验证 |
| SC-003: <10 秒 | TC-US4-007 | `time decay` 实测 |
| SC-004: 可追溯历史 | TC-US3-003、TC-US3-007、TC-US4-004 | `.history/` 文件存在且可读 |
| SC-005: 漏检率 0 | TC-US4-009 | 精确 10 条衰减候选 |
| SC-006: 无 git 冲突 | TC-US5-008 | git merge 自动合并成功 |

---

## TC-EDGE：边界与异常场景

### TC-EDGE-001 修正提案本身有误可直接编辑 pending 文件
- **操作**: 直接编辑 `contributions/pending/<pending_id>.md` 修改内容后再 confirm
- **预期**: 修改生效

### TC-EDGE-002 批量衰减部分失败时已处理条目变更保留
- **前置**: 混合正常条目 + 格式损坏条目
- **操作**: `holmes kb decay --json`
- **预期**: `errors` 含损坏条目；`changes` 含已处理条目；退出码 1

### TC-EDGE-003 空 KB 执行 decay 正常返回
- **操作**: 空 KB 路径执行 `holmes kb decay --json`
- **预期**: `{"scanned": 0, "decayed": 0, "changes": [], "errors": []}`

### TC-EDGE-004 history 对无快照条目返回空列表
- **操作**: `holmes kb history PT-NEW-001` (无快照)
- **预期**: "No snapshots found" 或 JSON `[]`

### TC-EDGE-005 证据数组去重：同一 session 引用同一条目多次只记录一条
- **操作**: 相同 session_id 调用 update-refs 两次
- **预期**: evidence 数组长度 = 1（TC-US5-002 已覆盖）

### TC-EDGE-006 archive-orphans 在无孤儿条目时正常返回
- **操作**: 空 KB 或全部条目有 evidence
- **预期**: "No orphan draft entries found." 或 `{"archived": [], "errors": []}`

---

## 执行顺序建议

```
Phase A（单元）：
  pytest tests/test_governance.py
  pytest tests/test_history.py
  pytest tests/test_decay.py
  pytest tests/test_store.py

Phase B（集成）：
  pytest tests/test_integration.py

Phase C（端到端验收）：
  bash specs/003-kb-governance/quickstart.md  # US1–US4 手动/脚本验证

Phase D（性能）：
  TC-US4-007  # decay ≤1000 条 <10 秒

Phase E（并发/git）：
  TC-US5-008  # 多人 evidence 追加 + git merge
```

---

## 已自动化覆盖状态

| 测试用例 | 自动化文件 | 状态 |
|---------|-----------|------|
| TC-US1-002~008 | `test_integration.py::TestWritePendingDuplicateCheck` | ✓ |
| TC-US2-003~005 | `test_integration.py::TestConfirmAppendsEvidence` | ✓ |
| TC-US2-007 | `test_integration.py::TestCorrectionWorkflow::test_reject_*` | ✓ |
| TC-US3-001~006 | `test_integration.py::TestCorrectionWorkflow` | ✓ |
| TC-US5-001~007 | `test_integration.py::TestUpdateRefs` | ✓ |
| TC-US4-001~012 | `test_decay.py` | ✓ |
| TC-FR016-001~002 | `test_store.py::TestResolveMaturityConflict` | ✓ |
| TC-EDGE-005 | `test_integration.py::TestUpdateRefs::test_deduplicates_*` | ✓ |
| TC-US1-001 | 手动 / quickstart.md | ✓ PASS |
| TC-US4-007 (性能) | 手动 | ✓ PASS (0.41s < 10s) |
| TC-US5-008 (git 合并) | 手动脚本 | ✓ PASS (sidecar 文件方案) |
| TC-SC-002 (计时) | 手动 | ✓ PASS (纯命令行 <5min) |
