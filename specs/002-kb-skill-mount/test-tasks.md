# Test Tasks: KB Skill Mounting

**Input**: `specs/002-kb-skill-mount/test-plan.md`

**覆盖范围**: 数据建模 · CLI 链路 · 执行层 · TS 工具链 · Agent E2E · 沉淀链路 · 向后兼容 · 边界条件

## Format: `[ID] [P?] [Group] Description`

- **[P]**: 可与同阶段其他任务并行（不同文件/无依赖）
- **[Group]**: 所属测试组
- Exact file paths included in all descriptions

---

## Phase 1: 测试基础设施

**Purpose**: 建立测试夹具（fixtures）和工具函数，为所有测试组提供公共基础

- [X] TT001 在 `/home/wangzhi/project/projectTmp/holmes/holmes/kb/tests/` 创建 `conftest.py`，提供 `kb_root` fixture（`tmp_path` 下的 KB 目录）、`make_entry(kb_root, entry_id)` 辅助函数（生成最小合法 pitfall 条目）、`make_skill_with_script(kb_root, name, script)` 辅助函数
- [X] TT002 [P] 在 `conftest.py` 中补充 `run_sh_echo(name, message)` fixture（生成只 echo 固定文本的 run.sh）、`run_sh_env(name, var)` fixture（echo 指定环境变量值），用于 T-RUN 参数注入类测试
- [X] TT003 [P] 在 `conftest.py` 中补充 `skill_with_prereqs(kb_root, name, prereq)` fixture 和 `skill_with_required_param(kb_root, name, param_name)` fixture，供 T-RUN-008~011 使用

---

## Phase 2: 数据建模层测试 (T-DM-*)

**Purpose**: 验证所有实体的结构约束、字段类型、边界值

**⚠️ 依赖 Phase 1 fixtures**

- [X] TT004 [DM] 在 `/home/wangzhi/project/projectTmp/holmes/holmes/kb/tests/test_skill_data_model.py` 中实现 **T-DM-001**：验证 `create_skill` 生成的目录结构（SKILL.md 存在、scripts/ 存在、run.sh 存在且 chmod +x）
- [X] TT005 [P] [DM] 同文件实现 **T-DM-002**：验证 SKILL.md frontmatter 包含 name/description/version/platforms/timeout 所有字段，version 格式为 `x.y.z`
- [X] TT006 [P] [DM] 同文件实现 **T-DM-003**：构造含 params 的 SKILL.md，验证 `parse_skill_md` 正确解析 SkillParam.name/required/default（含 required=true 时 default 为空字符串）
- [X] TT007 [P] [DM] 同文件实现 **T-DM-004**：两种 prerequisites 格式（字符串列表 vs dict.commands）均能正确解析为同一结构；空 prerequisites 解析为 `[]`
- [X] TT008 [DM] 同文件实现 **T-DM-005**：schema.py `validate_entry` 对 skill_refs 的 5 个验证路径（合法值/非 list/含大写下划线/含路径分隔符/字段缺失）；在 `/home/wangzhi/project/projectTmp/holmes/holmes/kb/tests/test_schema.py` 中追加相关 case
- [X] TT009 [P] [DM] 同文件实现 **T-DM-006**：`validate_skill_name` 全量边界值（8 个有效 + 8 个无效，每个无效 case 验证 ValueError message 含关键词）
- [X] TT010 [P] [DM] 同文件实现 **T-DM-007**：`run_skill` 返回值所有字段类型检查（skill/exit_code/stdout/stderr/duration_ms/truncated 均已填充且类型正确）
- [X] TT011 [P] [DM] 同文件实现 **T-DM-008**：link_skill 两次后 skill_refs.count("check-redis") == 1（去重约束）

**Checkpoint**: 数据模型所有约束已有对应测试覆盖

---

## Phase 3: CLI 命令层测试 (T-CLI-*)

**Purpose**: 通过 Click Test Runner 或 subprocess 验证所有子命令的输入/输出/退出码

**⚠️ 依赖 Phase 1 fixtures；部分 case 依赖 Phase 2 通过（schema 已知正确）**

- [X] TT012 [CLI] 在 `/home/wangzhi/project/projectTmp/holmes/holmes/kb/tests/test_skill_cli.py` 中实现 **T-CLI-001~004**（`skill create` 正常/--platform/重复报错/非法名称），使用 `click.testing.CliRunner` 调用
- [X] TT013 [P] [CLI] 同文件实现 **T-CLI-005~008**（`skill link` 正常/幂等/条目不存在/skill 不存在报错，验证 stderr 含建议命令）
- [X] TT014 [P] [CLI] 同文件实现 **T-CLI-009~011**（`skill unlink` 正常/幂等/多 skill 只解除一个）
- [X] TT015 [CLI] 同文件实现 **T-CLI-012~013**（`kb show` 显示 skill 信息区块 + 悬空引用打印 Warning），需 patch `frontmatter.loads` 或构造真实文件
- [X] TT016 [P] [CLI] 同文件实现 **T-CLI-014~016**（`skill list` 全量表格/JSON 输出字段完整性/按 entry-id 过滤）
- [X] TT017 [P] [CLI] 同文件实现 **T-CLI-017~019**（`skill read` 默认输出/JSON 字段/skill 不存在 JSON 报错）
- [X] TT018 [CLI] 同文件实现 **T-CLI-020~025**（`skill run` 正常/JSON 完整性/多参数/非零退出码透传/not found/no run.sh），验证 JSON 模式下退出码不二次转换
- [X] TT019 [P] [CLI] 同文件实现 **T-CLI-026~027**（`detect-commands` JSON 输出/`auto-create` placeholder 展开）

**Checkpoint**: 所有 CLI 子命令正常/错误/边界路径均有测试覆盖

---

## Phase 4: 执行层测试 (T-RUN-*)

**Purpose**: 验证 runner.py 的 subprocess 行为、参数注入约定、超时/截断/日志

**⚠️ 依赖 Phase 1 fixtures；建议独立测试文件（已有 test_skill_runner.py，本 phase 为补充）**

- [X] TT020 [RUN] 在 `test_skill_runner.py` 中补充 **T-RUN-001~002**：参数名含连字符时转换为下划线（`my-host` → `SKILL_PARAM_MY_HOST`），脚本能正确读取
- [X] TT021 [P] [RUN] 补充 **T-RUN-004~005**：SKILL.md `timeout` 字段覆盖默认 30s（写 timeout:2 的 SKILL.md + sleep 5 的 run.sh，期望超时）；`timeout_override` 反向覆盖 SKILL.md 的 timeout（写 timeout:2 但 override=10，期望成功）
- [X] TT022 [P] [RUN] 补充 **T-RUN-010**：prerequisites 字符串含空格时取第一 token 检查（如 `"redis-cli -h host"` 应检查 `redis-cli` 是否存在）
- [X] TT023 [P] [RUN] 补充 **T-RUN-012**：run.sh 用 `pwd` 验证 cwd == skill_dir（确认 subprocess cwd 参数正确传递）
- [X] TT024 [RUN] 补充 **T-RUN-013**：结构化日志完整性（caplog 捕获 INFO，验证含 skill_run/skill=/exit_code=/duration_ms=/truncated= 字段，**不含**参数值本身）
- [X] TT025 [P] [RUN] 补充 **T-RUN-014**：stdout 和 stderr 独立捕获（`echo err >&2; echo out`，验证 stdout/stderr 分离正确）
- [X] TT026 [P] [RUN] 补充 **T-RUN-005**（10KB 精确截断）：生成 10241 字节输出，验证 `len(result.stdout.encode()) == 10240` 且 `truncated == True`

**Checkpoint**: runner.py 所有执行路径、参数约定、日志格式均有测试

---

## Phase 5: TypeScript 工具链测试 (T-TS-*)

**Purpose**: 验证 KbReadSkill / KbRunSkill 的属性声明、参数拼装、错误处理

**⚠️ 需在 `/home/wangzhi/project/claude-code/` 工程下添加测试；依赖 bun test 基础设施**

- [X] TT027 [TS] 在 `/home/wangzhi/project/claude-code/src/tools/kb/__tests__/KbSkillTools.test.ts` 中实现 **T-TS-001~002**：验证 KbReadSkill 和 KbRunSkill 的 `name/alwaysLoad/isReadOnly()/isConcurrencySafe()` 属性，以及 inputSchema 中各字段存在性（用 zod `safeParse` 验证）
- [X] TT028 [P] [TS] 同文件实现 **T-TS-004**：`HOLMES_KB_PATH` 未设置时，KbReadSkill/KbRunSkill 均返回含 `"HOLMES_KB_PATH not set"` 的错误 JSON（mock process.env）
- [X] TT029 [P] [TS] 同文件实现 **T-TS-005~007**：用 mock 替换 `execFileAsync`，验证 KbRunSkill 正确拼装 `--param k=v` 参数对（含多对）、`--timeout N`、无 params 时不添加 `--param`
- [X] TT030 [P] [TS] 同文件实现 **T-TS-008**：`import { KbReadSkill, KbRunSkill } from '../index.js'` 均可解析，且现有工具（KbReadEntry/KbSearch 等）的导出未受影响

**Checkpoint**: TS 工具层属性和参数拼装逻辑有单元测试覆盖，构建前可验证

---

## Phase 6: 向后兼容性测试 (T-COMPAT-*)

**Purpose**: 确保新增字段不破坏现有条目格式和测试

- [X] TT031 [COMPAT] 在 `/home/wangzhi/project/projectTmp/holmes/holmes/kb/tests/test_schema.py` 中补充 **T-COMPAT-001**：不含 skill_refs 的完整合法条目 `validate_entry` 返回 `valid=True, errors=[]`
- [X] TT032 [P] [COMPAT] 用 CliRunner 实现 **T-COMPAT-002**：对旧条目（无 skill_refs）执行 `kb show`，验证输出不含 "── Skills ──" 分隔行，exit 0，无 Warning
- [X] TT033 [P] [COMPAT] 实现 **T-COMPAT-003**：`kb list` 混合新旧条目时全部正常列出，格式与无 skill_refs 版本一致
- [X] TT034 [COMPAT] 执行现有全量 pytest 回归套件，验证 **T-COMPAT-004**：`test_schema.py / test_store.py / test_validator.py / test_integration.py` 全部通过（无新增失败）；在 CI 中作为门控步骤

**Checkpoint**: 现有功能零回归

---

## Phase 7: 边界条件测试 (T-EDGE-*)

**Purpose**: 覆盖异常输入、文件系统缺失、并发、安全约束等场景

- [X] TT035 [EDGE] 在 `/home/wangzhi/project/projectTmp/holmes/holmes/kb/tests/test_skill_edge.py` 中实现 **T-EDGE-001~003**（skills/ 不存在返回空/多条目引用同一 skill/SKILL.md 缺失时 list 跳过该目录）
- [X] TT036 [P] [EDGE] 同文件实现 **T-EDGE-004**：skill 名称边界值（3 字符最短合法/64 字符最长合法/65 字符失败/大写失败/下划线失败/空格失败）共 6 个 case
- [X] TT037 [P] [EDGE] 同文件实现 **T-EDGE-005**：精确截断 case（生成 10241 字节 → stdout 恰好为 10240 字节，truncated=True）
- [X] TT038 [P] [EDGE] 同文件实现 **T-EDGE-006**：空 params dict 时脚本内无多余 `SKILL_PARAM_*` 环境变量（用 `printenv | grep SKILL_PARAM` 验证无输出）
- [X] TT039 [P] [EDGE] 同文件实现 **T-EDGE-007**：`--param invalid-no-equals` 时 exit code == 2，stderr 含 "KEY=VALUE"
- [X] TT040 [EDGE] 同文件实现 **T-EDGE-008**：路径遍历防御——`validate_skill_name("../../../etc/passwd")` 抛 ValueError；skill_refs 含路径分隔符时 validate_entry 返回 valid=False
- [X] TT041 [P] [EDGE] 同文件实现 **T-EDGE-009**：run.sh 无可执行权限（chmod 0o644）时仍可通过 `bash run.sh` 执行，exit_code 正常
- [X] TT042 [P] [EDGE] 同文件实现 **T-EDGE-010**：并发 link_skill（3 线程同时执行），结果 skill_refs 中无重复项

**Checkpoint**: 所有边界和异常路径有测试保护，无安全漏洞

---

## Phase 8: 沉淀链路测试 (T-SED-*)

**Purpose**: 验证 KbExtractAndSave 命令检测逻辑及 auto_create_skill 的完整性

- [X] TT043 [SED] 在 `test_skill_manager.py` 中补充 **T-SED-003~004**：`detect_commands` 命令模式覆盖（`$` 前缀/反引号/已知工具名多种格式）；纯文字无误报
- [X] TT044 [P] [SED] 补充 **T-SED-005**：`auto_create_skill` 含 `{host}` `{port}` placeholder 时，run.sh 中出现 `${SKILL_PARAM_HOST}` 和 `${SKILL_PARAM_PORT}`
- [X] TT045 [SED] 在 `/home/wangzhi/project/claude-code/src/tools/kb/__tests__/KbExtractAndSave.test.ts` 中实现 **T-SED-001~002**：mock `execFileAsync`，验证有命令的 resolution 返回含 "[KB Skill Detection]" 的 data；无命令的 resolution 不含该标记，且 pending_id 正常返回
- [X] TT046 [P] [SED] 同文件实现 **T-SED-006**：detect-commands 调用失败时（mock 抛异常），KbExtractAndSave 仍返回正常 pending_id，不抛出异常

**Checkpoint**: 沉淀链路命令检测和 auto-create 逻辑有完整覆盖

---

## Phase 9: 性能与可观测性测试 (T-PERF-*)

**Purpose**: 验证关键路径耗时和结构化日志格式

- [X] TT047 [PERF] 在 `test_skill_runner.py` 中补充 **T-PERF-002**：sleep 0.1 的 skill，验证 duration_ms 在 [100, 500) 区间（无异常开销）
- [X] TT048 [P] [PERF] 补充 **T-PERF-003**（日志字段安全性）：run_skill 传入含敏感值的 params（如 `{"password": "secret123"}`），caplog 日志中**不含** "secret123"，仅含参数键名列表

---

## Phase 10: Setup 集成测试与已知缺口修复 (T-SETUP-*)

**Purpose**: 修复已知缺口并补充对应测试

- [X] TT049 [SETUP] 修复 `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/cli.py` 中 `setup_cmd` 的 `kb_tools` 列表，追加 `"KbReadSkill"` 和 `"KbRunSkill"`
- [X] TT050 [P] [SETUP] 在 `test_skill_cli.py` 中实现 **T-SETUP-001**：用 CliRunner 模拟 `holmes setup --kb-path /tmp/x --model gpt-4o`，验证写出的 settings.json 的 `permissions.allow` 包含 `"KbReadSkill"` 和 `"KbRunSkill"`

**Checkpoint**: setup 命令新用户流程完整

---

## Phase 11: 冒烟测试脚本 + CI 集成

**Purpose**: 创建可在 CI 中运行的端到端冒烟测试，作为合并门控

- [X] TT051 在 `/home/wangzhi/project/projectTmp/holmes/holmes/kb/tests/smoke_test.sh` 中编写冒烟测试脚本，覆盖 quickstart.md 全部 4 个场景（skill create → link → show → run → unlink → list → detect-commands），脚本最后清理临时 KB 目录
- [X] TT052 [P] 在 `/home/wangzhi/project/projectTmp/holmes/holmes/kb/pyproject.toml` 中（或 Makefile）添加 `test-smoke` target，执行 `smoke_test.sh`，可与 `pytest` 并列作为 CI step
- [X] TT053 [P] 在 `/home/wangzhi/project/claude-code/` 中确认 `bun test` 可发现 `__tests__/KbSkillTools.test.ts` 并运行（验证测试文件放置路径符合 bun test 扫描规则）

---

## Dependencies & Execution Order

### Phase 依赖关系

- **Phase 1 (基础设施)**: 无依赖，最先执行
- **Phase 2 (数据建模)**: 依赖 Phase 1 fixtures
- **Phase 3 (CLI)**: 依赖 Phase 1 fixtures；建议 Phase 2 通过后执行
- **Phase 4 (执行层)**: 依赖 Phase 1 fixtures；可与 Phase 3 并行
- **Phase 5 (TypeScript)**: 独立，可与 Phase 2-4 并行
- **Phase 6 (向后兼容)**: 依赖 Phase 2（schema 测试基础）
- **Phase 7 (边界条件)**: 依赖 Phase 1 fixtures
- **Phase 8 (沉淀链路)**: 依赖 Phase 1；Python 部分可与 Phase 3 并行
- **Phase 9 (性能)**: 依赖 Phase 4 已通过
- **Phase 10 (Setup 修复)**: 独立；TT050 依赖 TT049 修复完成
- **Phase 11 (冒烟)**: 依赖 Phase 3/4/8 全部通过

### 并行机会

```
Phase 2 [TT004-TT011] 内部全部可并行（同一文件不同 case）
Phase 3 [TT012-TT019] 按子命令分组，TT013/TT014/TT016/TT017/TT019 可并行
Phase 4 [TT020-TT026] 除 TT024（caplog 需串行） 其余可并行
Phase 5 [TT027-TT030] 全部可并行
Phase 7 [TT035-TT042] 除 TT040（安全测试独立文件）其余可并行
Phase 9/10/11 互相独立，可并行启动
```

---

## 实现策略

### 最小可运行集 (MVP)

先完成以下 tasks，即可运行完整 pytest 套件：

1. TT001（fixtures）
2. TT004-TT011（数据建模）
3. TT012-TT018（CLI）
4. TT031-TT034（向后兼容回归）
5. TT043-TT044（沉淀链路 Python 部分）

### 完整交付

在 MVP 基础上补充：TT027-TT030（TS）+ TT035-TT042（边界）+ TT045-TT046（TS 沉淀）+ TT049-TT053（Setup + 冒烟）

---

## 文件分布汇总

| 文件路径 | 包含测试 |
|----------|----------|
| `kb/tests/conftest.py` | TT001-TT003（共享 fixtures） |
| `kb/tests/test_skill_data_model.py` | TT004-TT011（T-DM-*） |
| `kb/tests/test_skill_cli.py` | TT012-TT019（T-CLI-*）+ TT050（T-SETUP） |
| `kb/tests/test_skill_runner.py` | TT020-TT026（T-RUN 补充）+ TT047-TT048（T-PERF） |
| `kb/tests/test_skill_edge.py` | TT035-TT042（T-EDGE-*） |
| `kb/tests/test_skill_sediment.py` | TT043-TT044（T-SED Python 部分） |
| `kb/tests/test_schema.py` | TT008（T-DM-005 追加）+ TT031（T-COMPAT-001 追加） |
| `kb/tests/smoke_test.sh` | TT051（冒烟脚本） |
| `claude-code/src/tools/kb/__tests__/KbSkillTools.test.ts` | TT027-TT030（T-TS-*） |
| `claude-code/src/tools/kb/__tests__/KbExtractAndSave.test.ts` | TT045-TT046（T-SED TS 部分） |
| `kb/holmes/cli.py`（修复） | TT049（T-SETUP-001 修复） |

---

## 任务统计

| Phase | 任务数 | 可并行 | 类型 |
|-------|--------|--------|------|
| Phase 1（基础设施） | 3 | 2/3 | 新建 |
| Phase 2（数据建模） | 8 | 7/8 | 新建 |
| Phase 3（CLI） | 8 | 5/8 | 新建 |
| Phase 4（执行层补充） | 7 | 5/7 | 补充 |
| Phase 5（TypeScript） | 4 | 3/4 | 新建 |
| Phase 6（向后兼容） | 4 | 2/4 | 新建+执行 |
| Phase 7（边界条件） | 8 | 7/8 | 新建 |
| Phase 8（沉淀链路） | 4 | 2/4 | 新建+补充 |
| Phase 9（性能） | 2 | 1/2 | 补充 |
| Phase 10（Setup 修复） | 2 | 1/2 | 修复+新建 |
| Phase 11（冒烟+CI） | 3 | 2/3 | 新建 |
| **合计** | **53** | **37/53** | |
