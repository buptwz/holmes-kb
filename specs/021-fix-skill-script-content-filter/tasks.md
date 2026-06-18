# Tasks: Import Pipeline v3 Bug 修复（Round 3）

**Input**: Design documents from `/specs/021-fix-skill-script-content-filter/`

**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ quickstart.md ✅

**Organization**: Tasks grouped by user story. US1-US3 have implementation + test tasks (SC-006 requires tests per fix). US4 is tests only (no code change). US5 has implementation + test tasks.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Setup

**Purpose**: Add new dependency required by US3.

- [X] T001 Add `langdetect` to `[project.dependencies]` in `kb/pyproject.toml`

**Checkpoint**: `pip install -e kb/` succeeds with langdetect available.

---

## Phase 2: Foundational

No shared foundational prerequisites — all user stories are independent and can begin after T001.

---

## Phase 3: User Story 1 — Skill run.sh 脚本可执行（QA-18）(Priority: P1) 🎯 MVP

**Goal**: LLM 生成的 `resolution_commands` 只含可执行 shell 命令（使用 `$PARAM` 格式），SKILL.md Parameters 章节与 frontmatter 一致。

**Independent Test**: 导入含参数化命令的事故报告 → `bash -n run.sh` 通过，SKILL.md Parameters 章节列出参数名。

### Implementation for User Story 1

- [X] T002 [US1] 在 `kb/holmes/kb/agent/runner.py` 中修复 `{PARAM}` → `$PARAM` 转换
- [X] T003 [US1] 修复 `kb/holmes/kb/skill/manager.py` 的 `_generate_skill_md()` — 当 `param_names` 非空时，将 `## Parameters` markdown 正文中的 "No parameters defined" 占位文字替换为各参数的描述行

### Tests for User Story 1

- [X] T004 [P] [US1] 在 `kb/tests/test_extractor_phase.py` 中新增测试：验证 extractor tool schema 中 `resolution_commands` 字段的 description 包含 `$PARAM` 格式要求和禁止步骤描述文字的约束
- [X] T005 [P] [US1] 在 `kb/tests/test_skill_manager.py` 中新增测试：Given `param_names=["NAMESPACE","APP_NAME"]`，When `_generate_skill_md()` 被调用，Then `## Parameters` 正文包含 `NAMESPACE` 和 `APP_NAME`，不含 "No parameters defined"；Given `param_names=[]`，Then 显示 "No parameters defined"

**Checkpoint**: T004/T005 通过，bash 语法检查场景（quickstart Scenario 1）手动验证通过。

---

## Phase 4: User Story 2 — 按知识价值判断文档是否值得沉淀（Priority: P2）

**Goal**: DocumentClassifier 以内容的客观知识价值为 `non_kb` 判断标准，而非文档形式或类型；含真实故障分析的会议纪要被提取，纯行政内容被拒绝；`--force` 可绕过 non_kb 拦截。

**Independent Test**: 导入含真实故障分析的会议纪要 → `created >= 1`；导入纯行动项会议纪要 → `0 created` + non_kb 提示；`--force` 导入时输出 warning 但不阻止。

### Implementation for User Story 2

- [X] T006 [US2] 修改 `kb/holmes/kb/agent/phases/classifier.py` 的 `_CLASSIFIER_SYSTEM_PROMPT`：将 `non_kb` 判断标准从文档形式改为内容知识价值，增加中英文 few-shot 示例区分"含技术故障分析的会议纪要 → 非 non_kb"与"纯行政/OKR/个人偏好 → non_kb"（参见 plan.md US2 章节的完整 prompt）
- [X] T007 [US2] 在 `kb/holmes/kb/agent/pipeline.py` 的 non_kb 拦截处添加 `--force` 绕过逻辑：`if self.force: report.warnings.append("non-kb document (--force bypassed): ..."); else: return report`

### Tests for User Story 2

- [X] T008 [P] [US2] 在 `kb/tests/test_classifier.py` 中新增测试：mock LLM 返回，验证含故障分析内容的 prompt 不被分类为 non_kb，纯行政内容被分类为 non_kb
- [X] T009 [P] [US2] 在 `kb/tests/test_pipeline.py` 中新增测试：验证 `--force=True` 时 non_kb 文档不触发早返回，report.warnings 包含 "non-kb document (--force bypassed)"；验证 `--force=False` 时早返回，`0 created`

**Checkpoint**: T008/T009 通过，quickstart Scenario 2/3（纯行政内容 → 0 created）和 Scenario 5（--force → warning 不阻止）手动验证。

---

## Phase 5: User Story 3 — 多语言语言检测与标签提取（normalizer 通用化）(Priority: P3)

**Goal**: normalizer 正确识别中文、日文、韩文、英文；`_TOKEN_RE` 提取日韩文 token。

**Independent Test**: 单测验证日文文档 → `language: ja`，韩文 → `language: ko`，中文 → `language: zh`，已有 language 字段不被覆盖。

### Implementation for User Story 3

- [X] T010 [US3] 在 `kb/holmes/kb/agent/normalizer.py` 中新增 `_detect_language(text: str) -> str` 函数：优先 `langdetect.detect()`，失败时 fallback 到 Unicode 范围启发式（`[\u3040-\u30ff]` → ja，`[\uac00-\ud7af]` → ko，`[\u4e00-\u9fff]` → zh），最终 fallback 到 `en`
- [X] T011 [US3] 将 `kb/holmes/kb/agent/normalizer.py` 中的 `_TOKEN_RE` 从 `[A-Za-z0-9\u4e00-\u9fff]+` 扩展为 `[A-Za-z0-9\u3040-\u9fff\uac00-\ud7af\uf900-\ufaff]+`，覆盖日文假名、韩文 Hangul、CJK 扩展区
- [X] T012 [US3] 将 `kb/holmes/kb/agent/normalizer.py` 中 Step 3a 的语言检测替换为调用 `_detect_language(combined)`，删除原有 `re.search(r"[\u4e00-\u9fff]", combined)` 启发式

### Tests for User Story 3

- [X] T013 [US3] 在 `kb/tests/test_normalizer.py` 中新增测试：验证日文文档（含平假名）→ `language: ja`；韩文文档（含 Hangul）→ `language: ko`；中文文档 → `language: zh`；已有 `language` 字段的文档不被覆盖；`_TOKEN_RE` 能提取日文和韩文 token

**Checkpoint**: T013 通过，`python -m pytest kb/tests/test_normalizer.py -k language -v` 全绿。

---

## Phase 6: User Story 4 — OPTIONAL Skill 候选提示测试覆盖（TC-S-02）(Priority: P4)

**Goal**: 验证 1-2 条命令触发 `skill candidate` suggestion，0 条无 suggestion，3+ 条走 RECOMMENDED 路径。无代码改动，仅补充单测。

**Independent Test**: `python -m pytest kb/tests/test_skill_advisor.py -k "optional or candidate" -v` 通过。

### Tests for User Story 4

- [X] T014 [US4] 在 `kb/tests/test_skill_advisor.py` 中新增测试：mock 1 条命令条目 → `_run_skill_and_curation` 返回的 report.suggestions 含 `skill candidate`；mock 2 条命令条目 → 同上
- [X] T015 [P] [US4] 在 `kb/tests/test_skill_advisor.py` 中新增测试：mock 0 条命令条目 → report.suggestions 不含 `skill candidate`
- [X] T016 [P] [US4] 在 `kb/tests/test_skill_advisor.py` 中新增测试：mock 3+ 条命令条目 → 走 RECOMMENDED 路径，不触发 OPTIONAL，无 `skill candidate` suggestion

**Checkpoint**: T014/T015/T016 全部通过。

---

## Phase 7: User Story 5 — CLI 体验改善（QA-19 / TC-I-07）(Priority: P5)

**Goal**: `--dry-run` 展示预期创建条目的标题和类型；`--dir` 不存在目录返回 exit 1 + 自定义错误信息。

**Independent Test**: `holmes import file --dry-run` 输出含 `Would create (est.): "..." (type/category)`；`holmes import --dir /nonexistent/` 返回 exit 1 + `Directory does not exist: /nonexistent/`。

### Implementation for User Story 5

- [X] T017 [US5] 修改 `kb/holmes/kb/agent/report.py` 的 `format_dry_run_plan()`：当 `self.knowledge_map` 非空且 `knowledge_map.knowledge_points` 非空时，遍历输出每个 KP 的 `f'  Would create (est.): "{kp.description}" ({kp.type_hint}/{kp.category_hint or "unknown"})'`；空时输出 `"  Would process: (~0 knowledge point(s) estimated)"`
- [X] T018 [US5] 修改 `kb/holmes/cli.py` 的 `--dir` 选项：移除 `click.Path` 中的 `exists=True`；在命令体顶部添加 `if import_dir is not None and not import_dir.is_dir(): click.echo(f"Directory does not exist: {import_dir}", err=True); sys.exit(1)`

### Tests for User Story 5

- [X] T019 [P] [US5] 在 `kb/tests/test_pipeline.py` 或 `kb/tests/test_agent_runner.py` 中新增测试：mock KnowledgeMap 含 2 个 KP，验证 `format_dry_run_plan()` 输出含 `Would create (est.):` 和对应 description/type_hint；mock 空 KnowledgeMap，验证输出含 `~0 knowledge point(s)`
- [X] T020 [P] [US5] 在 `kb/tests/test_skill_cli.py` 或 `kb/tests/test_integration.py` 中新增测试：验证 `holmes import --dir /nonexistent/path/` 退出码为 1，stderr 含 `Directory does not exist`

**Checkpoint**: T019/T020 通过，quickstart Scenario 7（dry-run 输出）和 Scenario 8（--dir exit 1）手动验证。

---

## Final Phase: Polish & 验证

- [X] T021 在 `021-fix-skill-script-content-filter` 分支上运行 `cd kb && python -m pytest tests/ -q`，确认通过数 ≥ 656（基线），所有新增测试通过（680 passed）
- [X] T022 [P] 验证 quickstart.md 中 Scenario 1（bash -n run.sh）和 Scenario 5（--force warning）手动场景正常

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，立即开始
- **US1–US5 (Phase 3–7)**: 均依赖 T001 完成（langdetect 安装）；US1–US5 彼此独立，可并行
- **Polish (Final)**: 依赖所有 US 完成

### User Story Dependencies

- US1、US2、US3、US4、US5 相互独立，无跨 story 依赖
- US4 无代码改动，仅写测试，最轻量

### Within Each User Story

- 实现任务先于对应测试任务（需要有实现才能写有意义的测试）
- 同一 story 内标 [P] 的任务可并行

---

## Parallel Opportunities

```bash
# US1 测试并行:
T004: test_extractor_phase.py  ← 并行
T005: test_skill_manager.py    ← 并行

# US2 测试并行:
T008: test_classifier.py       ← 并行
T009: test_pipeline.py         ← 并行

# US4 全部并行（测试独立文件不同 case）:
T014 + T015 + T016: test_skill_advisor.py ← 并行（不同 test case）

# US5 测试并行:
T019: test dry-run output      ← 并行
T020: test --dir exit code     ← 并行
```

---

## Implementation Strategy

### MVP First (US1 Only — QA-18 修复)

1. T001: 安装 langdetect
2. T002–T003: 修复 Extractor prompt + SKILL.md Parameters
3. T004–T005: 补充测试
4. T021: 验证基线通过
5. **STOP and VALIDATE**: Skill run.sh 可执行性问题修复，可交付

### Incremental Delivery

1. T001 → US1 (T002–T005) → MVP
2. 加 US2 (T006–T009) → 知识价值判断修复
3. 加 US3 (T010–T013) → 多语言通用化
4. 加 US4 (T014–T016) → 测试覆盖补充
5. 加 US5 (T017–T020) → CLI 体验改善
6. T021–T022: 全量验证

---

## Notes

- 所有新增测试必须不依赖真实 LLM（使用 mock/stub）
- US4 无任何代码改动，仅补充测试；如已有相关测试，验证后跳过
- `langdetect` 不可用时 fallback 链必须完整（T010 实现时验证）
- `--force` flag 在 pipeline.py 中已有 `self.force` 字段，T007 只需在 non_kb 判断处添加检查
