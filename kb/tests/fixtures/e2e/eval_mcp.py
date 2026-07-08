#!/usr/bin/env python3
"""Evaluate MCP tool usability with real generated KB entries.

Simulates an AI agent's actual workflow:
  1. kb_browse() — see full index, judge relevance from title+brief
  2. kb_browse(query=...) — search by engineer's problem description
  3. kb_read(id) — summary layer, check if symptoms/context match
  4. kb_read(id, full=true) — full content, follow resolution steps

For each step, checks that the returned data is useful for an agent.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# Setup — copy generated outputs into a temp KB structure
FIXTURE_DIR = Path(__file__).parent
KB_ROOT = FIXTURE_DIR / "_eval_kb"


def setup_kb():
    """Set up a temporary KB from generated output files."""
    if KB_ROOT.exists():
        shutil.rmtree(KB_ROOT)

    output_files = sorted(FIXTURE_DIR.glob("output_*.md"))
    if not output_files:
        print("ERROR: No output_*.md files found. Run run_e2e.py first.")
        sys.exit(1)

    import frontmatter as _fm

    for f in output_files:
        content = f.read_text(encoding="utf-8")
        try:
            post = _fm.loads(content)
        except Exception as e:
            print(f"SKIP {f.name}: YAML error: {e}")
            continue

        kb_type = post.metadata.get("type", "pitfall")
        category = post.metadata.get("category", "uncategorized")
        entry_id = post.metadata.get("id", f.stem)

        # Place in _pending/ for store.list_entries to find
        dest_dir = KB_ROOT / "_pending" / kb_type / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / f"{entry_id}.md"
        dest_file.write_text(content, encoding="utf-8")

    print(f"KB setup: {len(list(KB_ROOT.rglob('*.md')))} entries in {KB_ROOT}")
    return KB_ROOT


def teardown_kb():
    if KB_ROOT.exists():
        shutil.rmtree(KB_ROOT)


# ---------------------------------------------------------------------------
# Evaluation functions
# ---------------------------------------------------------------------------

from holmes.mcp.tools import handle_kb_browse, handle_kb_read


def eval_browse_index(kb_root: Path) -> list[str]:
    """Test 1: Full index browse — can agent see all entries with useful briefs?"""
    issues = []
    result = handle_kb_browse(kb_root)

    entries = result.get("entries", [])
    total = result.get("total", 0)

    print(f"\n{'='*70}")
    print("  TEST 1: kb_browse() — 目录浏览")
    print(f"{'='*70}")
    print(f"  共 {total} 条目, page {result.get('page')}/{result.get('total_pages')}")

    if total == 0:
        issues.append("kb_browse 返回 0 条目")
        return issues

    # Check directory overview
    directory = result.get("directory", {})
    if directory:
        print(f"  目录总览: by_type={directory.get('by_type')}, by_category={directory.get('by_category')}")
    else:
        issues.append("缺少 directory 目录总览")

    for e in entries:
        eid = e.get("id", "?")
        etype = e.get("type", "?")
        title = e.get("title", "")
        brief = e.get("brief", "")

        print(f"\n  [{etype}] {title}")
        print(f"    id: {eid}")
        print(f"    brief: {brief[:120]}")

        if not brief:
            issues.append(f"{eid}: brief 为空 — agent 无法判断相关性")
        elif len(brief) < 20:
            issues.append(f"{eid}: brief 太短 ({len(brief)} chars) — 信息量不足")
        if not title:
            issues.append(f"{eid}: title 为空")

    # Check lean format (no tags/category/maturity in browse entries)
    sample = entries[0] if entries else {}
    extra_keys = set(sample.keys()) - {"id", "type", "title", "brief"}
    if extra_keys:
        issues.append(f"browse entry 有多余字段 {extra_keys} — 浪费 tokens")

    if "guide" in result:
        print(f"\n  guide: ✅")
    else:
        issues.append("缺少 guide 使用指引")

    return issues


def eval_browse_by_type(kb_root: Path) -> list[str]:
    """Test 2: Type-filtered browse — can agent browse by type like a directory?"""
    issues = []

    print(f"\n{'='*70}")
    print("  TEST 2: kb_browse(type=...) — 按类型浏览")
    print(f"{'='*70}")

    expected_types = {
        "pitfall": {"min_count": 1, "description": "故障排查条目"},
        "model": {"min_count": 1, "description": "概念模型条目"},
        "process": {"min_count": 1, "description": "操作流程条目"},
        "decision": {"min_count": 1, "description": "决策记录条目"},
    }

    for etype, expect in expected_types.items():
        result = handle_kb_browse(kb_root, type=etype)
        entries = result.get("entries", [])

        print(f"\n  kb_browse(type='{etype}') → {len(entries)} 条")
        for e in entries:
            print(f"    [{e['type']}] {e['title']}")
            print(f"      brief: {e.get('brief','')[:80]}")

        if len(entries) < expect["min_count"]:
            issues.append(f"type={etype}: 只有 {len(entries)} 条，期望至少 {expect['min_count']}")

        # All entries should match the type filter
        wrong_type = [e for e in entries if e["type"] != etype]
        if wrong_type:
            issues.append(f"type={etype}: 返回了 {len(wrong_type)} 条非 {etype} 条目")

    # Test pagination info
    result = handle_kb_browse(kb_root)
    if "page" not in result or "total_pages" not in result:
        issues.append("browse 结果缺少分页信息 (page/total_pages)")
    else:
        print(f"\n  分页: page={result['page']}, total_pages={result['total_pages']}, total={result['total']}")

    return issues


def eval_read_summary(kb_root: Path) -> list[str]:
    """Test 3: kb_read summary — does the summary give agent enough to judge?"""
    issues = []

    all_entries = handle_kb_browse(kb_root).get("entries", [])

    print(f"\n{'='*70}")
    print("  TEST 3: kb_read(id) — 摘要层")
    print(f"{'='*70}")

    for entry in all_entries:
        eid = entry["id"]
        etype = entry["type"]

        summary = handle_kb_read(kb_root, eid, full=False)

        print(f"\n  [{etype}] {eid}")

        if "error" in summary:
            issues.append(f"{eid}: kb_read 失败: {summary['error']}")
            continue

        # Type-specific checks
        if etype == "pitfall":
            symptoms = summary.get("symptoms", [])
            root_cause = summary.get("root_cause", "")
            resolution = summary.get("resolution_overview", "")

            print(f"    symptoms: {len(symptoms)} 条")
            for s in symptoms[:3]:
                print(f"      - {s[:80]}")
            print(f"    root_cause: {root_cause[:120]}")
            print(f"    resolution: {resolution}")

            if not symptoms:
                issues.append(f"{eid}: pitfall 的 summary 没有 symptoms — agent 无法匹配工程师描述")
            if not root_cause:
                issues.append(f"{eid}: pitfall 的 summary 没有 root_cause — agent 无法判断是否匹配")
            if not resolution:
                issues.append(f"{eid}: pitfall 的 summary 没有 resolution_overview — agent 不知道有几条路径")

        elif etype == "model":
            overview = summary.get("overview", "")
            concepts = summary.get("key_concepts", [])

            print(f"    overview: {overview[:120]}")
            print(f"    key_concepts: {concepts}")

            if not overview:
                issues.append(f"{eid}: model 的 summary 没有 overview")

        elif etype == "process":
            purpose = summary.get("purpose", "")
            steps = summary.get("steps_count", 0)

            print(f"    purpose: {purpose[:120]}")
            print(f"    steps_count: {steps}")

            if not purpose:
                issues.append(f"{eid}: process 的 summary 没有 purpose")
            if steps == 0:
                issues.append(f"{eid}: process 的 summary steps_count=0 — agent 不知道有多少步")

        elif etype == "guideline":
            context = summary.get("context", "")
            guideline = summary.get("guideline", "")

            print(f"    context: {context[:120]}")
            print(f"    guideline: {guideline[:120]}")

            if not context:
                issues.append(f"{eid}: guideline 的 summary 没有 context")

        elif etype == "decision":
            context = summary.get("context", "")
            decision = summary.get("decision", "")

            print(f"    context: {context[:120]}")
            print(f"    decision: {decision[:120]}")

            if not context:
                issues.append(f"{eid}: decision 的 summary 没有 context")
            if not decision:
                issues.append(f"{eid}: decision 的 summary 没有 decision")

        # Check next hint
        next_hint = summary.get("next", "")
        if "kb_read" not in next_hint:
            issues.append(f"{eid}: summary 缺少 next 导航提示")

    return issues


def eval_read_full(kb_root: Path) -> list[str]:
    """Test 4: kb_read full — does the full content have actionable steps?"""
    issues = []

    all_entries = handle_kb_browse(kb_root).get("entries", [])

    print(f"\n{'='*70}")
    print("  TEST 4: kb_read(id, full=true) — 完整内容层")
    print(f"{'='*70}")

    for entry in all_entries:
        eid = entry["id"]
        etype = entry["type"]

        full = handle_kb_read(kb_root, eid, full=True)

        if "error" in full:
            issues.append(f"{eid}: kb_read full 失败: {full['error']}")
            continue

        content = full.get("content", "")

        # Check content structure
        sections = [l.strip() for l in content.splitlines() if l.strip().startswith("## ")]
        has_commands = "```" in content
        has_behavior_tags = any(
            tag in content for tag in ["[api]", "[physical]", "[decide]", "[remote]"]
        )

        # Count numbered steps (1. or ### Step N or #### N.)
        import re
        numbered = len(re.findall(r"^\d+\.", content, re.MULTILINE))
        subsection_steps = len(re.findall(r"^###\s+Step\s+\d+", content, re.MULTILINE | re.IGNORECASE))
        h4_steps = len(re.findall(r"^####\s+\d+\.", content, re.MULTILINE))
        step_count = max(numbered, subsection_steps, h4_steps)

        # Check for branch navigation table (pitfall multi-branch)
        has_branch_table = "| " in content and "路径" in content or "Path" in content

        print(f"\n  [{etype}] {eid}")
        print(f"    sections: {sections}")
        print(f"    commands: {'✅' if has_commands else '❌'}")
        print(f"    behavior_tags: {'✅' if has_behavior_tags else '⚠️ 无'}")
        print(f"    steps: {step_count}")
        print(f"    branch_table: {'✅' if has_branch_table else 'N/A'}")
        print(f"    content_length: {len(content)} chars")

        # Type-specific full content checks
        if etype == "pitfall":
            if not has_commands:
                issues.append(f"{eid}: pitfall 完整内容没有代码块 — agent 无法给工程师提供命令")
            if not has_behavior_tags:
                issues.append(f"{eid}: pitfall 完整内容没有行为标签 — agent 不知道哪些步骤需要物理操作")
            if step_count == 0:
                issues.append(f"{eid}: pitfall Resolution 没有编号步骤 — agent 无法逐步引导")

        elif etype == "process":
            if not has_commands:
                issues.append(f"{eid}: process 完整内容没有代码块")
            if step_count < 3:
                issues.append(f"{eid}: process 只有 {step_count} 步 — 内容可能不完整")

        elif etype == "model":
            if not has_commands:
                # model doesn't always need commands, but diagnostic commands are useful
                print(f"    ⚠️  model 没有诊断命令")

        # Check kb_confirm hint
        next_hint = full.get("next", "")
        if "kb_confirm" not in next_hint:
            issues.append(f"{eid}: full 内容缺少 kb_confirm 导航提示")

    return issues


def eval_agent_scenario(kb_root: Path) -> list[str]:
    """Test 5: End-to-end agent scenario — simulate a real troubleshooting session."""
    issues = []

    print(f"\n{'='*70}")
    print("  TEST 5: 端到端场景模拟 — 工程师报告 ECC 内存错误")
    print(f"{'='*70}")

    # Engineer reports: "服务器跑了两天后自动重启了，BMC 日志有 memory ECC error"
    engineer_problem = "服务器运行两天后自动重启 BMC memory ECC error"

    # Step 1: Agent browses KB directory
    print(f"\n  Step 1: Agent 浏览 KB 目录 kb_browse()")
    browse_result = handle_kb_browse(kb_root)
    entries = browse_result.get("entries", [])
    session_id = browse_result.get("session_id", "test")

    if not entries:
        issues.append("场景测试: 浏览返回 0 条目")
        return issues

    print(f"  → 看到 {len(entries)} 条目:")
    for e in entries:
        print(f"    [{e['type']}] {e['title']} — {e.get('brief', '')[:60]}")

    # Agent scans briefs and picks the most relevant one for ECC memory error
    ecc_entry = None
    for e in entries:
        brief_lower = (e.get("brief", "") + e.get("title", "")).lower()
        if "ecc" in brief_lower or "memory error" in brief_lower:
            ecc_entry = e
            break

    if not ecc_entry:
        issues.append("场景测试: agent 在目录中找不到 ECC 相关条目")
        return issues

    top = ecc_entry
    print(f"\n  → Agent 从目录中选择: [{top['type']}] {top['title']}")

    # Step 2: Agent reads summary
    print(f"\n  Step 2: Agent 读取摘要 kb_read('{top['id']}')")
    summary = handle_kb_read(kb_root, top["id"], full=False, session_id=session_id)
    symptoms = summary.get("symptoms", [])
    root_cause = summary.get("root_cause", "")

    print(f"  → symptoms ({len(symptoms)}):")
    for s in symptoms:
        print(f"      - {s[:80]}")
    print(f"  → root_cause: {root_cause[:150]}")

    # Agent judges: do symptoms match?
    symptom_text = " ".join(symptoms).lower()
    matched_symptoms = []
    for keyword in ["重启", "reboot", "ecc", "memory", "48", "72"]:
        if keyword in symptom_text:
            matched_symptoms.append(keyword)

    print(f"  → 症状匹配关键词: {matched_symptoms}")
    if len(matched_symptoms) < 2:
        issues.append(f"场景测试: 症状匹配不足 ({matched_symptoms})，agent 可能判断不相关")

    # Step 3: Agent reads full content
    print(f"\n  Step 3: Agent 读取完整内容 kb_read('{top['id']}', full=true)")
    full = handle_kb_read(kb_root, top["id"], full=True, session_id=session_id)
    content = full.get("content", "")

    # Check agent can find actionable steps
    import re
    steps = re.findall(r"^\d+\.\s+\[(\w+)\]\s+(.+?)$", content, re.MULTILINE)
    print(f"  → 找到 {len(steps)} 个带行为标签的步骤:")
    for tag, desc in steps[:5]:
        print(f"      [{tag}] {desc[:60]}")

    commands = re.findall(r"```bash\n(.+?)```", content, re.DOTALL)
    print(f"  → 找到 {len(commands)} 个代码块")

    if not steps:
        issues.append("场景测试: 完整内容没有带行为标签的步骤 — agent 无法逐步引导")
    if not commands:
        issues.append("场景测试: 完整内容没有代码块 — agent 无法给工程师提供命令")

    # Check if agent knows what to do at decision points
    decide_steps = [s for s in steps if s[0] == "decide"]
    print(f"  → 决策点: {len(decide_steps)} 个")
    for tag, desc in decide_steps:
        print(f"      [{tag}] {desc[:80]}")

    if not decide_steps:
        print(f"  ⚠️  没有 [decide] 步骤 — agent 可能无法处理分支逻辑")

    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    kb_root = setup_kb()

    all_issues: list[str] = []

    try:
        all_issues.extend(eval_browse_index(kb_root))
        all_issues.extend(eval_browse_by_type(kb_root))
        all_issues.extend(eval_read_summary(kb_root))
        all_issues.extend(eval_read_full(kb_root))
        all_issues.extend(eval_agent_scenario(kb_root))
    finally:
        teardown_kb()

    # Summary
    print(f"\n{'='*70}")
    print("  MCP 可用性评估总结")
    print(f"{'='*70}")

    if all_issues:
        print(f"\n  发现 {len(all_issues)} 个问题:\n")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
    else:
        print("\n  ✅ 所有测试通过，无问题")

    print()
    return 1 if all_issues else 0


if __name__ == "__main__":
    sys.exit(main())
