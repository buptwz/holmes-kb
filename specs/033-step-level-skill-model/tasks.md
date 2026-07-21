# Tasks: 步骤级 Skill 模型 (Feature 033)

**Input**: Design documents from `specs/033-step-level-skill-model/`

**Organization**: 按 User Story 分组，每个 Story 可独立实现和测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无未完成依赖）
- **[Story]**: 对应 spec.md 中的 User Story

---

## Phase 1: Setup（理解现有代码）

**Purpose**: 在动手前理解当前实现，避免破坏 harness 稳定性

- [x] T001 阅读 `kb/holmes/kb/agent/runner.py`，重点记录 `_extract_resolution_section()`（L536）、`_extract_section()`（L565）、`_run_skill_and_curation()`、`_finalize_skill_generation()` 的当前行为和调用路径
- [x] T002 [P] 阅读 `kb/holmes/mcp/tools.py`，记录 `_compute_linked_entries()`（L342）、`_read_entry()`（L222）、`handle_kb_read()` 的当前签名和行为
- [x] T003 [P] 阅读 `kb/holmes/kb/store.py`，确认 `read_entry()` 的 `include_pending` 参数用法，以及 `list_entries(include_pending=True)` 扫描 `contributions/pending/` 的行为
- [x] T004 [P] 阅读 `kb/holmes/kb/agent/skill_advisor.py`，记录 `SkillAdvisor.advise()` 的输入/输出接口和 `SkillAdvice` dataclass 字段
- [x] T005 [P] 阅读 `kb/holmes/kb/schema.py`，确认 `skill_name_re` 正则（用于 FR-1 标记验证）

---

## Phase 2: Foundational（基线验证）

**Purpose**: 确认现有测试全部通过，建立改动前基线

**⚠️ CRITICAL**: 所有 US 实现前必须完成本阶段

- [x] T006 运行现有测试确认基线通过：`cd kb && pytest tests/ -q --tb=short`，记录测试总数
- [x] T007 [P] 阅读 `kb/tests/` 目录结构，找到与 skill 生成相关的测试文件（`test_skill_*.py`、`test_runner.py`、`test_pipeline.py`），记录现有 skill 相关测试覆盖范围

**Checkpoint**: 基线测试数确认，可开始各 US 实现

---

## Phase 3: User Story 1 — SKILL.md 内容完整性（Bug-1 + FR-4）(Priority: P1) 🎯 MVP

**Goal**: 无论 Resolution 包含多少 `###` 子章节，SKILL.md 包含完整内容，不截断

**Independent Test**: 构造含 5 个 `### 阶段X` 子章节的 KB 条目，调用 `_extract_resolution_section()` 验证返回完整内容；比较修复前后的行数差异

### 实现

- [x] T008 [US1] 修改 `kb/holmes/kb/agent/runner.py` 中 `_extract_resolution_section()`（L558）：将正则 `(?=\n##|\Z)` 改为 `(?=\n## |\Z)`（加空格，只在 H2 处停止，允许 H3 子章节包含在内）
- [x] T009 [US1] 修改 `kb/holmes/kb/agent/runner.py` 中 `_extract_section()`（L568）：同步应用相同正则修复 `(?=\n## |\Z)`
- [x] T010 [US1] 在 `kb/tests/test_runner.py`（或新建 `kb/tests/test_resolution_extract.py`）新增测试：验证含 `### 阶段一`~`### 阶段五` 子章节的 Resolution 被完整提取，不在第一个 `###` 处截断

**Checkpoint**: `_extract_resolution_section()` 返回完整 5 阶段内容

---

## Phase 4: User Story 3 — Pending 条目可见性（Bug-3）(Priority: P1)

**Goal**: 导入文档后立即可通过 `kb_read(skill_name)` 看到 pending 条目；可通过 `kb_read(pending_id)` 读取 pending 内容

**Independent Test**: 在 `contributions/pending/` 放一个含 `skill_refs: [test-skill]` 的测试条目文件，调用 `_compute_linked_entries(kb_root, "test-skill")`，验证返回含该 pending ID；调用 `handle_kb_read(kb_root, "pending-xxx")` 验证返回内容而非错误

### Bug-3A：linked_entries 含 pending 条目

- [x] T011 [US3] 修改 `kb/holmes/mcp/tools.py` 中 `_compute_linked_entries()`（L342）：在现有循环结束后，额外扫描 `kb_root / "contributions" / "pending"` 目录，将含目标 `skill_name` 在 `skill_refs` 中的 pending 条目 ID 追加到 `linked` 列表（标注在 hint 中，不改变 `linked_entries` 原有 `list[str]` 格式以保持向后兼容）
- [x] T012 [US3] 在 `kb/holmes/mcp/tools.py` 的 `_read_skill()` 响应中，当 `linked_entries` 含 pending ID 时，在 hint 中补充说明哪些是 pending 状态（`"Note: pending-xxx is awaiting confirmation"`）

### Bug-3B：kb_read 支持读取 pending 条目

- [x] T013 [US3] 修改 `kb/holmes/kb/store.py` 中 `read_entry()`（L33）：将 `list_entries(kb_root)` 改为 `list_entries(kb_root, include_pending=True)`，使 pending ID 可被 `read_entry()` 命中
- [x] T014 [US3] 修改 `kb/holmes/mcp/tools.py` 中 `handle_kb_read()`：在 `_is_entry_id()` 检测之前，新增 pending ID 前缀检测（`id_str.startswith("pending-")`），若匹配则路由到 `_read_entry()`（带 `pending=True` 标志）
- [x] T015 [US3] 修改 `kb/holmes/mcp/tools.py` 中 `_read_entry()`：当读取的条目为 pending 时（通过 frontmatter `pending` 字段或 ID 前缀判断），在响应中新增 `"pending": True` 字段
- [x] T016 [US3] 在 `kb/tests/test_mcp_tools.py`（或新建 `kb/tests/test_pending_visibility.py`）新增测试：验证 `_compute_linked_entries()` 扫描 pending 目录；验证 `handle_kb_read("pending-xxx")` 返回内容并含 `pending: true`

**Checkpoint**: 导入后不 confirm 也可读取 skill 的 linked_entries（含 pending）和 pending 条目内容

---

## Phase 5: User Story 2+4 — 步骤级 Skill 模型（FR-1 + FR-2 + FR-3）(Priority: P1)

**Goal**: Resolution 支持 skill 调用标记，Import Pipeline 按标记或自动拆分生成多个独立 skill

**Independent Test**: 构造含 `> skill: test-skill-a` 和 `` `[skill:test-skill-b]` `` 标记的 Resolution 文本，调用 `extract_skill_markers()`，验证返回 2 个 marker；以含标记的 KB 条目触发 SkillAdvisor，验证走形态 B 路径并生成 2 个独立 SKILL.md

### FR-1：Skill 标记解析器

- [x] T017 [P] [US2] 新建 `kb/holmes/kb/skill/markers.py`，实现 `extract_skill_markers(resolution_text: str) -> list[dict]`：
  - Blockquote 形式：多行模式匹配 `^>\s*skill:\s*([a-z0-9][a-z0-9-]*)`
  - Inline 形式：匹配 `` `\[skill:([a-z0-9][a-z0-9-]*)\]` ``
  - 每个 marker 提取 `skill_name`、`step_heading`（向上最近的 `## ` 或 `### ` 标题）、`marker_type`、`line`
  - skill_name 不符合 `schema.py` 中 `skill_name_re` 规则时跳过并记录警告
  - 同一 skill_name 多次出现时全部返回
- [x] T018 [P] [US2] 在 `kb/tests/test_skill_markers.py` 新增测试，覆盖：blockquote 标记识别、inline 标记识别、混合标记、非法 skill name 跳过、无标记返回空列表、step_heading 正确关联上级标题

### FR-3：SkillAdvisor 双模式

- [x] T019 [US2] 修改 `kb/holmes/kb/agent/skill_advisor.py` 中 `SkillAdvice` dataclass，新增两个字段：
  - `form: str = "A"` — 形态选择（`"A"` 或 `"B"`）
  - `step_skills: list = field(default_factory=list)` — 形态 B 时的步骤 skill 列表（`[{step_heading, skill_name, content}]`）
- [x] T020 [US2] 修改 `kb/holmes/kb/agent/skill_advisor.py` 中 `SkillAdvisor.advise()` 方法：在现有逻辑之前，先调用 `extract_skill_markers(resolution_text)`；若有标记则设 `form="B"`，按标记填充 `step_skills`；无标记但满足自动拆分条件（步骤 > 10 且并列路径 ≥ 3）则同样设 `form="B"` 并自动识别分支；否则保持原有形态 A 逻辑（`form="A"`）不变
- [x] T021 [US2] 实现 `_count_steps(resolution_text: str) -> int` 和 `_count_parallel_branches(resolution_text: str) -> int` 两个辅助函数（`runner.py` 或 `skill_advisor.py`），用于自动拆分条件判断

### FR-2：Pipeline 步骤级 skill 生成

- [x] T022 [US2] 修改 `kb/holmes/kb/agent/runner.py` 中 `_run_skill_and_curation()`：当 `SkillAdvice.form == "B"` 时，遍历 `step_skills`，对每个条目分别调用 `create_skill(kb_root, skill_name, description, instructions=content)`；将所有生成的 skill name 通过 `link_skill()` 写入条目 `skill_refs`；形态 A 路径（`form == "A"`）代码完全不变
- [x] T023 [US2] 修改 `kb/holmes/kb/agent/runner.py` 中 `_finalize_skill_generation()`：同步支持形态 B（当 `SkillAdvice.form == "B"` 时走形态 B 路径）
- [x] T024 [US2] 在 `kb/tests/test_skill_advisor.py` 新增测试：验证含 skill 标记的 Resolution 触发形态 B；验证超阈值（>10 步 ≥3 分支）文档触发自动拆分；验证线性文档仍走形态 A

**Checkpoint**: 含 `> skill: name` 标记的文档导入后生成多个独立 SKILL.md，每个 skill 内容对应各自步骤

---

## Phase 6: FR-5 — skill_invocations 字段（Priority: P2）

**Goal**: `kb_read(entry_id)` 响应含 `skill_invocations` 字段，明确列出每个 skill 在哪一步被调用

**Independent Test**: 读取含 skill 标记的 KB 条目，验证响应中 `skill_invocations` 正确列出步骤和 skill 名；无标记条目返回空列表 `[]`

- [x] T025 [P] [US2] 修改 `kb/holmes/mcp/tools.py` 中 `_read_entry()`：在返回响应前，提取 Resolution 章节（通过 `_extract_resolution_section()` 复用），调用 `extract_skill_markers()` 解析标记，将结果转换为 `[{step: step_heading, skill: skill_name}]` 格式写入 `skill_invocations` 字段；无标记时写入空列表 `[]`
- [x] T026 [P] [US2] 在 `kb/tests/test_mcp_tools.py` 新增测试：验证含标记的条目响应含正确 `skill_invocations`；无标记条目 `skill_invocations` 为 `[]`

---

## Phase 7: Polish & 回归验证

**Purpose**: 确保所有改动无回归，补充边界用例

- [x] T027 运行完整测试套件：`cd kb && pytest tests/ -q --tb=short`，确认不低于 T006 记录的基线测试数（只增不减）
- [x] T028 [P] 手动验证端到端链路：构造含 5 个 `###` 子章节的 Resolution，import 并检查生成的 SKILL.md 行数与原文一致
- [x] T029 [P] 手动验证 pending 可见性：import 一份文档，不 confirm，用 `kb_read(skill_name)` 检查 `linked_entries` 含 pending ID，用 `kb_read(pending_id)` 读取内容
- [x] T030 [P] 检查 `_extract_section()` 修复是否同步影响 `## Symptoms` / `## Root Cause` 提取行为（预期：无副作用，因为这两节通常无子章节）
- [x] T031 更新 `specs/033-step-level-skill-model/checklists/requirements.md`，标记所有实现项已完成

---

## Dependencies（Story 完成顺序）

```
Phase 1 (Setup)
    ↓
Phase 2 (Foundational — 基线确认)
    ↓
Phase 3 (US1: Bug-1 正则修复)    ←─── 独立，可先做
Phase 4 (US3: Bug-3 pending)      ←─── 独立，可并行
    ↓                               ↓
Phase 5 (US2+US4: FR-1/2/3)  ←── 依赖 T017（markers.py）
    ↓
Phase 6 (FR-5: skill_invocations) ← 依赖 T017（markers.py）
    ↓
Phase 7 (回归验证)
```

**可并行执行**：
- Phase 3 + Phase 4 可同时进行（改不同文件，无共同依赖）
- T017（markers.py）+ T018（markers 测试）可并行写
- T025（skill_invocations 实现）+ T026（测试）可并行

---

## Implementation Strategy

**MVP**（建议最先完成）：Phase 3（Bug-1）+ Phase 4（Bug-3）
- 改动最小，风险最低，立即解决用户导入后知识不可见的问题
- Phase 3 只改两行正则，Phase 4 只改 3-4 个函数

**第二步**：Phase 5（FR-1 + FR-2 + FR-3）
- 核心新功能，依赖 markers.py 模块
- 注意形态 A 路径代码完全不变，新增的形态 B 路径作为新分支叠加

**最后**：Phase 6（FR-5）
- P2 优先级，可独立交付，不影响其他功能

---

## Summary

| 阶段 | Task 数 | 关联 Story |
|------|---------|-----------|
| Phase 1 Setup | 5 | — |
| Phase 2 Foundational | 2 | — |
| Phase 3 US1（Bug-1）| 3 | US1 |
| Phase 4 US3（Bug-3）| 6 | US3 |
| Phase 5 US2+4（FR-1/2/3）| 8 | US2 |
| Phase 6 FR-5 | 2 | US2 |
| Phase 7 Polish | 5 | — |
| **Total** | **31** | |

**并行机会**：T002-T005（Setup 阶段）、Phase 3 + Phase 4（不同文件）、T017+T018（markers 实现+测试）、T025+T026（FR-5 实现+测试）
