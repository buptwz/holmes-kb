# Spec 040 — Import 效率提升 + 语义搜索

> 第一优先：保证 import 质量和速度（满足生产更新）+ agent 通过 MCP 使用 KB 的效果（满足用户使用）

---

## 一、现状分析

### Import 瓶颈

实测数据（34 e2e tests, 6 session fixtures, deepseek-v4-flash）：总耗时 46 分钟，平均每个 pipeline run ~8 分钟。

| 环节 | LLM 调用次数 | 耗时占比 | 瓶颈原因 |
|---|---|---|---|
| Agent 1 (DAG 结构提取) | 8-15 次 tool-use | ~30% | 消息累积导致后期每轮变慢 |
| Agent 2 (per-node 内容生成) | 每节点 3-5 次 × N 节点 | ~55% | **串行处理，且每节点多轮调用** |
| Classic Reader + Extractor | 各 3-8 次 | ~15% | KP 串行 |

**Agent 2 调用分解**（每个 process 节点）：
1. LLM 收到节点上下文 → 调用 `read_entry(child_id)` 获取子节点 title（1-3 次）
2. LLM 调用 `write_entry(entry_id, content)` 写入（1 次）
3. 校验失败 → 修正重试（0-1 次）
4. LLM 调用 `finalize()`（1 次）

**关键发现**：步骤 1 的 `read_entry` 调用是冗余的——子节点 title 在 `briefs` 中已有，可以直接嵌入 prompt，省去 1-3 次 LLM 调用。

### MCP 搜索瓶颈

| 问题 | 现状代码 | 影响 |
|---|---|---|
| **纯关键词 `in` 匹配** | `sum(1 for term in terms if term in haystack)` | 搜 "redis 超时" 找不到 "Redis Connection Pool Exhausted" |
| **无 TF-IDF 权重** | 命中数/总词数 = score | 常见词和罕见词权重相同 |
| **无语义理解** | 只做字符串包含 | "timeout" 与 "连接超时" 无法关联 |
| **O(n) 全扫描** | 每次搜索读所有 .md 文件 | 随 KB 增长线性变慢 |

**实测 API 网关 embedding 模型可用性**：
- `text-embedding-ada-002` ✅ 可用
- `text-embedding-v1` ✅ 可用（1024 维）
- `text-embedding-3-small` ❌ 无渠道
- `bge-large-zh` ❌ 无渠道

---

## 二、Import 效率优化

### US-1：减少 Agent 2 每节点 LLM 调用数

**现状**：每个 process 节点需要 3-5 次 LLM 调用。
**优化**：将冗余调用合并，每节点降到 1-2 次。

| 优化项 | 现状 | 优化后 |
|---|---|---|
| `read_entry(child_id)` 获取子节点 title | LLM 主动调用 1-3 次 | **预嵌入 prompt**：`briefs` 中已有 title，直接写进 user message |
| `finalize()` 调用 | LLM 调用 1 次 | **隐式终止**：per-node 模式下 `write_entry` 成功后自动终止 |
| 校验重试 | `write_entry` 校验失败 0-1 次 | 不变（必要的质量保障） |

**实现**：

1. `_build_node_messages()` 中把子节点 brief（含 title）直接写入 prompt，消除 `read_entry` 调用：
```python
for c in children_ids:
    target = c.get("target", "")
    c_eid = self.entry_ids.get(target, target)
    c_title = next((b["title"] for b in briefs if b["node_id"] == target), "")
    lines.append(f"    {cond} → {target} ({c_eid}: \"{c_title}\")")
```
同时在 prompt 末尾改为："写完后无需调用 finalize()，系统会自动终止。"

2. per-node 模式下 `write_entry` 成功后自动终止（lint 统一推迟到 Phase 3 consistency review）：
```python
# harness2._run_per_node_mode() 中，_run_loop 结束后检查
# 不需要改 tools2.py — 只需在 _run_loop 外层检测 write 成功即可
```

**注意**：`finalize()` 中的 `run_lint()` 对单节点意义不大（此时只有一条 entry），全量 lint 在 Phase 3 consistency review 中统一执行，不损失质量。

**预期收益**：10 节点 DAG 从 ~40 次 LLM 调用降到 ~20 次，Agent 2 阶段耗时减半。

### US-2：Agent 2 同层并行

**现状**：`_run_per_node_mode()` 用 `for node in ordered_nodes` 串行处理。

**方案**：拓扑分层，同层叶子并行执行。

```
Layer 0 (叶子): [N3, N5, N7]  → ThreadPoolExecutor(3) 并行
  ↓ 收集 briefs
Layer 1 (中间): [N2, N6]       → ThreadPoolExecutor(2) 并行
  ↓ 收集 briefs
Layer 2 (根子): [N1, N4]       → ThreadPoolExecutor(2) 并行
  ↓ 收集 briefs
Pitfall root: [ROOT]            → 串行（最后写）
```

**安全性论证**：
- 每个节点有独立的 `messages` 列表（`_build_node_messages()` 每次新建）→ 天然线程安全
- 同层节点之间没有数据依赖（不互读对方的 entry）
- `ctx["written_entries"]` 的 append 需要加锁 → 用 `threading.Lock`
- API 调用是 I/O bound → `ThreadPoolExecutor` 正确选择（不受 GIL 限制）

**实现**：
```python
def _run_per_node_mode(self, process_nodes, ...):
    layers = self._topological_layers(process_nodes)  # 分层
    briefs = []

    for layer in layers:
        nodes_to_run = [n for n in layer if n["id"] not in written_node_ids]
        if not nodes_to_run:
            continue

        with ThreadPoolExecutor(max_workers=min(3, len(nodes_to_run))) as pool:
            futures = {
                pool.submit(self._generate_single_node, node, briefs, ...): node
                for node in nodes_to_run
            }
            for future in as_completed(futures):
                brief = future.result()
                if brief:
                    briefs.append(brief)

    # Pitfall root — 串行
    self._generate_root(briefs, ...)
```

**`_topological_layers()`**：现有 `_topological_reverse()` 返回扁平列表，改为返回分层列表。

**并发度**：默认 `max_workers=3`，受 API rate limit 限制。可通过 `HolmesConfig.import_concurrency` 配置。

**预期收益**：结合 US-1，10 节点 DAG 的 Agent 2 阶段从 ~5min 降到 ~1.5min。

### US-3：Classic Extractor 并行

**现状**：`pipeline.py` 中 KP 依次调用 `ExtractorAgent.run()`。

**安全性**：每个 KP 有独立的 `messages` 上下文（C-003 隔离保证），`doc_access` 工具只读 `ctx["source_text"]`（只读共享），天然可并行。

**实现**：
```python
# pipeline.py run() 中
with ThreadPoolExecutor(max_workers=min(3, len(knowledge_points))) as pool:
    futures = {
        pool.submit(extractor.run, kp, knowledge_map, ctx): kp
        for kp in knowledge_points
    }
    for future in as_completed(futures):
        kp = futures[future]
        draft = future.result()
        if draft:
            kp_drafts[kp.id] = draft
```

**预期收益**：3 个 KP 从串行 ~4min 降到 ~1.5min。

### US-4：增量 import（DAG 缓存复用）

**现状**：Agent 1 的 DAG 结果已保存在 `_import-state/<hash>.dag.json`，但每次 import 从零开始。

**方案**：
- 源文档 hash 相同 + DAG 文件存在 → 跳过 Agent 1，直接 Agent 2
- Agent 2 检查已写入的 entry → 只重跑未完成的节点（断点续跑）

**实现**：在 `pipeline.py._run_dag_pipeline()` 开头加缓存检查：
```python
dag_path = state_dir / f"{source_hash}.dag.json"
if dag_path.exists():
    self._progress("DAG cache hit — skipping Agent 1")
    dag_data = json.loads(dag_path.read_text())
    # 检查哪些 entry 已写入
    written = {nid for nid, eid in entry_ids.items()
               if find_entry(self.kb_root, eid) is not None}
    if written == set(entry_ids.keys()):
        self._progress("All entries already written — nothing to do")
        return report
    # 只生成未完成的节点
    ...
```

**预期收益**：重复/中断恢复 import 从 ~8min 降到 ~3min（跳过 Agent 1 的 ~3min）。

---

## 三、语义搜索（BM25 + LLM 查询扩展）

**设计原则**：不依赖 embedding 模型，不引入新的外部 API。复用已有的 chat LLM 做语义理解。

### US-5：BM25 搜索后端（替代 `term in haystack`）

**现状**：`LinearScanBackend` 用 `sum(1 for term in terms if term in haystack)` 做评分——所有词权重相同，不考虑词频和文档长度。

**方案**：用 BM25 算法替代，纯本地计算，零外部依赖。

BM25 核心优势：
- **IDF 权重**：罕见词（如 `nvidia-smi`）比常见词（如 `error`）权重高
- **词频饱和**：一个词出现 10 次不会比 3 次强太多（避免长文档偏差）
- **文档长度归一化**：短条目和长条目公平比较

**实现**：

```python
import math

class BM25Backend(SearchBackend):
    """BM25 ranked search, zero external dependencies."""

    K1 = 1.2   # 词频饱和参数
    B = 0.75   # 文档长度归一化参数

    def __init__(self, kb_root: Path):
        self._kb_root = kb_root
        self._docs: dict[str, dict] = {}   # entry_id → {terms, meta, ...}
        self._idf: dict[str, float] = {}
        self._avg_dl: float = 0.0
        self._built = False

    def _build_index(self):
        """扫描所有 entry，构建倒排索引 + IDF 表。懒加载，首次搜索时触发。"""
        ...
        # 对每个 entry：分词 → 统计词频 → 计算 IDF
        self._built = True

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        if not self._built:
            self._build_index()
        terms = self._tokenize(query)
        scores = {}
        for entry_id, doc in self._docs.items():
            score = sum(
                self._idf.get(t, 0) * (doc["tf"].get(t, 0) * (self.K1 + 1))
                / (doc["tf"].get(t, 0) + self.K1 * (1 - self.B + self.B * doc["dl"] / self._avg_dl))
                for t in terms
            )
            if score > 0:
                scores[entry_id] = score
        ...

    def _tokenize(self, text: str) -> list[str]:
        """中英文混合分词：英文按空格/标点拆分转小写，中文按字符 bigram。"""
        # 不引入 jieba 等重依赖
        # 英文: re.findall(r"[a-z0-9][-a-z0-9_.]*[a-z0-9]|[a-z0-9]+", text.lower())
        # 中文: 连续中文字符提取 bigram → ["连接", "接池", "池耗", "耗尽"]
        ...
```

**分词策略**（关键决策）：
- 英文：`re.findall` 提取 token，转小写。保留 `-` `.` `_`（`nvidia-smi`、`E01` 完整匹配）
- 中文：字符 bigram（"连接池耗尽" → ["连接", "接池", "池耗", "耗尽"]）
  - 不引入 jieba 等分词库（重依赖），bigram 对 BM25 够用
  - 单字命中率太低，trigram 太稀疏，bigram 是最佳平衡点
- 混合文本自动识别语种按对应策略分词

**索引生命周期**：
- 首次 `kb_search` 调用时懒构建（扫描所有 .md 文件，~100ms for 1000 entries）
- 进程内缓存（MCP server 是长驻进程，index 只建一次）
- `holmes kb rebuild-index` 手动刷新
- import 完成后通过 `_invalidate()` 标记需要重建

### US-6：LLM 查询扩展（语义层）

BM25 解决了权重和排序问题，但仍然是关键词匹配——搜 "redis 超时" 找不到 title 是 "Redis Connection Pool Exhausted" 的条目。

**方案**：在 BM25 搜索前，用已有的 chat LLM 做一次查询扩展：

```python
def _expand_query(self, query: str) -> str:
    """用 LLM 把用户查询扩展为多语言同义词列表，再交给 BM25。"""
    response = self._provider.simple_complete(
        messages=[{"role": "user", "content": query}],
        system=(
            "You are a search query expander for a technical troubleshooting knowledge base. "
            "Given the user's search query, output 5-8 additional search terms: "
            "synonyms, translations (Chinese↔English), related technical terms, "
            "and common error messages. Output ONLY the terms, space-separated, no explanation."
        ),
        max_tokens=100,
    )
    # "redis 超时" → "redis timeout connection pool exhausted 连接池 超时 ERR max clients"
    return f"{query} {response.strip()}"
```

**效果链路**：
```
用户搜 "redis 超时"
    ↓ LLM 扩展 (~200ms)
"redis 超时 timeout connection pool exhausted 连接池 ERR max clients"
    ↓ BM25 搜索 (~10ms)
✓ 命中 "Redis Connection Pool Exhausted"（通过 "connection pool exhausted" 匹配）
```

**控制开关**：
- MCP `kb_search` 默认启用 LLM 扩展（agent 搜索场景，延迟不敏感）
- CLI `holmes kb search` 默认禁用（用户可 `--expand` 手动开启）
- 若 LLM 调用失败，静默 fallback 到原始 query（不影响可用性）

**效果矩阵**：
| 查询 | 纯 BM25 | BM25 + LLM 扩展 |
|---|---|---|
| "redis 超时" | ✗（title 是英文） | ✓（扩展出 "timeout", "connection pool"） |
| "连接池耗尽" | 部分✓（bigram 匹配中文内容） | ✓（扩展出 "connection pool", "exhausted"） |
| "nvidia-smi" | ✓（精确匹配） | ✓ |
| "E01" | ✓（精确匹配） | ✓ |
| "GPU 初始化失败怎么排查" | 部分✓ | ✓（扩展出 "initialization", "firmware", "Xid"） |

### US-7：MCP search tool description 优化

```python
@mcp.tool()
def kb_search(query: str, ...):
    """Search the knowledge base by keyword or natural language query.

    Supports cross-language matching — queries in Chinese find English
    entries and vice versa. Technical terms, error codes, and command
    names are matched precisely.

    SEARCH TIPS:
    - Symptom description: "redis connection timeout under load"
    - Error message verbatim: "ERR max number of clients reached"
    - Component + problem: "kafka consumer lag"
    - If no results, try broader terms or different language
    """
```

---

## 四、实现计划

### Phase 1 — Import 提速（~2 天）
- US-1: 减少 Agent 2 每节点 LLM 调用（预嵌入 child title + write_entry 后隐式终止）
- US-2: Agent 2 同层并行（`_topological_layers` + `ThreadPoolExecutor`）
- US-3: Classic Extractor 并行
- US-4: DAG 缓存复用 + 断点续跑

### Phase 2 — 语义搜索（~2 天）
- US-5: BM25Backend 实现（替代 LinearScanBackend）
- US-6: LLM 查询扩展（MCP 默认启用）
- US-7: MCP search prompt 优化

### Phase 3 — 验证 + 调优（~1 天）
- LLM e2e 测试全量通过（质量不降低）
- 搜索效果人工评测（10 个代表性查询）
- 并发度调优

---

## 五、验收标准

### Import 效率
| 指标 | 现状 | 目标 |
|---|---|---|
| 10 节点 DAG 文档 import | ~8min | **≤3min** |
| 3 KP Classic 文档 import | ~4min | **≤2min** |
| 重复文档 import（缓存命中）| ~8min | **≤2min** |
| Agent 2 每节点 LLM 调用数 | 3-5 次 | **1-2 次** |
| LLM e2e 测试通过率 | 30/34 | **≥30/34（不降低）** |

### 搜索效果
| 场景 | 现状 | 目标 |
|---|---|---|
| "redis 超时" → "Redis Connection Pool Exhausted" | ✗ | ✓ |
| "连接池" → 英文条目 | ✗ | ✓ |
| "nvidia-smi" 精确匹配 | ✓ | ✓（不退化） |
| "E01" 精确匹配 | ✓ | ✓（不退化） |
| 搜索延迟（<1000 条目）| <200ms | **<300ms**（BM25 + LLM 扩展 ~200ms） |

### 不变量（质量红线）
- 逐字保真规则不受并行化影响
- 每个节点的 LLM prompt 内容与串行时完全一致
- DAG 缓存只在 source hash 严格匹配时复用
- LLM 扩展失败时静默 fallback 到原始 query，搜索不中断
