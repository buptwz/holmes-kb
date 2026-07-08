#!/usr/bin/env python3
"""Evaluate MCP from a real agent's perspective.

For each KB type, simulate an agent's actual decision chain:
  Layer 0: browse/search → title + brief + tags (enough to pick which entry?)
  Layer 1: kb_read summary → structured fields (enough to confirm match?)
  Layer 2: kb_read full → complete content (can agent guide step-by-step?)

Scores each layer's information sufficiency.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent
KB_ROOT = FIXTURE_DIR / "_eval_kb"


def setup_kb():
    if KB_ROOT.exists():
        shutil.rmtree(KB_ROOT)
    import frontmatter as _fm
    for f in sorted(FIXTURE_DIR.glob("output_*.md")):
        content = f.read_text(encoding="utf-8")
        try:
            post = _fm.loads(content)
        except Exception:
            continue
        kb_type = post.metadata.get("type", "pitfall")
        category = post.metadata.get("category", "uncategorized")
        entry_id = post.metadata.get("id", f.stem)
        dest_dir = KB_ROOT / "_pending" / kb_type / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / f"{entry_id}.md").write_text(content, encoding="utf-8")
    return KB_ROOT


def teardown_kb():
    if KB_ROOT.exists():
        shutil.rmtree(KB_ROOT)


from holmes.mcp.tools import handle_kb_browse, handle_kb_read


# ---------------------------------------------------------------------------
# Scenario definitions — each simulates a real engineer request
# ---------------------------------------------------------------------------

SCENARIOS = [
    {
        "name": "ECC 内存错误导致服务器重启",
        "engineer_says": "我的服务器跑了两天就自动重启了，BMC 日志里有 memory ECC error，怎么查？",
        "expect_entry": "samsung-ddr5-dimm-ecc-error-burn-in-reboot",
        "layer1_should_tell_agent": [
            "症状列表能匹配工程师描述（重启、ECC、48-72h）",
            "根因是什么（DIMM 颗粒缺陷）",
            "有几条解决路径",
        ],
        "layer2_should_tell_agent": [
            "第一步执行什么命令",
            "哪些步骤需要物理操作",
            "遇到分支点怎么判断走哪条路",
        ],
    },
    {
        "name": "PCIe 设备识别失败",
        "engineer_says": "新装的 GPU 卡 lspci 看不到，dmesg 有 link training failed",
        "expect_entry": "ai-inference-card-v2-pcie-gen5-link-training-failure",
        "layer1_should_tell_agent": [
            "症状列表能匹配（lspci 无法识别、link training failed）",
            "故障率信息（15%）",
            "有几条排查路径（物理/信号/电气）",
        ],
        "layer2_should_tell_agent": [
            "每条路径的具体排查步骤",
            "在哪个步骤需要工程师检查物理连接",
            "如何判断走哪条路径",
        ],
    },
    {
        "name": "想了解热节流机制",
        "engineer_says": "CPU 跑着跑着性能下降了，怀疑热节流，PROCHOT 是什么意思？",
        "expect_entry": "server-platform-thermal-throttling-mechanisms",
        "layer1_should_tell_agent": [
            "这是概念解释型文档（model），不是故障排查",
            "涵盖哪些关键概念（PROCHOT, THERMTRIP, RAPL, CLTT）",
            "agent 应该给工程师解释机制，而不是走排查流程",
        ],
        "layer2_should_tell_agent": [
            "PROCHOT 的定义和触发条件",
            "用什么命令检查当前状态",
            "各层级之间的关系",
        ],
    },
    {
        "name": "BMC 固件升级",
        "engineer_says": "需要给这批服务器升级 BMC 固件到 1.06 版本，有标准流程吗？",
        "expect_entry": "bmc-firmware-update-production-servers",
        "layer1_should_tell_agent": [
            "这是操作流程（process），有明确步骤数",
            "目的是什么（BMC 固件升级）",
            "agent 应该逐步引导工程师执行",
        ],
        "layer2_should_tell_agent": [
            "前置条件（网络可达、固件已验证、维护窗口）",
            "每步的具体命令",
            "风险警告（flash 期间不能断电）",
            "失败时的回滚步骤",
        ],
    },
    {
        "name": "PCIe 链路速度决策",
        "engineer_says": "我们的 Granite 平台 PCIe 应该默认跑 Gen4 还是 Gen5？",
        "expect_entry": "granite-pcie-link-speed-decision",
        "layer1_should_tell_agent": [
            "这是架构决策记录（decision），不是排查流程",
            "做了什么决定",
            "agent 应该解释决策背景和理由，不是走排查",
        ],
        "layer2_should_tell_agent": [
            "有哪些备选方案",
            "最终选了什么",
            "为什么这样选（trade-off）",
        ],
    },
]


def _print_json(data: dict, indent: int = 4):
    """Pretty-print JSON with proper CJK display."""
    print(json.dumps(data, ensure_ascii=False, indent=indent, default=str))


def eval_scenario(kb_root: Path, scenario: dict) -> list[str]:
    """Run one scenario through the full 3-layer agent flow."""
    issues: list[str] = []
    name = scenario["name"]

    print(f"\n{'='*70}")
    print(f"  场景: {name}")
    print(f"  工程师: \"{scenario['engineer_says']}\"")
    print(f"{'='*70}")

    # ===== Layer 0: Browse directory =====
    print(f"\n  --- Layer 0: kb_browse() → 浏览目录 ---")
    result = handle_kb_browse(kb_root)
    entries = result.get("entries", [])

    if not entries:
        issues.append(f"[{name}] L0: 目录为空")
        return issues

    # Print what agent actually sees
    print(f"  Agent 看到 {len(entries)} 条目:")
    for e in entries:
        print(f"    [{e['type']}] {e['title']}")
        print(f"      brief: {e['brief'][:80]}")

    # Agent scans directory and picks the expected entry by reading briefs/titles
    target = next((e for e in entries if e["id"] == scenario["expect_entry"]), None)
    if not target:
        issues.append(f"[{name}] L0: 期望 {scenario['expect_entry']} 不在目录中")
        return issues

    print(f"\n  Agent 选择: [{target['type']}] {target['title']}")
    brief = target["brief"]
    print(f"\n  L0 判断: agent 看到 brief=\"{brief}\"")
    if len(brief) < 30:
        issues.append(f"[{name}] L0: brief 太短 ({len(brief)} chars)，agent 无法判断相关性")
    print(f"  L0 brief 长度: {len(brief)} chars — {'✅ 足够' if len(brief) >= 30 else '❌ 不足'}")

    # ===== Layer 1: Summary =====
    eid = target["id"]
    print(f"\n  --- Layer 1: kb_read('{eid}') → 摘要 ---")
    summary = handle_kb_read(kb_root, eid, full=False)

    if "error" in summary:
        issues.append(f"[{name}] L1: kb_read 失败: {summary['error']}")
        return issues

    # Print full summary JSON — this is exactly what agent sees
    print("  Agent 收到的完整 summary:")
    # Remove content to keep output readable
    display = {k: v for k, v in summary.items() if k != "content"}
    _print_json(display)

    # Check if summary answers the L1 questions
    etype = target["type"]
    print(f"\n  L1 需要告诉 agent 的信息:")
    for q in scenario["layer1_should_tell_agent"]:
        print(f"    - {q}")

    # Type-specific L1 quality checks
    if etype == "pitfall":
        symptoms = summary.get("symptoms", [])
        root_cause = summary.get("root_cause", "")
        resolution = summary.get("resolution_overview", "")
        if not symptoms:
            issues.append(f"[{name}] L1: symptoms 为空 — agent 无法匹配工程师症状描述")
        if not root_cause:
            issues.append(f"[{name}] L1: root_cause 为空 — agent 无法判断根因是否匹配")
        if not resolution:
            issues.append(f"[{name}] L1: resolution_overview 为空 — agent 不知道有几条路径")
        # Can agent tell how many branches?
        if resolution and "branches" not in resolution and "steps" not in resolution:
            issues.append(f"[{name}] L1: resolution_overview 没有说明路径数量")

    elif etype == "model":
        overview = summary.get("overview", "")
        concepts = summary.get("key_concepts", [])
        if not overview:
            issues.append(f"[{name}] L1: overview 为空")
        if not concepts:
            issues.append(f"[{name}] L1: key_concepts 为空 — agent 不知道涵盖哪些概念")

    elif etype == "process":
        purpose = summary.get("purpose", "")
        steps = summary.get("steps_count", 0)
        if not purpose:
            issues.append(f"[{name}] L1: purpose 为空")
        if steps == 0:
            issues.append(f"[{name}] L1: steps_count=0 — agent 不知道流程有多长")

    elif etype == "decision":
        context = summary.get("context", "")
        decision = summary.get("decision", "")
        if not context:
            issues.append(f"[{name}] L1: context 为空")
        if not decision:
            issues.append(f"[{name}] L1: decision 为空 — agent 不知道结论是什么")

    # Check navigation hint
    next_hint = summary.get("next", "")
    if "kb_read" not in next_hint:
        issues.append(f"[{name}] L1: 缺少 next 导航提示")

    # ===== Layer 2: Full content =====
    print(f"\n  --- Layer 2: kb_read('{eid}', full=true) → 完整内容 ---")
    full = handle_kb_read(kb_root, eid, full=True)

    if "error" in full:
        issues.append(f"[{name}] L2: kb_read full 失败: {full['error']}")
        return issues

    content = full.get("content", "")

    # Print first 500 chars of content to show structure
    print(f"  内容前 500 字:")
    print(f"  {'─'*60}")
    for line in content[:500].splitlines():
        print(f"    {line}")
    if len(content) > 500:
        print(f"    ... (共 {len(content)} chars)")
    print(f"  {'─'*60}")

    # L2 quality checks
    import re
    print(f"\n  L2 需要告诉 agent 的信息:")
    for q in scenario["layer2_should_tell_agent"]:
        print(f"    - {q}")

    # Check actionability
    has_commands = "```" in content
    has_behavior_tags = any(tag in content for tag in ["[api]", "[physical]", "[decide]", "[remote]"])
    sections = [l.strip() for l in content.splitlines() if l.strip().startswith("## ")]

    print(f"\n  L2 结构分析:")
    print(f"    sections: {sections}")
    print(f"    has_commands: {has_commands}")
    print(f"    has_behavior_tags: {has_behavior_tags}")
    print(f"    content_length: {len(content)} chars")

    if etype == "pitfall":
        if not has_behavior_tags:
            issues.append(f"[{name}] L2: 缺少行为标签 — agent 不知道哪些需要物理操作")
        if not has_commands:
            issues.append(f"[{name}] L2: 缺少代码块 — agent 无法提供诊断命令")
        decide_points = re.findall(r"\[decide\]", content)
        if not decide_points:
            issues.append(f"[{name}] L2: 缺少 [decide] 分支点 — agent 无法处理条件逻辑")

    elif etype == "process":
        if not has_commands:
            issues.append(f"[{name}] L2: 流程文档缺少代码块")
        # Check for CRITICAL warnings
        if "CRITICAL" in content.upper() or "警告" in content or "注意" in content:
            print(f"    ✅ 包含风险警告")
        else:
            print(f"    ⚠️  没有风险警告")
        # Check rollback
        if "rollback" in content.lower() or "回滚" in content:
            print(f"    ✅ 包含回滚步骤")
        else:
            issues.append(f"[{name}] L2: 流程文档缺少回滚步骤")

    elif etype == "model":
        # Model should explain concepts, not necessarily have behavior tags
        if not has_commands:
            print(f"    ⚠️  model 没有诊断命令（可接受，但有命令更好）")

    elif etype == "decision":
        # Decision should have options and rationale
        if "option" not in content.lower() and "方案" not in content:
            issues.append(f"[{name}] L2: 决策文档缺少备选方案对比")

    # Check kb_confirm navigation
    next_hint = full.get("next", "")
    if "kb_confirm" not in next_hint:
        issues.append(f"[{name}] L2: 缺少 kb_confirm 导航提示")

    return issues


def main():
    kb_root = setup_kb()
    all_issues: list[str] = []

    try:
        for scenario in SCENARIOS:
            issues = eval_scenario(kb_root, scenario)
            all_issues.extend(issues)
    finally:
        teardown_kb()

    # Summary
    print(f"\n{'='*70}")
    print(f"  Agent 决策链路评估总结")
    print(f"{'='*70}")
    print(f"  测试场景: {len(SCENARIOS)}")

    if all_issues:
        print(f"\n  发现 {len(all_issues)} 个问题:\n")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
    else:
        print(f"\n  ✅ 所有场景的 3 层决策链路均通过")

    print()
    return 1 if all_issues else 0


if __name__ == "__main__":
    sys.exit(main())
