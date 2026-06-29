# 039 — MCP Agent 端到端测试

## 产品目标

验证 **硬件工程师通过 agent + KB MCP 工具排查问题** 的完整用户旅程：
- agent 能找到相关知识
- 返回的排查步骤准确、可执行
- 知识反馈闭环（confirm/draft）正确工作
- 每一步 MCP 调用的输入/输出可审计

## 测试架构

```
┌─────────────┐      ┌──────────────┐      ┌──────────────┐
│  Test        │─────▶│  LLM Agent   │─────▶│  MCP Tools   │
│  Harness     │      │  (real LLM)  │      │  (direct     │
│              │◀─────│              │◀─────│   function)  │
│  assertions  │      │  deepseek    │      │  handle_kb_* │
└─────────────┘      └──────────────┘      └──────────────┘
                                                  │
                                            ┌─────▼─────┐
                                            │  Test KB   │
                                            │  (tmp_path)│
                                            └───────────┘
```

**不启动 MCP HTTP server**。直接调用 `handle_kb_*` handler 函数，
用 LLM tool-use loop 模拟 agent 行为。好处：
1. 无网络开销，测试稳定
2. 可拦截每一次工具调用，记录审计日志
3. 与 e2e_llm.py 测试复用相同的 provider/config 基础设施

## 测试 KB 数据准备

使用 `conftest.py` 中的 fixture 在 `tmp_path` 下创建一个 **最小但完整** 的 KB：

```
test-kb/
├── pitfall/
│   ├── hardware/
│   │   └── PT-HW-001.md    ← NVMe SSD 写延迟飙升（已知问题，有 skill_ref）
│   ├── network/
│   │   └── PT-NET-001.md   ← 交换机端口 CRC 错误导致丢包
│   └── database/
│       └── PT-DB-001.md    ← Redis 连接池耗尽
├── process/
│   └── hardware/
│       └── PR-HW-001-01.md ← NVMe 排查子步骤（PT-HW-001 的 child）
├── guideline/
│   └── hardware/
│       └── GL-HW-001.md    ← 硬件巡检规范
├── skills/
│   └── nvme-smart-check/
│       └── SKILL.md         ← NVMe SMART 检查技能
├── contributions/
│   └── evidence/            ← 空目录
└── index.json
```

每个条目 **内容固定、已知**，用于精确断言。

## 场景设计

### Scenario 1: 精确命中 — NVMe 写延迟排查（Happy Path）

**模拟用户输入**：
> "我们的存储服务器 NVMe SSD 写延迟从 0.5ms 飙升到 50ms，iostat 显示 await 异常高，怎么排查？"

**期望 agent 行为链**（按顺序）：

| Step | 期望 MCP 调用 | 验证点 |
|------|---------------|--------|
| 1 | `kb_overview()` | 返回 session_id；entries 包含 pitfall 计数 |
| 2 | `kb_search(query="NVMe 写延迟")` | 返回 PT-HW-001，score > 0 |
| 3 | `kb_read(entry_id="PT-HW-001")` | 返回完整内容；包含 `children` 字段（PR-HW-001-01）；包含 `skill_refs`（nvme-smart-check） |
| 4 | `kb_read(entry_id="PR-HW-001-01")` | 读取子步骤详情 |
| 5 | `kb_read(entry_id="nvme-smart-check")` | 读取 skill 内容（SMART 检查命令） |

**最终输出验证**：
- agent 回复中包含 `smartctl` 或 `nvme smart-log` 等关键命令
- agent 回复中包含具体的排查步骤（来自 KB，非幻觉）
- agent 提及了固件版本/Wear Leveling 等 KB 中的关键信息

**追加验证 — confirm 闭环**：
| Step | 期望 MCP 调用 | 验证点 |
|------|---------------|--------|
| 6 | 用户说 "问题解决了" | agent 应调用 `kb_confirm(entry_id="PT-HW-001", session_id=<from step 1>)` |
| 7 | 验证 confirm 结果 | `ok=true`，maturity 从 draft → verified |
| 8 | 检查 evidence 目录 | `contributions/evidence/PT-HW-001/<session_id>.json` 存在 |

---

### Scenario 2: 未命中 — 新问题的知识沉淀（Draft Path）

**模拟用户输入**：
> "BMC 固件升级后 IPMI 无法连接，ping 通但 ipmitool 超时"

**期望 agent 行为链**：

| Step | 期望 MCP 调用 | 验证点 |
|------|---------------|--------|
| 1 | `kb_overview()` | 正常返回 |
| 2 | `kb_search(query="BMC IPMI 超时")` | 返回 0 条结果或无相关结果 |
| 3 | agent 基于自身知识给出排查建议 | 回复中不包含 KB entry ID |
| 4 | 用户说 "问题解决了，帮我记录一下" | — |
| 5 | `kb_draft(content=..., title=...)` | `saved` 字段包含 `_drafts/` 路径；文件实际存在于 test KB |

**验证点**：
- draft 文件内容包含 BMC/IPMI 关键词
- draft frontmatter 包含 `author` 和 `saved_at`
- agent 回复包含 `holmes import _drafts/...` 的提示

---

### Scenario 3: 多步导航 — 从 pitfall root 到 process 子条目

**模拟用户输入**：
> "NVMe SSD 有问题，该怎么一步步排查？"

**期望 agent 行为链**：

| Step | 期望 MCP 调用 | 验证点 |
|------|---------------|--------|
| 1 | `kb_overview()` | 正常 |
| 2 | `kb_search(query="NVMe SSD 排查")` | 命中 PT-HW-001 |
| 3 | `kb_read(entry_id="PT-HW-001")` | 返回 `children: [{id: "PR-HW-001-01", title: "..."}]` |
| 4 | `kb_read(entry_id="PR-HW-001-01")` | 返回具体排查步骤 |

**验证**：agent 按 KB 的 process 子条目结构输出排查步骤，而不是自行编造。

---

### Scenario 4: 模糊搜索 — 症状描述不精确

**模拟用户输入**：
> "服务器磁盘很慢，IO 很高"

**期望**：
- `kb_search` 被调用，query 包含磁盘/IO 相关词
- 如果命中 NVMe 条目，agent 会追问确认（SSD 还是 HDD？哪台机器？）
- 验证 agent 不会在没有读取 KB entry 的情况下直接给出 KB 中的具体步骤

---

### Scenario 5: Category 浏览 — 工程师主动查看知识库

**模拟用户输入**：
> "看看知识库里有哪些硬件相关的问题记录"

**期望 agent 行为链**：

| Step | 期望 MCP 调用 | 验证点 |
|------|---------------|--------|
| 1 | `kb_overview()` | categories 包含 "hardware" |
| 2 | `kb_list(type="pitfall", category="hardware")` | 返回 PT-HW-001 |

---

## 测试实现策略

### 文件：`kb/tests/test_e2e_mcp.py`

```python
@pytest.mark.llm           # 需要真实 LLM
@pytest.mark.mcp_e2e       # 可单独跑

class AgentMCPHarness:
    """轻量 agent 测试线束 — 驱动 LLM tool-use loop，拦截 MCP 调用。"""

    def __init__(self, provider, model, kb_root):
        self.provider = provider
        self.model = model
        self.kb_root = kb_root
        self.tool_log: list[dict] = []   # 记录每次工具调用
        self.session_id: str = ""

    def _dispatch_tool(self, name: str, args: dict) -> dict:
        """路由 tool call 到 handle_kb_* 函数，记录审计日志。"""
        result = handle_kb_xxx(self.kb_root, **args)
        self.tool_log.append({"tool": name, "args": args, "result": result})
        return result

    def run(self, user_messages: list[str], max_turns=20) -> AgentResult:
        """驱动多轮对话，返回 tool_log + final_response。"""
        ...
```

### 断言模式

```python
def test_scenario_1_nvme_exact_hit(agent_harness, test_kb):
    result = agent_harness.run(["NVMe SSD 写延迟从 0.5ms 飙升到 50ms..."])

    # 1. 必须调用了 kb_overview
    assert any(t["tool"] == "kb_overview" for t in result.tool_log)

    # 2. 必须搜索过
    search_calls = [t for t in result.tool_log if t["tool"] == "kb_search"]
    assert len(search_calls) >= 1

    # 3. 必须读取了 PT-HW-001
    read_calls = [t for t in result.tool_log if t["tool"] == "kb_read"]
    read_ids = {t["args"].get("entry_id") for t in read_calls}
    assert "PT-HW-001" in read_ids

    # 4. 最终回复包含 KB 中的关键命令
    assert "smartctl" in result.final_response or "nvme smart-log" in result.final_response

    # 5. 没有调用 kb_draft（命中了，不该存草稿）
    assert not any(t["tool"] == "kb_draft" for t in result.tool_log)
```

### 关键设计决策

1. **Tool 定义通过 JSON schema 注入 LLM**：从 `server.py` 的 6 个 `@mcp.tool()` 函数签名自动生成 tool schema，注入 LLM 的 `tools` 参数
2. **System prompt 模拟真实 CLAUDE.md**：使用与 `~/holmes-kb/CLAUDE.md` 相同的指令，确保 agent 行为一致
3. **Session-scoped test KB fixture**：KB 数据只创建一次，所有场景共享（只读场景）；confirm/draft 场景用 function-scoped copy
4. **Tool log 断言而非 response 文本断言**：优先验证"调用了什么工具、传了什么参数、返回了什么"，其次验证最终文本

## 验证矩阵

| 验证维度 | Scenario 1 | Scenario 2 | Scenario 3 | Scenario 4 | Scenario 5 |
|---------|:---------:|:---------:|:---------:|:---------:|:---------:|
| kb_overview 被调用 | ✓ | ✓ | ✓ | ✓ | ✓ |
| kb_search 被调用 | ✓ | ✓ | ✓ | ✓ | |
| kb_list 被调用 | | | | | ✓ |
| kb_read 命中正确 entry | ✓ | | ✓ | △ | |
| skill_ref 被读取 | ✓ | | | | |
| children 导航 | ✓ | | ✓ | | |
| kb_confirm 正确调用 | ✓ | | | | |
| kb_draft 正确调用 | | ✓ | | | |
| evidence 文件写入 | ✓ | | | | |
| draft 文件写入 | | ✓ | | | |
| maturity 变化 | ✓ | | | | |
| 回复含 KB 关键信息 | ✓ | | ✓ | | |
| 回复不含 KB 幻觉 | | ✓ | | ✓ | |

△ = 取决于搜索召回

## 预期测试数量

- Scenario 1: ~8 assertions → 1 test function
- Scenario 2: ~5 assertions → 1 test function
- Scenario 3: ~4 assertions → 1 test function
- Scenario 4: ~3 assertions → 1 test function
- Scenario 5: ~3 assertions → 1 test function
- **总计: 5 个 test functions，~23 assertions**

## 运行方式

```bash
# 仅 MCP e2e 测试
HOLMES_LLM_TESTS=1 python -m pytest kb/tests/test_e2e_mcp.py -v --tb=short -p no:timeout

# 与现有 e2e 测试一起跑
HOLMES_LLM_TESTS=1 python -m pytest kb/tests/ -m llm -v --tb=short -p no:timeout
```

## 预期耗时

每个 scenario ~3-8 轮 LLM 调用，deepseek-v4-flash 约 2.6s/轮：
- Scenario 1 (含 confirm): ~8 轮 ≈ 21s
- Scenario 2 (含 draft): ~6 轮 ≈ 16s
- Scenario 3: ~5 轮 ≈ 13s
- Scenario 4: ~4 轮 ≈ 10s
- Scenario 5: ~3 轮 ≈ 8s
- **总计: ~68s**（远快于 DAG pipeline e2e 测试）
