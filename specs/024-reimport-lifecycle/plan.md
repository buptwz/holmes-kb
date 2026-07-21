# Implementation Plan: Import Pipeline 永远新建策略

**Branch**: `024-reimport-lifecycle` | **Date**: 2026-06-11 | **Spec**: [spec.md](spec.md)

## Summary

移除 import pipeline 中的跨文档 dedup 逻辑，改为"每次 import 只新建知识"。知识有效性由 evidence 最新时间决定，旧知识自然淘汰。同时补充单次 import 内部草稿去重，防止同文档重复 KP 产生冗余条目。

核心改动：`pipeline.py` 的 `_run_dedup_pass` 从"跨 KB 更新"改为"草稿内去重"；`runner.py` 的 system prompt 移除跨 KB 去重指令。

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: frontmatter, difflib（标准库，无新依赖）

**Storage**: 文件系统（KB Markdown 文件），无数据库

**Testing**: pytest，现有测试套件 733 tests

**Target Platform**: Linux CLI

**Project Type**: library/cli

**Performance Goals**: 单次 import 内草稿去重不引入 LLM API 调用（使用 difflib），延迟无增加

**Constraints**: 不破坏现有 create 路径；文档级 hash 预检查必须保留

**Scale/Scope**: 单次 import 草稿数量通常 1-10 个，草稿间两两比较 O(n²) 可接受

## Constitution Check

- ✅ 单一职责：pipeline 只负责创建，evidence 系统负责淘汰，职责分离
- ✅ 开闭原则：`_run_dedup_pass` 改名+重写，不影响其他 phase
- ✅ 无新外部依赖
- ✅ 覆盖边界场景（非 pitfall 类型用 title 兜底）

## Project Structure

### Documentation (this feature)

```text
specs/024-reimport-lifecycle/
├── plan.md              ← 本文件
├── spec.md
├── research.md
└── tasks.md             ← speckit-tasks 生成
```

### Source Code (affected files)

```text
kb/holmes/kb/agent/
├── pipeline.py          # _run_dedup_pass → _run_intra_import_dedup（核心改动）
└── runner.py            # _IMPORT_SYSTEM_PROMPT 清理，移除 _pending_dedup_match

kb/tests/
└── test_pipeline.py     # 新增 intra-import dedup 测试，移除跨 KB dedup 测试
```

## Phase 0: Research

已完成，见 [research.md](research.md)。关键决策：
- 草稿间相似度用 `difflib.SequenceMatcher`，无 LLM 调用
- 非 pitfall 类型用 title 相似度兜底
- runner.py system prompt 和拦截逻辑同步清理

## Phase 1: Design & Implementation

### US1 — 移除跨文档 dedup，pipeline 只新建（FR-001）

**改动：`pipeline.py`**

将 `_run_dedup_pass()` 重命名为 `_run_intra_import_dedup()` 并重写：

```
旧逻辑：
  for draft in kp_drafts:
    查询 KB 存量条目（跨文档）
    if 相似度 >= 0.8: 更新存量条目，skip create

新逻辑：
  seen: list[(kp_id, root_cause_text)]
  for draft in kp_drafts:
    提取 root_cause（pitfall）或 title（其他类型）
    for (seen_id, seen_text) in seen:
      if similarity(draft_text, seen_text) >= 0.8:
        标记当前 draft 为 duplicate，加入 report.skipped
        break
    else:
      seen.append((kp_id, draft_text))
  return set(duplicate_kp_ids)
```

调用方不变（pipeline.run() 依然调用，返回 dedup_handled set，被 skip 的草稿不走 create 路径）。

**改动：`runner.py`**

1. `_IMPORT_SYSTEM_PROMPT` 移除第3步和第5步中的 update 指令：
   - 删除："For new content, use read_kb_entries_by_category then compare_root_cause to detect semantic duplicates (merge or link)."
   - 修改第5步：`write_kb_entry` only，移除 `update_kb_entry (merge)`

2. 移除 `_pending_dedup_match` 字段及 `_dispatch_tool` 中的 `write_kb_entry` 拦截逻辑（runner 的 LLM loop 已不执行，属于死代码）

### US2 — 单次 import 内部草稿去重（FR-004）

草稿间相似度计算：

```python
import difflib

def _text_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a[:500], b[:500]).ratio()

def _draft_dedup_key(draft_body: str, draft_metadata: dict) -> str:
    """提取草稿的去重 key：pitfall 用 Root Cause，其他类型用 title。"""
    m = re.search(r"## Root Cause\s*\n(.*?)(?=\n##|\Z)", draft_body, re.DOTALL)
    if m:
        return m.group(1).strip()[:500]
    return str(draft_metadata.get("title", ""))
```

ImportReport 中新增标注：`report.skipped.append(f"{kp_id} (intra-import duplicate of {seen_id})")`

### 测试要求

- 现有跨 KB dedup 测试删除或改写（验证不再更新存量条目）
- 新增：同文档两个相同 KP 草稿 → 只 create 一个
- 新增：同文档两个不同 KP 草稿 → 两个都 create
- 新增：非 pitfall 类型（guideline）用 title 去重
- 验证：文档级 hash 预检查仍正常 skip 完全重复文档

## Agent Context Update

CLAUDE.md 中 plan 引用更新为：`specs/024-reimport-lifecycle/plan.md`
