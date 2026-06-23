# M8 — 可观测性与日志

## 项目与代码库背景

**Holmes KB** 是一个 Python CLI 工具，用 Click 框架实现，管理工程团队的 Markdown 知识库。

- 代码库根：`/home/wangzhi/project/projectTmp/holmes/holmes/kb/`
- 配置文件：`~/.holmes/config.json`（api_key / api_base_url / model / username）
- 日志目录：`~/.holmes/logs/`

## 必读参考文档（实现前全部通读）

### 1. 施工蓝图（最重要，逐字阅读）
`/home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/blueprint.md`

**必须全部读完的章节**：

- `§ 可观测性与日志`（全节）
  - **设计原则**：Holmes 的可观测对象是**文档**；一份源文档从导入到上线的完整生命周期是一条完整的追踪链路；所有 CLI 操作（import、approve、delete、re-import）都归属于某份源文档
  - **TraceId 格式**：取源文档文件名 stem（如 `gpu-troubleshooting.md` → `trace_id: gpu-troubleshooting`）；同路径不同文件存在同名时追加 source_hash 前缀消歧（`gpu-troubleshooting-a3f1`）
  - **TraceId 存储**：首次 import 时生成，写入 `_import-state/<hash>.dag.json`；同时写入每个 entry frontmatter 的 `import_trace_id` 字段；`approve/delete` 操作从 entry 的 `source_file` 字段派生 trace_id，无需用户手动传入；`--resume` 时从状态文件读取原始 trace_id 继续追加
  - **Span 结构**（每次 import 的事件层级）：
    ```
    trace: gpu-troubleshooting
      span: agent1.read          Phase 1 通读
      span: agent1.draft         Phase 2 初稿（首次 write_dag）
      span: agent1.review[1]     第 1 轮 review
      span: agent1.review[N]     第 N 轮 review（直到 output_dag）
      span: step25.parse         DAG 解析规范化
      span: step25.validate      交叉验证
      span: agent2.node[<id>]    生成单个 process entry（每节点一个 span）
      span: agent2.root          生成 pitfall root entry
      span: lint                 import 完成后 lint 校验
      span: kb.approve           approve 操作（每次调用一个 span）
      span: kb.delete            delete 操作
    ```
  - **每个 span 记录**：`started_at`、`duration_ms`、`llm_calls`（该 span 内 LLM 调用次数）、`tokens`（输入+输出）、`result`（ok / error / warning）、`detail`（可选补充信息）
  - **日志格式与存储**：双格式并行写入
    - `~/.holmes/logs/<YYYY-MM-DD>.log`：人类可读，带 trace_id 前缀，适合 cat/grep
    - `~/.holmes/logs/<YYYY-MM-DD>.jsonl`：JSON Lines，适合工具消费（jq、grep 过滤）
  - **JSON Lines 格式**（每行一个事件）：
    ```json
    {"ts":"2026-06-23T14:30:00Z","trace":"gpu-troubleshooting","span":"agent1.draft","level":"INFO","msg":"write_dag","nodes":8,"duration_ms":42100}
    {"ts":"2026-06-23T14:35:00Z","trace":"gpu-troubleshooting","span":"agent2.node[N3]","level":"INFO","msg":"write_entry ok","entry_id":"gpu-init-firmware-001","tokens":1240,"duration_ms":8300}
    {"ts":"2026-06-23T14:36:00Z","trace":"gpu-troubleshooting","span":"lint","level":"WARN","msg":"content_source: description_match_failed","node_id":"N5"}
    {"ts":"2026-06-23T15:10:00Z","trace":"gpu-troubleshooting","span":"kb.approve","level":"INFO","msg":"approved","entry_id":"gpu-init-failure-root-001","user":"wangzhi"}
    ```
  - **人类可读格式**（`.log`）：
    ```
    2026-06-23T14:30:00Z [INFO ] gpu-troubleshooting | agent1.draft | write_dag nodes=8 duration_ms=42100
    ```
  - **日志滚动**：按天滚动，保留 30 天，超期自动删除
  - **CLI 查询接口**：
    ```bash
    holmes log list                              # 列出所有 trace 的最后事件摘要（import / draft / mcp session）
    holmes log show <trace_id>                   # 展示某条 trace 的完整 span 树（人类可读）
    holmes log show <trace_id> --json            # 原始 JSON Lines 输出
    holmes log show <trace_id> --since <date>    # 只显示指定日期之后的事件
    holmes import <file> --verbose               # 实时将 span 级日志打印到 terminal
    ```
  - **`holmes log show` 示例输出**：完整的 span 树格式（见蓝图，含缩进时间线格式）
  - **未配置 username 时的行为**：import 命令执行前检查 `config.username`；若未配置：写 ERROR 日志 + 终止 import + 打印 `"run: holmes config set username <name>"`；trace_id 照常生成

- `§ Frontmatter 新增字段 > import_trace_id`：字段定义（= 文件名 stem），用于日志关联

- `§ CLI 兼容性`：
  - `holmes log list`（新增）：列出所有 trace 的最后事件摘要
  - `holmes log show <trace_id>`（新增）：展示完整 span 树
  - `holmes import <file> --verbose`（参数新增）：实时日志到 terminal

- `§ MCP 接口 > MCP 日志记录`（M9 将调用本模块 Logger）：
  - `kb_overview` → `write_span(session_id, "mcp.kb_overview", "INFO", ...)`
  - `kb_search` → `write_span(session_id, "mcp.kb_search", "INFO", query=..., results=...)`
  - `kb_read` → `write_span(session_id, "mcp.kb_read", "INFO", entry_id=...)`
  - `kb_draft` → `write_span(filename_stem, "mcp.draft", "INFO", ...)` （trace_id = 文件名 stem）

### 2. 知乎 KB 数据模型
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/kb-data-model.md`

了解 §2 Entry Frontmatter 字段中的 `import_trace_id` 字段（M1 新增），理解与日志系统的关联。

### 3. 开发者指南
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/developer-guide.md`

了解项目架构、Python 包结构、配置文件路径约定（`~/.holmes/`）、Click 子命令注册模式。

## 涉及的现有代码（实现前全部通读）

```
kb/holmes/config.py             # HolmesConfig dataclass
                                # 重点：load_config() 读取路径、M1 新增的 username 字段
                                # ~/ .holmes/config.json 结构
kb/holmes/cli.py                # 了解子命令注册方式（Click group + subcommand）
                                # 了解 holmes import 现有参数（--force / --dry-run / --resume）
                                # M8 新增 --verbose 参数和 holmes log 子命令组
```

相关测试文件：
```
kb/tests/test_config.py         # 若有，了解 HolmesConfig 测试模式
```

## 前置依赖

**无**。本模块独立，可与 M1/M7/M9 并行开发。

注意：
- M8 完成后，M9 的 MCP 日志记录需要依赖 M8 的 `HolmesLogger` 接口
- M2/M4/M5/M6a 实现时也会调用 Logger 写 span（但这些模块的 Logger 调用可在 M8 完成后追加）
- M8 设计 Logger 接口时要考虑供其他模块调用的易用性

## 新建文件

```
kb/holmes/kb/logger.py          # HolmesLogger 类（日志核心）
```

## 主要改动清单

### 新建 `kb/holmes/kb/logger.py`

核心类 `HolmesLogger`：

```python
class HolmesLogger:
    def __init__(self, log_dir: Path):
        """log_dir 通常为 ~/.holmes/logs/"""
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def write_span(
        self,
        trace_id: str,
        span: str,
        level: str,          # "INFO" / "WARN" / "ERROR"
        msg: str,
        **extra              # 任意附加字段：nodes, duration_ms, tokens, entry_id, user 等
    ) -> None:
        """同时写入 .log（人类可读）和 .jsonl（JSON Lines）两种格式。"""
        ts = datetime.now(timezone.utc).isoformat()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        record = {"ts": ts, "trace": trace_id, "span": span, "level": level, "msg": msg}
        record.update(extra)

        # 写 .jsonl
        jsonl_path = self.log_dir / f"{today}.jsonl"
        with jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # 写 .log（人类可读）
        extra_str = " ".join(f"{k}={v}" for k, v in extra.items())
        log_line = f"{ts} [{level:<5}] {trace_id} | {span} | {msg} {extra_str}".rstrip()
        log_path = self.log_dir / f"{today}.log"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(log_line + "\n")

    def rotate(self) -> None:
        """删除 30 天前的 .log 和 .jsonl 文件。"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        for f in self.log_dir.glob("*.log"):
            # 从文件名解析日期，早于 cutoff 则删除
            ...
        for f in self.log_dir.glob("*.jsonl"):
            ...
```

### cli.py 新增子命令

**`holmes log list`**：
- 读取 `~/.holmes/logs/*.jsonl`，按 trace_id 分组
- 提取每个 trace 的最后事件摘要（ts / span / level / msg）
- 识别三类 trace：
  - `import` trace：含 agent1.*/agent2.*/lint 等 span
  - `draft` trace：含 mcp.draft span（trace_id = 草稿文件名 stem）
  - `session-*` trace：MCP 会话（trace_id 以 `session-` 开头）
- 展示格式：`<trace_id>  <类型>  <最后事件日期>  <摘要>`

**`holmes log show <trace_id>`**：
- 读取所有 `.jsonl` 文件，过滤该 trace_id 的所有 span
- 按时间顺序展示完整 span 树（参考蓝图示例输出格式，含缩进时间线）
- `--json` flag：原始 JSON Lines 输出（直接 cat 过滤后的行）
- `--since <YYYY-MM-DD>` flag：只显示指定日期之后的事件

**`holmes import <file>` 新增 `--verbose` flag**：
- 开启后实时将 span 级日志打印到 terminal（不仅写文件，同时打印到 stdout）
- 默认：只打印 INFO 级摘要（开始、结束、重要里程碑）；`--verbose` 打印所有 span

### config.py
- `HolmesConfig` 新增 `username: str = ""` 字段（若 M1 已完成此项则跳过）

## 关键实现细节

### HolmesLogger 是单例还是实例？
建议：`HolmesLogger` 作为普通类实例传递（不用单例模式），便于测试时 mock。各 CLI 命令在入口处创建实例并传入各子系统。

### trace_id 派生规则
```python
def derive_trace_id(source_file: str, source_hash: str = "") -> str:
    """从源文件路径派生 trace_id。"""
    stem = Path(source_file).stem          # "gpu-troubleshooting"
    # 若存在同名文件，追加 hash 前缀消歧
    # 简单实现：先用 stem，有冲突时 caller 追加 hash
    return stem
```

`approve/delete` 操作中，从 entry frontmatter 的 `import_trace_id` 字段读取 trace_id（不重新派生），保证跨操作 trace 连续。

### 日志滚动策略
```python
def rotate(self) -> None:
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)
    for f in self.log_dir.glob("*.jsonl"):
        try:
            date_str = f.stem        # "2026-06-23"
            file_date = date.fromisoformat(date_str)
            if file_date < cutoff:
                f.unlink()
        except ValueError:
            pass  # 跳过非日期格式文件名
    # 同样处理 *.log
```

### `--verbose` 实时打印
`write_span` 方法增加 `verbose_mode: bool = False` 参数，或通过 Logger 实例的属性控制：
```python
class HolmesLogger:
    def __init__(self, log_dir: Path, verbose: bool = False):
        self.verbose = verbose

    def write_span(self, trace_id, span, level, msg, **extra):
        # ... 写文件 ...
        if self.verbose:
            print(log_line)  # 同时打印到 stdout
```

## 验收条件

- [ ] `holmes import doc.md` 执行后，`~/.holmes/logs/<today>.jsonl` 中有对应 trace 记录
- [ ] 每条 JSON 日志记录包含 `ts / trace / span / level / msg` 必填字段
- [ ] 每次 `write_span` 同时写 `.log`（人类可读）和 `.jsonl`（JSON Lines）两个文件
- [ ] `holmes log list` 输出三类 trace 的摘要（import / draft / session），格式清晰
- [ ] `holmes log show gpu-troubleshooting` 打印该 trace 完整 span 树（时间线格式）
- [ ] `holmes log show gpu-troubleshooting --json` 输出原始 JSON Lines
- [ ] `holmes log show gpu-troubleshooting --since 2026-06-01` 只显示该日期后的事件
- [ ] 日志按天滚动（文件名格式 `YYYY-MM-DD.log / .jsonl`），`rotate()` 删除 30 天前的文件
- [ ] `config.username` 未配置时，import 命令写 ERROR 日志并终止，打印提示 `"run: holmes config set username <name>"`
- [ ] `holmes import --verbose` 实时将 span 日志打印到 terminal
- [ ] Logger 接口设计便于其他模块（M4/M5/M9）调用 `write_span()`（参数清晰，无强依赖）
- [ ] Logger 有单元测试：`write_span` 写入 `.log` 和 `.jsonl` 格式验证、`rotate()` 删除超期文件

## 执行步骤

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/modules/M8-logging/
/speckit-specify
/speckit-plan
/speckit-tasks
/speckit-implement
/speckit-analyze
```

**实现前务必**：完整读完蓝图 `§ 可观测性与日志` 全节（含 TraceId 格式、Span 结构、日志格式、CLI 查询接口示例输出），理解 trace_id 贯穿多个操作的机制，再读完 `config.py` 中 `HolmesConfig` 结构（特别是 `username` 字段和 `load_config()` 路径），再读完 `cli.py` 中 Click 子命令注册方式。
