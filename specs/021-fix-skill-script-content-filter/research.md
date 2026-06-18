# Research: Import Pipeline v3 Bug 修复（Round 3）

## R-001: QA-18 Skill run.sh 问题根因

**Decision**: 从 Extractor prompt 层面修复命令格式，不做 run.sh 后处理启发式规则。

**Rationale**:
- `create_skill()` 将 `resolution_commands` 列表原样写入 run.sh
- LLM 在生成 `resolution_commands` 时混入了步骤描述文字，并使用 `{PARAM}` 而非 `$PARAM`
- 根本原因：Extractor prompt 未对 `resolution_commands` 字段的内容格式做约束
- 正确修法：在 Extractor prompt 中明确要求：
  1. `resolution_commands` 只包含可执行 shell/CLI 命令行，不含步骤说明文字
  2. 命令中变量引用使用 `$PARAM` 格式（bash 变量语法），不使用 `{PARAM}`
- 这样无论文档语言是中文、英文还是其他语言，生成的命令列表从源头就是干净可执行的

**Alternatives considered**:
- 后处理 run.sh（检测 CJK 字符加 `#`，regex 替换 `{PARAM}`）：特定场景启发式，中英文以外失效，且 regex 可能误伤合法 bash 语法（如 JSON 字符串中的 `{key}`）

**SKILL.md Parameters 章节**: 这是代码 bug，与 LLM 无关。`_generate_skill_md()` 正确写入 frontmatter params，但 markdown 正文中 `## Parameters` 章节硬编码为 "No parameters defined"。需在 `_generate_skill_md()` 中根据 `param_names` 更新 markdown 正文。

## R-002: TC-T-06/TC-E-06 知识价值判断重新定义

**Decision**: 将 DocumentClassifier 的 `non_kb` 判断标准从「文档形式/类型」改为「内容是否包含客观可复用知识价值」，通过更新 LLM prompt 和 few-shot 示例实现，不添加确定性关键词检测。

**Rationale**:
- 原问题根因是判断标准错误：以文档格式（会议纪要、服务目录）为拒绝依据，而非内容价值
- 正确判断准则：**内容是否包含客观事实、可复用的技术/运维知识**，与文档形式无关
  - 会议纪要里有完整故障分析 → 有知识价值 → 提取为 pitfall
  - 服务目录（服务名/端口/依赖关系）→ 客观事实 → 提取为 model
  - 纯行程安排/出席人员/个人偏好 → 无知识价值 → `non_kb`
  - OKR 进度、主观评价 → 无可复用客观知识 → `non_kb`
- 确定性关键词/格式检测是形式导向的，是对 `non_kb` 标准的误实现，必须放弃
- 通用解法：在 DocumentClassifier prompt 中用清晰的 few-shot 示例明确「知识价值」判断边界：
  - 含真实技术故障分析的会议纪要 → 有价值，进入提取流程
  - 纯行政/组织/个人偏好文档 → 无价值，`non_kb`
  - 服务目录等客观事实表格 → 有价值，进入提取流程
- 系统接受**任意形式、任意语言**的文档，仅以内容知识价值决定是否创建条目

**`--force` 绕过**:
- `self.force` 已在 pipeline.py 存在，在 `non_kb` 拦截处检查即可
- 绕过时输出 warning 不阻断

## R-003: TC-S-02 OPTIONAL Skill 路径

**Decision**: 代码已正确实现，仅补充单测。

**Analysis**:
- `runner.py` L417-419 在 `Recommendation.OPTIONAL` 时已添加 `skill candidate` suggestion
- 测试报告误判为静默跳过，实际是 TC-S-02 文档已在 KB（source_hash skip），未触发 `write_kb_entry`，因此 `_run_skill_and_curation` 未被调用
- 无需代码改动，添加单测确保路径不退化

## R-004: QA-19 --dry-run 输出

**Decision**: 修改 `format_dry_run_plan()` 遍历 `knowledge_map.knowledge_points` 输出每个 KP 的 `description`/`type_hint`/`category_hint`。

**Rationale**:
- E-4 fix 已保证 Reader 在 dry-run 模式下执行，`knowledge_map` 已填充
- `KnowledgePoint.description` 是 Reader 的一句摘要，`type_hint`/`category_hint` 是 Reader 估算
- 标注 `(est.)` 表明这是 Reader 阶段估算，非最终 Extractor 结果

## R-005: TC-I-07 exit code

**Decision**: 移除 `click.Path(exists=True)`，在命令体内手动检查，`sys.exit(1)` 输出自定义错误。

**Rationale**: Click 的 `exists=True` 触发 `BadParameter` → exit 2，无法覆盖。手动检查是标准做法。

## R-006: normalizer 语言检测与 _TOKEN_RE 通用化

**Decision**: 语言检测使用 `langdetect` 库，`_TOKEN_RE` 扩展 Unicode 范围覆盖日韩文字符。

**Rationale**:
- 当前 `[\u4e00-\u9fff]` 仅覆盖 CJK Unified Ideographs（主要是中文和日文汉字共用区）
- 日文文档含平假名（`\u3040-\u309f`）和片假名（`\u30a0-\u30ff`），会被误判为 `zh`（因共用汉字区）
- 韩文 Hangul（`\uac00-\ud7af`）完全不在范围内，韩文文档误判为 `en`
- `langdetect` 是 Python 标准依赖，支持 55+ 语言，返回 ISO 639-1 代码，是通用解法
- `langdetect` 在文档过短时可能报错，需 try/except fallback：
  1. 先尝试 `langdetect.detect(combined)` → 直接得到语言代码
  2. 失败时 fallback 到 Unicode 范围判断（扩展后的范围）
  3. 最终 fallback 到 `en`
- `_TOKEN_RE` 扩展为 `[A-Za-z0-9\u3040-\u9fff\uac00-\ud7af\uf900-\ufaff]+`，覆盖：
  - 日文假名 `\u3040-\u30ff`
  - CJK Unified Ideographs `\u4e00-\u9fff`（原有范围）
  - CJK Extension A `\u3400-\u4dbf`（扩展）
  - 韩文 Hangul `\uac00-\ud7af`
  - CJK Compatibility Ideographs `\uf900-\ufaff`

**Alternatives considered**:
- 仅扩展 Unicode 范围：比 `langdetect` 简单但不够准确，中日文字符重叠会导致误判
- `langid` 库：同类产品，选 `langdetect` 因为更常见
