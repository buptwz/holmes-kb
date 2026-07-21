# Feature Specification: KB Skill Mounting

**Feature Branch**: `002-kb-skill-mount`

**Created**: 2026-05-29

**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 在 Skill 库中创建 Skill 并挂载到 KB 条目 (Priority: P1)

知识库维护者在 KB 仓库的 `skills/` 目录下创建一个完整的 Skill 文件夹（包含 SKILL.md 和可执行脚本），然后将该 Skill 挂载到相关的 KB 条目。之后所有引用该条目的 agent 都能知道存在可执行的诊断步骤，并知道去哪里读取。

**Why this priority**: 这是整个功能的基础——没有 Skill 定义和挂载机制，agent 无法感知和执行任何诊断。

**Independent Test**: 创建 `skills/check-redis/SKILL.md` 并执行 `holmes kb skill link PT-DB-001 check-redis`，验证 PT-DB-001.md 的 frontmatter 中出现 `skill_refs: [check-redis]`，且 `holmes kb show PT-DB-001` 输出中标注该 skill 可执行。

**Acceptance Scenarios**:

1. **Given** KB 仓库中尚无 `skills/` 目录，**When** 维护者运行 `holmes kb skill create check-redis --desc "检查 Redis 连接状态"`，**Then** 在 `$HOLMES_KB_PATH/skills/check-redis/` 下生成 SKILL.md 模板和空的 `scripts/` 目录。

2. **Given** `skills/check-redis/` 已存在，**When** 维护者运行 `holmes kb skill link PT-DB-001 check-redis`，**Then** PT-DB-001.md 的 YAML frontmatter 中新增 `skill_refs: [check-redis]`，原有内容不变。

3. **Given** 一个已挂载 skill 的 KB 条目，**When** 用 `holmes kb show PT-DB-001` 查看，**Then** 输出中列出关联的 skill 名称并标注路径 `skills/check-redis/`。

4. **Given** 维护者尝试挂载一个不存在的 skill 名称，**When** 运行 `holmes kb skill link`，**Then** 报错提示 skill 不存在并建议先运行 `holmes kb skill create`。

---

### User Story 2 - Agent 排查时读取并执行 Skill (Priority: P2)

排查过程中 agent 读取到含有 `skill_refs` 的 KB 条目，自动跟随引用读取 Skill 库，向用户展示可用的诊断脚本，获得确认后执行并将输出纳入排查推理。

**Why this priority**: Agent 能否执行 skill 是整个功能的核心价值。

**Independent Test**: 对含 `skill_refs: [check-redis]` 的条目运行 agent，验证 agent 读取 `skills/check-redis/SKILL.md` 后主动提议执行，并在用户确认后输出脚本执行结果。

**Acceptance Scenarios**:

1. **Given** agent 通过 `KbReadEntry` 读取到 `skill_refs: [check-redis]`，**When** agent 向用户呈现该条目，**Then** agent 自动调用 `KbReadSkill(check-redis)` 获取 SKILL.md 内容，并告知用户"此条目有可执行诊断：check-redis，是否运行？"

2. **Given** 用户确认执行 check-redis skill，**When** agent 调用 `KbRunSkill(check-redis, params)`，**Then** `scripts/` 下的入口脚本被执行，stdout/stderr/退出码返回给 agent，agent 将输出作为诊断上下文继续推理。

3. **Given** skill 执行失败（非零退出码或超时），**When** agent 收到结果，**Then** 错误输出作为诊断线索被纳入分析，agent 不中断排查流程。

4. **Given** SKILL.md 中声明了参数（如 `{host}`、`{port}`），**When** agent 执行时上下文中没有这些值，**Then** agent 先向用户询问参数值，填充后再执行。

---

### User Story 3 - Agent 沉淀经验时自动生成 Skill (Priority: P2)

排查成功后，agent 将本次排查思路总结写入 KB。在生成 Resolution 内容时，agent 识别到其中包含可直接执行的诊断命令，异步发起 skill 生成建议：为这些命令创建对应的 skill 文件夹，并将其挂载到新生成的条目上。用户确认后随条目一同进入 pending 流程。

**Why this priority**: 沉淀时上下文最完整，是 skill 库自然增长的主要来源；若没有自动识别，skill 库将长期空置。

**Independent Test**: 模拟一次包含 `redis-cli info | grep connected_clients` 的排查沉淀，验证 agent 提议生成 `skills/check-redis-connections/`，用户确认后 pending 条目的 frontmatter 包含 `skill_refs: [check-redis-connections]`。

**Acceptance Scenarios**:

1. **Given** agent 完成排查并生成 Resolution 内容，**When** Resolution 中含可执行命令，**Then** agent 在写入 pending 前展示候选 skill 列表，询问"是否为以下命令创建 Skill？"，并给出建议的 skill 名称。

2. **Given** 用户确认某 skill 候选，**When** agent 写入，**Then** `skills/<agent-suggested-name>/SKILL.md` 和入口脚本直接写入 `skills/`（不经过 pending），KB 条目（含 `skill_refs`）写入 pending 等待用户 confirm。

3. **Given** 用户拒绝 skill 提议，**When** agent 写入条目，**Then** 条目不含 `skill_refs`，命令仅作为文字描述保留，用户可事后手动通过 `holmes kb skill create` 添加。

4. **Given** agent 无法确定某步骤是否为可执行命令（如自然语言混合命令），**When** 生成条目时，**Then** agent 不强制提议该步骤，降低误报率。

---

### User Story 4 - 用户通过 CLI 管理 Skill 库 (Priority: P3)

用户可通过 `holmes kb skill` 系列命令独立管理 Skill 库：浏览所有 skill、查看某 skill 详情、单独运行某 skill 验证其有效性、删除或解除挂载。

**Why this priority**: 方便运维人员在不启动 agent 的情况下维护和验证 skill 库质量。

**Independent Test**: `holmes kb skill run check-redis` 独立执行 skill 并打印输出，无需启动 agent。

**Acceptance Scenarios**:

1. **Given** Skill 库中有多个 skill，**When** 运行 `holmes kb skill list`，**Then** 输出所有 skill 的名称、描述和挂载条目数。

2. **Given** 有效的 skill 名称，**When** 运行 `holmes kb skill run <skill-name>`，**Then** skill 入口脚本被执行，输出打印到终端，退出码反映执行结果。

3. **Given** 一个已挂载的 skill，**When** 运行 `holmes kb skill unlink <entry-id> <skill-name>`，**Then** 条目 frontmatter 中的 `skill_refs` 移除该 skill，skill 文件夹本身不删除。

---

### Edge Cases

- 如果 skill 脚本引用了系统上不存在的工具（如 `netstat` 未安装），agent 应提示用户工具缺失而非崩溃。
- 如果 KB 条目引用了 `skills/` 中不存在的 skill 名称（如被删除），`holmes kb show` 应警告引用悬空，agent 读取时跳过该引用。
- skill 脚本输出超过 10KB 时，agent 只取前 10KB 并标注截断，防止占满上下文窗口。
- 多个 KB 条目可引用同一个 skill；删除 skill 文件夹前应检查是否有条目仍在引用（悬空引用保护）。
- Skill 文件夹随 KB 仓库一起 git 管理；用户 pull 后本地自动获得新增 skill，无需单独同步。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: KB 仓库 MUST 在根目录维护 `skills/` 目录，每个 skill 以子文件夹形式存放，包含 SKILL.md（名称、描述、参数声明、When to Use、执行说明）和 `scripts/` 目录（入口脚本）。
- **FR-002**: KB 条目的 YAML frontmatter MUST 支持 `skill_refs` 字段（字符串列表），值为 `skills/` 下对应子目录名；无 skill 的条目不含此字段，向后兼容。
- **FR-003**: `holmes kb skill create <name> --desc "<description>"` MUST 在 `$HOLMES_KB_PATH/skills/<name>/` 下生成 SKILL.md 模板和空 `scripts/` 目录。
- **FR-004**: `holmes kb skill link <entry-id> <skill-name>` MUST 将 skill 名称追加到条目 frontmatter 的 `skill_refs` 列表；若 skill 不存在则报错。
- **FR-005**: `holmes kb show <id>` MUST 在输出中列出该条目的所有 skill 引用及其路径，标注为"可执行诊断"。
- **FR-006**: agent 工具 `KbReadEntry` MUST 在返回条目内容时包含 `skill_refs` 字段，agent 据此判断是否存在可执行诊断。
- **FR-007**: 新增 agent 工具 `KbReadSkill(<skill-name>)` MUST 读取并返回 `skills/<name>/SKILL.md` 的完整内容，agent 据此了解 skill 的用途、参数和执行方式。
- **FR-008**: 新增 agent 工具 `KbRunSkill(<skill-name>, <params>)` MUST 执行 `skills/<name>/scripts/run.sh`（固定约定入口），返回 stdout、stderr 和退出码；执行有超时保护，默认 30 秒，可在 SKILL.md 中通过 `timeout` 字段覆盖；若 `run.sh` 不存在则报错。
- **FR-009**: agent MUST 在执行任何 skill 前向用户展示 skill 名称和将执行的脚本内容（或摘要），需用户确认；非交互模式（`-p`）下自动执行。
- **FR-010**: `holmes kb skill list` MUST 列出 `skills/` 下所有 skill 的名称、描述和被引用条目数；`holmes kb skill list <entry-id>` 只列出该条目引用的 skill。
- **FR-011**: `holmes kb skill run <skill-name>` MUST 独立执行指定 skill 并将输出打印到终端，无需启动 agent。
- **FR-012**: agent 在执行 KbExtractAndSave 沉淀流程时，MUST 扫描 Resolution 内容识别可执行命令（以 `$`、反引号包裹或匹配常见命令模式），向用户展示候选列表；用户确认后自动创建 skill 文件夹并写入 `skill_refs`。
- **FR-013**: Skill 文件夹、SKILL.md、脚本文件均通过 git 与 KB 仓库一起版本管理，与条目文件遵循相同的 pending/confirm/push 流程。

### Key Entities

- **KbEntry**: 现有的知识库条目文件，YAML frontmatter 新增可选的 `skill_refs: [<skill-name>, ...]` 字段。
- **SkillDefinition**: `skills/<name>/` 文件夹，包含 SKILL.md（描述、参数声明、执行说明）和 `scripts/` 目录（入口脚本及辅助文件）。
- **SkillLibrary**: KB 仓库根目录下的 `skills/` 目录，所有 SkillDefinition 的集合，随 KB 仓库 git 管理。
- **SkillParam**: SKILL.md 中声明的参数，含名称、描述、是否必填、默认值；agent 执行前负责填充。
- **SkillExecution**: 一次 skill 执行记录（仅在 agent 会话内存中，不持久化），含实际命令、参数值、stdout、stderr、退出码、耗时。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: KB 维护者能在 5 分钟内完成"创建 skill → 编写入口脚本 → 挂载到条目"全流程，无需阅读额外文档。
- **SC-002**: agent 读取含 `skill_refs` 的条目后，从发现引用到完成 `KbReadSkill` 并向用户展示 skill 信息，总延迟不超过 3 秒。
- **SC-003**: 含 `skill_refs` 的条目和 `skills/` 目录能被正常 git push/pull，现有不含 skill 的条目解析不受影响（向后兼容率 100%）。
- **SC-004**: agent 沉淀经验时，对含可执行命令的 Resolution 步骤，skill 识别准确率达 80% 以上（宁漏勿误）。
- **SC-005**: 对于成功执行 skill 的排查会话，agent 定位根因所需对话轮次相比纯文字条目有可量化减少。

## Clarifications

### Session 2026-05-29

- Q: Skill 步骤是否需要独立于 pending/confirm 流程之外的额外安全审查？→ A: 复用现有 pending/confirm + git push 流程，skill 和条目受同等权限约束，git history 作为审计轨迹。
- Q: 通过 CLI 添加 skill 时，命令来源是什么？→ A: 通过 `holmes kb skill create` 创建 skill 文件夹后手动编写入口脚本；CLI 提供模板降低门槛。
- Q: Skill 步骤的 ID 如何产生？→ A: 用户通过 `--name` 指定 skill 文件夹名（如 `check-redis`），在 `skills/` 目录内唯一。
- Q: Skill 何时生成——用户触发还是 agent 沉淀时自动识别？→ A: 两者都支持。用户可手动 `holmes kb skill create`；agent 沉淀时识别命令自动提议生成 skill 文件夹。
- Q: Skill 存储为内嵌代码块还是独立文件夹？→ A: 独立文件夹（Tier 2 only），参考 hermes-agent 的 skills/ 模式；每个 skill 是 `skills/<name>/SKILL.md + scripts/`，KB 条目通过 `skill_refs` frontmatter 字段引用。
- Q: 沉淀时新建的 skill 文件夹是否经过 pending 流程？→ A: Skill 文件夹直接写入 `skills/`，不走 pending；只有 KB 条目走 pending/confirm 流程。条目 confirm 时 skill 已就绪，不存在悬空引用。
- Q: `KbRunSkill` 如何确定 `scripts/` 下的入口脚本？→ A: 固定约定 `scripts/run.sh` 为入口，其他文件为辅助脚本，无需配置。

## Assumptions

- Skill 脚本是 shell 脚本，运行在用户本机环境（Linux/macOS）；不支持跨平台容器化执行（v1 范围外）。
- Skill 执行结果不写回 KB，只在当前 agent 会话中作为诊断上下文使用。
- 不含 `skill_refs` 的现有 KB 条目格式完全不变，向后兼容。
- 用户在运行 skill 时具备执行相关命令的权限，agent 不负责权限提升。
- Skill 文件夹直接写入 `$HOLMES_KB_PATH/skills/`，不经过 pending 暂存；KB 条目仍走 pending/confirm 流程。两者通过 `skill_refs` 关联，条目 confirm 时 skill 已存在，不存在悬空引用。
- v1 不支持 skill 之间的条件分支或链式调用，留待后续迭代。
- `skills/` 目录下的 skill 可被多个条目引用；skill 的增删改走 git 流程，对所有 clone 用户同步生效。
