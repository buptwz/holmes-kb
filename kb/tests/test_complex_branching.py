"""Tests for complex branching support: decision_map, Diagnostic Flow, branch-level kb_read."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from holmes.kb.schema import DecisionMapEntry, parse_decision_map, serialize_decision_map
from holmes.kb.store import EntryMeta
from holmes.kb.agent.normalizer import DraftNormalizer
from holmes.kb.agent.phases.classifier import ClassificationResult
from holmes.kb.agent.outline import (
    extract_document_outline,
    format_outline_for_prompt,
    check_outline_coverage,
)
from holmes.mcp.tools import (
    handle_kb_read,
    _extract_branch_section,
    _extract_full_section,
    _list_branch_labels,
    _extract_navigation_table,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

COMPLEX_PITFALL_BODY = """\
## Symptoms

- 服务器按下电源按钮无反应
- BMC 不可达或可达但 Host 不起来
- 风扇转但无 POST 输出

## Root Cause

服务器不开机可能涉及电源、内存、CPU、BMC 四个子系统。

## Diagnostic Flow

```
服务器不开机
├─ 电源 LED 不亮? ─→ [A] 电源子系统
│   ├─ PSU 更换后恢复 ─→ ✓ PSU 故障
│   └─ PSU 正常 ─→ 转 [B]
├─ 风扇转无 POST? ─→ [B] 内存/CPU
│   ├─ POST code 0xA2 ─→ [B1] 内存排查
│   └─ POST code 0xB4 ─→ [B2] CPU 排查
└─ BMC 可达 Host 不起? ─→ [C] BMC 固件
```

## Resolution

| 你看到的现象 | 对应分支 |
|---|---|
| 电源 LED 不亮 | [A] 电源子系统 |
| 风扇转无 POST | [B] 内存/CPU |
| BMC 可达 Host 不起 | [C] BMC 固件 |

### [A] 电源子系统

1. [physical] 检查电源线连接和 PSU LED 状态
2. [api] 查看 BMC 电源状态
   ```bash
   ipmitool chassis power status
   ```
3. [decide] PSU 正常 → 转分支 [B]

### [B] 内存/CPU

1. [api] 检查 POST code
   ```bash
   ipmitool raw 0x30 0x70 0x0c 0x03 0x01
   ```
2. [decide] POST code 0xA2 → 转分支 [B1]

### [B1] 内存排查

1. [api] 检查内存错误日志
   ```bash
   ipmitool sel list | grep Memory
   ```
2. [decide] 单条 DIMM 报错 → 更换 DIMM

### [B2] CPU 排查

1. [api] 检查 CPU 状态
   ```bash
   ipmitool sdr type "Processor"
   ```
2. [decide] CPU 故障 → 上报 RMA

### [C] BMC 固件

1. [api] 检查 BMC 版本
   ```bash
   ipmitool mc info
   ```
2. [decide] 版本过低 → 升级固件
"""

COMPLEX_FRONTMATTER = {
    "id": "PT-BOOT-001",
    "type": "pitfall",
    "title": "服务器不开机综合排查",
    "category": "boot",
    "maturity": "draft",
    "tags": ["boot", "power", "memory", "bmc"],
    "created_at": "2026-07-09T00:00:00+00:00",
    "updated_at": "2026-07-09T00:00:00+00:00",
    "brief": "服务器不开机，可能涉及电源、内存、CPU、BMC 四个子系统",
    "language": "zh",
    "decision_map": [
        {"symptom": "电源 LED 不亮", "branch": "[A] 电源子系统"},
        {"symptom": "风扇转无 POST", "branch": "[B] 内存/CPU"},
        {"symptom": "BMC 可达 Host 不起", "branch": "[C] BMC 固件"},
    ],
}


def _make_complex_entry(kb_root: Path) -> Path:
    """Create a complex pitfall entry with Diagnostic Flow and decision_map."""
    post = frontmatter.Post(COMPLEX_PITFALL_BODY, **COMPLEX_FRONTMATTER)
    entry_dir = kb_root / "pitfall" / "boot"
    entry_dir.mkdir(parents=True, exist_ok=True)
    path = entry_dir / "PT-BOOT-001.md"
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return path


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestDecisionMap:
    def test_parse_valid(self):
        raw = [
            {"symptom": "电源 LED 不亮", "branch": "电源子系统"},
            {"symptom": "风扇转无 POST", "branch": "内存/CPU"},
        ]
        entries = parse_decision_map(raw)
        assert len(entries) == 2
        assert entries[0].symptom == "电源 LED 不亮"
        assert entries[0].branch == "电源子系统"

    def test_parse_none(self):
        assert parse_decision_map(None) == []

    def test_parse_empty(self):
        assert parse_decision_map([]) == []

    def test_parse_skips_invalid(self):
        raw = [
            {"symptom": "", "branch": "A"},  # empty symptom
            {"symptom": "B", "branch": ""},  # empty branch
            "not a dict",
            {"symptom": "valid", "branch": "valid"},
        ]
        entries = parse_decision_map(raw)
        assert len(entries) == 1
        assert entries[0].symptom == "valid"

    def test_serialize_roundtrip(self):
        entries = [
            DecisionMapEntry(symptom="LED off", branch="Power"),
            DecisionMapEntry(symptom="No POST", branch="Memory"),
        ]
        serialized = serialize_decision_map(entries)
        parsed = parse_decision_map(serialized)
        assert len(parsed) == 2
        assert parsed[0].symptom == "LED off"
        assert parsed[1].branch == "Memory"


# ---------------------------------------------------------------------------
# Branch extraction tests
# ---------------------------------------------------------------------------


class TestBranchExtraction:
    def test_list_branch_labels(self):
        labels = _list_branch_labels(COMPLEX_PITFALL_BODY)
        assert len(labels) == 5
        assert "[A] 电源子系统" in labels
        assert "[B] 内存/CPU" in labels
        assert "[C] BMC 固件" in labels

    def test_extract_branch_section_exact(self):
        content = _extract_branch_section(COMPLEX_PITFALL_BODY, "[A] 电源子系统")
        assert content is not None
        assert "ipmitool chassis power status" in content
        assert "[physical]" in content

    def test_extract_branch_section_fuzzy(self):
        content = _extract_branch_section(COMPLEX_PITFALL_BODY, "电源子系统")
        assert content is not None
        assert "ipmitool chassis power status" in content

    def test_extract_branch_not_found(self):
        content = _extract_branch_section(COMPLEX_PITFALL_BODY, "不存在的分支")
        assert content is None

    def test_extract_full_section(self):
        symptoms = _extract_full_section(COMPLEX_PITFALL_BODY, "## Symptoms")
        assert "服务器按下电源按钮无反应" in symptoms
        assert "Root Cause" not in symptoms  # should not bleed into next section

    def test_extract_diagnostic_flow(self):
        flow = _extract_full_section(COMPLEX_PITFALL_BODY, "## Diagnostic Flow")
        assert "服务器不开机" in flow
        assert "电源子系统" in flow
        assert "BMC 固件" in flow

    def test_extract_navigation_table(self):
        table = _extract_navigation_table(COMPLEX_PITFALL_BODY)
        assert "电源 LED 不亮" in table
        assert "BMC 可达" in table


# ---------------------------------------------------------------------------
# MCP kb_read tests — progressive disclosure levels
# ---------------------------------------------------------------------------


class TestKbReadProgressiveDisclosure:
    def test_summary_includes_decision_map(self, kb_root: Path):
        _make_complex_entry(kb_root)
        result = handle_kb_read(kb_root, "PT-BOOT-001")
        assert result["id"] == "PT-BOOT-001"
        assert "decision_map" in result
        assert len(result["decision_map"]) == 3
        assert "branch=" in result["next"]

    def test_navigate_returns_contents(self, kb_root: Path):
        _make_complex_entry(kb_root)
        result = handle_kb_read(kb_root, "PT-BOOT-001", detail="navigate")
        assert "contents" in result
        assert "服务器不开机" in result["contents"]
        assert "branches" in result
        assert len(result["branches"]) == 5

    def test_branch_returns_specific_section(self, kb_root: Path):
        _make_complex_entry(kb_root)
        result = handle_kb_read(kb_root, "PT-BOOT-001", branch="[A] 电源子系统")
        assert "content" in result
        assert "ipmitool chassis power status" in result["content"]
        # Should include context (Symptoms + Root Cause)
        assert "context" in result
        assert "服务器按下电源按钮无反应" in result["context"]

    def test_branch_not_found(self, kb_root: Path):
        _make_complex_entry(kb_root)
        result = handle_kb_read(kb_root, "PT-BOOT-001", branch="不存在")
        assert "error" in result
        assert "available_branches" in result

    def test_full_returns_complete_body(self, kb_root: Path):
        _make_complex_entry(kb_root)
        result = handle_kb_read(kb_root, "PT-BOOT-001", detail="full")
        assert "content" in result
        assert "## Diagnostic Flow" in result["content"]
        assert "## Resolution" in result["content"]

    def test_detail_full_same_as_full_flag(self, kb_root: Path):
        _make_complex_entry(kb_root)
        r1 = handle_kb_read(kb_root, "PT-BOOT-001", full=True)
        r2 = handle_kb_read(kb_root, "PT-BOOT-001", detail="full")
        assert r1["content"] == r2["content"]

    def test_summary_without_decision_map_shows_branches(self, kb_root: Path):
        """Entry with ≥3 branches but no decision_map still shows branch navigation."""
        post = frontmatter.Post(COMPLEX_PITFALL_BODY, **{
            **COMPLEX_FRONTMATTER,
            "decision_map": None,  # no decision_map
        })
        entry_dir = kb_root / "pitfall" / "boot"
        entry_dir.mkdir(parents=True, exist_ok=True)
        path = entry_dir / "PT-BOOT-001.md"
        path.write_text(frontmatter.dumps(post), encoding="utf-8")

        result = handle_kb_read(kb_root, "PT-BOOT-001")
        assert "branches" in result
        assert len(result["branches"]) >= 3
        assert "branch=" in result["next"]


# ---------------------------------------------------------------------------
# Normalizer tests — decision_map validation
# ---------------------------------------------------------------------------


class TestNormalizerDecisionMap:
    def test_valid_decision_map_kept(self):
        post = frontmatter.Post(COMPLEX_PITFALL_BODY, **COMPLEX_FRONTMATTER)
        draft = frontmatter.dumps(post)
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="pitfall")
        parsed = frontmatter.loads(result)
        dm = parsed.metadata.get("decision_map", [])
        assert len(dm) == 3

    def test_invalid_branch_removed(self):
        meta = {
            **COMPLEX_FRONTMATTER,
            "decision_map": [
                {"symptom": "test", "branch": "[A] 电源子系统"},
                {"symptom": "bad", "branch": "不存在的分支"},
            ],
        }
        post = frontmatter.Post(COMPLEX_PITFALL_BODY, **meta)
        draft = frontmatter.dumps(post)
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="pitfall")
        parsed = frontmatter.loads(result)
        dm = parsed.metadata.get("decision_map", [])
        assert len(dm) == 1
        assert dm[0]["branch"] == "[A] 电源子系统"
        assert any("不存在的分支" in w for w in warnings)


# ---------------------------------------------------------------------------
# Classifier tests — branch_count
# ---------------------------------------------------------------------------


class TestClassifierBranchCount:
    def test_has_complex_branching_threshold(self):
        result = ClassificationResult(
            doc_type=None,  # type: ignore
            reason="test",
            branch_count=3,
            has_complex_branching=True,
        )
        assert result.has_complex_branching is True
        assert result.branch_count == 3

    def test_simple_document(self):
        result = ClassificationResult(
            doc_type=None,  # type: ignore
            reason="test",
            branch_count=1,
            has_complex_branching=False,
        )
        assert result.has_complex_branching is False


# ---------------------------------------------------------------------------
# EntryMeta decision_map field
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Agent workflow simulation — end-to-end progressive disclosure
# ---------------------------------------------------------------------------


class TestAgentWorkflowSimulation:
    """Simulate how an AI Agent would use progressive disclosure to troubleshoot.

    This validates that the kb_read API provides enough information at each step
    for an Agent to navigate a complex multi-branch entry without reading the
    full document.
    """

    def test_full_troubleshooting_workflow(self, kb_root: Path):
        """Simulate: user reports '风扇转但无POST' → Agent navigates to [B] → [B1]."""
        _make_complex_entry(kb_root)

        # Step 1: Agent reads summary — sees decision_map
        summary = handle_kb_read(kb_root, "PT-BOOT-001")
        assert summary["id"] == "PT-BOOT-001"
        dm = summary["decision_map"]
        assert len(dm) == 3

        # Agent matches user symptom to decision_map entry
        matched = [e for e in dm if "风扇" in e["symptom"] or "POST" in e["symptom"]]
        assert len(matched) == 1
        target_branch = matched[0]["branch"]
        assert "内存" in target_branch or "CPU" in target_branch

        # Step 2: Agent reads the navigate level to see the Contents
        nav = handle_kb_read(kb_root, "PT-BOOT-001", detail="navigate")
        assert "contents" in nav
        assert "内存/CPU" in nav["contents"]
        assert len(nav["branches"]) == 5

        # Step 3: Agent reads the matched branch
        branch_result = handle_kb_read(kb_root, "PT-BOOT-001", branch=target_branch)
        assert "content" in branch_result
        assert "POST code" in branch_result["content"]
        # Has shared context (Symptoms + Root Cause)
        assert "context" in branch_result
        assert "服务器按下电源按钮无反应" in branch_result["context"]

        # Step 4: Branch [B] has a [decide] point → POST code 0xA2 → go to [B1]
        assert "[B1]" in branch_result["content"] or "B1" in branch_result["content"]
        sub_branch = handle_kb_read(kb_root, "PT-BOOT-001", branch="[B1] 内存排查")
        assert "content" in sub_branch
        assert "DIMM" in sub_branch["content"] or "Memory" in sub_branch["content"]

        # Step 5: Agent has actionable resolution — verify 'next' suggests confirm
        assert "kb_confirm" in sub_branch.get("next", "")

    def test_workflow_with_power_symptom(self, kb_root: Path):
        """Simulate: user reports '电源 LED 不亮' → Agent navigates to [A]."""
        _make_complex_entry(kb_root)

        summary = handle_kb_read(kb_root, "PT-BOOT-001")
        dm = summary["decision_map"]
        matched = [e for e in dm if "LED" in e["symptom"] or "电源" in e["symptom"]]
        assert len(matched) == 1

        branch_result = handle_kb_read(kb_root, "PT-BOOT-001", branch=matched[0]["branch"])
        assert "content" in branch_result
        assert "ipmitool chassis power status" in branch_result["content"]

    def test_workflow_branch_not_in_decision_map(self, kb_root: Path):
        """Agent can still discover branches via navigate even without decision_map match."""
        _make_complex_entry(kb_root)

        nav = handle_kb_read(kb_root, "PT-BOOT-001", detail="navigate")
        # [B2] CPU 排查 is a branch but not in decision_map
        branches = nav["branches"]
        b2_branches = [b for b in branches if "B2" in b or "CPU" in b]
        assert len(b2_branches) >= 1

        result = handle_kb_read(kb_root, "PT-BOOT-001", branch=b2_branches[0])
        assert "content" in result
        assert "CPU" in result["content"] or "Processor" in result["content"]

    def test_token_efficiency(self, kb_root: Path):
        """Branch-level read should be much shorter than full document."""
        _make_complex_entry(kb_root)

        full = handle_kb_read(kb_root, "PT-BOOT-001", detail="full")
        branch = handle_kb_read(kb_root, "PT-BOOT-001", branch="[A] 电源子系统")

        full_chars = len(full["content"])
        branch_chars = len(branch["content"]) + len(branch.get("context", ""))
        # Branch should be significantly shorter than full
        assert branch_chars < full_chars * 0.6, (
            f"Branch ({branch_chars}) should be <60% of full ({full_chars})"
        )


# ---------------------------------------------------------------------------
# Document outline extraction + coverage check tests
# ---------------------------------------------------------------------------

MULTI_SECTION_DOC = """\
# PCIe Link Training 失败排查

## 背景

NPI 验证阶段故障。

## 症状

- lspci 无法识别
- dmesg 报错

## 排查过程

### 路径 A：物理连接问题

检查金手指、Riser card。

### 路径 B：信号完整性问题

BIOS 降速、眼图测试。

### 路径 C：电气兼容性问题

AER 错误、固件升级。

## 根因总结

物理连接 60%，信号完整性 25%，电气兼容性 15%。
"""


class TestDocumentOutline:
    def test_extract_headings(self):
        outline = extract_document_outline(MULTI_SECTION_DOC)
        texts = [h["text"] for h in outline]
        assert "PCIe Link Training 失败排查" in texts
        assert "背景" in texts
        assert "路径 A：物理连接问题" in texts
        assert "路径 B：信号完整性问题" in texts
        assert "路径 C：电气兼容性问题" in texts

    def test_heading_levels(self):
        outline = extract_document_outline(MULTI_SECTION_DOC)
        level_map = {h["text"]: h["level"] for h in outline}
        assert level_map["背景"] == 2
        assert level_map["路径 A：物理连接问题"] == 3

    def test_heading_offsets_ordered(self):
        outline = extract_document_outline(MULTI_SECTION_DOC)
        offsets = [h["offset"] for h in outline]
        assert offsets == sorted(offsets)

    def test_empty_document(self):
        assert extract_document_outline("") == []
        assert extract_document_outline("no headings here") == []

    def test_format_outline_for_prompt(self):
        outline = extract_document_outline(MULTI_SECTION_DOC)
        formatted = format_outline_for_prompt(outline, len(MULTI_SECTION_DOC))
        assert "Document outline" in formatted
        assert "路径 A" in formatted
        assert "路径 C" in formatted
        assert "Ensure ALL sections" in formatted

    def test_format_empty_outline(self):
        assert format_outline_for_prompt([], 100) == ""

    def test_section_lengths_computed(self):
        outline = extract_document_outline(MULTI_SECTION_DOC)
        for h in outline:
            assert "length" in h
            assert h["length"] > 0
        # Last section extends to end of doc
        total_length = sum(h["length"] for h in outline)
        # Total of all sections ≤ doc length (first section may not start at 0)
        assert total_length <= len(MULTI_SECTION_DOC)

    def test_large_section_warning_in_prompt(self):
        """Sections ≥ 3000 chars get a LARGE warning."""
        large_doc = "## Short\n\nbrief\n\n## Big\n\n" + "x" * 4000 + "\n\n## End\n\ndone"
        outline = extract_document_outline(large_doc)
        formatted = format_outline_for_prompt(outline, len(large_doc))
        assert "LARGE" in formatted
        assert "multiple read_document_range" in formatted


class TestOutlineCoverage:
    def test_full_coverage(self):
        """When all ### sections are mentioned in summary, coverage is complete."""
        summary = {
            "brief": "PCIe link training 失败排查",
            "key_facts": [
                "物理连接不良占比60%",
                "信号完整性margin不足",
                "电气兼容性问题需固件升级",
            ],
            "commands": [],
            "symptoms": [],
            "resolution_branches": [
                {"when": "lspci看不到", "label": "路径A物理连接"},
                {"when": "link降级", "label": "路径B信号完整性"},
                {"when": "AER错误", "label": "路径C电气兼容性"},
            ],
        }
        outline = extract_document_outline(MULTI_SECTION_DOC)
        uncovered = check_outline_coverage(outline, summary)
        assert len(uncovered) == 0

    def test_partial_coverage(self):
        """When a ### section is missing from summary, it's flagged."""
        summary = {
            "brief": "PCIe 排查",
            "key_facts": ["物理连接不良", "信号完整性margin不足"],
            "commands": [],
            "symptoms": [],
            "resolution_branches": [
                {"when": "lspci看不到", "label": "路径A物理连接"},
                {"when": "link降级", "label": "路径B信号完整性"},
                # Missing: 路径 C — "电气兼容性" not in any summary field
            ],
        }
        outline = extract_document_outline(MULTI_SECTION_DOC)
        uncovered = check_outline_coverage(outline, summary)
        assert any("路径 C" in s for s in uncovered)

    def test_no_outline_returns_empty(self):
        assert check_outline_coverage([], {"key_facts": []}) == []


class TestDagStructureCheck:
    """Test that _check_structure validates DAG artifacts when has_complex_branching=True."""

    def test_dag_check_passes_with_contents_and_map(self):
        from holmes.kb.agent.pipeline import ImportPipeline
        draft = """\
---
type: pitfall
title: test
decision_map:
  - symptom: "A"
    branch: "B"
---

## Contents

```
A → B
```

## Symptoms

test

## Root Cause

test

## Resolution

test
"""
        errors = ImportPipeline._check_structure(draft, "pitfall", has_complex_branching=True)
        assert len(errors) == 0

    def test_dag_check_fails_missing_contents(self):
        from holmes.kb.agent.pipeline import ImportPipeline
        draft = """\
---
type: pitfall
title: test
decision_map:
  - symptom: "A"
    branch: "B"
---

## Symptoms

test

## Root Cause

test

## Resolution

test
"""
        errors = ImportPipeline._check_structure(draft, "pitfall", has_complex_branching=True)
        assert any("Contents" in e for e in errors)

    def test_dag_check_fails_missing_decision_map(self):
        from holmes.kb.agent.pipeline import ImportPipeline
        draft = """\
---
type: pitfall
title: test
---

## Contents

```
A → B
```

## Symptoms

test

## Root Cause

test

## Resolution

test
"""
        errors = ImportPipeline._check_structure(draft, "pitfall", has_complex_branching=True)
        assert any("decision_map" in e for e in errors)

    def test_simple_pitfall_needs_contents(self):
        from holmes.kb.agent.pipeline import ImportPipeline
        draft = """\
---
type: pitfall
title: test
---

## Symptoms

test

## Root Cause

test

## Resolution

test
"""
        errors = ImportPipeline._check_structure(draft, "pitfall", has_complex_branching=False)
        assert any("Contents" in e for e in errors)
        assert not any("decision_map" in e for e in errors)

    def test_simple_pitfall_passes_with_contents(self):
        from holmes.kb.agent.pipeline import ImportPipeline
        draft = """\
---
type: pitfall
title: test
---

## Contents

| Section | Description |
|---|---|
| Symptoms | test |
| Root Cause | test |
| Resolution | test |

## Symptoms

test

## Root Cause

test

## Resolution

test
"""
        errors = ImportPipeline._check_structure(draft, "pitfall", has_complex_branching=False)
        assert len(errors) == 0


class TestContentsBodyCrossValidation:
    """Contents table/tree must match actual body headings exactly."""

    def test_contents_lists_section_not_in_body(self):
        """Contents says 'Workaround' but body has no ## Workaround."""
        from holmes.kb.agent.pipeline import ImportPipeline
        draft = """\
---
type: pitfall
title: test
---

## Contents

| Section | Description |
|---|---|
| Symptoms | test |
| Root Cause | test |
| Resolution | test |
| Workaround | extra section |

## Symptoms

test

## Root Cause

test

## Resolution

test
"""
        errors = ImportPipeline._check_structure(draft, "pitfall", has_complex_branching=False)
        assert any("workaround" in e.lower() and "no matching" in e.lower() for e in errors)

    def test_body_has_section_not_in_contents(self):
        """Body has ## Notes but Contents doesn't list it."""
        from holmes.kb.agent.pipeline import ImportPipeline
        draft = """\
---
type: pitfall
title: test
---

## Contents

| Section | Description |
|---|---|
| Symptoms | test |
| Root Cause | test |
| Resolution | test |

## Symptoms

test

## Root Cause

test

## Resolution

test

## Notes

extra body section
"""
        errors = ImportPipeline._check_structure(draft, "pitfall", has_complex_branching=False)
        assert any("notes" in e.lower() and "not listed in contents" in e.lower() for e in errors)

    def test_bidirectional_match_passes(self):
        """Perfect match between Contents table and body headings."""
        from holmes.kb.agent.pipeline import ImportPipeline
        draft = """\
---
type: model
title: test
---

## Contents

| Section | Description |
|---|---|
| Overview | 3 core concepts |
| Key Concepts | definitions |
| Usage | 5 examples |

## Overview

test

## Key Concepts

test

## Usage

test
"""
        errors = ImportPipeline._check_structure(draft, "model", has_complex_branching=False)
        assert len(errors) == 0

    def test_dag_tree_labels_match_branches(self):
        """Decision tree [A], [B] must match ### Branch headings."""
        from holmes.kb.agent.pipeline import ImportPipeline
        draft = """\
---
type: pitfall
title: test
decision_map:
  - symptom: "X"
    branch: "A"
  - symptom: "Y"
    branch: "B"
---

## Contents

```
问题根节点
├─ 条件1 ─→ [A] 物理问题
└─ 条件2 ─→ [B] 信号问题
```

## Symptoms

test

## Root Cause

test

## Resolution

### 物理问题

fix A

### 信号问题

fix B
"""
        errors = ImportPipeline._check_structure(draft, "pitfall", has_complex_branching=True)
        assert len(errors) == 0

    def test_dag_tree_label_also_passes_with_branch_prefix(self):
        """Old-style ### Branch A: ... format should also pass."""
        from holmes.kb.agent.pipeline import ImportPipeline
        draft = """\
---
type: pitfall
title: test
decision_map:
  - symptom: "X"
    branch: "A"
  - symptom: "Y"
    branch: "B"
---

## Contents

```
问题根节点
├─ 条件1 ─→ [A] 物理问题
└─ 条件2 ─→ [B] 信号问题
```

## Symptoms

test

## Root Cause

test

## Resolution

### Branch A: 物理问题

fix A

### Branch B: 信号问题

fix B
"""
        errors = ImportPipeline._check_structure(draft, "pitfall", has_complex_branching=True)
        assert len(errors) == 0

    def test_dag_tree_label_missing_branch(self):
        """Contents tree has [C] 电气问题 but body only has 物理问题 and 信号问题."""
        from holmes.kb.agent.pipeline import ImportPipeline
        draft = """\
---
type: pitfall
title: test
decision_map:
  - symptom: "X"
    branch: "A"
---

## Contents

```
问题根节点
├─ 条件1 ─→ [A] 物理问题
├─ 条件2 ─→ [B] 信号问题
└─ 条件3 ─→ [C] 电气问题
```

## Symptoms

test

## Root Cause

test

## Resolution

### 物理问题

fix A

### 信号问题

fix B
"""
        errors = ImportPipeline._check_structure(draft, "pitfall", has_complex_branching=True)
        assert any("电气问题" in e and "no matching" in e.lower() for e in errors)

    def test_dag_body_branch_not_in_tree(self):
        """Body has ### 未知问题 but Contents tree only shows [A] 物理问题."""
        from holmes.kb.agent.pipeline import ImportPipeline
        draft = """\
---
type: pitfall
title: test
decision_map:
  - symptom: "X"
    branch: "A"
---

## Contents

```
问题根节点
└─ 条件1 ─→ [A] 物理问题
```

## Symptoms

test

## Root Cause

test

## Resolution

### 物理问题

fix A

### 未知问题

fix C
"""
        errors = ImportPipeline._check_structure(draft, "pitfall", has_complex_branching=True)
        assert any("未知问题" in e and "not represented in contents" in e.lower() for e in errors)


class TestEntryMetaDecisionMap:
    def test_default_empty(self):
        meta = EntryMeta(
            id="test", type="pitfall", title="test", maturity="draft",
            category="test", tags=[], created_at="", updated_at="",
            file_path="",
        )
        assert meta.decision_map == []

    def test_populated(self):
        dm = [{"symptom": "A", "branch": "B"}]
        meta = EntryMeta(
            id="test", type="pitfall", title="test", maturity="draft",
            category="test", tags=[], created_at="", updated_at="",
            file_path="", decision_map=dm,
        )
        assert len(meta.decision_map) == 1
