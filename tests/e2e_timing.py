"""Quick timing test for one chat call with HOLMES_HOME env var.

Configure via environment variables:
  HOLMES_MODEL    — LLM model name (default: gpt-4o)
  HOLMES_API_BASE — OpenAI-compatible API base URL (default: https://api.openai.com/v1)
  HOLMES_API_KEY  — API key
"""
import socket, json, os, subprocess, sys, tempfile, time, select
from pathlib import Path

AGENT_DIR = Path(__file__).parent.parent

with tempfile.TemporaryDirectory() as d:
    kb = Path(d) / "kb"
    (kb / "pitfalls").mkdir(parents=True)
    (kb / "pitfalls" / "PT-DB-001.md").write_text(
        "---\nid: PT-DB-001\ntype: pitfall\ntitle: Redis timeout\nmaturity: verified\n"
        "category: database\ntags: []\ncreated_at: \"\"\nupdated_at: \"\"\n---\n"
        "## Symptoms\nTimeout\n## Root Cause\nSmall pool\n## Resolution\nIncrease pool"
    )
    home = Path(d) / "home"
    home.mkdir()
    (home / "config.json").write_text(json.dumps({
        "kb_path": str(kb),
        "model": os.getenv("HOLMES_MODEL", "gpt-4o"),
        "api_base_url": os.getenv("HOLMES_API_BASE", "https://api.openai.com/v1"),
        "api_key": os.getenv("HOLMES_API_KEY", ""),
        "max_tokens": 512, "log_level": "WARNING", "mcp_servers": [],
    }))
    sock = str(Path(d) / "a.sock")
    env = {**os.environ, "HOLMES_HOME": str(home)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "holmes.agent_server", f"--socket={sock}"],
        cwd=str(AGENT_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    while not os.path.exists(sock):
        time.sleep(0.1)
    print("agent ready", flush=True)

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock)
    s.setblocking(False)
    buf = bytearray()

    def send(obj):
        s.sendall((json.dumps(obj) + "\n").encode())

    def read_line(timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = select.select([s], [], [], min(0.5, deadline - time.time()))
            if r[0]:
                chunk = s.recv(65536)
                if chunk:
                    buf.extend(chunk)
            idx = buf.find(b"\n")
            if idx >= 0:
                line = bytes(buf[:idx]).strip()
                del buf[:idx + 1]
                if line:
                    return json.loads(line)
        return None

    send({"jsonrpc": "2.0", "id": 1, "method": "session.create", "params": {}})
    r = read_line(5)
    if not r:
        print("FAIL: no session.create response", flush=True)
        proc.terminate(); sys.exit(1)
    sid = r["result"]["session_id"]
    print(f"session: {sid[:8]}", flush=True)

    t0 = time.time()
    send({"jsonrpc": "2.0", "id": 2, "method": "chat.send", "params": {
        "session_id": sid, "message": "What Redis issues are in the KB?",
    }})
    print("sent chat, waiting for agent/done...", flush=True)

    deadline = time.time() + 60
    done = False
    while time.time() < deadline:
        obj = read_line(1.0)
        if obj is None:
            continue
        m = obj.get("method", "")
        if m == "agent/token":
            print(".", end="", flush=True)
        elif m:
            print(f"\n[{m}] t+{time.time()-t0:.1f}s", flush=True)
        if m in ("agent/done", "agent/error"):
            done = True
            break

    if done:
        print(f"\nSuccess: done in {time.time()-t0:.1f}s", flush=True)
    else:
        print(f"\nTIMEOUT after {time.time()-t0:.1f}s", flush=True)

    proc.terminate()
    proc.wait()
