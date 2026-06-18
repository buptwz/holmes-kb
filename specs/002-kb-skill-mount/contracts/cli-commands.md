# CLI Command Contracts: KB Skill

**Date**: 2026-05-29 | **Branch**: `002-kb-skill-mount`

所有命令共用顶层 `--kb-path` 选项（通过 Click context 传递）：
```
holmes --kb-path <path> kb skill <subcommand>
```

---

## `holmes kb skill create <name>`

**用途**: 在 `skills/` 目录下创建新 Skill 文件夹并生成模板文件。

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | argument | ✅ | Skill 名称（kebab-case，`[a-z0-9-]`，3-64字符） |
| `--desc TEXT` | option | ✅ | 一句话描述，写入 SKILL.md frontmatter |
| `--platform TEXT` | option | ❌ | 平台（默认 `linux,macos`） |

**成功输出** (stdout):
```
✓ Skill created: skills/check-redis/
  Edit SKILL.md to add parameter declarations.
  Write your diagnostics to scripts/run.sh.
  Link to an entry: holmes kb skill link <entry-id> check-redis
```

**错误情况**:
- `skills/<name>/` 已存在 → `Error: Skill 'check-redis' already exists.`
- `name` 格式不合法 → `Error: Skill name must match [a-z0-9-] and be 3-64 chars.`

**副作用**: 创建 `skills/<name>/SKILL.md` 和 `skills/<name>/scripts/run.sh`（模板内容）。

---

## `holmes kb skill link <entry-id> <skill-name>`

**用途**: 将 Skill 挂载到 KB 条目（写入条目 frontmatter `skill_refs`）。

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `entry-id` | argument | ✅ | 条目 ID，如 `PT-DB-001` |
| `skill-name` | argument | ✅ | Skill 名称 |

**成功输出**:
```
✓ Linked skill 'check-redis' to PT-DB-001.
```

**错误情况**:
- 条目不存在 → `Error: Entry 'PT-DB-001' not found.`
- Skill 目录不存在 → `Error: Skill 'check-redis' not found. Run: holmes kb skill create check-redis`
- 已挂载（幂等）→ `Info: Skill 'check-redis' already linked to PT-DB-001.`（exit 0）

**副作用**: 修改条目文件 `skill_refs` 字段（追加），更新 `updated_at`。

---

## `holmes kb skill unlink <entry-id> <skill-name>`

**用途**: 从条目移除 Skill 挂载（不删除 Skill 文件夹）。

**参数**: 同 link。

**成功输出**:
```
✓ Unlinked skill 'check-redis' from PT-DB-001.
```

**错误情况**:
- 条目或 Skill 不存在 → 对应报错
- 未挂载（幂等）→ `Info: Skill 'check-redis' was not linked to PT-DB-001.`（exit 0）

---

## `holmes kb skill list [entry-id]`

**用途**: 列出 Skill 库中所有 Skill，或列出特定条目引用的 Skill。

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `entry-id` | argument | ❌ | 指定条目；省略则列出全部 |
| `--json` | flag | ❌ | JSON 输出 |

**成功输出（无 entry-id）**:
```
NAME                     DESCRIPTION                        REFS
check-redis              检查 Redis 连接数                  PT-DB-001, PT-DB-002
check-nginx-upstream     检查 Nginx upstream 状态           PT-NET-001
```

**JSON 格式** (`--json`):
```json
[
  {
    "name": "check-redis",
    "description": "检查 Redis 连接数",
    "version": "1.0.0",
    "platforms": ["linux", "macos"],
    "linked_entries": ["PT-DB-001", "PT-DB-002"]
  }
]
```

**错误情况**: `skills/` 目录不存在 → 空列表，不报错。

---

## `holmes kb skill read <name>`

**用途**: 返回 Skill 的 SKILL.md 完整内容（供 agent 工具 `KbReadSkill` 调用）。

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | argument | ✅ | Skill 名称 |
| `--json` | flag | ❌ | JSON 格式返回 |

**成功输出（默认）**: SKILL.md 原始 Markdown 文本

**JSON 格式**:
```json
{
  "name": "check-redis",
  "content": "---\nname: check-redis\n...",
  "scripts_path": "skills/check-redis/scripts/run.sh",
  "has_run_script": true
}
```

**错误情况**: Skill 不存在 → JSON `{"error": "Skill 'check-redis' not found."}` + exit 1

---

## `holmes kb skill run <name>`

**用途**: 执行 Skill 的 `scripts/run.sh`，打印输出（供测试验证用）。

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | argument | ✅ | Skill 名称 |
| `--param TEXT` | option（可多次） | ❌ | 参数 `key=value`，可传多个 |
| `--timeout INT` | option | ❌ | 覆盖超时秒数 |
| `--json` | flag | ❌ | JSON 格式输出 |

**示例**:
```bash
holmes --kb-path ~/holmes-kb kb skill run check-redis --param host=192.168.1.10 --param port=6380
```

**JSON 格式** (`--json`):
```json
{
  "skill": "check-redis",
  "exit_code": 0,
  "stdout": "connected_clients:5\nmaxclients:100",
  "stderr": "",
  "duration_ms": 342,
  "truncated": false
}
```

**错误情况**:
- Skill 不存在 → `{"error": "Skill 'check-redis' not found."}` + exit 1
- `run.sh` 不存在 → `{"error": "No run.sh in skills/check-redis/scripts/."}` + exit 1
- 必填参数缺失 → `{"error": "Missing required param: host"}` + exit 1
- 执行超时 → `{"exit_code": -1, "error": "Timeout after 30s", ...}`
- 先决命令缺失 → `{"error": "Prerequisite command not found: redis-cli"}` + exit 1
