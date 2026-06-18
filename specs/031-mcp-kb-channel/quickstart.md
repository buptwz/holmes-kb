# Quickstart: MCP KB Channel (Feature 031)

## 开发环境

```bash
cd kb/
pip install -e ".[dev]"
```

## 运行现有测试

```bash
cd kb/
pytest tests/ -v
```

## 启动 MCP Server（测试用）

```bash
holmes start --kb-path /path/to/kb --port 8765
```

## 手动测试 MCP 工具

使用 MCP Inspector 或直接调用：

```bash
# 概览
curl -X POST http://localhost:8765/mcp/tools/kb_overview -d '{}'

# 浏览 skills
curl -X POST http://localhost:8765/mcp/tools/kb_list \
  -d '{"type": "skill"}'

# 读取 entry
curl -X POST http://localhost:8765/mcp/tools/kb_read \
  -d '{"id": "PT-DB-001"}'

# 读取 skill
curl -X POST http://localhost:8765/mcp/tools/kb_read \
  -d '{"id": "redis-oom-recovery"}'

# 读取 skill 子文件
curl -X POST http://localhost:8765/mcp/tools/kb_read \
  -d '{"id": "redis-oom-recovery", "path": "scripts/check.sh"}'

# 搜索
curl -X POST http://localhost:8765/mcp/tools/kb_search \
  -d '{"query": "Redis OOM", "limit": 5}'
```

## 主要修改文件

| 文件 | 变更类型 |
|------|---------|
| `kb/holmes/mcp/tools.py` | 修改：扩展所有 handler，新增 `handle_kb_search` |
| `kb/holmes/mcp/server.py` | 修改：注册 `kb_search`，per-connection session_id |
| `kb/holmes/kb/search.py` | 复用（无需修改） |
| `kb/holmes/kb/skill/manager.py` | 复用（无需修改） |
| `kb/holmes/kb/importer.py` | 复用，适配为同步调用 |
| `docs/kb-data-model.md` | 新增：KB 数据模型权威文档 |

## 注意事项

- `kb_submit` 调用 LLM，需配置 `OPENAI_API_KEY` 或 `~/.holmes/config.json`
- `kb_submit` 可能耗时 30-120s，MCP 客户端需配置足够超时（建议 ≥ 180s）
- per-connection session_id 依赖 FastMCP 的连接生命周期机制，实现前需验证 FastMCP 版本支持
