# Holmes KB 技术债务与待办事项

> 记录已知的设计缺口、暂缓实现的功能及其原因，供后续迭代参考。
> 每条记录包含：问题描述、暂缓原因、建议实现方向。

---

## TD-001：知识淘汰链路断裂——Draft 条目永不退出 ✅ 已实现（043 验证）

**文件**：`kb/holmes/kb/decay.py`

**状态**：`run_decay()` 已包含 draft 分支（`decay.py` draft 段）：条目年龄 >
`draft_min_age_days`（默认 30 天）且最后证据距今 > `draft_stale_months`
（默认 3 个月）时自动调用 `archive_orphan()` 归档，并写入 log。两个阈值从
`kb-config.yml` 的 `decay:` 段读取，缺省用默认值。僵尸 draft 问题已消除。

**原始问题**（存档）：
`run_decay()` 只对 `proven` / `verified` 条目做降级，`draft` 条目直接跳过（`continue`）。
`archive_orphan()` 只处理从未有过证据的孤儿 draft。

结果：条目经过 `proven → verified → draft` 完整 decay 后，因为 evidence 目录里仍有历史证据文件，永远不会被自动 archive。形成"僵尸 draft"——仍出现在搜索结果和 Agent 查询中，永远不会退出 KB。

**实现方向**：

在 `run_decay()` 中补充 `draft` 分支，用两个维度同时判断，避免误删新条目：

```python
if maturity == "draft":
    last_ref = _get_reference_date(metadata_with_evidence)
    months_stale = _months_since(last_ref)
    age_days = (datetime.now(timezone.utc) - created_at).days
    if age_days > draft_min_age_days and months_stale > draft_stale_months:
        archive_orphan(kb_root, entry_id)
```

- `age_days > draft_min_age_days`：条目本身存在超过 N 天，排除刚 import 的新条目
- `months_stale > draft_stale_months`：最后证据距今超过 M 个月，确认真正无人引用

`kb-config.yml` 新增两个配置项：
```yaml
decay:
  draft_min_age_days: 30     # 条目至少存在 30 天才考虑归档（默认值）
  draft_stale_months: 3      # 最后证据距今超过 3 个月才归档（默认值）
```

---

## TD-002：Archive 时未同步清理关联 Skill

**文件**：`kb/holmes/kb/decay.py` → `archive_orphan()`

**状态**：**仍开放**。TD-001 已实现（draft 会自动 archive），孤儿 Skill 问题随之变得实际——`archive_orphan()` 目前仍只移动条目 `.md` 文件，不处理 `skills/` 下关联的 Skill。

**问题**：
`archive_orphan()` 仅将条目的 `.md` 文件移动到 `contributions/archive/`，不处理 `skills/` 目录下关联的 Skill。条目归档后，对应的 `SKILL.md` 成为孤儿文件，长期积累会造成 `skills/` 目录膨胀，并可能被 Agent 错误调用。

**暂缓原因**：
~~与 TD-001 同步：在 draft 自动 archive 未实现之前，`archive_orphan()` 调用频率极低（仅手动触发），孤儿 Skill 问题尚不紧迫。待 TD-001 实现后需一并处理。~~
TD-001 已实现，此项成为下一步候选。

**建议实现方向**：
在 `archive_orphan()` 中，归档条目 `.md` 文件后，查找 `skills/` 目录下 `SKILL.md` 内 `linked_entry` 字段等于该条目 ID 的 Skill 目录，一并移动到 `contributions/archive/skills/`。

---

## TD-003：搜索结果未按 Evidence 最新时间排序 ◐ 部分实现（043）

**文件**：`kb/holmes/kb/search.py`（及 Agent 侧搜索调用）

**状态**：**部分实现**。`search.py` 已构建 evidence 日期索引（`_build_evidence_date_index`）并参与排序：
- `BM25Backend`：主排序仍为 BM25 相关度分数，evidence 最新时间作为次要排序键
- `LinearScanBackend`：主排序为 evidence 最新时间，分数次之

仍未实现：以 `max(evidence[*].date)` 为**第一**排序键（BM25 路径下相关度仍优先于新鲜度）；`kb_browse` 的排序（maturity → updated_at）同样未按 evidence 日期。

**问题**：
在"import 永远新建"策略下，同一主题可能同时存在新旧两批条目。旧条目可能 maturity 为 `proven`（历史上积累过证据），新条目刚创建为 `draft`。当前搜索结果倾向于返回 maturity 更高的条目，导致用户/Agent 优先看到旧的（可能有问题的）知识，与 re-import 修正的初衷相悖。

**暂缓原因**：
搜索排序策略涉及 Agent 侧展示逻辑，需要与 Agent 端一起联调，不适合在 import pipeline 改造中独立修改。

**建议实现方向**：
搜索结果排序优先使用 `max(evidence[*].date)`（evidence 最新时间）而非 maturity 等级。无 evidence 的条目排在有 evidence 的条目之后。同等 evidence 时间的条目再按 `created_at` 降序排列（优先展示新创建的）。

---

## TD-004：Import 不支持知识删除

**文件**：`kb/holmes/kb/agent/pipeline.py`

**状态**：**仍开放**（043 部分缓解）。`holmes approve` 现在会检测同一 `source_file` 的旧 confirmed 条目并提示标记为 deprecated——"重新 import 替换旧知识"链路已通；但"源文档删掉某章节 → 对应条目删除"仍不支持。手动删除可用已存在的 `holmes delete <entry-id>`（软删除到 `_trash/`）。

**问题**：
当前 import pipeline 只支持 Create（新建）操作，不支持 Delete。当源文档删除了某个章节（某个故障的解决方案被废弃），对应的 KB 条目无法通过重新 import 删除，只能依赖 evidence 机制自然淘汰或手动删除。

**暂缓原因**：
在没有"来源追踪"（记录每个条目来自哪个文档）的情况下，无法可靠判断"哪些存量条目应该被这次 import 删除"，贸然删除有误删其他文档产生的条目的风险。来源追踪的引入会增加 schema 复杂度，与现有"条目与文档解耦"的设计原则冲突。

**建议实现方向**：
不做自动删除。通过 TD-001 的 evidence 过期机制自然淘汰无效知识。如需主动删除，提供 `holmes delete <entry-id>` 命令供用户手动操作，并同步删除关联 Skill（参考 TD-002）。

---

## TD-005：条目更新时未同步重建关联 Skill

**文件**：`kb/holmes/kb/agent/pipeline.py`、`kb/holmes/kb/agent/tools.py`

**状态**：**仍开放**。import 仍为"永远新建"策略，不触发此问题；但勘误流程（`write-pending --corrects` + `holmes confirm` 替换原条目）同样不会重建关联 Skill。

**问题**：
在当前（024 之前的）dedup 路径中，当 KB 条目 body 被更新（新 Resolution 内容），关联的 `SKILL.md` 不会自动重建，导致 KB 条目已修复但 Skill 内容仍是旧版。

**暂缓原因**：
feature 024 采用"永远新建"策略，import 不再走 update 路径，此问题在新策略下不会通过 import 触发。但若未来其他工具（手动编辑、外部 API）调用 `update_kb_entry`，仍会触发此问题。

**建议实现方向**：
在 `update_kb_entry` 工具执行写入后，检查该条目是否存在关联 Skill，存在则从新 body 的 Resolution 段重新生成 `SKILL.md`，可复用 `SkillAdvisor` + `create_skill()` 逻辑。

---

*最后更新：2026-07-20（043-kb-hardening 后核对）*
