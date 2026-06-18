# 测试计划：KB Skill Mounting

**Feature**: `002-kb-skill-mount`
**Date**: 2026-05-29
**覆盖范围**: 数据建模 · CLI 链路 · Agent 工具链 · 集成场景 · 边界条件 · 向后兼容

---

## 测试范围概览

| 层次 | 测试类型 | 覆盖重点 |
|------|----------|----------|
| 数据层 | 单元测试 | SKILL.md frontmatter 合法性、skill_refs 字段约束 |
| CLI 层 | 单元 + 集成 | 6 个子命令的输入/输出/错误路径 |
| 执行层 | 单元测试 | subprocess 执行、参数注入、超时、截断、先决条件 |
| 工具链 | 集成测试 | KbReadSkill / KbRunSkill TypeScript 工具 |
| Agent 链路 | E2E 测试 | KbReadEntry → KbReadSkill → KbRunSkill 完整调用流 |
| 沉淀链路 | E2E 测试 | KbExtractAndSave 命令检测 + Skill 提议 |
| 向后兼容 | 回归测试 | 旧条目解析、schema 验证不受影响 |
| 边界条件 | 专项测试 | 悬空引用、并发引用、特殊字符、超长输出 |

---

## 第一部分：数据建模层测试

### T-DM-001 SkillDefinition 目录结构

**目标**: 验证 `create_skill` 生成的文件系统结构符合 data-model.md 规范

```
前置: 空 kb_root
操作: holmes kb skill create check-redis --desc "检查 Redis 连接数"
验证:
  ✓ $KB/skills/check-redis/ 目录存在
  ✓ $KB/skills/check-redis/SKILL.md 存在
  ✓ $KB/skills/check-redis/scripts/ 目录存在
  ✓ $KB/skills/check-redis/scripts/run.sh 存在且有执行权限 (chmod +x)
  ✓ 目录名 == SKILL.md frontmatter 中的 name 字段
```

### T-DM-002 SKILL.md frontmatter 字段完整性

**目标**: 验证生成的 SKILL.md 包含所有必填字段

```
操作: 读取新建 Skill 的 SKILL.md
验证 frontmatter 包含:
  ✓ name: string（与目录名一致）
  ✓ description: string（非空）
  ✓ version: "1.0.0"（语义化版本格式 x.y.z）
  ✓ platforms: 非空（默认 "linux,macos"）
  ✓ timeout: 存在（默认 30 或可选）
```

### T-DM-003 SkillParam 结构验证

**目标**: 验证含参数声明的 SKILL.md 能被正确解析

```python
# 构造带 params 的 SKILL.md
content = """
---
name: check-redis
description: test
version: 1.0.0
platforms: linux,macos
params:
  - name: host
    description: Redis host
    required: false
    default: "127.0.0.1"
  - name: port
    description: Redis port
    required: true
---
body
"""
验证:
  ✓ parse_skill_md() 返回 SkillDefinition.params 长度 == 2
  ✓ params[0].name == "host"
  ✓ params[0].required == False
  ✓ params[0].default == "127.0.0.1"
  ✓ params[1].name == "port"
  ✓ params[1].required == True
  ✓ params[1].default == ""（未声明时为空字符串）
```

### T-DM-004 prerequisites 格式解析

**目标**: 验证两种 prerequisites 格式都能被正确解析

```python
# 格式 1: 字符串列表
prerequisites:
  - redis-cli
  - netstat

# 格式 2: dict with commands key
prerequisites:
  commands: [redis-cli]

验证:
  ✓ 两种格式均解析为 SkillDefinition.prerequisites == ["redis-cli"]
  ✓ 空 prerequisites 解析为 []（不报错）
```

### T-DM-005 KbEntry skill_refs 字段约束

**目标**: 验证 schema.py 对 skill_refs 的校验逻辑

```python
# Case 1: 合法值
skill_refs: [check-redis, reload-nginx]  →  validate_entry() → valid=True

# Case 2: 非 list 类型
skill_refs: "check-redis"  →  valid=False，error 含 "must be a list"

# Case 3: 含非法字符的条目
skill_refs: [Check_Redis]  →  valid=False，error 含 "Invalid skill_refs entry"

# Case 4: 含路径分隔符
skill_refs: [skills/check-redis]  →  valid=False

# Case 5: 无 skill_refs 字段
（字段缺失）  →  valid=True（向后兼容）
```

### T-DM-006 skill_name 命名规则验证

**目标**: validate_skill_name 的边界值

```python
有效名称（应 PASS）:
  "abc"              # 最短 3 字符
  "check-redis"      # 标准 kebab-case
  "my-tool-v2"       # 含数字
  "a" * 64           # 最长 64 字符（如 "a" * 62 + "-b"）

无效名称（应 FAIL + ValueError）:
  "ab"               # 少于 3 字符
  "a" * 65           # 超过 64 字符
  "Check"            # 含大写
  "check_redis"      # 含下划线
  "-check"           # 以连字符开头
  "check-"           # 以连字符结尾
  "check redis"      # 含空格
  ""                 # 空字符串
```

### T-DM-007 SkillExecution 数据结构完整性

**目标**: run_skill 返回 SkillExecution 所有字段均已填充

```python
result = run_skill(kb_root, "my-skill", {"host": "127.0.0.1"})
验证:
  ✓ result.skill == "my-skill"
  ✓ type(result.exit_code) == int
  ✓ type(result.stdout) == str
  ✓ type(result.stderr) == str
  ✓ type(result.duration_ms) == int
  ✓ result.duration_ms > 0
  ✓ type(result.truncated) == bool
```

### T-DM-008 skill_refs 去重约束

**目标**: 同一 skill 不能在 skill_refs 中出现两次

```python
link_skill(kb_root, "PT-DB-001", "check-redis")
link_skill(kb_root, "PT-DB-001", "check-redis")  # 第二次，幂等
post = frontmatter.load(entry_path)
验证:
  ✓ post.metadata["skill_refs"].count("check-redis") == 1
```

---

## 第二部分：CLI 命令层测试

### T-CLI-001 `skill create` 正常流程

```bash
holmes --kb-path $KB kb skill create check-redis --desc "检查 Redis 连接数"
验证:
  ✓ exit code == 0
  ✓ stdout 含 "✓ Skill created: skills/check-redis/"
  ✓ stdout 含使用提示（Edit SKILL.md / Write scripts/run.sh / Link to an entry）
  ✓ 文件系统: skills/check-redis/SKILL.md 存在
  ✓ 文件系统: skills/check-redis/scripts/run.sh 存在
```

### T-CLI-002 `skill create` 自定义 platform

```bash
holmes --kb-path $KB kb skill create my-skill --desc "test" --platform linux
验证:
  ✓ SKILL.md frontmatter platforms == "linux"（不含 macos）
```

### T-CLI-003 `skill create` 重复创建报错

```bash
holmes --kb-path $KB kb skill create check-redis --desc "first"
holmes --kb-path $KB kb skill create check-redis --desc "second"
验证:
  ✓ 第二次 exit code == 1
  ✓ stderr 含 "already exists"
  ✓ 原始 SKILL.md 未被覆盖（description 仍为 "first"）
```

### T-CLI-004 `skill create` 非法名称报错

```bash
holmes --kb-path $KB kb skill create Check_Redis --desc "test"
验证:
  ✓ exit code == 1
  ✓ stderr 含 "Error:"
  ✓ skills/ 目录未被创建
```

### T-CLI-005 `skill link` 正常挂载

```bash
# 前提: PT-DB-001 已存在，check-redis 已创建
holmes --kb-path $KB kb skill link PT-DB-001 check-redis
验证:
  ✓ exit code == 0
  ✓ stdout == "✓ Linked skill 'check-redis' to PT-DB-001."
  ✓ PT-DB-001.md frontmatter skill_refs 包含 "check-redis"
  ✓ PT-DB-001.md 其他字段（title/type/maturity 等）未改变
  ✓ updated_at 已更新
```

### T-CLI-006 `skill link` 幂等性

```bash
holmes --kb-path $KB kb skill link PT-DB-001 check-redis
holmes --kb-path $KB kb skill link PT-DB-001 check-redis  # 重复
验证:
  ✓ 两次均 exit code == 0
  ✓ skill_refs 中 check-redis 只出现一次
```

### T-CLI-007 `skill link` 条目不存在报错

```bash
holmes --kb-path $KB kb skill link NONEXISTENT check-redis
验证:
  ✓ exit code == 1
  ✓ stderr 含 "Entry 'NONEXISTENT' not found"
```

### T-CLI-008 `skill link` skill 不存在报错

```bash
holmes --kb-path $KB kb skill link PT-DB-001 nonexistent-skill
验证:
  ✓ exit code == 1
  ✓ stderr 含 "Skill 'nonexistent-skill' not found"
  ✓ stderr 含 "holmes kb skill create" 建议
```

### T-CLI-009 `skill unlink` 正常解除挂载

```bash
# 前提: PT-DB-001 已挂载 check-redis
holmes --kb-path $KB kb skill unlink PT-DB-001 check-redis
验证:
  ✓ exit code == 0
  ✓ stdout 含 "✓ Unlinked skill 'check-redis' from PT-DB-001."
  ✓ PT-DB-001.md frontmatter skill_refs 不含 "check-redis"
  ✓ skills/check-redis/ 目录仍存在（不删除 skill 文件夹）
```

### T-CLI-010 `skill unlink` 幂等性（未挂载时）

```bash
holmes --kb-path $KB kb skill unlink PT-DB-001 never-linked
验证:
  ✓ exit code == 0（幂等）
  ✓ stdout 含 "was not linked"
```

### T-CLI-011 `skill unlink` 多个 skill 解除一个

```bash
# 前提: PT-DB-001 挂载了 [check-redis, reload-nginx]
holmes --kb-path $KB kb skill unlink PT-DB-001 check-redis
验证:
  ✓ skill_refs == ["reload-nginx"]（另一个保留）
```

### T-CLI-012 `kb show` 显示 skill 信息

```bash
holmes --kb-path $KB kb show PT-DB-001
验证:
  ✓ 输出含 YAML frontmatter（包含 skill_refs）
  ✓ 输出含 "── Skills ──" 分隔行
  ✓ 输出含 "check-redis [可执行] @ skills/check-redis/"
```

### T-CLI-013 `kb show` 悬空引用警告

```bash
# 前提: PT-DB-001.md frontmatter 含 skill_refs: [deleted-skill]，但目录不存在
holmes --kb-path $KB kb show PT-DB-001
验证:
  ✓ exit code == 0（不中断）
  ✓ 输出含 "Warning: skill 'deleted-skill' not found in skills/"
```

### T-CLI-014 `skill list` 全量列出

```bash
holmes --kb-path $KB kb skill list
验证:
  ✓ 每行含 NAME / DESCRIPTION / REFS 三列
  ✓ 含 check-redis 行
  ✓ REFS 列显示引用该 skill 的条目 ID（如 PT-DB-001）
  ✓ 无 skills/ 目录时：输出 "No skills found."（不报错，exit 0）
```

### T-CLI-015 `skill list` JSON 输出

```bash
holmes --kb-path $KB kb skill list --json
验证（JSON 数组）:
  ✓ 每项含 name / description / version / platforms / linked_entries
  ✓ linked_entries 为数组（即使为空也是 []）
  ✓ 合法 JSON（可被 jq 解析）
```

### T-CLI-016 `skill list` 按条目过滤

```bash
holmes --kb-path $KB kb skill list PT-DB-001
验证:
  ✓ 只返回 PT-DB-001 挂载的 skill
  ✓ 未挂载到该条目的 skill 不出现
```

### T-CLI-017 `skill read` 默认输出

```bash
holmes --kb-path $KB kb skill read check-redis
验证:
  ✓ exit code == 0
  ✓ 输出即 SKILL.md 原始内容
  ✓ 含 frontmatter "---" 分隔符
```

### T-CLI-018 `skill read` JSON 输出

```bash
holmes --kb-path $KB kb skill read check-redis --json
验证（JSON 对象）:
  ✓ name == "check-redis"
  ✓ content 非空（包含完整 SKILL.md 文本）
  ✓ scripts_path == "skills/check-redis/scripts/run.sh"
  ✓ has_run_script == true
```

### T-CLI-019 `skill read` skill 不存在时 JSON 报错

```bash
holmes --kb-path $KB kb skill read nonexistent --json
验证:
  ✓ exit code == 1
  ✓ stdout == {"error": "Skill 'nonexistent' not found."}
```

### T-CLI-020 `skill run` 正常执行

```bash
# run.sh 内容: echo "hello $SKILL_PARAM_NAME"
holmes --kb-path $KB kb skill run my-skill --param name=world
验证:
  ✓ exit code == 0
  ✓ stdout 含 "hello world"
```

### T-CLI-021 `skill run` JSON 输出完整性

```bash
holmes --kb-path $KB kb skill run check-redis --json
验证（JSON 对象）:
  ✓ skill == "check-redis"
  ✓ exit_code == 0
  ✓ stdout 为字符串（非空）
  ✓ stderr 为字符串
  ✓ duration_ms > 0
  ✓ truncated == false（正常输出）
```

### T-CLI-022 `skill run` 多参数传递

```bash
holmes --kb-path $KB kb skill run check-redis \
  --param host=192.168.1.100 --param port=6380
验证:
  ✓ 脚本内 SKILL_PARAM_HOST=192.168.1.100
  ✓ 脚本内 SKILL_PARAM_PORT=6380
```

### T-CLI-023 `skill run` 非零退出码透传

```bash
# run.sh: exit 2
holmes --kb-path $KB kb skill run fail-skill
验证:
  ✓ CLI exit code == 2（透传）
holmes --kb-path $KB kb skill run fail-skill --json
验证:
  ✓ {"exit_code": 2, ...}（JSON 模式不二次转换退出码）
```

### T-CLI-024 `skill run` skill 不存在时 JSON 报错

```bash
holmes --kb-path $KB kb skill run nonexistent --json
验证:
  ✓ exit code == 1
  ✓ stdout == {"error": "Skill 'nonexistent' not found."}
```

### T-CLI-025 `skill run` run.sh 不存在时报错

```bash
# 手动创建 skill 目录但不创建 run.sh
mkdir -p $KB/skills/no-script/scripts && touch $KB/skills/no-script/SKILL.md
holmes --kb-path $KB kb skill run no-script --json
验证:
  ✓ exit code == 1
  ✓ stdout == {"error": "No run.sh in skills/no-script/scripts/."}
```

### T-CLI-026 `skill detect-commands` 隐藏命令

```bash
holmes --kb-path $KB kb skill detect-commands \
  --content "执行 \$ redis-cli info | grep connected 检查" \
  --json
验证:
  ✓ exit code == 0
  ✓ 返回 JSON 数组，含 {"line": "redis-cli info | grep connected 检查", "suggested_name": "redis-cli-info"}
  ✓ suggested_name 符合 [a-z0-9-] 格式
```

### T-CLI-027 `skill auto-create` 含 placeholder 参数

```bash
holmes --kb-path $KB kb skill auto-create \
  --name check-host --cmd "curl -I {host}:{port}" --desc "检查主机"
验证:
  ✓ skills/check-host/scripts/run.sh 存在
  ✓ run.sh 中含 SKILL_PARAM_HOST
  ✓ run.sh 中含 SKILL_PARAM_PORT
```

---

## 第三部分：执行层（runner.py）测试

### T-RUN-001 参数环境变量注入

**目标**: 验证 `SKILL_PARAM_<NAME_UPPER>` 约定

```python
# run.sh: echo "h=$SKILL_PARAM_HOST p=$SKILL_PARAM_PORT_NUM"
result = run_skill(kb_root, "check", {"host": "10.0.0.1", "port_num": "6380"})
验证:
  ✓ "h=10.0.0.1" in result.stdout
  ✓ "p=6380" in result.stdout
  ✓ 环境变量名: SKILL_PARAM_HOST（大写）、SKILL_PARAM_PORT_NUM（下划线分隔）
```

### T-RUN-002 参数名含连字符转换为下划线

```python
# param name "my-host" → 环境变量 SKILL_PARAM_MY_HOST
result = run_skill(kb_root, "skill", {"my-host": "127.0.0.1"})
验证:
  ✓ 脚本可读取 $SKILL_PARAM_MY_HOST
```

### T-RUN-003 执行超时返回 exit_code=-1

```python
# run.sh: sleep 60
result = run_skill(kb_root, "slow", timeout_override=1)
验证:
  ✓ result.exit_code == -1
  ✓ "Timeout" in result.error
  ✓ result.duration_ms < 2000（1s+缓冲内返回）
```

### T-RUN-004 SKILL.md timeout 字段覆盖默认值

```python
# SKILL.md frontmatter: timeout: 5
# run.sh: sleep 10
result = run_skill(kb_root, "skill", timeout_override=None)
验证:
  ✓ result.exit_code == -1（5s 超时触发）
```

### T-RUN-005 timeout_override 覆盖 SKILL.md timeout

```python
# SKILL.md: timeout: 5
# run.sh: sleep 3
result = run_skill(kb_root, "skill", timeout_override=10)
验证:
  ✓ result.exit_code == 0（timeout_override=10 > 3s，不超时）
```

### T-RUN-006 stdout 超 10KB 时截断

```python
# run.sh: python3 -c "print('x' * 12000)"
result = run_skill(kb_root, "big")
验证:
  ✓ result.truncated == True
  ✓ len(result.stdout.encode("utf-8")) <= 10 * 1024
  ✓ result.exit_code == 0（截断不影响退出码）
```

### T-RUN-007 stdout 不足 10KB 时不截断

```python
# run.sh: echo "short"
result = run_skill(kb_root, "short")
验证:
  ✓ result.truncated == False
```

### T-RUN-008 先决条件检查——缺失时 PrerequisiteError

```python
# SKILL.md prerequisites: [definitely-not-a-real-command-xyz]
with pytest.raises(PrerequisiteError, match="definitely-not-a-real-command-xyz"):
    run_skill(kb_root, "skill")
```

### T-RUN-009 先决条件检查——存在时正常执行

```python
# SKILL.md prerequisites: [bash]  （bash 必然存在）
result = run_skill(kb_root, "skill")
验证:
  ✓ 不抛 PrerequisiteError
  ✓ result.exit_code == 0
```

### T-RUN-010 先决条件取命令第一个 token

```python
# prerequisites: ["redis-cli -h host"]  → 检查 "redis-cli" 是否存在
# 若 redis-cli 不存在应报错 "redis-cli" 而非完整字符串
```

### T-RUN-011 必填参数缺失时 MissingParamError

```python
# SKILL.md params: [{name: host, required: true}]
with pytest.raises(MissingParamError, match="host"):
    run_skill(kb_root, "skill", params={})
```

### T-RUN-012 运行目录为 skill_dir（cwd）

```python
# run.sh: pwd（打印当前工作目录）
result = run_skill(kb_root, "cwd-skill")
验证:
  ✓ result.stdout.strip() == str(kb_root / "skills" / "cwd-skill")
```

### T-RUN-013 结构化日志输出

```python
import logging
with caplog.at_level(logging.INFO, logger="holmes.kb.skill.runner"):
    result = run_skill(kb_root, "my-skill", {"host": "127.0.0.1"})

验证 caplog.records:
  ✓ 含一条 INFO 日志
  ✓ 日志含 "skill_run"
  ✓ 日志含 "skill=my-skill"
  ✓ 日志含 f"exit_code={result.exit_code}"
  ✓ 日志含 "duration_ms="
  ✓ 日志含 f"truncated={result.truncated}"
```

### T-RUN-014 stderr 独立捕获

```python
# run.sh: echo "err msg" >&2; echo "out"; exit 1
result = run_skill(kb_root, "err-skill")
验证:
  ✓ result.stdout == "out\n"
  ✓ "err msg" in result.stderr
  ✓ result.exit_code == 1
```

---

## 第四部分：TypeScript 工具链测试

### T-TS-001 KbReadSkill 工具属性

**目标**: 验证工具符合 buildTool 接口规范

```typescript
验证 KbReadSkill 对象属性:
  ✓ KbReadSkill.name == "KbReadSkill"
  ✓ KbReadSkill.alwaysLoad == true（不被 defer）
  ✓ KbReadSkill.isReadOnly() == true
  ✓ KbReadSkill.isConcurrencySafe() == true
  ✓ KbReadSkill.inputSchema 含 skill_name 字段（z.string）
```

### T-TS-002 KbRunSkill 工具属性

```typescript
验证 KbRunSkill 对象属性:
  ✓ KbRunSkill.name == "KbRunSkill"
  ✓ KbRunSkill.alwaysLoad == true
  ✓ KbRunSkill.isReadOnly() == false（有副作用）
  ✓ KbRunSkill.isConcurrencySafe() == false
  ✓ inputSchema 含 skill_name（required）、params（optional record）、timeout（optional number）
```

### T-TS-003 KbReadSkill 调用成功路径

```typescript
// 前提: HOLMES_KB_PATH 已设置，check-redis skill 存在
const result = await KbReadSkill.call({ skill_name: "check-redis" })
验证:
  ✓ result.data 包含 "name: check-redis"
  ✓ result.data 包含 "has_run_script"（JSON 格式）
  ✓ JSON.parse(result.data).has_run_script == true
```

### T-TS-004 KbReadSkill HOLMES_KB_PATH 未设置时报错

```typescript
// 前提: process.env.HOLMES_KB_PATH 未设置
const result = await KbReadSkill.call({ skill_name: "check-redis" })
验证:
  ✓ JSON.parse(result.data).error 含 "HOLMES_KB_PATH not set"
```

### T-TS-005 KbRunSkill 参数传递

```typescript
const result = await KbRunSkill.call({
  skill_name: "check-redis",
  params: { host: "192.168.1.10", port: "6380" }
})
验证（CLI 被调用时的参数）:
  ✓ 调用包含 "--param host=192.168.1.10"
  ✓ 调用包含 "--param port=6380"
  ✓ 调用包含 "--json"
```

### T-TS-006 KbRunSkill timeout 参数

```typescript
const result = await KbRunSkill.call({
  skill_name: "check-redis",
  timeout: 60
})
验证:
  ✓ CLI 调用包含 "--timeout 60"
  ✓ execFileAsync 的 timeout 选项为 (60 + 5) * 1000 = 65000ms
```

### T-TS-007 KbRunSkill 无 params 时不传 --param

```typescript
const result = await KbRunSkill.call({ skill_name: "simple-skill" })
验证:
  ✓ CLI 调用不含 "--param"（params 为 undefined 时）
```

### T-TS-008 index.ts 导出验证

```typescript
import { KbReadSkill, KbRunSkill } from './tools/kb/index.js'
验证:
  ✓ KbReadSkill !== undefined
  ✓ KbRunSkill !== undefined
  ✓ 现有导出（KbReadEntry 等）未被破坏
```

---

## 第五部分：Agent 工具链 E2E 测试

### T-AGENT-001 KbReadEntry → 解析 skill_refs → KbReadSkill 链路

```
前置: PT-DB-001.md frontmatter 含 skill_refs: [check-redis]
操作序列:
  1. KbReadEntry("PT-DB-001")
     ✓ 返回内容含 "skill_refs:\n  - check-redis"
  2. Agent 解析出 skill_refs = ["check-redis"]
  3. KbReadSkill("check-redis")
     ✓ 返回 SKILL.md JSON，含 name/content/has_run_script
  4. Agent 向用户展示 "发现诊断 skill: check-redis，是否执行？"
  5. KbRunSkill("check-redis", {"host": "127.0.0.1", "port": "6379"})
     ✓ 返回 exit_code=0, stdout 非空
```

### T-AGENT-002 KbRunSkill 执行结果纳入推理

```
CLAUDE.md 指令验证:
  ✓ CLAUDE.md 含 "KbReadSkill" 必须调用指引
  ✓ CLAUDE.md 含 "KbRunSkill" 执行后需分析结果指引
  ✓ CLAUDE.md 含 "NEVER ignore skill execution output"
  ✓ settings.json permissions.allow 包含 "KbReadSkill"
  ✓ settings.json permissions.allow 包含 "KbRunSkill"
```

### T-AGENT-003 skill 执行失败不中断排查

```
前置: run.sh 返回 exit_code=1
操作: KbRunSkill("fail-skill", {})
验证:
  ✓ 工具返回 JSON 含 exit_code=1（不抛异常）
  ✓ agent 收到错误输出后继续推理（不终止会话）
```

### T-AGENT-004 多 skill_refs 条目全量读取

```
前置: PT-NET-001 含 skill_refs: [check-nginx, reload-nginx]
验证:
  ✓ KbReadSkill("check-nginx") 成功
  ✓ KbReadSkill("reload-nginx") 成功
  ✓ 两次调用结果不互相干扰
```

---

## 第六部分：沉淀链路（US3）测试

### T-SED-001 KbExtractAndSave 检测命令并返回候选

```typescript
// summary 含 "$ redis-cli info | grep connected"
const result = await KbExtractAndSave.call({ summary: "..." })
验证:
  ✓ result.data 含 "[KB Skill Detection]"
  ✓ result.data 含候选列表（行号/命令）
  ✓ result.data 含建议的 suggested_name
```

### T-SED-002 KbExtractAndSave 无命令时不展示候选

```typescript
// summary 为纯文字描述，无命令行
const result = await KbExtractAndSave.call({ summary: "只是一些文字说明" })
验证:
  ✓ result.data 不含 "[KB Skill Detection]"
  ✓ 仍正常返回 pending_id
```

### T-SED-003 detect_commands 命令模式覆盖

```python
text = """
运行以下命令排查:
$ redis-cli info | grep connected_clients
执行 `nginx -t && nginx -s reload` 重载配置
systemctl status redis 查看服务状态
curl -I http://backend/health 检查上游
"""
candidates = detect_commands(text)
验证:
  ✓ 检测到 redis-cli 相关命令
  ✓ 检测到 nginx 相关命令（backtick 模式）
  ✓ 检测到 systemctl（已知工具前缀）
  ✓ 检测到 curl
  ✓ 无重复项
  ✓ 每个 suggested_name 符合 [a-z0-9-] 格式，长度 3-64
```

### T-SED-004 detect_commands 误报率控制

```python
text = "这个问题很重要，需要仔细分析系统架构。没有任何命令。"
candidates = detect_commands(text)
验证:
  ✓ candidates 为空（纯文字不误报）
```

### T-SED-005 auto_create_skill 含 placeholder

```python
skill_dir = auto_create_skill(kb_root, "check-redis", "redis-cli -h {host}", "检查")
run_sh = (skill_dir / "scripts" / "run.sh").read_text()
验证:
  ✓ run_sh 含 "${SKILL_PARAM_HOST}"（而非原始 {host}）
  ✓ SKILL.md frontmatter 含 name: check-redis
```

### T-SED-006 KbExtractAndSave skill 检测失败不阻塞主流程

```typescript
// 模拟 holmes kb skill detect-commands 返回错误
验证:
  ✓ KbExtractAndSave 仍返回 pending_id（非 null/undefined）
  ✓ 不抛出异常
```

---

## 第七部分：向后兼容性测试

### T-COMPAT-001 旧条目（无 skill_refs）schema 验证通过

```python
content = """
---
id: PT-DB-001
type: pitfall
title: Old entry
maturity: draft
category: database
tags: []
created_at: "2024-01-01T00:00:00+00:00"
updated_at: "2024-01-01T00:00:00+00:00"
---
## Symptoms ...
## Root Cause ...
## Resolution ...
"""
result = validate_entry(content)
验证:
  ✓ result.valid == True
  ✓ result.errors == []
```

### T-COMPAT-002 旧条目 `kb show` 正常显示

```bash
# PT-OLD-001.md 无 skill_refs 字段
holmes --kb-path $KB kb show PT-OLD-001
验证:
  ✓ exit code == 0
  ✓ 输出不含 "── Skills ──" 分隔行
  ✓ 不报错、不报 Warning
```

### T-COMPAT-003 旧条目 `kb list` 正常列出

```bash
holmes --kb-path $KB kb list
验证:
  ✓ 旧条目（无 skill_refs）正常出现在列表中
  ✓ 含 skill_refs 的新条目也正常出现
  ✓ 格式与旧版本一致
```

### T-COMPAT-004 现有 pytest 回归测试全通过

```bash
cd kb/ && python -m pytest tests/ -v
验证:
  ✓ test_schema.py 全通过（新增 skill_refs 验证未破坏旧 schema 测试）
  ✓ test_store.py 全通过
  ✓ test_validator.py 全通过
  ✓ test_integration.py 全通过
```

### T-COMPAT-005 KbReadEntry 返回内容含 skill_refs

```
前提: PT-DB-001.md frontmatter 含 skill_refs: [check-redis]
操作: KbReadEntry("PT-DB-001")
验证:
  ✓ 返回的 Markdown 字符串含 "skill_refs:"
  ✓ 含 "- check-redis"
  ✓ KbReadEntry 代码无需修改（skill_refs 随 frontmatter 自动透传）
```

---

## 第八部分：边界条件与异常场景测试

### T-EDGE-001 skills/ 目录不存在时 `skill list` 返回空

```bash
# 全新 KB 无 skills/ 目录
holmes --kb-path $NEW_KB kb skill list
验证:
  ✓ exit code == 0
  ✓ 输出 "No skills found."（不是 FileNotFoundError）
```

### T-EDGE-002 多条目引用同一 skill

```bash
holmes --kb-path $KB kb skill link PT-DB-001 check-redis
holmes --kb-path $KB kb skill link PT-DB-002 check-redis
holmes --kb-path $KB kb skill list --json
验证:
  ✓ check-redis 条目的 linked_entries 含 ["PT-DB-001", "PT-DB-002"]
```

### T-EDGE-003 skill 目录存在但 SKILL.md 缺失

```bash
mkdir -p $KB/skills/broken-skill/scripts
# 不创建 SKILL.md
holmes --kb-path $KB kb skill read broken-skill --json
验证:
  ✓ 报 "not found" 错误（不 crash）

holmes --kb-path $KB kb skill list
验证:
  ✓ broken-skill 不出现在列表中（list 跳过无 SKILL.md 的目录）
```

### T-EDGE-004 skill 名称边界值

```bash
# 最短合法名
holmes --kb-path $KB kb skill create abc --desc "min"
验证: ✓ 成功

# 最长合法名（64 字符）
NAME=$(python3 -c "print('a' * 32 + '-' + 'b' * 31)")  # 64 chars
holmes --kb-path $KB kb skill create "$NAME" --desc "max"
验证: ✓ 成功

# 65 字符（超限）
NAME=$(python3 -c "print('a' * 65)")
holmes --kb-path $KB kb skill create "$NAME" --desc "too long"
验证: ✓ exit code == 1，含 "3-64" 错误信息
```

### T-EDGE-005 stdout 超大输出截断精度

```python
# 生成 10241 字节（刚好超过 10KB）
result = run_skill(kb_root, "big-skill")
验证:
  ✓ result.truncated == True
  ✓ len(result.stdout.encode("utf-8")) == 10 * 1024（精确截断到 10240 字节）
```

### T-EDGE-006 空 params 字典不注入任何环境变量

```python
# run.sh: printenv | grep SKILL_PARAM || echo "no params"
result = run_skill(kb_root, "skill", params={})
验证:
  ✓ "no params" in result.stdout（无多余环境变量）
```

### T-EDGE-007 `--param` 格式错误时报错

```bash
holmes --kb-path $KB kb skill run check-redis --param invalid-no-equals
验证:
  ✓ exit code == 2
  ✓ stderr 含 "KEY=VALUE"
```

### T-EDGE-008 skill 名称在 skill_refs 中的唯一性（SQL-注入防御）

```python
# 名称中含路径字符
validate_skill_name("../../../etc/passwd")
验证:
  ✓ 抛 ValueError（正则拒绝非 [a-z0-9-] 字符）

# 通过 frontmatter 直接写入非法 skill_refs
skill_refs: ["../../../secret"]
result = validate_entry(content)
验证:
  ✓ result.valid == False
```

### T-EDGE-009 skill 目录权限问题（run.sh 无执行权限）

```python
run_sh.chmod(0o644)  # 移除执行权限
result = run_skill(kb_root, "no-exec-skill")
验证:
  ✓ bash script 仍可执行（bash run.sh 而非 ./run.sh）
  ✓ result.exit_code == 0（或脚本内容决定的正确退出码）
```

### T-EDGE-010 并发 link_skill 幂等性

```python
from concurrent.futures import ThreadPoolExecutor
def link():
    link_skill(kb_root, "PT-DB-001", "check-redis")

with ThreadPoolExecutor(max_workers=3) as ex:
    list(ex.map(lambda _: link(), range(3)))

post = frontmatter.load(str(entry_path))
验证:
  ✓ skill_refs.count("check-redis") == 1（无重复）
```

---

## 第九部分：性能与可观测性测试

### T-PERF-001 KbReadSkill 响应时间 < 3s

```
前提: SKILL.md 约 2KB
操作: KbReadSkill("check-redis")
验证:
  ✓ 端到端耗时 < 3000ms（含 holmes 进程启动 + 文件读取）
```

### T-PERF-002 duration_ms 精度

```python
# run.sh: sleep 0.1（100ms）
result = run_skill(kb_root, "sleep-skill")
验证:
  ✓ result.duration_ms >= 100
  ✓ result.duration_ms < 500（无异常开销）
```

### T-PERF-003 结构化日志字段完整性

```python
# 参照 T-RUN-013，进一步验证所有字段名
验证日志消息格式:
  ✓ 含 "skill_run"（操作标识）
  ✓ 含 "skill=<name>"
  ✓ 含 "params=<list-of-keys>"（仅 key，不暴露 value）
  ✓ 含 "exit_code=<int>"
  ✓ 含 "duration_ms=<int>"
  ✓ 含 "truncated=<bool>"
  ✗ 不含参数值（防止敏感信息泄露到日志）
```

---

## 第十部分：`holmes setup` 集成测试

### T-SETUP-001 setup 命令自动写入新工具权限

```bash
holmes setup --kb-path /tmp/test-kb --model gpt-4o
cat ~/.holmes/settings.json
验证:
  ✓ permissions.allow 含 "KbReadSkill"
  ✓ permissions.allow 含 "KbRunSkill"
```

> **注意**: 当前实现存在缺口（T-SETUP-001 预期失败），需修复 `cli.py` setup_cmd 中的 `kb_tools` 列表。

---

## 第十一部分：快速验证检查清单（冒烟测试）

按 quickstart.md 场景逐步验证，用于 CI 合并门控：

```bash
# 冒烟测试脚本（smoke-test.sh）
set -e
KB=$(mktemp -d)

# 场景 1: 创建并挂载
holmes --kb-path $KB kb skill create check-redis --desc "测试"
# 创建示例条目
# ...（略）
holmes --kb-path $KB kb skill link PT-DB-001 check-redis
holmes --kb-path $KB kb show PT-DB-001 | grep -q "check-redis"

# 场景 2: 读取和执行 skill
holmes --kb-path $KB kb skill read check-redis --json | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['has_run_script']"
holmes --kb-path $KB kb skill run check-redis --json | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['exit_code'] == 0"

# 场景 3: 命令检测
holmes --kb-path $KB kb skill detect-commands --content "$ redis-cli info" --json | python3 -c "import sys,json; d=json.load(sys.stdin); assert len(d) > 0"

# 场景 4: list
holmes --kb-path $KB kb skill list | grep -q check-redis

echo "✓ 所有冒烟测试通过"
rm -rf $KB
```

---

## 测试矩阵汇总

| 测试组 | 测试数 | 类型 | 当前状态 |
|--------|--------|------|----------|
| 数据建模层 (T-DM-*) | 8 | 单元 | 部分覆盖（T-DM-001~003 在 test_skill_manager.py 中已有） |
| CLI 命令层 (T-CLI-*) | 27 | 集成 | 基础覆盖（需补充 T-CLI-017~027） |
| 执行层 (T-RUN-*) | 14 | 单元 | 已在 test_skill_runner.py 覆盖约 70% |
| TypeScript 工具 (T-TS-*) | 8 | 单元 | **未实现**（需添加 TS 单元测试） |
| Agent 链路 (T-AGENT-*) | 4 | E2E | **未实现**（依赖真实 agent 运行） |
| 沉淀链路 (T-SED-*) | 6 | 集成 | **部分缺口**（US3 pending+skill_refs 未完整覆盖） |
| 向后兼容 (T-COMPAT-*) | 5 | 回归 | T-COMPAT-001~003 现有测试覆盖 |
| 边界条件 (T-EDGE-*) | 10 | 专项 | 部分覆盖 |
| 性能可观测 (T-PERF-*) | 3 | 非功能 | **未实现** |
| Setup 集成 (T-SETUP-*) | 1 | 集成 | **预期失败**（已知缺口） |

### 已知未实现 / 需补充

1. **T-SETUP-001**：`holmes setup` 不写入 KbReadSkill/KbRunSkill 权限（已知缺口）
2. **T-SED-US3-scenario2**：KbExtractAndSave 写入 pending 时不含 skill_refs（已知缺口）
3. **T-TS-* 全组**：TypeScript 工具层缺乏单元测试
4. **T-AGENT-***: 需要配合真实 LLM 调用的 E2E 测试
