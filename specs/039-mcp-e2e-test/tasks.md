# 039 — MCP Agent E2E Test — Tasks

## T1: 创建测试 KB fixture

**文件**: `kb/tests/fixtures/test_kb/` (目录结构)

在 `conftest.py` 中创建 `mcp_test_kb` session-scoped fixture：
- `pitfall/hardware/PT-HW-001.md` — NVMe SSD 写延迟飙升
  - 包含 `skill_refs: [nvme-smart-check]`
  - 包含 `child_entry_ids: [PR-HW-001-01]`
  - maturity: draft
  - 内容包含 smartctl、nvme smart-log 命令
- `process/hardware/PR-HW-001-01.md` — NVMe SMART 检查子步骤
  - `parent_id: PT-HW-001`
  - 具体排查步骤 1-2-3
- `pitfall/network/PT-NET-001.md` — 交换机端口 CRC 错误导致丢包
  - maturity: verified
- `pitfall/database/PT-DB-001.md` — Redis 连接池耗尽
  - maturity: proven
- `guideline/hardware/GL-HW-001.md` — 硬件巡检规范
- `skills/nvme-smart-check/SKILL.md` — NVMe SMART 检查技能
  - 包含 smartctl -a /dev/nvmeX 命令
- `contributions/evidence/` — 空目录
- `index.json` — 基本统计

每个文件内容完全固定，写死在 fixture 代码中。

**验收**: `pytest kb/tests/test_e2e_mcp.py::test_fixture_smoke -v` 通过

---

## T2: 实现 AgentMCPHarness

**文件**: `kb/tests/test_e2e_mcp.py`

实现测试线束类：

```python
class AgentMCPHarness:
    def __init__(self, provider, model, kb_root, system_prompt):
        self.provider = provider
        self.model = model
        self.kb_root = kb_root
        self.system_prompt = system_prompt
        self.tool_log: list[dict] = []

    def _get_tool_schemas(self) -> list[dict]:
        """返回 6 个 KB MCP 工具的 JSON schema，供 LLM tool-use。"""

    def _dispatch_tool(self, name: str, args: dict) -> str:
        """路由到 handle_kb_* 函数，记录到 tool_log，返回 JSON 字符串。"""

    def run(self, user_messages: list[str], max_turns=20) -> AgentResult:
        """驱动多轮 LLM tool-use loop。
        每条 user_message 按顺序注入（模拟多轮对话）。
        返回 AgentResult(tool_log, final_response, turn_count)。
        """
```

关键：
- tool schema 从 `server.py` 的函数签名 + docstring 手动定义（6 个工具）
- system prompt 从 spec 中定义的 MCP 版指令生成
- `_dispatch_tool` 直接调用 `handle_kb_overview(kb_root)`、`handle_kb_search(kb_root, query=...)` 等
- tool_log 记录 `{tool, args, result, turn}` 四元组

**验收**: harness 可实例化，`_get_tool_schemas()` 返回 6 个 schema

---

## T3: 编写 MCP Agent System Prompt

**位置**: `kb/tests/test_e2e_mcp.py` 顶部常量

编写 `MCP_AGENT_SYSTEM_PROMPT`，模拟真实 agent 使用 MCP 工具的指令：

```
你是 Holmes，一个专业的故障排查助手，通过 MCP 工具访问结构化知识库。

## 必须遵守的工作流程

1. 收到排查问题时，先调用 kb_overview() 获取 session_id
2. 用 kb_search(query=...) 搜索相关知识
3. 对搜索结果调用 kb_read(entry_id=...) 读取完整内容
4. 如果 entry 有 skill_refs，读取 skill 内容
5. 如果 entry 有 children，读取子条目获取详细步骤
6. 基于 KB 知识给出排查建议，引用 entry ID
7. 用户确认解决后，调用 kb_confirm(entry_id, session_id)
8. 如果 KB 无匹配，用自身知识回答；用户确认解决后调用 kb_draft 记录

## 禁止
- 不要在没有读取 entry 的情况下引用 KB 内容
- 不要编造 entry ID
```

**验收**: prompt 完整定义 6 个工具的使用时机

---

## T4: Scenario 1 — 精确命中 NVMe 问题

**文件**: `kb/tests/test_e2e_mcp.py`

```python
class TestScenario1ExactHit:
    """Agent 精确命中 KB 已知问题，完成搜索→阅读→回复→confirm 全流程。"""

    def test_agent_calls_overview_first(self, scenario1_result):
        """第一个工具调用必须是 kb_overview。"""

    def test_agent_searches_nvme(self, scenario1_result):
        """agent 调用了 kb_search，query 包含 NVMe/延迟/写 相关词。"""

    def test_agent_reads_correct_entry(self, scenario1_result):
        """agent 读取了 PT-HW-001。"""

    def test_agent_reads_skill(self, scenario1_result):
        """agent 读取了 nvme-smart-check skill。"""

    def test_response_contains_kb_commands(self, scenario1_result):
        """最终回复包含 smartctl 或 nvme smart-log 命令。"""

    def test_agent_does_not_draft(self, scenario1_result):
        """命中已知问题，不应调用 kb_draft。"""
```

**验收**: 6 个 assertions 全过

---

## T5: Scenario 1 续 — Confirm 闭环

**文件**: `kb/tests/test_e2e_mcp.py`

在 Scenario 1 结果基础上，追加一轮用户消息 "问题解决了"：

```python
class TestScenario1Confirm:
    def test_confirm_called(self, scenario1_confirm_result):
        """agent 调用了 kb_confirm(PT-HW-001, session_id)。"""

    def test_confirm_result_ok(self, scenario1_confirm_result):
        """confirm 返回 ok=true。"""

    def test_evidence_file_created(self, scenario1_confirm_result, test_kb_path):
        """contributions/evidence/PT-HW-001/ 下创建了 evidence JSON。"""

    def test_maturity_promoted(self, scenario1_confirm_result):
        """maturity 从 draft 变为 verified。"""
```

**验收**: 4 个 assertions 全过

---

## T6: Scenario 2 — 未命中走 Draft 路径

**文件**: `kb/tests/test_e2e_mcp.py`

```python
class TestScenario2DraftPath:
    """KB 无匹配时 agent 用自身知识回答，解决后创建 draft。"""

    def test_search_returns_no_match(self, scenario2_result):
        """kb_search 被调用但无高相关结果。"""

    def test_no_kb_read_called(self, scenario2_result):
        """没有读取任何 entry（或读了但发现不相关）。"""

    def test_draft_called_on_resolution(self, scenario2_draft_result):
        """用户确认解决后，kb_draft 被调用。"""

    def test_draft_file_exists(self, scenario2_draft_result, test_kb_path):
        """_drafts/ 目录下创建了 .md 文件。"""

    def test_draft_contains_keywords(self, scenario2_draft_result, test_kb_path):
        """draft 内容包含 BMC/IPMI 关键词。"""
```

**验收**: 5 个 assertions 全过

---

## T7: Scenario 3 — Children 导航

**文件**: `kb/tests/test_e2e_mcp.py`

```python
class TestScenario3ChildNavigation:
    """Agent 从 pitfall root 导航到 process 子条目。"""

    def test_reads_root_entry(self, scenario3_result):
        """读取了 PT-HW-001。"""

    def test_reads_child_entry(self, scenario3_result):
        """读取了 PR-HW-001-01。"""

    def test_response_has_structured_steps(self, scenario3_result):
        """回复中包含来自子条目的具体步骤。"""
```

**验收**: 3 个 assertions 全过

---

## T8: Scenario 5 — Category 浏览

**文件**: `kb/tests/test_e2e_mcp.py`

```python
class TestScenario5Browse:
    """Agent 使用 kb_list 浏览知识库。"""

    def test_list_called(self, scenario5_result):
        """kb_list 被调用，参数包含 category 或 type。"""

    def test_response_lists_entries(self, scenario5_result):
        """回复中包含 entry 标题。"""
```

**验收**: 2 个 assertions 全过

---

## T9: 集成运行与 CI 标记

- 确保 `@pytest.mark.llm` 和 `@pytest.mark.mcp_e2e` 标记正确
- 确保 `HOLMES_LLM_TESTS=1` 环境变量控制是否跳过
- 运行全部 5 个 scenario，验证总耗时 < 3 分钟
- Session-scoped fixture 确保 scenario 1/3 共享同一次 agent 运行（相似 query）

**验收**: `HOLMES_LLM_TESTS=1 pytest kb/tests/test_e2e_mcp.py -v --tb=short` 全绿
