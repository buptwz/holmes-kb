# Agent Tool Contracts: KB Skill

**Date**: 2026-05-29 | **Branch**: `002-kb-skill-mount`

所有工具遵循现有 `buildTool` / `ToolDef<InputSchema, string>` 接口约定：`alwaysLoad: true`，`call()` 返回 `{ data: string }`。

---

## KbReadEntry (已有，无代码改动)

`KbReadEntry` 调用 `holmes --kb-path <path> kb show <id>` 返回条目完整 Markdown。

由于 `skill_refs` 作为 frontmatter 字段存储在条目文件中，`KbReadEntry` 无需修改即可返回 `skill_refs`。Agent 通过解析 YAML frontmatter 获取引用的 Skill 名称列表。

**Agent 使用示例**:
```
KbReadEntry("PT-DB-001")
→ 返回包含 "skill_refs:\n  - check-redis" 的 Markdown
→ Agent 解析出 skill_refs = ["check-redis"]
→ 调用 KbReadSkill("check-redis")
```

---

## KbReadSkill (新增)

**名称**: `KbReadSkill`

**描述**: Read the SKILL.md of a named Skill from the KB skill library. Use this after finding `skill_refs` in a KB entry to understand what the skill does and what parameters it needs.

**Input Schema**:
```typescript
z.object({
  skill_name: z.string().describe('Skill name, e.g. "check-redis" (from skill_refs field)'),
})
```

**实现**: 调用 `holmes --kb-path <path> kb skill read <skill_name> --json`

**成功返回** (`data` 字段):
```json
{
  "name": "check-redis",
  "content": "---\nname: check-redis\ndescription: 检查 Redis 连接数...",
  "scripts_path": "skills/check-redis/scripts/run.sh",
  "has_run_script": true
}
```

**错误返回**:
```json
{ "error": "Skill 'check-redis' not found." }
```

**属性**:
- `alwaysLoad: true`
- `isReadOnly(): true`
- `isConcurrencySafe(): true`

---

## KbRunSkill (新增)

**名称**: `KbRunSkill`

**描述**: Execute a KB Skill's run.sh script and return the output. Call this after `KbReadSkill` confirms the skill exists and parameters are understood. Always show the user what will be executed and get confirmation before calling this tool.

**Input Schema**:
```typescript
z.object({
  skill_name: z.string().describe('Skill name to execute, e.g. "check-redis"'),
  params: z.record(z.string()).optional().describe(
    'Key-value pairs for skill parameters, e.g. {"host": "192.168.1.10", "port": "6380"}'
  ),
  timeout: z.number().optional().describe('Override execution timeout in seconds (default: 30)'),
})
```

**实现**: 调用 `holmes --kb-path <path> kb skill run <skill_name> [--param k=v ...] [--timeout N] --json`

**成功返回** (`data` 字段):
```json
{
  "skill": "check-redis",
  "exit_code": 0,
  "stdout": "connected_clients:5\nmaxclients:100\n",
  "stderr": "",
  "duration_ms": 342,
  "truncated": false
}
```

**失败返回** (exit_code ≠ 0 或超时):
```json
{
  "skill": "check-redis",
  "exit_code": 1,
  "stdout": "",
  "stderr": "Could not connect to Redis at 127.0.0.1:6379",
  "duration_ms": 105,
  "truncated": false
}
```

**属性**:
- `alwaysLoad: true`
- `isReadOnly(): false`（执行外部命令，有副作用）
- `isConcurrencySafe(): false`

---

## Agent 完整调用流程

```
1. KbSearch("redis 连接超时") or KbReadCategoryIndex("pitfall")
   → 找到 PT-DB-001

2. KbReadEntry("PT-DB-001")
   → 返回 frontmatter 含 skill_refs: [check-redis]
   → Agent: "此条目有可执行诊断 skill: check-redis"

3. KbReadSkill("check-redis")
   → 返回 SKILL.md 内容
   → Agent 了解用途、参数（host, port）、prerequisites（redis-cli）

4. Agent → 用户: "发现诊断脚本 check-redis，将执行:
   bash scripts/run.sh（检查 Redis 连接数）
   需要参数: host（当前: 127.0.0.1）, port（当前: 6379）
   是否执行？"

5. 用户确认后:
   KbRunSkill("check-redis", {"host": "127.0.0.1", "port": "6379"})
   → 返回 stdout: "connected_clients:87\nmaxclients:100"

6. Agent 分析: "当前连接数 87/100，接近上限，建议增加 maxclients"
   → 继续排查推理
```

---

## CLAUDE.md 工具调用指引（更新片段）

在 `~/.holmes/CLAUDE.md` 和 `~/holmes-kb/CLAUDE.md` 的工具调用部分新增：

```markdown
4. **KbReadSkill** — 当 KbReadEntry 返回的条目包含 `skill_refs` 时，MUST 立即调用此工具
   读取每个引用 skill 的 SKILL.md 内容，了解可执行诊断的用途和参数。

5. **KbRunSkill** — 在向用户展示 skill 信息并获得确认后，调用此工具执行诊断脚本。
   将执行结果（stdout/exit_code）纳入排查推理，不得忽略执行输出。
```
