#!/usr/bin/env bash
# 启动 Holmes KB MCP server
# 用法: ./start-mcp.sh [port]
PORT=${1:-8765}
KB_PATH=${HOLMES_KB_PATH:-/home/wangzhi/holmes-kb}

cd "$(dirname "$0")"

# 杀掉已有进程
lsof -ti :$PORT | xargs kill -9 2>/dev/null || true
sleep 1

echo "Starting Holmes KB MCP server on port $PORT (KB: $KB_PATH)"
HOLMES_KB_PATH="$KB_PATH" python -c "
from holmes.mcp.server import run_server
from pathlib import Path
run_server(Path('$KB_PATH'), port=$PORT)
" &

sleep 2
curl -s -X POST http://localhost:$PORT/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
  | grep -o '"name":"holmes-kb"' && echo " — server ready" || echo "ERROR: server not responding"
