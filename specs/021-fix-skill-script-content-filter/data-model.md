# Data Model: Import Pipeline v3 Bug 修复（Round 3）

## 变更摘要

本 feature 不引入新实体或新字段，只对现有实体的行为和 prompt 进行修正。

---

## 修改的实体

### DocumentType（行为变更，枚举不变）

**位置**: `kb/holmes/kb/agent/phases/classifier.py`

**现有枚举值**（不变）:
- `single_incident`, `multi_incident`, `runbook`, `guideline`, `non_kb`

**行为变更**: `non_kb` 的识别率通过 prompt few-shot 改善，覆盖中英文及其他语言的非技术文档，无新增枚举值。

---

### Skill（文件系统结构，SKILL.md 行为修正）

**位置**: `kb/holmes/kb/skill/manager.py`, `kb/holmes/kb/skill/template.py`

**变更**: `_generate_skill_md()` 当 `param_names` 非空时，同步更新 `## Parameters` markdown 正文，不再显示 "No parameters defined"。

**修复后 SKILL.md Parameters 章节格式**:
```markdown
## Parameters

- **NAMESPACE**: Required. Set via `SKILL_PARAM_NAMESPACE` environment variable.
- **APP_NAME**: Required. Set via `SKILL_PARAM_APP_NAME` environment variable.
```

**run.sh**: 不再需要后处理。Extractor prompt 修复后，LLM 直接生成正确格式的命令。

---

### DraftNormalizer（行为变更）

**位置**: `kb/holmes/kb/agent/normalizer.py`

**变更1: 语言检测**

| | 修复前 | 修复后 |
|--|--------|--------|
| 检测方式 | `re.search(r"[\u4e00-\u9fff]", ...)` | `langdetect.detect(combined)`，fallback 到扩展 Unicode 范围 |
| 日文文档 | 误判为 `zh`（汉字区重叠） | 正确识别为 `ja` |
| 韩文文档 | 误判为 `en`（Hangul 不在范围） | 正确识别为 `ko` |
| 中文文档 | `zh` ✓ | `zh` ✓ |
| 英文文档 | `en` ✓ | `en` ✓ |

**变更2: `_TOKEN_RE` Unicode 范围**

| | 修复前 | 修复后 |
|--|--------|--------|
| 正则范围 | `[A-Za-z0-9\u4e00-\u9fff]+` | `[A-Za-z0-9\u3040-\u9fff\uac00-\ud7af\uf900-\ufaff]+` |
| 日文假名 token | 不提取 | 提取 |
| 韩文 Hangul token | 不提取 | 提取 |
| CJK Extension A | 不提取 | 提取 |

---

## 不变的实体

- `ImportReport`: dry-run 输出格式变更，无结构变更
- `KnowledgePoint`: 只读已有字段，无变更
- `ClassificationResult`: 无字段变更
- `SkillAdvice` / `Recommendation`: 无变更（OPTIONAL 路径已正确）
- `ThreePhaseImportPipeline`: `--force` 绕过非技术文档过滤，已有 `self.force` 字段，仅增加判断逻辑
