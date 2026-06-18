# Research: Skill Concept Alignment

## R-001: Anthropic Agent Skills 标准格式

**Decision**: SKILL.md frontmatter 只使用 `name` + `description` 两个必填字段。可选字段：`license`、`allowed-tools`、`metadata`、`compatibility`。

**Rationale**: 参考 `/home/wangzhi/project/skills/skills/skill-creator/scripts/quick_validate.py` — `ALLOWED_PROPERTIES = {'name', 'description', 'license', 'allowed-tools', 'metadata', 'compatibility'}`。

**名称规则**:
- kebab-case，只含小写字母/数字/连字符
- 不以连字符开头/结尾，不含连续连字符
- 最长 64 字符

**描述规则**:
- 最长 1024 字符
- 不含尖括号 `<` `>`
- 应说明触发时机（when to use）+ 功能（what it does）
- 遵循"触发粘性"原则：宁可多触发，不欠触发

---

## R-002: Skill Body 结构（skill-creator 方法论）

**Decision**: 生成的 SKILL.md body 使用三节结构：

```markdown
# {title}

## When to Use

{症状描述 + 触发条件，告诉 agent 何时应该参考此 skill}

## Resolution Steps

{分步骤的操作指引，agent 按此执行}

## Key Points

{重要注意事项、边界条件、常见误区}
```

**Rationale**: skill-creator SKILL.md 指出 body 是 agent 的执行指令，需结构清晰、步骤明确。`## When to Use` 对应 description 的扩展，`## Resolution Steps` 是核心操作，`## Key Points` 补充上下文。

**质量原则（来自 skill-creator）**:
- 用祈使语气（imperative form）
- 解释"为什么"而不仅是"做什么"
- 避免过度 MUST/NEVER，用理由引导
- body ≤ 500 行

---

## R-003: skill 触发条件（不变）

**Decision**: 保留现有命令计数机制：
- `detect_commands(resolution_text)` 计数
- ≥3 → RECOMMENDED（自动创建 skill）
- 1-2 → OPTIONAL（建议，不自动创建）
- 0 → SKIP
- 已有 skill_refs → LINK

**Rationale**: 命令计数是判断"是否有足够可操作内容"的代理指标。≥3 个命令意味着存在多步骤过程，agent skill 的价值显著。1-2 个步骤的操作价值有限，不值得专门创建 skill。这个阈值经过 feature 018/023 的迭代验证，不需改变。

**`detect_commands()` 保留**，但仅用于计数，不再用于生成 run.sh。

---

## R-004: LLM 生成 skill instructions 的设计

**Decision**: 新增 `ImportAgentRunner._generate_skill_instructions(entry_content: str, resolution_text: str) -> str`，调用 `self._provider.simple_complete()` 生成 SKILL.md body。

**Prompt 设计原则**:
```
你是一个 KB skill 生成器。根据以下 KB entry 内容，生成一个 Anthropic Agent Skill 的 SKILL.md body。

要求：
1. ## When to Use：描述 agent 应在何种症状/条件下使用此 skill，2-4 句话
2. ## Resolution Steps：分步骤列出操作，每步一行，清晰可执行
3. ## Key Points：列出 2-4 条重要注意事项或边界条件
4. 使用祈使语气，解释原因而非仅列步骤
5. 总长度控制在 50 行以内

KB Entry 内容：
{entry_content}

只输出 markdown body（从 # {title} 开始），不要输出 frontmatter。
```

**name slug 生成**: 沿用现有 `_make_slug(entry_id)` 逻辑（`SkillAdvisor._make_slug`）。

**description 生成**: 由 LLM 在 instructions 生成时一并输出，或从 entry title + resolution 首句提炼。具体实现：在 prompt 中要求 LLM 同时输出 `DESCRIPTION:` 行，`_generate_skill_instructions()` 解析并分离。

**降级策略**: LLM 调用失败时，返回空字符串，`create_skill()` 使用默认占位 body；pipeline 记录 warning，不阻断主流程。

---

## R-005: tool-use loop 路径 vs fallback 路径

**两条 skill 创建路径**:

**路径 A（LLM tool-use loop）**:
1. LLM 读 entry 内容（知道完整 context）
2. LLM 自行生成 `instructions` 内容
3. LLM 调用 `create_skill_for_entry(name, entry_id, description, instructions)`
4. handler 直接调 `create_skill()`

**路径 B（fallback: `_finalize_skill_generation`）**:
1. `_finalize_skill_generation()` 发现 LLM 未调用 evaluate/create_skill
2. 调 `_run_skill_and_curation()`
3. `detect_commands()` 计数 → RECOMMENDED
4. `_generate_skill_instructions(entry_content, resolution_text)` → LLM 调用
5. 调 `create_skill_for_entry(instructions=instructions)`

**路径 A 的 system prompt 更新**: 在 `_IMPORT_SYSTEM_PROMPT` step 6 中，明确要求 LLM 调用 `create_skill_for_entry` 时提供 `instructions` 参数（structured agent instructions，含三节）。

---

## R-006: 被删除的 CLI 命令与 test coverage

**删除的命令**: `skill create/link/unlink/run/detect-commands/auto-create`

**影响的测试文件**:
- `test_skill_runner.py` → 整体删除（`runner.py` 删除）
- `test_skill_manager.py` → 删除 `auto_create_skill`/run.sh 相关测试，保留 `detect_commands` 测试
- `test_skill_data_model.py` → 删除 `version`/`platforms`/`timeout`/`params`/`prerequisites`/`run.sh` 相关断言
- `test_skill_edge.py` → 删除 EDGE-005/006/007/009（runner 依赖），保留其余
- `test_skill_cli.py` → 删除 create/link/unlink/run/detect-commands/auto-create 测试；保留 list/read/show 测试
- `conftest.py` → 删除 `make_skill_with_script`/`run_sh_echo`/`run_sh_env`/`skill_with_prereqs`/`skill_with_required_param`

**新增测试**:
- `test_skill_manager.py`: `create_skill` 不生成 `run.sh`；`validate_skill_md()` 合法/非法 key；新格式 SkillDefinition 字段
- `test_skill_advisor.py` 或 `test_skill_manager.py`: skill advisor 命令计数触发逻辑
- `test_skill_cli.py`: 删除的命令返回 "No such command"；list/read JSON 字段正确

---

## R-007: kb-template 状态

`kb-template/skills/` 目录不存在 → 无需清理旧格式样本。

---

## R-008: docs 需更新内容

**`docs/reference.md`**:
- 删除 `holmes kb skill run` 条目
- 删除 `holmes kb skill detect-commands` 条目
- 删除 `holmes kb skill create` 中的 `--platform` 说明
- 删除 `holmes kb skill create/link/unlink/auto-create` 条目
- 更新 `holmes kb skill` 为只读命令（list/read）

**`docs/kb-management.md`**:
- 更新 skill 相关描述：skill 是 agent 指令包，由 import 自动生成
- 删除手动创建 skill、skill run 等操作说明
