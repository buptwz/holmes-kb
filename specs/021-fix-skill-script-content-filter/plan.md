# Implementation Plan: Import Pipeline v3 Bug 修复（Round 3）

**Branch**: `021-fix-skill-script-content-filter` | **Date**: 2026-06-09 | **Spec**: [spec.md](spec.md)

## Summary

修复使用报告 v3 中发现的问题及已实现代码中的通用性缺陷：

- **US1 (P1, QA-18)**: Skill run.sh 脚本不可执行 → 从 Extractor prompt 层面修复，要求只输出可执行命令且使用 `$PARAM` 格式；SKILL.md Parameters 章节代码 bug 单独修复
- **US2 (P2, TC-T-06/TC-E-06)**: 知识价值判断重新定义 → DocumentClassifier `non_kb` 判断标准从「文档形式」改为「内容是否有客观可复用知识价值」；通过 few-shot 示例实现，任意形式/语言文档均可处理
- **US3 (P3, normalizer 通用化)**: 语言检测和 token 提取只覆盖 CJK 范围 → 使用 `langdetect` 库实现通用语言检测，扩展 `_TOKEN_RE` Unicode 范围
- **US4 (P4, TC-S-02)**: OPTIONAL Skill 路径无单测 → 补充测试，无代码改动
- **US5 (P5, QA-19/TC-I-07)**: `--dry-run` 输出过于简略、`--dir` exit code 错误 → 修复两处 CLI 行为

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: click, python-frontmatter, pytest, langdetect（新增）

**Storage**: 文件系统（KB entries, Skill 目录）

**Testing**: pytest

**Target Platform**: Linux CLI

**Constraints**: 不修改 `/home/wangzhi/holmes-kb/` 下任何 KB 数据文件

## Constitution Check

| 原则 | 符合情况 |
|------|---------|
| 单一职责 | ✅ Extractor prompt 修复在 extractor.py，classifier prompt 在 classifier.py，normalizer 修复在 normalizer.py，各自独立 |
| 验证原则 | ✅ 每项修复对应单测（T005/T008/T011/T013/T015） |
| 渐进式实现 | ✅ prompt 修复为最小 diff，无新抽象层 |
| 开闭原则 | ✅ prompt 改善不改变调用接口；`langdetect` 通过 try/except 渐进引入 |
| 可观测性 | ✅ non_kb 拒绝输出明确 warning；TC-I-07 自定义错误信息 |

## Project Structure

### Documentation (this feature)

```text
specs/021-fix-skill-script-content-filter/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
└── tasks.md          # /speckit-tasks 生成
```

### Source Code

```text
kb/holmes/kb/agent/phases/
├── extractor.py         # US1: resolution_commands prompt 约束（FR-001/FR-002）
└── classifier.py        # US2: few-shot non_kb prompt 改善（FR-004）

kb/holmes/kb/skill/
└── manager.py           # US1: _generate_skill_md() Parameters 章节修复（FR-003）

kb/holmes/kb/agent/
├── normalizer.py        # US3: 语言检测 + _TOKEN_RE 通用化（FR-007/FR-008）
└── report.py            # US5: format_dry_run_plan() 展示 KP 详情（FR-009）

kb/holmes/kb/agent/pipeline.py  # US2: --force 绕过 non_kb 拦截

kb/holmes/
└── cli.py               # US5: --dir exit code 修复（FR-010）

kb/tests/
├── test_extractor.py        # US1: resolution_commands 格式单测（新增或已存在）
├── test_classifier.py       # US2: non_kb 识别单测
├── test_normalizer.py       # US3: 语言检测通用化单测
└── test_runner.py           # US4: skill candidate suggestion 单测
```

---

## Implementation Details

### US1: QA-18 — Extractor prompt 修复 + SKILL.md Parameters

#### 修改1: `extractor.py` — resolution_commands 格式约束

在 Extractor 的工具调用 schema 或系统 prompt 中，为 `resolution_commands` 字段增加明确约束：

```
resolution_commands: List of EXECUTABLE shell/CLI commands extracted from the
resolution section. IMPORTANT:
- Include ONLY actual runnable commands (e.g., kubectl, bash, python, curl).
- Do NOT include step descriptions, numbered lists, or prose text.
- Use bash variable syntax $PARAM_NAME (not {PARAM_NAME}) for parameters.
- Each entry must be a single executable command line.
```

在 JSON schema 中为 `resolution_commands` 添加 `description` 字段体现上述约束。

#### 修改2: `manager.py` — `_generate_skill_md()` Parameters 正文

当 `param_names` 非空时，替换 `## Parameters` markdown 正文中的 "No parameters defined" 占位文字：

```python
if param_names:
    param_lines = [
        f"- **{p}**: Required. Set via `SKILL_PARAM_{p}` environment variable."
        for p in param_names
    ]
    base = base.replace(
        "_(No parameters defined. Edit the frontmatter `params` section to add parameters.)_",
        "\n".join(param_lines),
    )
```

---

### US2: TC-T-06/TC-E-06 — DocumentClassifier prompt 知识价值判断

#### 修改: `classifier.py` — `_CLASSIFIER_SYSTEM_PROMPT`

将 `non_kb` 的判断标准从「文档形式/类型」改为「内容是否包含客观可复用知识价值」：

```
- non_kb: Content that contains NO objective, reusable factual knowledge worth
  preserving. The criterion is CONTENT VALUE, not document format or type.
  RULE: Classify as non_kb ONLY when the content consists entirely of
  subjective opinions, personal preferences, administrative logistics, or
  organizational information with no reusable technical knowledge.
  ANY document format (meeting notes, tables, wikis, emails) CAN contain
  valuable knowledge — judge the content, not the form.

Content with knowledge value (NOT non_kb, extract into KB):
  - "会议纪要：Redis 连接池耗尽导致超时，根因是最大连接数配置不足，解决方案：..." → single_incident
    (meeting note containing real incident analysis with root cause and fix)
  - "服务目录：order-service 端口8080，依赖 payment-service 8082，数据库 orders_db" → guideline
    (objective facts: service names, ports, dependencies — reusable reference)
  - 任何包含故障根因、解决步骤、运维规程等可复用技术知识的文档 → 对应 KB 类型

Content without knowledge value (non_kb):
  - "Q2 周会纪要: 议题1... 与会人员: 张三... 行动项: 更新文档" → non_kb
    (pure logistics, no technical analysis or reusable knowledge)
  - "Meeting Notes: Attendees: Alice, Bob. Q2 OKR check-in. Action: update docs." → non_kb
    (administrative/organizational, no objective technical knowledge)
  - "OKR Q2: 目标1... 关键结果..." → non_kb
    (subjective goals and progress tracking, not factual reusable knowledge)
  - "个人偏好：我认为 Go 比 Python 好..." → non_kb
    (personal opinion, not objective reusable fact)
```

#### 修改: `pipeline.py` — `--force` 绕过

```python
if classification.doc_type == DocumentType.non_kb:
    if self.force:
        report.warnings.append(
            f"non-kb document (--force bypassed): {classification.reason}"
        )
    else:
        report.warnings.append(
            f"non-kb document: {classification.reason} — skipped"
        )
        return report
```

---

### US3: normalizer 通用化

#### 修改1: `normalizer.py` — 语言检测（Step 3a）

```python
# Step 3a: Language detection (021 generalization).
lang = str(meta.get("language", "") or "").strip()
if not lang:
    combined = f"{title} {body}"
    detected = _detect_language(combined)
    meta["language"] = detected
    warnings.append(f'language: injected "{detected}" (auto-detected)')
```

新增 `_detect_language(text: str) -> str` 函数：

```python
def _detect_language(text: str) -> str:
    """Detect document language using langdetect with Unicode fallback."""
    try:
        from langdetect import detect
        return detect(text)
    except Exception:  # noqa: BLE001
        pass
    # Fallback: Unicode range heuristics (Japanese kana, Korean Hangul, CJK broad).
    if re.search(r"[\u3040-\u30ff]", text):   # Japanese hiragana/katakana
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):   # Korean Hangul
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", text):   # CJK (Chinese / Japanese kanji)
        return "zh"
    return "en"
```

#### 修改2: `normalizer.py` — `_TOKEN_RE`

```python
# 021: Expanded Unicode range to cover Japanese kana, Korean Hangul, CJK extensions.
_TOKEN_RE = re.compile(r"[A-Za-z0-9\u3040-\u9fff\uac00-\ud7af\uf900-\ufaff]+")
```

---

### US4: TC-S-02 — 单测补充

在 `kb/tests/test_runner.py` 中新增测试验证 OPTIONAL 路径：

- 1 命令 → `skill candidate` suggestion 出现
- 2 命令 → 同上
- 0 命令 → 无 suggestion
- 3+ 命令 → RECOMMENDED 路径，无 candidate suggestion

无代码改动。

---

### US5: CLI 改善

#### `report.py` — `format_dry_run_plan()`

```python
elif self.knowledge_map is not None:
    kps = self.knowledge_map.knowledge_points
    if kps:
        for kp in kps:
            cat = kp.category_hint or "unknown"
            lines.append(
                f'  Would create (est.): "{kp.description}" ({kp.type_hint}/{cat})'
            )
    else:
        lines.append("  Would process: (~0 knowledge point(s) estimated)")
```

#### `cli.py` — `--dir` exit code

```python
# 修改 option: 移除 exists=True
@click.option("--dir", "import_dir", default=None,
              type=click.Path(file_okay=False, path_type=Path), ...)

# 在命令体内添加手动检查
if import_dir is not None and not import_dir.is_dir():
    click.echo(f"Directory does not exist: {import_dir}", err=True)
    sys.exit(1)
```

---

## Complexity Tracking

无 constitution 违规。`langdetect` 作为新依赖需添加到 `requirements.txt` / `pyproject.toml`。
