# Feature Specification: Skill Concept Alignment (Anthropic Agent Skills)

**Feature Branch**: `030-skill-concept-alignment`

**Created**: 2026-06-12

**Status**: Draft

**Input**: 将 Holmes KB 中的 skill 概念从"bash 脚本执行包"（run.sh）替换为 Anthropic Agent Skills 标准（SKILL.md 作为 agent 指令包），保证整个逻辑闭环、可运行、衔接正常。

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Import Pipeline 自动生成高质量 Agent Skill (Priority: P1)

运维工程师运行 `holmes import` 处理一份故障报告。Pipeline 检测 Resolution 中的命令步骤数（≥3 → RECOMMENDED），触发后调用 LLM 按照 skill-creator 方法论提炼 entry 内容，生成结构化 agent 指令（When to Use / Resolution Steps / Key Points），写入 `SKILL.md`。frontmatter 只含 `name` 和 `description`，无 `run.sh`、无 `scripts/` 目录。

**Why this priority**: 这是 skill 进入 KB 的唯一自动路径，生成质量直接决定后续 agent 能否正确使用 skill。

**Independent Test**: 对含 ≥3 个命令的 `## Resolution` 文档运行 `holmes import`，检查生成的 `SKILL.md`。

**Acceptance Scenarios**:

1. **Given** Resolution 含 ≥3 个命令的源文档，**When** `holmes import` 完成，**Then** 自动创建 `skills/<slug>/SKILL.md`，frontmatter 仅含 `name`/`description`，body 包含 When to Use / Resolution Steps / Key Points，无 `run.sh`；`validate_skill_md()` 校验通过。
2. **Given** Resolution 含 1-2 个命令，**When** import 完成，**Then** 不创建 skill，报告中出现 OPTIONAL 建议提示。
3. **Given** 无 `## Resolution` 或零命令，**When** import 完成，**Then** 不创建 skill（SKIP）。
4. **Given** entry 已有 `skill_refs`，**When** 再次触发 skill 评估，**Then** 不重复创建（LINK）。
5. **Given** LLM 生成的 `description` 超过 1024 字符，**When** `validate_skill_md()` 校验，**Then** 报错，pipeline 截断后记录 warning。

---

### User Story 2 — SKILL.md 格式正确性保证 (Priority: P1)

任何通过代码路径创建的 skill，其 `SKILL.md` 都符合 Anthropic Agent Skills 标准，`validate_skill_md()` 校验通过。旧格式字段（`version`、`platforms`、`timeout`、`params`、`prerequisites`）不再出现在任何新建 skill 中。

**Why this priority**: 格式正确是后续所有 agent 读取、MCP 暴露、知识治理的前提。

**Acceptance Scenarios**:

1. **Given** 只含 `name`/`description` frontmatter 的 SKILL.md，**When** `validate_skill_md()`，**Then** valid=True。
2. **Given** 含旧字段（如 `version: 1.0.0`）的 SKILL.md，**When** `validate_skill_md()`，**Then** valid=False，错误说明非法 key。
3. **Given** 缺少 `name` 或 `description`，**When** 验证，**Then** valid=False，错误指明缺失字段。

---

### User Story 3 — 旧范式彻底清除 (Priority: P1)

`runner.py`（bash 脚本执行）、`auto_create_skill()`、所有写入/执行类 CLI 命令（`skill create/link/unlink/run/detect-commands/auto-create`）完全移除，代码库中无任何旧范式遗留。

**Acceptance Scenarios**:

1. **Given** 重构完成，**When** 搜索源文件中 `run.sh`、`auto_create_skill`、`SkillExecution`、`generate_run_sh_template`，**Then** 仅在已删除文件中存在，主源码零引用。
2. **Given** 调用 `holmes kb skill run`，**When** CLI 处理，**Then** 报 "No such command 'run'"。

---

### User Story 4 — CLI 与新概念对齐 (Priority: P2)

CLI skill 子命令只保留只读命令（`list`、`read`），移除所有写入/执行类命令。`kb show <id>` 展示关联 skill 的名称和 description（不再显示"可执行"标签）。

**Acceptance Scenarios**:

1. **Given** 重构完成，**When** `holmes kb skill --help`，**Then** 只显示 `list` 和 `read`。
2. **Given** `skill list --json`，**When** 返回，**Then** 每条含 `name`/`description`/`linked_entries`，不含 `version`/`platforms`。
3. **Given** `skill read <name> --json`，**When** 返回，**Then** 含 `name`/`content`，不含 `scripts_path`/`has_run_script`。
4. **Given** entry 有关联 skill，**When** `kb show <id>`，**Then** 展示 skill 名称和 description，标签为 `[skill]`（不再是 `[可执行]`）。

---

### User Story 5 — KB Template 和文档与新概念同步 (Priority: P2)

`kb-template/` 中无旧格式 skill 样本；`docs/reference.md` 和 `docs/kb-management.md` 中的 skill 相关内容与新概念一致。

**Acceptance Scenarios**:

1. **Given** `kb-template/skills/` 目录，**When** 检查，**Then** 不含任何 `run.sh` 文件。
2. **Given** `docs/reference.md`，**When** 检查 skill 相关命令，**Then** 不含 `skill run`、`detect-commands`、`--platform` 说明。

---

### Edge Cases

- 旧 KB 中已存在含 `run.sh` 的 skill：`list`/`read` 正常工作（`parse_skill_md` 读 `name`/`description` 向后兼容），`validate_skill_md()` 会标记为非法，但不强制迁移。
- `detect_commands()` 保留用于计数判断，但计数结果不再用于生成 run.sh 内容。
- LLM 生成 skill 失败（provider 错误等）：pipeline 降级为 SKIP，记录 warning，不阻断 import 主流程。
- `_generate_skill_instructions()` fallback 路径（LLM 未在 tool-use loop 调用 create_skill_for_entry）：`ImportAgentRunner` 用 `self._provider` 直接调 LLM 生成 instructions。

---

## Requirements *(mandatory)*

### Functional Requirements

**数据模型：**

- **FR-001**: `SkillDefinition` 只含 `name`、`description`、`content`；移除 `version`、`platforms`、`timeout`、`params`、`prerequisites`。
- **FR-002**: `SkillSummary` 只含 `name`、`description`、`linked_entries`；移除 `version`、`platforms`。
- **FR-003**: 新增 `validate_skill_md(path) -> (bool, str)` 函数：`name`/`description` 必填，frontmatter key 只允许 `name`、`description`、`license`、`allowed-tools`、`metadata`、`compatibility`；`name` ≤ 64 字符、kebab-case；`description` ≤ 1024 字符、无尖括号。

**SKILL.md 生成：**

- **FR-004**: `generate_skill_template(name, description, instructions="")` 生成 frontmatter 只含 `name`/`description`，body 为 instructions 内容（空时用默认占位 body）；移除 `generate_run_sh_template()`。
- **FR-005**: `create_skill(kb_root, name, description, instructions="")` 不创建 `scripts/` 目录和 `run.sh`；移除 `platforms`、`commands`、`param_names` 参数。

**Import Pipeline / Skill Advisor：**

- **FR-006**: Skill Advisor 触发条件**不变**：`detect_commands()` 计数 ≥3 → RECOMMENDED；1-2 → OPTIONAL；0 → SKIP；已有 skill_refs → LINK。
- **FR-007**: 新增 `ImportAgentRunner._generate_skill_instructions(entry_content, resolution_text) -> str`：调用 `self._provider` 按 skill-creator 方法论生成 agent 指令 markdown，包含 When to Use、Resolution Steps、Key Points 三节；`description` 写法遵循触发粘性原则（说明触发时机，不欠触发）。
- **FR-008**: `_run_skill_and_curation()` 在 RECOMMENDED 时，先调 `_generate_skill_instructions()` 获取 instructions，再调 `create_skill_for_entry`（传 `instructions`）；移除 `cmd_lines`/`param_names` 提取逻辑。
- **FR-009**: `_dispatch_tool()` 中移除 T014 block（不再强制 override `resolution_commands`）。
- **FR-010**: `_IMPORT_SYSTEM_PROMPT` 更新 step 6：告知 LLM 调用 `create_skill_for_entry` 时须提供 `instructions`（结构化 agent 指令，含三节）。
- **FR-011**: `create_skill_for_entry` tool：移除 `resolution_commands`/`param_names` 参数，加 `instructions` 参数；TOOL_DEFINITIONS 同步更新。
- **FR-012**: 移除 `auto_create_skill()`、`_inject_param_bindings()`、`_slugify()`、`_generate_skill_md()`。
- **FR-013**: `detect_commands()` 和 `CommandCandidate` **保留**，仅用于计数。

**CLI：**

- **FR-014**: 移除 `skill create`、`skill link`、`skill unlink`、`skill run`、`skill detect-commands`、`skill auto-create` 命令。
- **FR-015**: 保留 `skill list`、`skill read` 命令；`list --json` 输出不含 `version`/`platforms`；`read --json` 输出不含 `scripts_path`/`has_run_script`。
- **FR-016**: `kb show <id>` 中 skill 展示改为显示名称和 description，标签由 `[可执行]` 改为 `[skill]`。

**移除：**

- **FR-017**: 删除 `kb/holmes/kb/skill/runner.py`。
- **FR-018**: 删除 `kb/tests/test_skill_runner.py`。
- **FR-019**: `conftest.py` 移除 `make_skill_with_script`、`run_sh_echo`、`run_sh_env`、`skill_with_prereqs`、`skill_with_required_param`。

**测试：**

- **FR-020**: 移除所有测试中对 `run.sh`、`auto_create_skill`、`run_skill`、`SkillExecution`、`--platform`、`skill run/detect-commands/auto-create` CLI 的引用。
- **FR-021**: 新增测试：`create_skill` 不生成 `run.sh`；`validate_skill_md()` 通过/失败；skill advisor 按命令计数触发；`_generate_skill_instructions()` 返回含三节结构的 markdown；`create_skill_for_entry` 使用 `instructions` 参数。

**KB Template 与文档：**

- **FR-022**: `kb-template/skills/` 清理旧格式 skill 样本（如有）。
- **FR-023**: `docs/reference.md` 更新 skill 相关章节，移除 `skill run`/`detect-commands`/`--platform` 说明。
- **FR-024**: `docs/kb-management.md` 更新 skill 相关描述，反映新概念。

### Key Entities

- **Skill**：Anthropic Agent Skills 包，`skills/<name>/SKILL.md`，frontmatter 仅 `name`+`description`，body 为 agent 指令 markdown（When to Use / Resolution Steps / Key Points）。可选子目录 `scripts/`/`references/`/`assets/` 由 agent 按需使用，不自动生成。
- **SkillDefinition**：`name`、`description`、`content`。
- **SkillAdvice**：RECOMMENDED/LINK/OPTIONAL/SKIP + 建议 slug。

---

## Success Criteria *(mandatory)*

- **SC-001**: `holmes import` 对含 ≥3 命令 Resolution 的文档运行后，生成的 `SKILL.md` 通过 `validate_skill_md()` 校验（零错误）。
- **SC-002**: 生成的 `SKILL.md` body 包含 When to Use、Resolution Steps、Key Points 三节，内容来自 LLM 对 entry 的提炼。
- **SC-003**: 所有保留的测试用例通过，无回归。
- **SC-004**: 源码中零引用 `run.sh`、`auto_create_skill`、`SkillExecution`、`generate_run_sh_template`（已删除文件除外）。
- **SC-005**: `holmes kb skill --help` 仅显示 `list` 和 `read`。
- **SC-006**: `kb-template/` 中无 `run.sh` 文件；`docs/reference.md` 中无 `skill run`/`detect-commands`/`--platform` 条目。

---

## Assumptions

- 旧格式 skill（含 `run.sh`）不做自动迁移；`parse_skill_md()` 向后兼容读取 `name`/`description`。
- MCP 暴露 skill 内容（agent 通过 MCP 读取 SKILL.md）留待后续 feature，本次不实现；`skill_refs` 字段保留在 entry frontmatter 中。
- `skill/usage.py` 保持现有接口不变。
- `SkillCurator`（`curator.py`）逻辑不变，仅基于 description 查重，无 `run.sh` 依赖。
- LLM 生成 skill instructions 失败时，pipeline 降级为 SKIP，不阻断主流程。
- `_generate_skill_instructions()` 的 prompt 设计遵循 skill-creator 方法论：description 说明触发时机，body 结构化呈现解决步骤，不过度冗长（SKILL.md body 控制在合理范围内）。
