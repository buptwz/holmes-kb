# Implementation Plan: KB Skill Mounting

**Branch**: `002-kb-skill-mount` | **Date**: 2026-05-29 | **Spec**: [spec.md](spec.md)

## Summary

为 Holmes KB 添加 Skill 挂载能力：在 KB 仓库的 `skills/` 目录维护独立的可执行诊断 Skill（`SKILL.md` + `scripts/run.sh`），KB 条目通过 `skill_refs` frontmatter 字段引用。

**架构决策（2026-06-01 更新）**: Agent 侧不再封装自定义 KB 工具。Agent 通过原生文件工具（`Read`/`Glob`/`Grep`/`Bash`）直接访问 KB 文件，由 `CLAUDE.md` 描述 KB 目录结构和操作规范引导模型。原有 `KbReadOverview`、`KbSearch`、`KbReadEntry` 等 9 个自定义工具全部移除，避免与 OpenAI 兼容端点的流式响应兼容性问题。

## Technical Context

**Language/Version**: Python 3.11（holmes CLI / KB 包）+ TypeScript / Bun（holmes-agent TUI 工具）

**Primary Dependencies**:
- Python: `click`（CLI）、`python-frontmatter`（YAML frontmatter 解析）、`subprocess`（脚本执行）、`pathlib`（文件操作）
- Agent 侧：无新依赖，使用现有原生文件工具；CLAUDE.md 描述 KB 结构

**Storage**: 纯文件系统（KB = git 仓库，无数据库）。Skill 存储在 `$HOLMES_KB_PATH/skills/<name>/`

**Testing**: pytest（Python）；TypeScript 工具通过 e2e 集成测试验证

**Target Platform**: Linux / macOS CLI

**Project Type**: CLI 工具 + TUI 工具扩展

**Performance Goals**: Skill 读取 <3s；脚本执行默认超时 30s；脚本 stdout 截断 10KB

**Constraints**: 无数据库依赖；Skill 结果不持久化；向后兼容现有 KB 条目格式

## Constitution Check

| 原则 | 状态 | 说明 |
|------|------|------|
| 开闭原则 | ✅ | 新增 `skills/` 目录和可选 `skill_refs` 字段不修改现有条目解析逻辑 |
| 依赖倒置 | ✅ | Agent 通过原生文件工具（Read/Glob/Grep/Bash）访问 KB；CLAUDE.md 作为配置而非硬编码 |
| 单一职责 | ✅ | 每个 CLI 命令 / TS 工具职责单一；Skill 读取与执行分离 |
| 接口隔离 | ✅ | KbReadSkill / KbRunSkill 接口精简，不混入其他功能 |
| 环境配置 | ✅ | 使用 `HOLMES_KB_PATH` 环境变量，无硬编码路径 |
| 验证原则 | ✅ | 所有 CLI 命令和 TS 工具需有 pytest / e2e 测试覆盖 |
| 渐进式实现 | ✅ | 文件系统存储，无额外抽象层 |
| 可观测性 | ✅ | Skill 执行记录日志（命令、参数、退出码、耗时） |
| 代码规范 | ✅ | Python: Google Style；TypeScript: ESLint + Prettier |
| 安全 | ✅ | Skill 执行走用户确认；Skill 添加复用 pending/confirm + git 流程 |

## Project Structure

### Documentation (this feature)

```text
specs/002-kb-skill-mount/
├── plan.md           ← 本文件
├── research.md       ← Phase 0
├── data-model.md     ← Phase 1
├── quickstart.md     ← Phase 1
├── contracts/        ← Phase 1
│   ├── cli-commands.md
│   └── agent-tools.md
└── tasks.md          ← /speckit-tasks 生成
```

### Source Code

```text
# KB 仓库 (holmes-kb) — 运行时数据目录
$HOLMES_KB_PATH/
├── pitfall/
│   ├── database/PT-DB-001.md       ← 现有条目，frontmatter 含可选 skill_refs
│   └── network/...
├── model/...
├── guideline/...
├── skills/                          ← 新增 Skill 库目录
│   └── check-redis/
│       ├── SKILL.md
│       └── scripts/
│           └── run.sh
├── pending/                         ← 待确认的新条目
└── index.json                       ← KB 概览（条目统计）

# Python holmes CLI 包
kb/holmes/
├── cli.py                           ← 新增 skill 子命令组（create/link/unlink/list/run/read）
├── kb/
│   ├── schema.py                    ← skill_refs 作为可选字段，不破坏现有验证
│   ├── store.py                     ← 不变（skill_refs 随 frontmatter 自动读出）
│   └── skill/                       ← 新增模块
│       ├── __init__.py
│       ├── manager.py               ← create/link/unlink/list/read 操作
│       ├── runner.py                ← run.sh 执行（subprocess + timeout + stdout 截断）
│       └── template.py              ← SKILL.md 模板生成

# Agent 配置（不再有自定义 KB 工具）
~/.holmes/CLAUDE.md                  ← 描述 KB 目录结构 + 用 Read/Glob/Grep/Bash 访问规范
~/holmes-kb/CLAUDE.md               ← 同上（与 ~/.holmes/CLAUDE.md 保持一致）
# claude-code/src/tools/kb/         ← 所有自定义 KB 工具文件移除（KbReadOverview、
#                                      KbSearch、KbReadEntry 等 9 个工具全部删除）
# claude-code/src/tools.ts          ← 移除所有 KB 工具的 import 和注册
```

**Structure Decision**: Python 侧新增 `kb/skill/` 子模块，CLI 功能不变。Agent 侧移除所有自定义 KB 工具，改为通过 `CLAUDE.md` 引导模型用原生文件工具访问 KB 文件系统。

## 参考代码

实现时优先阅读以下文件，不要凭空猜测接口。

### Python — holmes CLI 现有实现

| 文件 | 参考目的 |
|------|----------|
| `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/cli.py` | Click 命令组结构、`--kb-path` context 传递、`kb` 子命令注册方式 |
| `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/store.py` | `read_entry`、`list_entries`、frontmatter 读取模式 |
| `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/schema.py` | frontmatter 字段校验逻辑，新增 `skill_refs` 可选字段的正确位置 |
| `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/pending.py` | `write_pending`、`get_pending` — 了解 pending 文件格式，skill create 直接写 `skills/` 不走 pending |

### Python — hermes-agent Skill 机制参考

| 文件 | 参考目的 |
|------|----------|
| `/home/wangzhi/project/hermes-agent/agent/skill_utils.py` | `parse_frontmatter`、`skill_matches_platform` — SKILL.md 解析的完整实现可直接借鉴 |
| `/home/wangzhi/project/hermes-agent/agent/skill_preprocessing.py` | `run_inline_shell`、`expand_inline_shell` — subprocess 执行 + timeout + 错误处理模式 |
| `/home/wangzhi/project/hermes-agent/agent/background_review.py` | `_SKILL_REVIEW_PROMPT` — agent 沉淀时识别命令的 prompt 模式参考 |
| `/home/wangzhi/project/hermes-agent/skills/apple/imessage/SKILL.md` | 完整 SKILL.md 格式范例（frontmatter + When to Use + Quick Reference） |
| `/home/wangzhi/project/hermes-agent/skills/apple/apple-reminders/SKILL.md` | 另一个 SKILL.md 范例（含 prerequisites） |

### Agent 配置 — CLAUDE.md 文件访问规范

Agent 不再有自定义 KB 工具，需通过 `CLAUDE.md` 告知模型如何用原生工具访问 KB：

| 内容 | 说明 |
|------|------|
| KB 根目录路径 | `$HOLMES_KB_PATH`（来自环境变量） |
| 条目位置规律 | `$HOLMES_KB_PATH/<type>/<category>/<ID>.md` |
| Skill 位置 | `$HOLMES_KB_PATH/skills/<name>/SKILL.md` + `scripts/run.sh` |
| 搜索方式 | `Grep` 关键词搜索全目录；`Glob` 列出某类条目 |
| 执行 Skill | `Bash: bash $HOLMES_KB_PATH/skills/<name>/scripts/run.sh`（需用户确认）|
