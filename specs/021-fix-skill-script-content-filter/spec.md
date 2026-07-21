# Feature Specification: Import Pipeline v3 Bug 修复（Round 3）

**Feature Branch**: `021-fix-skill-script-content-filter`

**Created**: 2026-06-09

**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Skill 脚本可执行（QA-18）(Priority: P1)

SRE 工程师导入含 shell 命令的事故报告后，生成的 Skill `run.sh` 脚本应可直接执行，无需手动修正。当前问题：LLM 生成的 `resolution_commands` 中混入了步骤描述文字（非命令）、参数格式使用 `{PARAM}` 而非 bash 变量格式，以及 SKILL.md Parameters 章节与 frontmatter 矛盾。根本原因在于 Extractor 对命令格式没有约束，需从生成源头修复。

**Why this priority**: Skill 是 Holmes 知识库的核心可操作资产。脚本无法执行意味着 58 个已生成的 Skills 无实际使用价值，严重影响产品可信度。

**Independent Test**: 导入含参数化命令的事故报告 → 检查生成的 `scripts/run.sh` 可通过 `bash -n` 语法检查，参数引用格式正确，SKILL.md Parameters 章节列出所有参数名称。

**Acceptance Scenarios**:

1. **Given** 一个含 `kubectl get pods -n {NAMESPACE}` 命令的事故报告，**When** 导入后生成 Skill，**Then** `run.sh` 中该命令变为 `kubectl get pods -n $NAMESPACE`，脚本通过 `bash -n` 检查。
2. **Given** Resolution 章节含步骤说明（任意语言），**When** 生成 Skill，**Then** `resolution_commands` 中只包含可执行 shell 命令行，不含步骤描述文字。
3. **Given** Skill frontmatter 中有 `params: [{name: NAMESPACE}, {name: APP_NAME}]`，**When** 查看 SKILL.md，**Then** `## Parameters` 章节列出 `NAMESPACE`、`APP_NAME` 两个参数，而非 "No parameters defined"。
4. **Given** Resolution 不含任何参数占位符，**When** 生成 Skill，**Then** `run.sh` 不含任何参数声明行，SKILL.md Parameters 显示 "No parameters defined"。

---

### User Story 2 - 按知识价值判断文档是否值得沉淀（TC-T-06 / TC-E-06 重新定义）(Priority: P2)

系统接受任意形式、任意语言的文档，并判断其内容是否包含值得沉淀的客观事实知识。判断标准是内容的知识价值，而非文档的形式或类型——会议纪要里的真实故障分析值得提取，纯行程安排不值得；服务目录是客观事实可映射为 model，纯个人偏好/主观意见无知识价值。当前 DocumentClassifier 的 `non_kb` 判断以文档格式为依据，导致有价值的内容被错误拒绝，或无价值内容被错误接受。

**Why this priority**: 知识库的价值在于沉淀客观可复用的知识，而非限制输入格式。错误的判断标准会导致有价值知识流失或无价值内容污染库。

**Independent Test**: 导入一份含真实故障分析的会议纪要 → 故障知识点被提取为 pitfall 条目；导入一份纯行程安排的会议纪要 → `0 created` + 明确的无知识价值提示。

**Acceptance Scenarios**:

1. **Given** 会议纪要中有一段完整的 Redis 超时故障分析和解决步骤，**When** 执行导入，**Then** 该故障知识被提取为 pitfall 条目，`created >= 1`。
2. **Given** 纯行程/出席人员/OKR 进度等主观或行政内容，无可复用的客观技术知识，**When** 执行导入，**Then** `0 created` + 提示无有价值知识点。
3. **Given** 服务目录（服务名/端口/依赖关系等客观事实），**When** 执行导入，**Then** 被提取为 model 类型条目。
4. **Given** 任意文档，**When** 执行导入，**Then** 系统不因文档形式或语言拒绝处理，只基于内容是否有知识价值决定是否创建条目。

---

### User Story 3 - 多语言文档语言检测与标签提取（normalizer 通用化）(Priority: P3)

工程师导入非中英文文档（如日文、韩文事故报告）时，系统应正确识别语言并提取有意义的标签，而非将其误判为中文或英文。当前 normalizer 中 Unicode 范围仅覆盖 CJK Unified Ideographs，导致日韩文字符在语言检测和标签提取两个路径均处理错误。

**Why this priority**: 语言字段和标签是 KB 条目的核心元数据，错误检测会导致搜索和分类失效。

**Independent Test**: 导入一份日文事故报告 → `language` 字段为 `ja`；导入韩文报告 → `language` 为 `ko`；导入中文报告 → `language` 为 `zh`；tags 字段包含文档语言的关键词 token。

**Acceptance Scenarios**:

1. **Given** 日文文档（含平假名/片假名），**When** 导入，**Then** `language: ja`，`tags` 中含有日文 token。
2. **Given** 韩文文档（含 Hangul），**When** 导入，**Then** `language: ko`，`tags` 包含韩文 token。
3. **Given** 中文文档，**When** 导入，**Then** `language: zh`（现有行为保持不变）。
4. **Given** 已有 `language` 字段的文档，**When** 导入，**Then** 现有 `language` 值不被覆盖（现有行为保持不变）。

---

### User Story 4 - OPTIONAL Skill 候选提示测试覆盖（TC-S-02）(Priority: P4)

当前代码已在 `Recommendation.OPTIONAL` 路径正确添加 `skill candidate` suggestion，但缺乏单测验证，存在退化风险。

**Why this priority**: 功能已正确，仅需补充测试防止退化。

**Independent Test**: 单测验证 1-2 命令条目触发 `skill candidate` suggestion，3+ 命令走自动创建路径，0 命令无 suggestion。

**Acceptance Scenarios**:

1. **Given** 单测中模拟 1-2 命令条目，**When** 执行 `_run_skill_and_curation`，**Then** report.suggestions 中包含 `skill candidate` 字样。
2. **Given** 0 命令条目，**When** 执行，**Then** 无 skill candidate suggestion。
3. **Given** 3+ 命令条目，**When** 执行，**Then** 走 RECOMMENDED 路径，不走 OPTIONAL。

---

### User Story 5 - CLI 体验改善（QA-19 / TC-I-07）(Priority: P5)

`--dry-run` 应展示预期创建的条目标题和类型；`--dir` 指定不存在目录时返回 exit 1 + 自定义错误信息。

**Why this priority**: 纯体验改善，不影响核心功能。

**Independent Test**: `--dry-run` 输出含条目标题/类型；`--dir /nonexistent/` 返回 exit 1 + 自定义信息。

**Acceptance Scenarios**:

1. **Given** 一份含 2 个知识点的文档，**When** 执行 `--dry-run`，**Then** 输出包含两行 `Would create (est.): "<title>" (type/category)`。
2. **Given** `--dry-run --verbose`，**When** 执行，**Then** 额外输出每个知识点的分类依据。
3. **Given** `--dir /nonexistent/`，**When** 执行，**Then** 输出 `Directory does not exist: /nonexistent/`，exit code 为 1。

---

### Edge Cases

- `run.sh` 中 `${VAR:-default}` 格式的合法 bash 变量展开不应被误修改。
- 含少量非技术段落（如开头背景介绍）的技术故障报告不应被整体拒绝。
- `language` 字段已存在时，normalizer 不覆盖（任何语言均如此）。
- langdetect 检测失败时（如文档过短），fallback 到启发式 Unicode 范围检测，再 fallback 到 `en`。
- `--dry-run` 输出的条目信息来自 Reader 估算，标注 `(est.)` 表示非最终结果。

---

## Requirements

### Functional Requirements

- **FR-001**: Extractor prompt 必须明确要求 `resolution_commands` 只包含可执行 shell 命令，禁止包含步骤说明文字。
- **FR-002**: Extractor prompt 必须明确要求命令中的变量引用使用 `$PARAM` 格式，而非 `{PARAM}`。
- **FR-003**: 系统在生成 SKILL.md 时，必须根据 frontmatter `params` 列表填充 `## Parameters` 章节；列表非空则列出各参数名，为空则显示 "No parameters defined"。
- **FR-004**: DocumentClassifier prompt 必须通过清晰的 few-shot 示例（涵盖中英文场景）区分技术运维知识与非技术组织文档，使 LLM 对任意语言的非技术文档均能正确返回 `non_kb`。
- **FR-005**: `--force` 标志必须绕过非技术文档过滤，允许强制导入，但输出警告信息。
- **FR-006**: 当 Resolution 命令数量为 1 或 2 时，系统必须输出 `skill candidate` suggestion；不自动创建 Skill。
- **FR-007**: normalizer 的语言检测必须使用通用语言检测方案，至少正确区分中文、日文、韩文、英文。
- **FR-008**: normalizer 的 `_TOKEN_RE` 必须覆盖常用多语言脚本的 Unicode 范围，不限于 CJK Unified Ideographs。
- **FR-009**: `--dry-run` 模式输出必须包含每个预期创建条目的标题、类型和分类（来自 Reader 阶段估算，标注 est.）。
- **FR-010**: `--dir` 指定不存在目录时，输出 `Directory does not exist: <path>`，exit code 为 1。

### Key Entities

- **Skill**: 包含 `SKILL.md`（frontmatter + Parameters 章节）和 `scripts/run.sh`（可执行 bash 脚本）。
- **DocumentType**: 现有枚举，`non_kb` 类型的识别能力需通过 prompt 改善覆盖所有语言。
- **SkillAdvisorDecision**: `RECOMMENDED`（3+）、`OPTIONAL`（1-2，输出 candidate）、`SKIP`（0 命令）。

---

## Success Criteria

### Measurable Outcomes

- **SC-001**: 新导入文档生成的 `run.sh` 100% 通过 `bash -n` 语法检查。
- **SC-002**: 中英文会议纪要和服务目录表格导入后 `0 created`，输出明确拒绝原因。
- **SC-003**: 日文、韩文测试文档的 `language` 字段正确检测（不再误判为 zh 或 en）。
- **SC-004**: `--dry-run` 输出包含条目标题和类型估算，而非仅 KP 数量。
- **SC-005**: `--dir /nonexistent/` 返回 exit 1 + 自定义错误信息。
- **SC-006**: 全量测试套件通过率不低于修复前（656 passed），每项修复有对应单测。

---

## Assumptions

- Extractor prompt 修复通过在现有 prompt 中增加明确的格式约束实现，不改变工具调用结构。
- DocumentClassifier prompt 改善通过增加 few-shot 示例实现，不改变 JSON 输出结构。
- 语言检测优先使用 `langdetect` 库（Python 常用依赖），不可用时 fallback 到扩展 Unicode 范围启发式，最终 fallback 到 `en`。
- `_TOKEN_RE` 扩展 Unicode 范围覆盖 CJK 扩展区、日文假名（`\u3040-\u30ff`）、韩文 Hangul（`\uac00-\ud7af`）。
- TC-D-02 语义去重 UPDATE 路径不在本 feature 范围内，记录为 future work。
- US4（TC-S-02）无代码改动，仅补充单测。
