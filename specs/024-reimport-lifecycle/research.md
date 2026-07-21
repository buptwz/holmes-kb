# Research: Import Pipeline 永远新建策略

## 现有实现分析

### 跨文档 dedup 存在两处

**1. pipeline.py — `_run_dedup_pass()`（Phase 2.5）**
- 对每个新草稿提取 `## Root Cause`，在 KB 中同 category 内找相似度 ≥ 0.8 的存量条目
- 匹配到 → 用新草稿 body 覆盖旧条目，跳过 create 路径
- 问题：跨文档去重，阻止了新知识的创建

**2. runner.py — `_IMPORT_SYSTEM_PROMPT` + `_pending_dedup_match` 拦截**
- system prompt 第3步指示 LLM 调用 `compare_root_cause` 做跨 KB 语义去重
- `_dispatch_tool` 里有 `write_kb_entry` 拦截：若 `_pending_dedup_match` 命中则转 `update_kb_entry`
- 注意：`runner.run()` 当前已全量委托给 `ThreePhaseImportPipeline`，runner 的 LLM loop 不再执行，此处为半死代码，但 system prompt 仍在定义中

### 文档级 hash 预检查（需保留）
- `pipeline.py` 开头：`_find_all_entries_by_hash` 查找 `source_hash` 匹配的存量条目
- 完全相同文档 → 直接 skip，正确行为，保留

### 单次 import 内部草稿间目前无去重
- `_run_dedup_pass` 只比较草稿 vs 存量条目，不比较草稿 vs 草稿
- US2 需要新增：同一次 import 中多个草稿互相比较

## 技术决策

### Decision 1：`_run_dedup_pass` 改为草稿内去重
- 原名改为 `_run_intra_import_dedup`，语义明确
- 逻辑改为：对 `kp_drafts` 内的草稿两两比较 root-cause 相似度
- 相似度 ≥ 0.8 → 保留第一个（section_start 更早的），丢弃后续，在 report 标注
- 不再查询或修改任何存量 KB 条目

### Decision 2：`compare_root_cause` 仅用于草稿间比较
- `compare_root_cause` 工具本身保留（仍有 runner 侧使用），但 pipeline 中不再用它查 KB 存量
- 草稿间比较直接提取两个草稿的 root-cause 文本做字符串相似度，无需 LLM 调用（简单实现）
- 备选：若草稿 root-cause 文本超过 200 字差异，再用 `compare_root_cause` LLM 调用

### Decision 3：`runner.py` system prompt 清理
- 移除第3步（`read_kb_entries_by_category + compare_root_cause` 跨 KB 语义去重）
- 移除第5步中的 `update_kb_entry (merge)` 说法，改为仅 `write_kb_entry (new)`
- 移除 `_pending_dedup_match` 及 `write_kb_entry` 拦截逻辑（runner 不再执行 LLM loop，但仍清理避免误导）

### Decision 4：草稿间相似度算法
- 使用简单的序列相似度（`difflib.SequenceMatcher`）比较 root-cause 文本，无 API 调用
- 阈值 0.8 与现有 dedup pass 保持一致
- 非 pitfall 类型无 Root Cause 章节 → 用 title 做比较兜底
