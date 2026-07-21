# Contract: Skill Python API

## skill/manager.py 公开接口

### validate_skill_name(name: str) -> None
不变。name 须 kebab-case，3-64 字符，无前导/尾随连字符。

### validate_skill_md(path: Path) -> tuple[bool, str]
**新增**。
- 返回 `(True, "")` 表示合法
- 返回 `(False, "<错误描述>")` 表示非法
- 校验规则：frontmatter 必须存在；`name`/`description` 必填；key 只允许 `{name, description, license, allowed-tools, metadata, compatibility}`；name ≤ 64 字符、kebab-case；description ≤ 1024 字符、无尖括号

### create_skill(kb_root, name, description, instructions="") -> Path
- 创建 `skills/<name>/SKILL.md`
- 不创建 `scripts/` 目录或 `run.sh`
- `instructions` 为空时使用默认占位 body
- 抛 `ValueError` 若 skill 已存在或 name 非法

### parse_skill_md(path: Path) -> SkillDefinition
- 向后兼容：能读含旧字段（version 等）的 SKILL.md，只提取 `name`/`description`
- 返回 `SkillDefinition(name, description, content)`
- 抛 `FileNotFoundError` / `ValueError`

### detect_commands(resolution_text: str) -> list[CommandCandidate]
**保留**，仅用于计数（判断 RECOMMENDED/OPTIONAL/SKIP）。

### get_skill_dir / skill_exists / link_skill / unlink_skill / list_skills
**不变**接口，内部不依赖 run.sh。

---

## agent/tools.py create_skill_for_entry tool 合约

### Input schema（更新）
```json
{
  "name": "string (kebab-case)",
  "entry_id": "string",
  "description": "string",
  "instructions": "string (agent instruction markdown body, optional)",
  "link_only": "boolean (optional, default false)"
}
```

### Output schema（不变）
```json
{
  "created": "boolean",
  "linked": "boolean",
  "skill_dir": "string | null",
  "action": "string"
}
```

---

## CLI skill 子命令合约

### 保留命令

`holmes kb skill list [entry_id] [--json]`
- JSON 输出字段：`name`, `description`, `linked_entries`
- 不含：`version`, `platforms`

`holmes kb skill read <name> [--json]`
- JSON 输出字段：`name`, `content`
- 不含：`scripts_path`, `has_run_script`

### 删除命令（调用时报 "No such command"）
`skill create`, `skill link`, `skill unlink`, `skill run`, `skill detect-commands`, `skill auto-create`
