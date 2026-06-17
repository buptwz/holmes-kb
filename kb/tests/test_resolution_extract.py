"""Tests for Bug-1 fix: _extract_resolution_section() and _extract_section()
must not truncate at H3 sub-sections (### ...) inside a Resolution block.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_runner():
    """Return an ImportAgentRunner instance without initialising LLM provider."""
    from holmes.kb.agent.runner import ImportAgentRunner
    from holmes.config import HolmesConfig

    cfg = MagicMock(spec=HolmesConfig)
    cfg.model = "gpt-4o"
    cfg.api_key = "test"
    cfg.api_base_url = "https://api.openai.com/v1"
    cfg.provider = "openai"

    runner = object.__new__(ImportAgentRunner)
    runner.kb_root = None  # not used in extract methods
    runner.cfg = cfg
    runner.no_interactive = True
    runner.verbose = False
    runner.dry_run = True
    runner.force_type = None
    runner.force = False
    runner._provider = MagicMock()
    runner._current_report = None
    runner._pending_trace = None
    runner._created_entry_contents = {}
    runner._updated_entry_ids = set()
    runner._skill_evaluated_entries = set()
    runner._skill_executor = None
    return runner


MULTI_STAGE_ENTRY = """\
---
id: PT-NW-001
type: pitfall
title: E810 TX Hang 排查
maturity: draft
category: network
tags: [e810, firmware]
created_at: 2026-06-17T00:00:00+00:00
updated_at: 2026-06-17T00:00:00+00:00
---

## Symptoms

间歇性 TX Hang，驱动报错。

## Root Cause

固件版本过低。

## Resolution

总览：分五个阶段逐步排查。

### 阶段一：确认型号

运行以下命令确认型号：

```bash
lspci | grep E810
```

### 阶段二：读取固件版本

```bash
ethtool -i eth0 | grep firmware
```

### 阶段三：升级固件

下载最新固件包并执行升级：

```bash
./nvmupdate64e -u -l -o update.xml -b -c nvmupdate.cfg
```

### 阶段四：调整驱动参数

```bash
ethtool -C eth0 rx-usecs 50
```

### 阶段五：验证修复

观察 TX Hang 是否消失，确认网卡正常运行。
"""


class TestExtractResolutionSection:
    """_extract_resolution_section() must return complete multi-stage content."""

    def test_single_stage_extracted(self):
        """Baseline: single-stage Resolution returns correct content."""
        runner = _make_runner()
        content = """\
---
id: PT-DB-001
type: pitfall
title: Redis OOM
maturity: draft
category: database
tags: []
created_at: 2026-06-17T00:00:00+00:00
updated_at: 2026-06-17T00:00:00+00:00
---

## Symptoms

OOM killer.

## Root Cause

Memory limit too low.

## Resolution

Restart the service with higher memory limit.
"""
        result = runner._extract_resolution_section(content)
        assert "Restart the service" in result

    def test_multi_stage_not_truncated(self):
        """Bug-1: All 5 stages must be present in extracted Resolution."""
        runner = _make_runner()
        result = runner._extract_resolution_section(MULTI_STAGE_ENTRY)

        assert "阶段一" in result, "Stage 1 missing"
        assert "阶段二" in result, "Stage 2 missing"
        assert "阶段三" in result, "Stage 3 missing"
        assert "阶段四" in result, "Stage 4 missing"
        assert "阶段五" in result, "Stage 5 missing"

    def test_multi_stage_truncation_was_bug(self):
        """Confirm the old regex \n## would have matched \n### (regression guard)."""
        import re
        old_pattern = r"## Resolution\s*\n(.*?)(?=\n##|\Z)"
        new_pattern = r"## Resolution\s*\n(.*?)(?=\n## |\Z)"

        # Old regex stops at first ### heading
        old_match = re.search(old_pattern, MULTI_STAGE_ENTRY, re.DOTALL)
        assert old_match is not None
        old_result = old_match.group(1)
        assert "阶段二" not in old_result, "Old regex should have truncated at 阶段二"

        # New regex includes all sub-sections
        new_match = re.search(new_pattern, MULTI_STAGE_ENTRY, re.DOTALL)
        assert new_match is not None
        new_result = new_match.group(1)
        assert "阶段五" in new_result, "New regex must include all stages"

    def test_last_section_no_following_h2(self):
        """Resolution as the last section (no following ## heading) works correctly."""
        runner = _make_runner()
        content = """\
---
id: PT-DB-001
type: pitfall
title: Redis OOM
maturity: draft
category: database
tags: []
created_at: 2026-06-17T00:00:00+00:00
updated_at: 2026-06-17T00:00:00+00:00
---

## Symptoms

OOM killer.

## Resolution

### Step 1

Do something.

### Step 2

Do something else.
"""
        result = runner._extract_resolution_section(content)
        assert "Step 1" in result
        assert "Step 2" in result

    def test_chinese_resolution_header(self):
        """Chinese 解决方案 header also extracts sub-sections correctly."""
        runner = _make_runner()
        content = """\
---
id: PT-DB-001
type: pitfall
title: Redis OOM
maturity: draft
category: database
tags: []
created_at: 2026-06-17T00:00:00+00:00
updated_at: 2026-06-17T00:00:00+00:00
---

## 症状

OOM.

## 解决方案

### 步骤一

重启服务。

### 步骤二

调整内存配置。
"""
        result = runner._extract_resolution_section(content)
        assert "步骤一" in result
        assert "步骤二" in result


class TestExtractSection:
    """_extract_section() must also not truncate at H3 sub-sections."""

    def test_section_with_subsections(self):
        """Generic extractor preserves H3 sub-sections."""
        runner = _make_runner()
        content = """\
## Root Cause

### Sub-cause A

Memory pressure.

### Sub-cause B

CPU throttling.

## Resolution

Fix it.
"""
        from holmes.kb.agent.runner import ImportAgentRunner
        result = runner._extract_section(content, ("## Root Cause",))
        assert "Sub-cause A" in result
        assert "Sub-cause B" in result
        assert "Fix it" not in result  # Should stop before ## Resolution
