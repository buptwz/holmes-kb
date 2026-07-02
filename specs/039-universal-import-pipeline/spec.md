# 039 — Universal Import Pipeline

**状态**: 设计稿 v5（终版）
**日期**: 2026-06-29
**依赖**: 037 (DAG pipeline), 038 (per-node context), 018 (quality normalization)

---

## 0. 核心洞察

**DAG 不等于 pitfall。** DAG 是提取"复杂多分支诊断树"的手段，不是所有 pitfall 的必经之路。

一个简单的 pitfall（"Redis 连接池满了 → 调大 max_connections"）只需要一个 flat entry，走 DAG 的 Agent1（20-50 轮 tool-use）是严重浪费。只有多分支、多决策点的复杂排查流程（"先看日志 → 分两条路：如果是 A 就检查 X，如果是 B 就检查 Y → 各自再分支"）才值得 DAG 的重投入。

**所以路由的依据不是"文档类型"，而是"诊断复杂度"。**

---

## 1. 架构

```
                          ┌─────────────────────────────┐
                          │        holmes import         │
                          └──────────────┬──────────────┘
                                         │
                   ┌─────────────────────┤ Step 0: 幂等检查
                   │ hash match → skip   │ (source_hash / source_file)
                   │                     │
                   │           ┌─────────┴──────────┐
                   │           │ --dag flag?         │
                   │           │ Y → 跳过 Classifier │
                   │           └─────────┬──────────┘
                   │                     │ N
                   │              ┌──────┴──────┐
                   │              │  Classifier  │  1 call, ~128 tokens
                   │              │  type +      │
                   │              │  complexity  │
                   │              └──────┬──────┘
                   │                     │
             ┌─────┴─────┐               │
             │  non_kb   │               │
             │  → skip   │     ┌─────────┼────────────────┐
             └───────────┘     │                          │
                        incident +              其他所有情况
                        complex_branching       (simple pitfall, guideline,
                        或 --dag 强制           runbook, model, decision,
                               │                 mixed, simple incident)
                               │                          │
                       ┌───────▼────────┐         ┌───────▼────────┐
                       │  DAG Pipeline  │         │ Classic Pipeline│
                       │  (不改)        │         │ (增强)          │
                       │  Agent1→2.5→2  │         │                │
                       └───────┬────────┘         │ Doc Map        │
                               │                  │ → Reader       │
                       ┌───────▼────────┐         │ → Confirm 1    │
                       │ Complementary  │         │ → Extractor    │
                       │ Extraction     │         │ → Fidelity Chk │
                       │ (Reader扫描    │         │ → Confirm 2    │
                       │  DAG未覆盖段)  │         │ → Write        │
                       └───────┬────────┘         └───────┬────────┘
                               │                          │
                               └──────────┬───────────────┘
                                          │
                                   Post-processing
                                   (Normalize, Dedup, Skill)
                                          │
                                    ImportReport
```

**路由规则**：

| 条件 | 路由 |
|------|------|
| `--dag` flag | DAG Pipeline（跳过 Classifier） |
| Classifier: incident + complex_branching | DAG Pipeline → 可选 Complementary Extraction |
| 其他一切 | Classic Pipeline |

**CLI flag 设计**：

| flag | 控制 | 说明 |
|------|------|------|
| `--type <type>` | 知识类型 | pitfall/guideline/model/process/decision，传递给 Extractor |
| `--dag` | 提取方式 | 强制走 DAG 管线，不经 Classifier 判断 |

两者**正交**：`--type` 控制"输出什么类型的 entry"，`--dag` 控制"用什么方式提取"。

| 命令 | 路由 |
|------|------|
| `holmes import doc.md` | Classifier 自动决定 |
| `holmes import doc.md --type pitfall` | Classic（type=pitfall） |
| `holmes import doc.md --dag` | DAG |
| `holmes import doc.md --type pitfall --dag` | DAG（type=pitfall） |
| `holmes import doc.md --type guideline` | Classic（type=guideline） |

---

## 2. Classifier 重设计

当前 Classifier 只判断 doc_type，用 doc_type 硬路由。改为同时输出 **complexity**。

```python
class DocumentType(Enum):
    incident = "incident"       # 问题-解决对（合并原 single/multi_incident）
    runbook = "runbook"         # 操作流程
    guideline = "guideline"    # 最佳实践、规范、设计决策
    mixed = "mixed"            # 多种类型混合
    non_kb = "non_kb"          # 无可复用知识

class DiagnosticComplexity(Enum):
    simple = "simple"           # 线性：一个问题 → 一个解法
    complex_branching = "complex"  # 多分支诊断树（≥2 决策点 + 分支路径）

@dataclass
class ClassificationResult:
    doc_type: DocumentType
    complexity: DiagnosticComplexity   # 仅 incident 时有意义
    reason: str
    granularity_hint: str
```

**Classifier prompt 关键判别指引**：

```
## Complexity（仅当 type=incident 时评估）

| complexity | 特征 |
|------------|------|
| simple | 一个问题、一条解决路径、无分支决策 |
| complex | ≥2 个独立决策点，各决策点引出不同诊断/操作分支 |

示例：
- "Redis 连接池满了 → 调大 max_connections" → simple
- "API 超时 → 先看网络还是服务端？网络：检查 DNS/路由/防火墙。服务端：检查负载/GC/DB连接" → complex

如果拿不准，选 simple。DAG 的投入大，只在确定需要时使用。

## Output Format

{"doc_type": "<type>", "complexity": "<simple|complex>", "reason": "<≤80 char>"}
```

截断从 4K → 8K（1 次调用增加 ~1 分钱，但对大文档分类更准）。

**速度影响**：零。仍然是 1 次 LLM 调用，128 tokens output。

---

## 3. Classic Pipeline 增强

Classic 管线处理**所有非 complex_branching 的文档**，包括简单 pitfall。

### 3.1 Document Map（长文档预处理）

**问题**：Reader 对长文档（>20K chars）只能线性探索，容易在前半段花太多轮次。

**方案**：在 Reader 之前做**确定性标题扫描**，零 LLM 调用：

```python
def build_document_map(source_text: str) -> str:
    """扫描 Markdown 标题，生成目录索引。"""
    lines = source_text.split("\n")
    toc = []
    char_pos = 0
    for line in lines:
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            title = line.lstrip("# ").strip()
            toc.append(f"{'  ' * (level-1)}- [{title}] (char {char_pos})")
        char_pos += len(line) + 1
    return "\n".join(toc) if toc else ""
```

注入到 Reader 的第一条 user message：

```
Document table of contents (use this to navigate efficiently):
{document_map}

Total length: {total_chars} characters.
```

**效果**：Reader 有全局导航能力，可以直接 `read_document_range` 跳到关键段落，不需要线性扫描。对 50K+ 文档改善显著。

**改动量**：~20 行，在 `reader.py` 的 `run()` 方法开头。

### 3.2 Reader Multi-type Awareness

当前 Reader prompt 偏向 pitfall。增加多类型指令：

```
## Multi-type Awareness

一份文档可能包含多种知识类型。请识别并注册所有类型：
  - 问题-解决对 → type_hint=pitfall
  - 诊断/操作步骤 → type_hint=process
  - 最佳实践/规范 → type_hint=guideline
  - 概念定义/模型 → type_hint=model
  - 架构/技术选型决策 → type_hint=decision

如果一段内容同时包含 pitfall 和它的诊断步骤，注册两个 KP：
  - 一个 pitfall（症状 + 根因）
  - 一个 process（步骤），parent_kp 指向 pitfall

confidence 字段使用：
  - 1.0：明确的知识点
  - 0.7：边界模糊或内容简短（<200 chars）
  - 0.5：不确定是否构成独立知识
```

**改动量**：~15 行 prompt 文本，追加到 `READER_SYSTEM_PROMPT`。

### 3.3 KnowledgePoint 增强

```python
@dataclass
class KnowledgePoint:
    # 现有字段不变
    id: str
    description: str
    section_start: int
    section_end: int
    type_hint: str = "pitfall"
    category_hint: str = ""
    language: str = "en"
    extracted: bool = False

    # 新增
    parent_kp: Optional[str] = None    # 父 KP id（用于 Classic 管线的树形关系）
    confidence: float = 1.0            # LLM 自评置信度
```

`record_knowledge_point` tool schema 增加 2 个 optional 参数。完全向后兼容。

**改动量**：~15 行。

### 3.4 用户确认环节 1：KP 列表确认

新增 `agent/interactive_review.py`，Reader 后、Extractor 前：

```python
def review_knowledge_points(km, source_text, no_interactive, report) -> KnowledgeMap:
    """展示 KP 列表，让用户确认/跳过/取消。"""

    if no_interactive:
        for kp in km.knowledge_points:
            if kp.confidence < 0.6:
                report.warnings.append(f"{kp.id}: low confidence ({kp.confidence:.0%})")
        return km

    print(f"\n检测到 {len(km.knowledge_points)} 个知识点：")
    for kp in km.knowledge_points:
        parent = f"  └── (子 of {kp.parent_kp})" if kp.parent_kp else ""
        conf = f" ({kp.confidence:.0%})" if kp.confidence < 0.9 else ""
        print(f"  {kp.id} [{kp.type_hint:10s}] {kp.description[:60]}{conf}{parent}")

    choice = click.prompt("\n[1] 确认 [2] 跳过某些 [3] 取消", default="1").strip()

    if choice == "3":
        km.knowledge_points.clear()
        return km
    if choice == "2":
        skip_ids = click.prompt("输入要跳过的 KP id（逗号分隔）").strip()
        skip_set = {s.strip() for s in skip_ids.split(",") if s.strip()}
        km.knowledge_points = [kp for kp in km.knowledge_points if kp.id not in skip_set]

    return km
```

**改动量**：~40 行。

### 3.5 Extractor Sibling Brief Injection

```python
# extractor.py 的 user message 中追加
if len(knowledge_map.knowledge_points) > 1:
    siblings = "\n".join(
        f"  - {kp.id}: [{kp.type_hint}] {kp.description}"
        for kp in knowledge_map.knowledge_points if kp.id != current_kp.id
    )
    user_msg += f"\n\nOther KPs in this document (terminology consistency only):\n{siblings}"
```

**改动量**：~10 行。

### 3.6 内容保真检查（替代 Phase 3 LLM Verifier）

当前 Phase 3 用 LLM tool-use loop 做 verify_content + write_kb_entry。verify_content 有截断 bug（只看前 3000 chars），不可靠。

替换为**确定性保真检查**，零 LLM 成本：

```python
def verify_content_fidelity(source_section: str, draft: str) -> list[str]:
    """程序化检查：源文档关键信息是否保留在生成的 entry 中。"""
    warnings = []

    # 1. 数字保真（版本号、端口、阈值、超时值等硬事实）
    src_nums = set(re.findall(r'\b\d+\.?\d*\b', source_section))
    draft_nums = set(re.findall(r'\b\d+\.?\d*\b', draft))
    missing_nums = src_nums - draft_nums
    if missing_nums:
        warnings.append(f"数字丢失: {missing_nums}")

    # 2. 代码/命令片段保真
    src_code = set(re.findall(r'`([^`]+)`', source_section))
    draft_code = set(re.findall(r'`([^`]+)`', draft))
    dropped = src_code - draft_code
    if dropped and len(dropped) > len(src_code) * 0.3:
        warnings.append(f"代码片段丢失: {len(dropped)}/{len(src_code)} 个")

    # 3. 专有名词保真（CamelCase、全大写缩写 ≥2 字母）
    src_terms = set(re.findall(r'\b[A-Z][a-zA-Z]{2,}\b', source_section))
    draft_terms = set(re.findall(r'\b[A-Z][a-zA-Z]{2,}\b', draft))
    missing_terms = src_terms - draft_terms
    if missing_terms and len(missing_terms) > len(src_terms) * 0.3:
        warnings.append(f"术语丢失: {missing_terms}")

    return warnings
```

**检查时机**：Extractor 生成每条 draft 后立即执行。warnings 记入 `ImportReport.warnings` 并在用户确认 2 中展示。

**改动量**：~30 行。

### 3.7 用户确认环节 2：生成结果确认

Extractor 全部完成后、写入 `_pending/` 前：

```python
def review_drafts(kp_drafts, fidelity_results, no_interactive, report) -> dict:
    """展示生成结果 + 保真检查结果，让用户确认写入。"""

    if no_interactive:
        # 非交互模式：保真 warning 记入 report，全部写入
        for kp_id, warnings in fidelity_results.items():
            for w in warnings:
                report.warnings.append(f"{kp_id}: {w}")
        return kp_drafts

    print(f"\n生成结果（{len(kp_drafts)} 条）：")
    for kp_id, draft in kp_drafts.items():
        title = _extract_title(draft)
        type_ = _extract_type(draft)
        chars = len(draft)
        warnings = fidelity_results.get(kp_id, [])
        status = " ⚠ " + "; ".join(warnings) if warnings else " ✓"
        print(f"  {kp_id} [{type_:10s}] {title[:50]} ({chars} chars){status}")

    choice = click.prompt(
        "\n[1] 全部写入 [2] 逐条查看 [3] 取消", default="1"
    ).strip()

    if choice == "3":
        return {}
    if choice == "2":
        # 逐条展示完整内容，用户可选择跳过
        approved = {}
        for kp_id, draft in kp_drafts.items():
            print(f"\n{'='*60}\n{kp_id}:\n{'='*60}")
            print(draft[:2000])  # 截断展示前 2000 chars
            if len(draft) > 2000:
                print(f"  ... ({len(draft) - 2000} chars truncated)")
            keep = click.prompt(f"  写入? [y/n]", default="y").strip().lower()
            if keep == "y":
                approved[kp_id] = draft
        return approved

    return kp_drafts
```

**改动量**：~40 行（在 `interactive_review.py` 中）。

---

## 4. DAG Pipeline

**零改动。** 代码路径完全不变。

触发条件变化：

| | 当前 | 新 |
|---|------|-----|
| 自动路由 | 所有 incident → DAG | incident + complex_branching → DAG |
| 手动指定 | `--type pitfall` → DAG | `--dag` → DAG |

**`--type pitfall` 不再强制 DAG**。它只设置 type hint，路由仍由 Classifier 或 `--dag` 决定。

---

## 5. Complementary Extraction（DAG 后的补充提取）

**场景**：一份复杂诊断文档中，DAG 提取了核心排查树，但文档末尾有"最佳实践"章节未被 DAG 覆盖。

**方案**：DAG 完成后，检查未覆盖率。>10% 未覆盖 → Classic Reader 扫描剩余段落。

```python
def _run_complementary_extraction(self, source_text, dag_report, file_path):
    covered = self._get_dag_covered_ranges()  # 从 .dag.json 的 line_range 计算
    uncovered_pct = _calc_uncovered_pct(source_text, covered)

    if uncovered_pct < 10:
        return  # 几乎全部覆盖，不需要补充

    reader = ReaderAgent(provider=self._provider, model=self.cfg.model)
    km = reader.run(source_text, ctx={"skip_ranges": covered})

    # 过滤掉 pitfall/process（DAG 已覆盖）
    km.knowledge_points = [kp for kp in km.knowledge_points
                           if kp.type_hint not in ("pitfall", "process")]
    if not km.knowledge_points:
        return

    km = review_knowledge_points(km, source_text, self.no_interactive, dag_report)
    if not km.knowledge_points:
        return

    # Extractor + fidelity check + review（复用 Classic 管线逻辑）
    self._extract_and_write(km, source_text, dag_report)
```

**职责分工**：
- DAG 擅长提取多分支诊断树 → 让它只做这个
- Classic Reader 擅长通用知识提取 → 让它处理 DAG 不覆盖的部分
- 两者职责清晰，互不干扰

**改动量**：~50 行，在 `pipeline.py`。

---

## 6. 准确性保障链

完整的 11 层保障，从输入到输出：

| # | 阶段 | 机制 | 防什么 | 成本 |
|---|------|------|--------|------|
| 1 | 分类 | Classifier complexity 判断 | 用错管线 | 1 LLM call |
| 2 | 分类 | `--dag` 手动覆盖 | Classifier 误判 | 0 |
| 3 | 导航 | Document Map 标题索引 | 长文档迷路 | 0 |
| 4 | 覆盖 | Reader 多轮 95%+ coverage | 遗漏知识 | 1-3 LLM calls |
| 5 | 覆盖 | Forced gap fill (≥500 chars) | 未读区间 | 0 (same call) |
| 6 | 确认1 | review_knowledge_points | 错误分类/边界 | 0（用户交互） |
| 7 | 隔离 | Extractor forked agent pattern | 内容串扰 | 0 |
| 8 | 约束 | Extractor "不编造不推断" prompt | 幻觉 | 0 |
| 9 | 一致 | Sibling brief injection | 术语不一致 | 0 |
| 10 | 保真 | verify_content_fidelity | 数字/命令/术语丢失 | 0（确定性） |
| 11 | 确认2 | review_drafts（含逐条查看） | 语义错误 | 0（用户交互） |

之后还有：
- DraftNormalizer（格式标准化）
- schema validation（字段完整性）
- `_pending/` → `holmes kb approve`（最终人工审核）

**无任何层依赖不可靠的 LLM 验证。** 层 4/8 是 LLM 生成，但由层 6/10/11 的确定性检查 + 用户确认兜底。

---

## 7. 速度对比

### 简单 pitfall（当前 vs 新）

| | 当前 | 新 |
|---|------|-----|
| 路由 | → DAG | → Classic |
| 调用数 | 1 + 20-50 + N (Agent1+Agent2) | 1 + 1-3 + 1 (Classifier+Reader+Extractor) |
| 耗时 | **2-5 分钟** | **10-20 秒** |

**10-30x 提速**。

### Guideline / Model / Decision（当前 vs 新）

| | 当前 | 新 |
|---|------|-----|
| 路由 | Classic + Phase 3 LLM | Classic（无 Phase 3 LLM） |
| 调用数 | 1 + 1-3 + N + N (verify) | 1 + 1-3 + N |
| 耗时 | ~30-60 秒 | **~15-30 秒** |

**~2x 提速**。

### 复杂诊断（不变 + 可选补充）

DAG 管线不变。Complementary Extraction 仅在 >10% 未覆盖时触发，增加 1-3 Reader calls + M Extractor calls。

---

## 8. UX 效果

### 简单 pitfall（Classic，~15 秒）

```
$ holmes import ./redis-pool-issue.md

  [classify] incident / simple (0.93)
  [reader]   pass 1: 1 KP, coverage 92%
  [reader]   pass 2: coverage 97%, done

  检测到 1 个知识点：
  kp-1 [pitfall   ] Redis连接池耗尽导致服务超时 (2340 chars)
  [1] 确认 [2] 跳过某些 [3] 取消
  > 1

  [extract]  (1/1) Generating: Redis连接池耗尽...

  生成结果（1 条）：
  kp-1 [pitfall   ] Redis连接池耗尽导致服务超时 (1240 chars) ✓
  [1] 全部写入 [2] 逐条查看 [3] 取消
  > 1

  [write]    1 entry → _pending/pitfall/database/
  ✓ 1 created | 15.2s
```

### 复杂诊断（DAG，~3 分钟）

```
$ holmes import ./network-switch-failover.md

  [classify] incident / complex (0.88)
  [dag]      Agent1 提取排查树... (turn 24)
  [dag]      DAG: 6 nodes, 4 process nodes
  [validate] Step 2.5 通过
  排查树：
  Root [pitfall] 交换机故障切换失败
  ├─ N1 [process] SSH/SNMP 连通性检查
  ├─ N2 [process] SFP 模块物理检查
  └─ N3 [process] 备用链路切换验证
  [1] 确认 [2] 编辑 [3] 取消
  > 1

  [generate] (1/3) N1...
  [generate] (2/3) N2...
  [generate] (3/3) Root...
  [write]    4 entries → _pending/

  [complement] DAG 覆盖 78%，扫描剩余内容...
  [reader]   1 KP: guideline (交换机固件升级规范)

  检测到 1 个知识点：
  kp-1 [guideline ] 交换机固件升级规范 (1800 chars)
  [1] 确认 [2] 跳过某些 [3] 取消
  > 1

  [extract]  (1/1) Generating...
  [write]    1 entry → _pending/guideline/network/
  ✓ 5 created | 3m12s
```

### 强制走 DAG

```
$ holmes import ./simple-issue.md --dag

  [dag]      (--dag 跳过 Classifier)
  [dag]      Agent1 提取排查树... (turn 18)
  ...
```

### Guideline（Classic，~20 秒）

```
$ holmes import ./coding-standards.md

  [classify] guideline / simple (0.96)
  [reader]   Document Map: 8 sections detected
  [reader]   pass 1: 4 KPs, coverage 85%
  [reader]   pass 2: 6 KPs, coverage 98%, done

  检测到 6 个知识点：
  kp-1 [guideline ] 命名规范 (1200 chars)
  kp-2 [guideline ] 错误处理标准 (980 chars)
  kp-3 [guideline ] 日志格式要求 (1100 chars)
  kp-4 [decision  ] 选择 Go 而非 Rust 的理由 (2100 chars)
  kp-5 [guideline ] 代码审查清单 (1500 chars)
  kp-6 [model     ] 微服务边界定义原则 (1800 chars)
  [1] 确认 [2] 跳过某些 [3] 取消
  > 1

  [extract]  (1/6) Generating...
  ...

  生成结果（6 条）：
  kp-1 [guideline ] 命名规范 (520 chars) ✓
  kp-2 [guideline ] 错误处理标准 (480 chars) ✓
  kp-3 [guideline ] 日志格式要求 (510 chars) ⚠ 数字丢失: {512, 1024}
  kp-4 [decision  ] 选择Go而非Rust (890 chars) ✓
  kp-5 [guideline ] 代码审查清单 (620 chars) ✓
  kp-6 [model     ] 微服务边界定义原则 (730 chars) ✓
  [1] 全部写入 [2] 逐条查看 [3] 取消
  > 2

  ============================================================
  kp-3:
  ============================================================
  ---
  id: GL-APP-003
  type: guideline
  ...
  写入? [y/n] > n

  [write]    5 entries → _pending/
  ✓ 5 created, 1 skipped | 22.4s
```

### 混合文档（Classic，~25 秒）

```
$ holmes import ./quarterly-review.md

  [classify] mixed / simple (0.85)
  [reader]   Document Map: 12 sections detected
  [reader]   pass 1: 3 KPs, coverage 72%
  [reader]   pass 2: 5 KPs, coverage 91%
  [reader]   pass 3: 5 KPs, coverage 96%, done

  检测到 5 个知识点：
  kp-1 [pitfall   ] Q2数据库迁移故障 (3200 chars)
  kp-2 [decision  ] 从MySQL迁移到PostgreSQL (2100 chars)
  kp-3 [guideline ] 数据库迁移前检查清单 (1500 chars)
  kp-4 [pitfall   ] DNS缓存导致切换延迟 (1800 chars)
  kp-5 [process   ] 数据库回滚操作步骤 (1200 chars)
    └── (子 of kp-1)
  [1] 确认 [2] 跳过某些 [3] 取消
  > 1

  [extract]  (1/5) Generating...
  ...

  生成结果（5 条）：
  kp-1 [pitfall   ] Q2数据库迁移故障 (1580 chars) ✓
  kp-2 [decision  ] 从MySQL迁移到PostgreSQL (920 chars) ✓
  kp-3 [guideline ] 数据库迁移前检查清单 (680 chars) ✓
  kp-4 [pitfall   ] DNS缓存导致切换延迟 (890 chars) ✓
  kp-5 [process   ] 数据库回滚操作步骤 (560 chars) ✓
  [1] 全部写入 [2] 逐条查看 [3] 取消
  > 1

  [write]    5 entries → _pending/
  ✓ 5 created | 24.8s
```

### 非交互模式（CI/Pipeline）

```
$ holmes import ./doc.md --no-interactive

  [classify] incident / simple (0.93)
  [reader]   pass 1: 1 KP, coverage 97%, done
  [auto]     1 KP confirmed (non-interactive)
  [extract]  (1/1) Generating...
  [auto]     fidelity check passed
  [auto]     1 draft written (non-interactive)
  [write]    1 entry → _pending/pitfall/database/
  ✓ 1 created | 12.1s
```

---

## 9. 逐条对照需求

| # | 要求 | 方案 |
|---|------|------|
| **R1** 所有类型可导入 | Classic 处理 5 种类型 + mixed。Reader 多类型 prompt。`--type` 可强制类型 |
| **R2** 元信息自动填充 | Reader: type/category/language/confidence。Extractor: 完整 frontmatter。零手工 |
| **R3** 生命周期闭环 | 不改。import → _pending → approve → 正式 → evidence → maturity → decay |
| **R4** Git 管理 | 不改。evidence sidecars 无冲突，maturity 冲突有 resolve 机制 |
| **R5** DAG 不打折 | DAG 代码零改动。更精准路由 + `--dag` 手动覆盖 |
| **R6** 准确不遗漏 | 11 层保障链（见第 6 节）。两次用户确认 + 确定性保真检查 |
| **R7** Agentic 问题 | Document Map + 多轮 coverage + semantic compaction + forked isolation |
| **R8** MCP 通道 | 不改。产出格式兼容现有 MCP tools |
| **R9** 多用户协作 | 不改。git 机制已支持 |
| **R10** 学习现有代码 | 保留所有好模式。替换不可靠的 Phase 3 为确定性检查 |
| **R11** 幂等 import | source_hash 不变。`--dag` + `--force` 可强制重新导入 |
| **R12** 日志和 UX | 统一 progress_callback。两次确认。保真检查结果可见 |

---

## 10. 改动清单

### 新增

| 文件 | 行数 | 职责 |
|------|------|------|
| `agent/interactive_review.py` | ~80 | review_knowledge_points + review_drafts |
| `agent/fidelity.py` | ~30 | verify_content_fidelity |

### 修改

| 文件 | 改动量 | 内容 |
|------|--------|------|
| `agent/phases/classifier.py` | ~30 行 | complexity 维度 + 截断 8K + output format |
| `agent/knowledge_map.py` | ~15 行 | parent_kp + confidence |
| `agent/phases/reader.py` | ~35 行 | Document Map 注入 + 多类型 prompt |
| `agent/phases/extractor.py` | ~10 行 | sibling brief injection |
| `agent/pipeline.py` | ~90 行 | 路由逻辑 + Complementary + Phase 3 简化 + `--dag` |
| `cli.py` (import command) | ~5 行 | `--dag` flag |

### 不改

| 文件/模块 | 原因 |
|-----------|------|
| `agent/dag/*`（全部 7 个文件） | DAG 质量不打折 |
| `mcp/tools.py` | MCP 接口已就绪 |
| `schema.py` | 数据模型不变 |
| `store.py` | 存储层不变 |
| `agent/normalizer.py` | 后处理不变 |
| `agent/doc_access.py` | 文档访问层不变 |

### 总量

| 类别 | 行数 |
|------|------|
| 新增 | ~110 |
| 修改 | ~185 |
| 删除 | ~50 (Phase 3 LLM loop) |
| **净增** | **~245 行** |

---

## 11. LLM 调用成本

| 场景 | 当前 | 新 | 变化 |
|------|------|-----|------|
| 简单 pitfall | 1 + 20-50 + N (DAG) | 1 + 1-3 + 1 (Classic) | **-90%** |
| 复杂诊断 | 1 + 20-50 + N (DAG) | 不变 + 0-3 (补充) | +0-3 |
| Guideline | 1 + 1-3 + N + N (verify) | 1 + 1-3 + N | **-N** |
| Mixed | 1 + 1-3 + N + N (verify) | 1 + 1-3 + N | **-N** |

---

## 12. 实施计划

| 里程碑 | 内容 | 依赖 | 可独立测试 |
|--------|------|------|-----------|
| **M1** | Classifier complexity 维度 | 无 | ✓ unit test |
| **M2** | KnowledgePoint parent_kp + confidence | 无 | ✓ unit test |
| **M3** | Document Map + Reader 多类型 prompt | M2 | ✓ unit test |
| **M4** | interactive_review.py（两次确认） | M2 | ✓ unit test |
| **M5** | Extractor sibling briefs | M2 | ✓ unit test |
| **M6** | fidelity.py（确定性保真检查） | 无 | ✓ unit test |
| **M7** | Pipeline 路由 + Phase 3 简化 + `--dag` flag | M1-M6 | ✓ E2E 回归 |
| **M8** | Complementary Extraction | M3, M7 | ✓ E2E 测试 |
| **M9** | 进度回调统一 | M7 | ✓ |

M1-M6 相互独立，可并行开发。M7 集成。M8 在 M7 之后。
