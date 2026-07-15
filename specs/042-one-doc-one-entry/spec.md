# 042 — One Doc One Entry: Import Pipeline & MCP Redesign

## 1. Problem Statement

当前 import 管线将一个源文档拆分为多个 KB 条目（Classic 路径拆 KP，DAG 路径拆 tree），导致：

1. **知识碎片化**：一个 README 生成 19 个条目，每个只有 2-3 句话，信息密度极低
2. **上下文丢失**：拆分后每个条目失去文档语境，"什么场景该用 Dynamo" 这种决策知识直接消失
3. **大量重复**：同源文档多次导入产生重复条目，MCP Agent 搜索返回 3 个一样的 Quick Start
4. **Agent 使用低效**：Agent 需要多次 `kb_read` 跳转才能拼出完整排查路径
5. **管线复杂度高**：Reader→Summarizer→Generator→Dedup→Fidelity→Review 六阶段，~12,000 行代码

## 2. Design Principle

**渐进式披露（Progressive Disclosure）**

Import 管线不是在"压缩"文档，而是在**规范和清晰化**知识文档。目标是减少 Agent 的上下文注意力稀释：

```
第一层：title + brief         → Agent 看 overview 判断相关性
第二层：symptoms + root_cause → Agent 确认是否匹配用户问题
第三层：resolution 导航表     → Agent 定位到正确的排查分支
第四层：具体步骤 + 命令       → Agent 逐步引导用户执行
```

Agent 的注意力按需分配——不匹配的条目在第一层就跳过，匹配的条目只深入到用户需要的分支。

## 3. Core Change: One Document = One Entry

**一个源文档导入后产生且仅产生一个 KB 条目。**

- 不拆 KP、不拆 tree、不拆行
- 条目保留源文档的完整知识和上下文
- 排查分支用 `###` 子章节 + 行为标签表达，不再拆成独立条目
- DAG 和 Classic 路径统一为同一条管线

## 4. Import Pipeline

### 4.1 New Pipeline Flow

```
源文档
  → Classifier（判断文档类型 + 多主题检测）
  → Summarizer（整篇文档提取 key_facts + commands + brief）
  → User Review（确认摘要内容）
  → Generator（按渐进披露原则生成结构化条目）
  → Normalizer（确定性规范化）
  → Fidelity Check（摘要 vs 条目一致性校验）
  → Write（写入 _pending/）
```

三个 LLM 调用：Classifier（1 次）、Summarizer（1 次）、Generator（1 次）。
对比现在：Classifier(1) + Reader(10-30) + Summarizer(N) + Generator(N) = 大量调用。

### 4.2 Classifier Phase

保留文档类型分类，去除 DAG 分流和粒度指导。

**输入**：源文档前 8000 字符
**输出**：

```python
@dataclass
class ClassificationResult:
    doc_type: DocumentType     # incident / runbook / guideline / mixed / non_kb
    suggested_type: str        # pitfall / model / guideline / process / decision
    language: str              # zh / en
    is_multi_topic: bool       # 是否多主题拼接文档
    topic_boundaries: list[int]  # 多主题时的切分位置（字符偏移）
```

**删除**：`complexity`、`needs_dag`、`granularity_hint`

**多主题文档处理**：当 `is_multi_topic=True` 时，按 `topic_boundaries` 切分源文档，每段独立走后续管线。这处理的是"一个 wiki 页面堆了 10 个不相关故障"的边界情况。按文档结构（h1/h2 标题边界）切分，不是按 LLM 判断逐段拆。

### 4.3 Summarizer Phase

对**整篇文档**做一次结构化提取。不再逐 KP 调用。

**输入**：完整源文档（通过 `read_document_range` 工具分段读取）
**输出**：

```json
{
  "brief": "一句话描述这个文档的核心知识",
  "key_facts": ["fact 1", "fact 2", ...],
  "commands": ["command 1", "code snippet 2", ...],
  "symptoms": ["symptom 1", ...],
  "resolution_branches": [
    {"when": "条件", "label": "分支名称"}
  ]
}
```

**设计要点**：
- `brief` 是新增字段，用于 `kb_browse` 的条目预览
- `symptoms` 和 `resolution_branches` 是可选的，只有 pitfall 类型才有
- Summarizer 的 prompt 强调"不丢不编"——提取所有事实和命令，不合并不省略
- 参考 claude-code 的上下文预算管理：对超长文档（>50K 字符），Summarizer 分段读取并合并结果

### 4.4 User Review

单条目确认，简化为 yes/no：

```
┌─────────────────────────────────────────────┐
│ Document: gpu-troubleshooting-guide.md      │
│ Type: pitfall                               │
│ Brief: PSU 冗余降级触发功耗墙...             │
│                                             │
│ Key Facts: 12 items                         │
│ Commands: 8 items                           │
│ Symptoms: 3 items                           │
│ Resolution Branches: 3 branches             │
│                                             │
│ [C]onfirm  [V]iew details  [S]kip          │
└─────────────────────────────────────────────┘
```

去掉多 KP 选择跳过、逐 KP 确认等复杂交互。

### 4.5 Generator Phase

按渐进披露原则生成结构化条目。Generator 的核心任务不是"塞 key_facts 进模板"，而是**重新组织知识结构**。

**Type-Section Table**（不变）：

| type      | required sections                            |
|-----------|----------------------------------------------|
| pitfall   | Symptoms · Root Cause · Resolution           |
| model     | Overview · Key Concepts · Usage              |
| guideline | Context · Guideline · Rationale              |
| process   | Purpose · Steps · Outcome                    |
| decision  | Context · Decision · Rationale               |

**Pitfall 特殊要求——分支结构**：

当 Summarizer 识别出多个 symptoms 或 resolution_branches 时，Generator 必须在 Resolution 段落开头生成**导航表格**：

```markdown
## Resolution

### 确认症状 → 选择分支
| 你看到的现象 | 走哪条分支 |
|---|---|
| dmesg 有 Xid 79 | 分支 A：GPU Xid 错误排查 |
| BMC power fault | 分支 B：PSU 冗余排查 |

### 分支 A：GPU Xid 错误排查
1. [api] `nvidia-smi -q -d PAGE_RETIREMENT`
2. [decide] 若 retired pages > 0 → 更换 GPU；否则继续
3. [api] `dmesg | grep -i "fallen off the bus"`
...

### 分支 B：PSU 冗余排查
1. [physical] 检查 PSU LED 状态
2. [api] `ipmitool sdr list | grep PS`
...
```

**行为标签**（保留，从 DAG 继承）：
- `[api]` — 执行命令/API 调用
- `[physical]` — 物理操作（看 LED、拔插模块）
- `[remote]` — 远程状态变更操作
- `[decide]` — 条件判断分支点

### 4.6 Normalizer + Fidelity Check

不变。Normalizer 做确定性规范化（header 翻译、title 长度、tag 提取、category slugify）。Fidelity check 对比 Summarizer 输出 vs Generator 输出的一致性。

新增：Normalizer 清理 `kp-\d+` 内部引用残留（虽然新管线不再产生，但防御性处理）。

### 4.7 Source File Dedup & Update

**source_file 改存 basename**（而非 kb_root 相对路径），确保外部导入的文档也能识别：

```python
def _compute_source_file(file_path: Optional[Path]) -> str:
    if file_path is None:
        return ""
    return file_path.name  # basename only
```

**更新策略**：

```
同 source_file + 不同 source_hash
  → 提示用户："已有同名来源的条目 <id>，是否更新？[Y/n]"
  → 旧内容存入 .history/<id>-<timestamp>.md
  → 在旧 ID 上重新生成内容（保留 maturity + evidence）
  → 更新 source_hash + updated_at
```

## 5. KB Data Model Changes

### 5.1 Frontmatter 变更

**新增字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `brief` | string | 是 | 一句话描述，用于 `kb_browse` 预览 |

**删除字段**：

| 字段 | 原用途 | 删除理由 |
|------|--------|---------|
| `parent_id` | tree 子条目指向父条目 | 不再有 tree |
| `child_entry_ids` | tree 父条目列举子条目 | 不再有 tree |
| `pitfall_structure` | 区分 tree/flat pitfall | 不再有 tree |
| `skill_refs` | 关联 skill | 不再有 skill |

**保留字段（不变）**：
`id`, `type`, `title`, `category`, `tags`, `language`, `maturity`, `source_hash`, `source_file`, `import_confidence`, `created_at`, `updated_at`

### 5.2 Type 系统

保留全部 5 种 type（pitfall / model / guideline / process / decision），含义不变。`process` 不再是 pitfall 的子条目类型，而是独立的操作指南文档类型。

### 5.3 Skill 删除

删除整个 skill 概念：
- 删除 `skills/` 目录下所有 SKILL.md
- 删除 `kb/skill/manager.py`
- 删除 CLI 中 `skill list/read` 命令
- 删除 MCP 中 skill 相关逻辑
- 删除 pipeline 中 `_finalize_skill_generation()`
- 删除 `detect_commands()` 相关逻辑

理由：一文档一条目后，条目的 Resolution/Steps 段落本身就是 Agent 的执行指令。Skill 是条目的冗余子集。

## 6. MCP Tools Redesign

### 6.1 Tool: `kb_browse`

合并现有 `kb_overview` + `kb_list` + `kb_search`。

```
kb_browse()                        → 全量索引
kb_browse(type="pitfall")          → 按类型过滤
kb_browse(query="GPU power fault") → 关键词搜索
```

**返回**：

```json
{
  "entries": [
    {
      "id": "gpu-power-fault",
      "type": "pitfall",
      "title": "GPU 供电异常导致训练中断",
      "brief": "PSU 冗余降级触发功耗墙。涵盖 Xid 错误、BMC power fault、进程 hang 三种排查分支。",
      "maturity": "verified"
    }
  ],
  "total": 42,
  "usage": "调用 kb_read(id) 查看条目摘要。确认症状匹配后，调用 kb_read(id, full=true) 获取完整排查步骤。"
}
```

**Tool description**（Agent 看到的语义）：
```
Browse the knowledge base. Returns entries with brief descriptions.
- No params: returns full index for browsing
- query: keyword search to find relevant entries
- type: filter by entry type (pitfall/model/guideline/process/decision)
After finding a relevant entry, call kb_read(id) to read its summary.
```

### 6.2 Tool: `kb_read`

两层读取：默认摘要层，`full=true` 完整文档。

```
kb_read(id="gpu-power-fault")              → 摘要层
kb_read(id="gpu-power-fault", full=true)   → 完整文档
```

**摘要层返回**（运行时从 Markdown 解析，不同 type 结构不同）：

**pitfall 摘要**：
```json
{
  "id": "gpu-power-fault",
  "type": "pitfall",
  "title": "GPU 供电异常导致训练中断",
  "brief": "PSU 冗余降级触发功耗墙...",
  "symptoms": [
    "GPU utilization 降为 0，dmesg 显示 Xid 79",
    "BMC 报 power fault，LED 橙灯"
  ],
  "root_cause": "PSU 冗余降级导致功耗墙触发 GPU throttle",
  "resolution_overview": "三条排查分支：GPU Xid 排查(4步) / PSU 冗余排查(3步) / 功耗墙确认(5步)",
  "commands_count": 12,
  "next": "症状匹配后，调用 kb_read(id='gpu-power-fault', full=true) 获取完整排查步骤。"
}
```

**model 摘要**：
```json
{
  "id": "dynamo-framework",
  "type": "model",
  "title": "Dynamo Inference Framework",
  "brief": "NVIDIA 开源推理编排框架...",
  "overview": "Dynamo 是推理引擎之上的编排层...",
  "key_concepts": ["Disaggregated Serving", "KV-Aware Routing", "Planner", "ModelExpress"],
  "next": "调用 kb_read(id='dynamo-framework', full=true) 获取完整内容。"
}
```

**process 摘要**：
```json
{
  "id": "dynamo-container-quickstart",
  "type": "process",
  "title": "Quick Start with Dynamo Container",
  "brief": "用容器最快启动 Dynamo...",
  "purpose": "用 Docker 容器快速启动 Dynamo 推理服务",
  "steps_count": 4,
  "next": "调用 kb_read(id='dynamo-container-quickstart', full=true) 获取完整步骤。"
}
```

**完整层返回**：
```json
{
  "id": "gpu-power-fault",
  "type": "pitfall",
  "content": "---\ntitle: GPU 供电异常...\n---\n\n## Symptoms\n...",
  "next": "排查完成后，调用 kb_confirm(id='gpu-power-fault', outcome='solved') 记录结果。"
}
```

**摘要解析实现**（方案 B：运行时解析）：

```python
def _parse_entry_summary(entry_type: str, body: str, meta: dict) -> dict:
    """从 Markdown body 解析结构化摘要。按 type 提取不同字段。"""
    summary = {
        "id": meta["id"],
        "type": entry_type,
        "title": meta["title"],
        "brief": meta.get("brief", ""),
    }
    if entry_type == "pitfall":
        summary["symptoms"] = _extract_bullet_list(body, "## Symptoms")
        summary["root_cause"] = _extract_first_paragraph(body, "## Root Cause")
        summary["resolution_overview"] = _extract_subsection_overview(body, "## Resolution")
        summary["commands_count"] = body.count("```")
    elif entry_type == "model":
        summary["overview"] = _extract_first_paragraph(body, "## Overview")
        summary["key_concepts"] = _extract_bullet_list(body, "## Key Concepts")
    elif entry_type == "process":
        summary["purpose"] = _extract_first_paragraph(body, "## Purpose")
        summary["steps_count"] = len(re.findall(r"^\d+\.", body, re.MULTILINE))
    # guideline, decision similar patterns...
    summary["next"] = f"调用 kb_read(id='{meta['id']}', full=true) 获取完整内容。"
    return summary
```

**Tool description**：
```
Read a KB entry. Default: returns a structured summary (symptoms, root cause,
resolution branches). Use full=true to get the complete document with all
commands and detailed steps. Start with the summary to confirm relevance
before reading the full entry.
```

### 6.3 Tool: `kb_confirm`

```
kb_confirm(id, outcome, session_id, notes="")
```

**outcome 枚举**：
- `solved` — 正向信号，驱动 maturity 升级
- `not_solved` — 中性信号，不归因，不惩罚

去掉 `wrong` 和 `partial`。

**Tool description**：
```
Record the outcome after using a KB entry. Call this after a troubleshooting
session completes. outcome='solved' means the entry helped resolve the issue.
outcome='not_solved' means it did not help (the entry may still be correct —
this is not a judgment on the entry's accuracy).
```

### 6.4 Tool: `kb_draft`

保留，不改。Agent 在排查过程中发现新知识，通过 `kb_draft` 沉淀。

```
kb_draft(title, content, session_id)
```

### 6.5 删除的 MCP Tools

| Tool | 删除理由 |
|------|---------|
| `kb_overview` | 合并进 `kb_browse` |
| `kb_list` | 合并进 `kb_browse` |
| `kb_search` | 合并进 `kb_browse` |

## 7. Evidence & Maturity Lifecycle

### 7.1 Maturity 升级（不变）

```
draft → verified（≥1 次 solved）→ proven（≥2 session + ≥2 contributor）
```

### 7.2 衰减（不变）

```
proven 12个月无 evidence → verified
verified 6个月无 evidence → draft
```

### 7.3 去掉 wrong 惩罚

`not_solved` 只是不加分，不扣分。自然选择：长期无 `solved` 的条目会被时间衰减降级。

## 8. Deletion Plan

### 8.1 删除的文件

```
# DAG pipeline（全部）
holmes/kb/agent/dag/__init__.py
holmes/kb/agent/dag/harness1.py
holmes/kb/agent/dag/harness2.py
holmes/kb/agent/dag/prompt2.py
holmes/kb/agent/dag/report2.py
holmes/kb/agent/dag/tools2.py
holmes/kb/agent/dag/schema.py

# Reader phase
holmes/kb/agent/phases/reader.py

# Legacy extractor
holmes/kb/agent/phases/extractor.py

# Knowledge map (replaced by simple summary dict)
holmes/kb/agent/knowledge_map.py

# Skill system
holmes/kb/skill/manager.py
holmes/kb/skill/__init__.py

# Doc access cursor tracking (tools retained, cursor deleted)
# → doc_access.py 保留 read_document_range / search_in_document 工具
# → 删除 DocumentCursor 类和 coverage 追踪逻辑
```

### 8.2 大幅修改的文件

```
holmes/kb/agent/pipeline.py        → 重写，~300 行（现 1092 行）
holmes/kb/agent/phases/summarizer.py → 改为整篇文档模式
holmes/kb/agent/phases/generator.py  → 新增渐进披露 prompt
holmes/kb/agent/phases/classifier.py → 删除 DAG 分流，新增多主题检测
holmes/kb/agent/interactive_review.py → 简化为单条目确认
holmes/kb/agent/fidelity.py          → 只保留 verify_summary_fidelity
holmes/kb/agent/normalizer.py        → 新增 kp-N 清理
holmes/kb/agent/tools.py             → 删除 skill 相关
holmes/kb/agent/runner.py            → 删除 skill 生成、简化调用
holmes/kb/agent/report.py            → 简化（无多 KP 报告）
holmes/kb/store.py                   → 删除 tree 操作、新增 update_entry
holmes/kb/schema.py                  → 删除 tree 字段、新增 brief
holmes/mcp/tools.py                  → 重写 MCP 工具
holmes/mcp/server.py                 → 更新工具注册
holmes/cli.py                        → 删除 skill 命令、简化 approve
```

### 8.3 删除的测试文件

```
tests/test_dag_*.py (6 files)
tests/test_harness2*.py (2 files)
tests/test_reader_phase.py
tests/test_extractor_*.py (2 files)
tests/test_knowledge_map.py
tests/test_skill_*.py (6 files)
tests/test_pipeline_run_parallel.py (no more parallel KP extraction)
tests/test_approve_tree.py
```

### 8.4 代码量估算

| | 现在 | 重构后 | 变化 |
|---|---|---|---|
| pipeline.py | 1,092 | ~300 | -72% |
| DAG 全套 | 3,103 | 0 | -100% |
| reader.py | 667 | 0 | -100% |
| store.py tree ops | ~200 | 0 | -100% |
| skill/ | 516 | 0 | -100% |
| MCP tools.py | 831 | ~500 | -40% |
| **总计** | ~12,000 | ~5,000 | **-58%** |

## 9. Implementation Order

### Phase 1: Data Model + MCP（无 LLM 依赖，可立即测试）

1. schema.py: 新增 `brief` 字段，删除 tree 字段
2. store.py: 删除 tree 操作，新增 `update_entry_content()`
3. mcp/tools.py: 实现 `kb_browse`、两层 `kb_read`、简化 `kb_confirm`
4. mcp/server.py: 更新工具注册
5. 测试：MCP 工具对现有条目的兼容性

### Phase 2: Import Pipeline（核心重构）

1. classifier.py: 删除 DAG 分流，新增 `is_multi_topic` + `topic_boundaries`
2. summarizer.py: 改为整篇文档模式，新增 `brief`/`symptoms`/`branches` 输出
3. generator.py: 新增渐进披露 prompt，分支导航表格生成
4. pipeline.py: 重写 `run()`，Classifier→Summarizer→Review→Generator→Write
5. interactive_review.py: 简化为单条目确认
6. normalizer.py: 新增 kp-N 清理
7. fidelity.py: 只保留 `verify_summary_fidelity`
8. 测试：端到端导入测试

### Phase 3: Cleanup（删除旧代码）

1. 删除 `dag/` 目录
2. 删除 `phases/reader.py`、`phases/extractor.py`
3. 删除 `knowledge_map.py`
4. 删除 `skill/` 目录
5. 删除 runner.py 中 skill 相关代码
6. 删除 cli.py 中 skill 命令和 tree approve
7. 删除对应测试文件
8. `source_file` 改存 basename

### Phase 4: Validation

1. 用 Dynamo README 做端到端导入测试，验证：
   - 一个文档生成一个条目
   - brief 字段正确
   - 所有关键知识保留（When to use / Build from Source / K8s YAML）
   - 命令完整可复制
2. 用 MCP 模拟 Agent 使用流程：
   - `kb_browse` 能找到条目
   - `kb_read` 摘要层信息充分
   - `kb_read(full=true)` 内容完整
3. 确认测试通过数量
