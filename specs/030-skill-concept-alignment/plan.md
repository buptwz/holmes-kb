# Implementation Plan: Skill Concept Alignment (Anthropic Agent Skills)

**Branch**: `030-skill-concept-alignment` | **Date**: 2026-06-12 | **Spec**: [spec.md](spec.md)

## Summary

将 Holmes KB 的 skill 概念从"bash 脚本执行包"（run.sh）替换为 Anthropic Agent Skills 标准（SKILL.md 作为 agent 指令包）。触发条件不变（命令计数 ≥3 → RECOMMENDED），skill 内容改由 LLM 按 skill-creator 方法论生成结构化 agent 指令。涉及 skill 核心模块、import pipeline、CLI、测试、文档全链路改造。

---

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `python-frontmatter`, `click`, LLM provider（Anthropic / OpenAI-compatible）

**Storage**: 文件系统（`skills/<name>/SKILL.md`，无数据库）

**Testing**: pytest；现有测试套件在 `kb/tests/`

**Target Platform**: Linux/macOS CLI + Python library

**Project Type**: CLI tool + Python library

**Performance Goals**: skill 生成调用 LLM 一次，不影响 import 主流程延迟（失败降级为 SKIP）

**Constraints**: LLM 生成的 `SKILL.md` body 不超过 500 行；`description` ≤ 1024 字符

**Scale/Scope**: 与现有 import pipeline 相同规模；无新外部依赖

---

## Constitution Check

Constitution 为空模板，无项目级硬性约束。遵循以下现有惯例：
- 所有文件写入走 `atomic_write()`（现有约定）
- LLM 调用复用 `self._provider.simple_complete()`（不引入新 provider 接口）
- 测试先于实现（删除旧测试 → 新增新测试 → 实现）
- 无违规项，可直接进入 Phase 0

---

## Project Structure

### Documentation (this feature)

```text
specs/030-skill-concept-alignment/
├── plan.md              # 本文件
├── research.md          # Phase 0 输出
├── data-model.md        # Phase 1 输出
├── contracts/           # Phase 1 输出
└── tasks.md             # /speckit-tasks 输出
```

### Source Code (affected files)

```text
kb/
├── holmes/kb/skill/
│   ├── template.py          # 重写
│   ├── manager.py           # 重构
│   ├── runner.py            # 删除
│   └── usage.py             # 不动
├── holmes/kb/agent/
│   ├── skill_advisor.py     # 更新触发逻辑
│   ├── tools.py             # 更新 create_skill_for_entry
│   └── runner.py            # 更新 _run_skill_and_curation, 新增 _generate_skill_instructions
├── holmes/cli.py            # 移除写入/执行类 skill 命令
└── tests/
    ├── conftest.py           # 移除 run.sh helpers
    ├── test_skill_manager.py # 更新
    ├── test_skill_data_model.py # 更新
    ├── test_skill_edge.py   # 更新
    ├── test_skill_cli.py    # 更新
    └── test_skill_runner.py # 删除

docs/
├── reference.md             # 更新 skill 章节
└── kb-management.md         # 更新 skill 描述
```

---

## Phase 0: Research

见 [research.md](research.md)

---

## Phase 1: Design & Contracts

见 [data-model.md](data-model.md) 和 [contracts/](contracts/)
