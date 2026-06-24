"""
多轮对话追踪脚本 — 手动验证 Agent1Harness 多轮交互行为。

验证场景：
  S1: 校验失败 → 修复循环（output_dag 返回错误 → LLM 修复 → 再次 output_dag 成功）
  S2: Read/Grep 穿插 write_dag（三阶段真实流程）
  S3: 消息历史是否正确追加（tool results 回传）
  S4: Phase 标记 read→draft→review[1]→review[2] 是否正确

运行方法：
  cd /home/wangzhi/project/projectTmp/holmes/holmes
  python -m kb.tests.trace_multiturn
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from holmes.kb.agent.dag.formatter import dag_to_markdown
from holmes.kb.agent.dag.harness1 import Agent1Harness
from holmes.kb.agent.dag.schema import (
    Complexity, DAGEdge, DAGGraph, DAGNode, NodeType,
)
from holmes.kb.agent.provider.base import LLMProvider, ToolCall


# ---------------------------------------------------------------------------
# 带追踪的 MockProvider
# ---------------------------------------------------------------------------

class TracingProvider(LLMProvider):
    """按脚本回放工具调用，同时打印每轮输入/输出详情。"""

    def __init__(self, turns: list[list[ToolCall]], name: str = ""):
        self._turns = list(turns)
        self._idx = 0
        self._name = name
        self._turn_history: list[dict] = []

    def complete(self, messages, system, model, max_tokens, tools):
        turn_n = self._idx + 1
        print(f"\n{'='*60}")
        print(f"  TURN {turn_n} → provider.complete() 被调用")
        print(f"  messages 长度: {len(messages)}")
        # 打印最后一条消息（当前轮输入）
        if messages:
            last = messages[-1]
            role = last.get("role", "?")
            # tool_results 回传
            if "results" in last or "tool_results" in last:
                results = last.get("results") or last.get("tool_results") or []
                print(f"  ← 上轮工具结果回传 ({len(results)} 个):")
                for r in results:
                    if isinstance(r, tuple):
                        tid, content = r
                        try:
                            data = json.loads(content)
                        except Exception:
                            data = content
                        print(f"      [{tid}] {json.dumps(data, ensure_ascii=False)[:120]}")
                    elif isinstance(r, dict):
                        print(f"      {json.dumps(r, ensure_ascii=False)[:120]}")
            elif role == "user":
                content = last.get("content", "")
                print(f"  ← user: {str(content)[:80]}...")

        if self._idx >= len(self._turns):
            print(f"  → stop=True (脚本结束)")
            print(f"{'='*60}")
            self._idx += 1
            return True, [], messages, {}

        calls = self._turns[self._idx]
        self._idx += 1

        if not calls:
            print(f"  → stop=True (空轮次 = LLM 结束)")
            print(f"{'='*60}")
            updated = list(messages) + [{"role": "assistant", "content": "(no tool calls)"}]
            return True, [], updated, {}

        print(f"  → LLM 发出 {len(calls)} 个工具调用:")
        for c in calls:
            inp_str = json.dumps(c.input, ensure_ascii=False)
            if len(inp_str) > 100:
                inp_str = inp_str[:97] + "..."
            print(f"      [{c.id}] {c.name}({inp_str})")
        print(f"{'='*60}")

        updated = list(messages) + [{"role": "assistant", "tool_calls": calls}]
        return False, calls, updated, {}

    def simple_complete(self, messages, system="", max_tokens=512):
        return ""

    def append_tool_results(self, messages, results):
        return list(messages) + [{"role": "user", "results": results}]


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _valid_dag(extra_node: bool = False) -> str:
    """构造一个通过全部5条规则的 DAG。"""
    n1 = DAGNode("N1", "检查电源", NodeType.decision, Complexity.simple,
                  children=[DAGEdge("正常", "N2"), DAGEdge("故障", "N3")])
    n2 = DAGNode("N2", "端口检查", NodeType.action, Complexity.simple,
                  children=[DAGEdge("通过", "END")])
    n3 = DAGNode("N3", "固件修复", NodeType.action, Complexity.process,
                  section_heading="### 固件修复步骤",
                  children=[DAGEdge("完成", "END")])
    nodes = [n1, n2, n3]
    if extra_node:
        n4 = DAGNode("N4", "备用路径", NodeType.action, Complexity.simple,
                      children=[DAGEdge("ok", "END")])
        nodes.append(n4)
    g = DAGGraph(nodes=nodes, title="硬件初始化失败",
                 source_file="hardware.md", generated="2026-06-24")
    return dag_to_markdown(g)


def _invalid_dag_cycle() -> str:
    """构造一个有环的 DAG（违反规则3）。"""
    return textwrap.dedent("""\
        # 排查树：有环DAG

        > source: hardware.md
        > generated: 2026-06-24
        > 说明：test

        ---

        ## 文档摘要

        test

        ---

        ## 排查树概览

        test

        ---

        ## 节点详情

        ### N1 — root
        complexity: simple
        node_type: action

        - go → **N2**

        ---

        ### N2 — middle
        complexity: simple
        node_type: action

        - loop → **N3**

        ---

        ### N3 — cycle back
        complexity: simple
        node_type: action

        - back → **N2**
    """)


def _make_cfg():
    cfg = MagicMock()
    cfg.model = "test-model"
    return cfg


def _make_harness(tmp_path: Path, provider: TracingProvider) -> Agent1Harness:
    return Agent1Harness(
        kb_root=tmp_path,
        cfg=_make_cfg(),
        provider=provider,
        source_hash="abc12345678901ab",
        source_file="hardware.md",
        no_interactive=True,
        dry_run=False,
    )


def _print_report(report, scenario: str):
    print(f"\n{'#'*60}")
    print(f"  FINAL REPORT — {scenario}")
    print(f"{'#'*60}")
    print(f"  errors:          {report.errors}")
    print(f"  warnings:        {report.warnings}")
    print(f"  phase_traces:    {report.phase_traces}")
    print(f"  auto_decisions:  {report.auto_decisions}")


def _check(condition: bool, msg: str):
    status = "PASS" if condition else "FAIL"
    icon = "✓" if condition else "✗"
    print(f"  [{status}] {icon} {msg}")
    if not condition:
        print(f"         ^^^ 预期断言失败")
    return condition


# ---------------------------------------------------------------------------
# 场景 S1：校验失败 → 修复循环
# ---------------------------------------------------------------------------

def scenario_s1(tmp_path: Path):
    """
    S1: LLM 先写了有环的 DAG → output_dag 返回错误 → 修复后再写 → output_dag 成功

    预期行为：
      turn1: write_dag(有环内容) → 写入文件，返回 success
      turn2: output_dag() → 返回 error (cycle)，_terminate 为 False，循环继续
      turn3: write_dag(有效内容) → 覆盖文件，返回 success
      turn4: output_dag() → 通过5条规则，_terminate=True，循环结束
    """
    print(f"\n{'*'*60}")
    print(f"  场景 S1：校验失败 → 修复循环")
    print(f"{'*'*60}")

    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()

    turns = [
        [ToolCall(id="t1", name="write_dag", input={"content": _invalid_dag_cycle()})],
        [ToolCall(id="t2", name="output_dag", input={})],
        [ToolCall(id="t3", name="write_dag", input={"content": _valid_dag()})],
        [ToolCall(id="t4", name="output_dag", input={})],
    ]
    provider = TracingProvider(turns, "S1")
    harness = _make_harness(tmp_path, provider)
    report = harness.run("硬件初始化失败文档内容")

    _print_report(report, "S1 校验失败→修复循环")

    print("\n  验证点：")
    all_pass = True
    all_pass &= _check(not report.errors, "没有 errors（最终成功）")
    all_pass &= _check(
        any("节点" in t for t in report.phase_traces),
        "phase_traces 包含节点提取信息"
    )
    # 验证 .dag.json 存在且内容正确（output_dag 第2次成功才写）
    dag_json = state_dir / "abc12345678901ab.dag.json"
    all_pass &= _check(dag_json.exists(), ".dag.json 存在（output_dag 第2次成功时写入）")
    if dag_json.exists():
        data = json.loads(dag_json.read_text())
        all_pass &= _check(len(data["nodes"]) == 3, ".dag.json 包含3个节点（有效DAG）")
    # 验证 .dag.md 最终内容是有效版本（有环版本被覆盖）
    dag_md = state_dir / "abc12345678901ab.dag.md"
    if dag_md.exists():
        content = dag_md.read_text()
        all_pass &= _check("固件修复" in content, ".dag.md 最终是有效版本（覆盖了有环版本）")

    print(f"\n  S1 结果: {'全部通过' if all_pass else '存在失败'}")
    return all_pass


# ---------------------------------------------------------------------------
# 场景 S2：Read/Grep 穿插 write_dag（真实三阶段流程）
# ---------------------------------------------------------------------------

def scenario_s2(tmp_path: Path):
    """
    S2: 模拟真实三阶段流程
      Phase 1 (study):  Read → Grep → Read
      Phase 2 (draft):  write_dag(初稿)
      Phase 3 (review): read_dag → write_dag(修订) → output_dag

    预期行为：
      - Read/Grep 调用正常返回文件内容
      - write_dag 两次调用都成功（第2次覆盖第1次）
      - output_dag 最终成功
      - phase 追踪：read→draft→review[1]
    """
    print(f"\n{'*'*60}")
    print(f"  场景 S2：三阶段真实流程（Read/Grep 穿插）")
    print(f"{'*'*60}")

    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()

    turns = [
        # Phase 1: study
        [ToolCall(id="t1", name="Read",
                   input={"path": "hardware.md", "offset": 0, "limit": 50})],
        [ToolCall(id="t2", name="Grep",
                   input={"pattern": "初始化", "path": "hardware.md"})],
        [ToolCall(id="t3", name="Read",
                   input={"path": "hardware.md", "offset": 50, "limit": 50})],
        # Phase 2: first draft
        [ToolCall(id="t4", name="write_dag",
                   input={"content": _valid_dag()})],
        # Phase 3: review
        [ToolCall(id="t5", name="read_dag", input={})],
        [ToolCall(id="t6", name="write_dag",
                   input={"content": _valid_dag(extra_node=True)})],
        [ToolCall(id="t7", name="output_dag", input={})],
    ]
    provider = TracingProvider(turns, "S2")
    harness = _make_harness(tmp_path, provider)
    report = harness.run(
        "设备在上电后无法完成初始化序列。错误代码：ERR_INIT_FAIL。"
        "排查步骤：检查电源 → 检查固件 → 硬件更换。"
    )

    _print_report(report, "S2 三阶段流程")

    print("\n  验证点：")
    all_pass = True
    all_pass &= _check(not report.errors, "没有 errors")
    dag_json = state_dir / "abc12345678901ab.dag.json"
    all_pass &= _check(dag_json.exists(), ".dag.json 存在")
    if dag_json.exists():
        data = json.loads(dag_json.read_text())
        all_pass &= _check(len(data["nodes"]) == 4,
                            ".dag.json 包含4个节点（extra_node=True 的版本被写入）")
    all_pass &= _check(
        any("节点" in t for t in report.phase_traces),
        "phase_traces 包含节点信息"
    )

    print(f"\n  S2 结果: {'全部通过' if all_pass else '存在失败'}")
    return all_pass


# ---------------------------------------------------------------------------
# 场景 S3：消息历史正确追加（tool results 回传验证）
# ---------------------------------------------------------------------------

def scenario_s3(tmp_path: Path):
    """
    S3: 验证每轮工具结果是否真的追加进消息历史，影响下一轮 provider.complete() 收到的 messages

    预期行为：
      - 每次 provider.complete() 收到的 messages 长度递增
      - 第2轮 messages 包含第1轮工具结果
      - 第3轮 messages 包含第2轮工具结果（output_dag 的 error）
    """
    print(f"\n{'*'*60}")
    print(f"  场景 S3：消息历史追加验证（tool results 回传）")
    print(f"{'*'*60}")

    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()

    message_lengths: list[int] = []

    class MessageTrackingProvider(TracingProvider):
        def complete(self, messages, system, model, max_tokens, tools):
            message_lengths.append(len(messages))
            return super().complete(messages, system, model, max_tokens, tools)

    turns = [
        [ToolCall(id="t1", name="write_dag", input={"content": _valid_dag()})],
        [ToolCall(id="t2", name="output_dag", input={})],
    ]
    provider = MessageTrackingProvider(turns, "S3")
    harness = _make_harness(tmp_path, provider)
    harness.run("source text")

    print(f"\n  每轮收到的 messages 长度: {message_lengths}")
    print("  说明：output_dag 成功后 _terminate=True → 立即 break，不再调用 complete()")
    print("  验证点：")
    all_pass = True
    # output_dag 成功时立即 break，不会再调用 complete()，所以恰好 2 次
    all_pass &= _check(len(message_lengths) == 2,
                        "provider.complete() 被调用恰好2次（_terminate=True后直接break）")
    if len(message_lengths) >= 2:
        all_pass &= _check(
            message_lengths[1] > message_lengths[0],
            f"turn2 的 messages({message_lengths[1]}) > turn1({message_lengths[0]}) — 工具结果已追加"
        )
        all_pass &= _check(
            message_lengths[0] == 1,
            "turn1 初始只有1条消息（用户的源文档消息）"
        )
        all_pass &= _check(
            message_lengths[1] == 3,
            "turn2 有3条消息（初始 + assistant工具调用 + 工具结果回传）"
        )

    print(f"\n  S3 结果: {'全部通过' if all_pass else '存在失败'}")
    return all_pass


# ---------------------------------------------------------------------------
# 场景 S4：output_dag 连续失败不终止循环
# ---------------------------------------------------------------------------

def scenario_s4(tmp_path: Path):
    """
    S4: output_dag 第1次失败（有环），第2次失败（悬空边），第3次成功
    验证：循环不因 output_dag 失败而终止，每次失败后继续

    turn1: write_dag(有环)
    turn2: output_dag → error:cycle
    turn3: write_dag(悬空边)
    turn4: output_dag → error:dangling
    turn5: write_dag(有效)
    turn6: output_dag → success
    """
    print(f"\n{'*'*60}")
    print(f"  场景 S4：output_dag 连续失败不终止循环")
    print(f"{'*'*60}")

    state_dir = tmp_path / "_import-state"
    state_dir.mkdir()

    dangling_md = textwrap.dedent("""\
        # 排查树：悬空边

        > source: hardware.md
        > generated: 2026-06-24
        > 说明：test

        ---

        ## 文档摘要

        test

        ---

        ## 排查树概览

        test

        ---

        ## 节点详情

        ### N1 — root
        complexity: simple
        node_type: action

        - go → **N99**
    """)

    turns = [
        [ToolCall(id="t1", name="write_dag", input={"content": _invalid_dag_cycle()})],
        [ToolCall(id="t2", name="output_dag", input={})],
        [ToolCall(id="t3", name="write_dag", input={"content": dangling_md})],
        [ToolCall(id="t4", name="output_dag", input={})],
        [ToolCall(id="t5", name="write_dag", input={"content": _valid_dag()})],
        [ToolCall(id="t6", name="output_dag", input={})],
    ]
    provider = TracingProvider(turns, "S4")
    harness = _make_harness(tmp_path, provider)
    report = harness.run("source text")

    _print_report(report, "S4 连续失败→最终成功")

    print("\n  验证点：")
    all_pass = True
    all_pass &= _check(not report.errors, "没有 errors（第3次 output_dag 成功）")
    dag_json = state_dir / "abc12345678901ab.dag.json"
    all_pass &= _check(dag_json.exists(), ".dag.json 存在（最终成功时写入）")
    if dag_json.exists():
        data = json.loads(dag_json.read_text())
        all_pass &= _check(len(data["nodes"]) == 3, ".dag.json 是最终有效的3节点版本")

    print(f"\n  S4 结果: {'全部通过' if all_pass else '存在失败'}")
    return all_pass


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    import tempfile

    results = {}

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s1"
        p.mkdir(parents=True)
        results["S1"] = scenario_s1(p)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s2"
        p.mkdir(parents=True)
        results["S2"] = scenario_s2(p)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s3"
        p.mkdir(parents=True)
        results["S3"] = scenario_s3(p)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s4"
        p.mkdir(parents=True)
        results["S4"] = scenario_s4(p)

    print(f"\n{'='*60}")
    print("  汇总结果")
    print(f"{'='*60}")
    all_pass = True
    for s, passed in results.items():
        icon = "✓" if passed else "✗"
        print(f"  {icon} {s}: {'PASS' if passed else 'FAIL'}")
        all_pass = all_pass and passed

    print(f"\n  总体: {'全部通过 ✓' if all_pass else '存在失败 ✗'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
