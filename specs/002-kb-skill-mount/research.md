# Research: KB Skill Mounting

**Date**: 2026-05-29 | **Branch**: `002-kb-skill-mount`

## Decision 1: Skill 存储格式 — SKILL.md + scripts/run.sh

**Decision**: 每个 Skill 是 KB 仓库 `skills/` 目录下的一个子文件夹，包含 `SKILL.md`（元数据 + 描述）和 `scripts/run.sh`（固定约定的入口脚本）。

**Rationale**:
- 参考 hermes-agent（`/home/wangzhi/project/hermes-agent/skills/`）的成熟实践：SKILL.md 携带 YAML frontmatter（name, description, platforms, prerequisites）+ Markdown 说明体
- 独立文件夹支持多文件辅助脚本，不污染 KB 条目文件
- `scripts/run.sh` 固定约定消除歧义，实现最简单
- 随 KB 仓库 git 管理，天然版本控制

**Alternatives considered**:
- 内嵌代码块（`\`\`\`skill ... \`\`\``）: 简单但不支持复杂多文件 Skill，被排除
- 独立 skill 仓库: 增加同步复杂度，被排除

---

## Decision 2: KB 条目引用 Skill — frontmatter `skill_refs` 字段

**Decision**: KB 条目 YAML frontmatter 新增可选列表字段 `skill_refs: [<skill-name>, ...]`，值为 `skills/` 下的子目录名。

**Rationale**:
- frontmatter 是现有条目的元数据载体（已有 `id`, `type`, `title` 等字段），`skill_refs` 自然融入
- 可选字段不破坏现有条目格式，向后兼容
- `KbReadEntry` 工具无需修改 — 返回完整 frontmatter，agent 自行解析 `skill_refs`
- 已验证：现有 `python-frontmatter` 库支持任意额外字段

**Alternatives considered**:
- 条目 body 内嵌引用标签: 需修改 body 解析逻辑，复杂度高
- 独立 index 文件维护映射: 额外同步开销，被排除

---

## Decision 3: Skill 执行 — subprocess.run + 固定 run.sh 约定

**Decision**: `runner.py` 使用 `subprocess.run(['bash', 'scripts/run.sh'], cwd=skill_dir, timeout=30, capture_output=True)` 执行，stdout/stderr 截断 10KB。

**Rationale**:
- Python `subprocess.run` 是标准跨平台 shell 执行方案，已在 hermes-agent `skill_preprocessing.py` 中验证
- `bash scripts/run.sh` 而非 `./run.sh` 避免 chmod +x 问题
- 10KB stdout 截断防止超大输出占满 agent 上下文（hermes 用 4000 chars，我们适当放大）
- 30s 默认超时，SKILL.md frontmatter `timeout` 字段可覆盖

**Alternatives considered**:
- SKILL.md 声明 entrypoint 路径: 灵活但需额外解析，约定优于配置
- 容器化执行: v1 范围外

---

## Decision 4: Skill 生成时机 — 沉淀时异步识别

**Decision**: agent 执行 `KbExtractAndSave` 沉淀后，扫描 Resolution 内容识别命令模式（以 `$` 开头、反引号包裹、或匹配 `CMD_PATTERN` 正则），向用户展示候选 Skill 列表；用户确认后直接写入 `skills/`，条目写入 pending。

**Rationale**:
- 沉淀时 agent 上下文最完整（已知完整排查路径），此时生成 Skill 质量最高
- 参考 hermes-agent `background_review.py` 的 `_SKILL_REVIEW_PROMPT`："Be ACTIVE — most sessions produce at least one skill update"
- 异步提议（而非强制）：降低误报影响，保持用户控制权

**Command detection pattern** (Python regex):
```python
CMD_PATTERN = re.compile(
    r'(?:^|\n)\s*(?:'
    r'\$\s+\S+'          # $ command
    r'|`[^`]+`'          # `backtick`
    r'|(?:redis-cli|netstat|curl|kubectl|docker|systemctl|journalctl|ps|grep|awk|sed)\s'
    r')',
    re.MULTILINE
)
```

---

## Decision 5: 新增 TypeScript 工具 — KbReadSkill / KbRunSkill

**Decision**:
- `KbReadSkill`: 调用 `holmes --kb-path <path> kb skill read <name>` 返回 SKILL.md 内容
- `KbRunSkill`: 调用 `holmes --kb-path <path> kb skill run <name> [--param k=v ...]` 返回 stdout/stderr/exit_code JSON

**Rationale**:
- 遵循现有 KB 工具模式（KbReadEntry, KbSearch 等均为 execFile → holmes CLI subprocess）
- `alwaysLoad: true` 确保工具不被 defer，与其他 KB 工具一致
- 参数通过 `--param key=value` 传递给 CLI，CLI 在执行前完成占位符替换

**KbReadEntry 不变**: `skill_refs` 随 frontmatter 自动返回，agent 解析 YAML 即可获得引用列表，无需修改现有工具。

---

## Decision 6: SKILL.md 格式

**Decision**: 参考 hermes-agent SKILL.md 格式，精简适配 KB 场景：

```yaml
---
name: check-redis-connections
description: 检查 Redis 当前连接数及连接池状态
version: 1.0.0
platforms: [linux, macos]
timeout: 30
params:
  - name: host
    description: Redis 主机地址
    required: false
    default: "127.0.0.1"
  - name: port
    description: Redis 端口
    required: false
    default: "6379"
prerequisites:
  commands: [redis-cli]
---

## 用途

检查 Redis 当前连接数，判断是否存在连接池耗尽风险。

## 执行说明

脚本读取 `{host}:{port}` 的 Redis info，输出 connected_clients 和 maxclients。

## 参数

- `host`: Redis 主机地址（默认 127.0.0.1）
- `port`: Redis 端口（默认 6379）
```

`scripts/run.sh` 通过环境变量接收参数（`$SKILL_PARAM_HOST`, `$SKILL_PARAM_PORT`），`runner.py` 在执行前将 params 注入环境变量。
