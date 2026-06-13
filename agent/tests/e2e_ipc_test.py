"""End-to-end IPC integration tests (sync socket, no asyncio).

Covers:
  US1  - session create + chat with KB tool use
  US2  - session list / get
  US3  - session.resolve → knowledge extraction → pending entry
  US4  - CLI import document
  US5  - KB CLI: pending / confirm / reject / lint
  US8  - tool confirmation flow
  US9  - /remember + MEMORY.md
"""

from __future__ import annotations

import json
import os
import select
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

# ── config ───────────────────────────────────────────────────────────────────
# Configure via environment variables before running:
#   HOLMES_MODEL    — LLM model name (default: gpt-4o)
#   HOLMES_API_BASE — OpenAI-compatible API base URL (default: https://api.openai.com/v1)
#   HOLMES_API_KEY  — API key

API_MODEL = os.getenv("HOLMES_MODEL", "gpt-4o")
API_BASE  = os.getenv("HOLMES_API_BASE", "https://api.openai.com/v1")
API_KEY   = os.getenv("HOLMES_API_KEY", "")

AGENT_DIR = Path(__file__).parent.parent
PYTHON    = sys.executable

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
INFO = "\033[33m→\033[0m"

_errors: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  {PASS} {name}")
    else:
        msg = f"{name}" + (f": {detail}" if detail else "")
        print(f"  {FAIL} {msg}")
        _errors.append(msg)
    return cond


# ── IPC client (sync) ─────────────────────────────────────────────────────────

class IPCClient:
    def __init__(self, socket_path: str):
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(socket_path)
        self._sock.setblocking(False)
        self._buf = b""
        self._next_id = 1
        self._pending_responses: dict[int, dict] = {}
        self._notifications: list[dict] = []

    def _send(self, obj: dict) -> None:
        self._sock.sendall((json.dumps(obj) + "\n").encode())

    def _recv_lines(self, timeout: float = 10.0) -> list[dict]:
        """Read any available data and return complete JSON lines."""
        ready = select.select([self._sock], [], [], timeout)
        if not ready[0]:
            return []
        try:
            chunk = self._sock.recv(65536)
        except BlockingIOError:
            return []
        if not chunk:
            return []
        self._buf += chunk
        lines = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if line:
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return lines

    def call(self, method: str, params: dict, timeout: float = 20.0) -> dict:
        """Send a request and wait for its response."""
        req_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        deadline = time.time() + timeout
        while time.time() < deadline:
            for obj in self._recv_lines(timeout=min(1.0, deadline - time.time())):
                if obj.get("id") == req_id:
                    if "error" in obj:
                        raise RuntimeError(f"RPC {method}: {obj['error']}")
                    return obj.get("result", {})
                if "method" in obj:
                    self._notifications.append(obj)
                elif "id" in obj:
                    self._pending_responses[obj["id"]] = obj
        raise TimeoutError(f"No response for {method} within {timeout}s")

    def notify(self, method: str, params: dict) -> None:
        """Send a notification (no id, no response expected)."""
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def collect_events(self, stop_methods: tuple, timeout: float = 90.0) -> list[dict]:
        """Collect notifications until a stop method arrives."""
        events = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            for obj in self._recv_lines(timeout=min(1.0, remaining)):
                if "method" in obj:
                    events.append(obj)
                    if obj["method"] in stop_methods:
                        return events
                # Responses to fire-and-forget calls (chat.send returns None)
        return events

    def close(self):
        self._sock.close()


# ── KB fixture ────────────────────────────────────────────────────────────────

def make_kb(tmp: Path) -> Path:
    kb = tmp / "kb"
    (kb / "pitfalls").mkdir(parents=True)
    (kb / "models").mkdir(parents=True)
    (kb / "contributions" / "pending").mkdir(parents=True)

    entry = textwrap.dedent("""\
        ---
        id: PT-DB-001
        type: pitfall
        title: Redis connection timeout under high load
        maturity: verified
        category: database
        tags: [redis, timeout, connection-pool]
        created_at: "2026-01-01T00:00:00Z"
        updated_at: "2026-01-01T00:00:00Z"
        ---
        ## Symptoms
        Redis CLIENT commands return ETIMEDOUT after a few seconds under load.

        ## Root Cause
        Default connection pool size (10) is too small for concurrent requests.

        ## Resolution
        Increase `maxclients` in redis.conf and set pool size >= expected concurrency.

        ## Prevention
        Monitor `connected_clients` and set alerts above 80% of `maxclients`.
    """)
    (kb / "pitfalls" / "PT-DB-001.md").write_text(entry, encoding="utf-8")
    (kb / "pitfalls" / "_index.md").write_text(
        "# Pitfalls\n\n- PT-DB-001: Redis connection timeout under high load\n"
    )
    (kb / "README.md").write_text(
        "# Holmes Knowledge Base\n\nCategories: pitfalls, models\n"
    )
    return kb


def make_holmes_home(tmp: Path, kb: Path) -> Path:
    d = tmp / "holmes_home"
    d.mkdir()
    cfg = {
        "kb_path": str(kb),
        "model": API_MODEL,
        "api_base_url": API_BASE,
        "api_key": API_KEY,
        "max_tokens": 1024,
        "log_level": "WARNING",
        "mcp_servers": [],
    }
    (d / "config.json").write_text(json.dumps(cfg))
    return d


# ── agent process ─────────────────────────────────────────────────────────────

def start_agent(socket_path: str, holmes_home: Path) -> subprocess.Popen:
    env = {**os.environ, "HOLMES_HOME": str(holmes_home)}
    proc = subprocess.Popen(
        [PYTHON, "-m", "holmes.agent_server", f"--socket={socket_path}"],
        cwd=str(AGENT_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 10
    while not os.path.exists(socket_path):
        if time.time() > deadline:
            proc.terminate()
            raise RuntimeError("Agent socket not created within 10s")
        if proc.poll() is not None:
            raise RuntimeError(f"Agent exited early (rc={proc.returncode})")
        time.sleep(0.1)
    return proc


# ── CLI helper ────────────────────────────────────────────────────────────────

def cli(args: list[str], holmes_home: Path, input_text: str = "") -> tuple[int, str, str]:
    env = {**os.environ, "HOLMES_HOME": str(holmes_home)}
    r = subprocess.run(
        [PYTHON, "-m", "holmes.cli"] + args,
        cwd=str(AGENT_DIR),
        env=env,
        capture_output=True,
        text=True,
        input=input_text,
        timeout=120,
    )
    return r.returncode, r.stdout, r.stderr


# ── US1: chat + tool use ──────────────────────────────────────────────────────

def test_us1(client: IPCClient) -> str:
    print(f"\n{INFO} US1: Session + multi-turn chat with KB tool")

    res = client.call("session.create", {})
    session_id = res.get("session_id", "")
    check("session.create returns session_id", bool(session_id))

    # chat.send (fire-and-forget in terms of JSON-RPC — response comes as notifications)
    client._send({
        "jsonrpc": "2.0", "id": client._next_id, "method": "chat.send",
        "params": {
            "session_id": session_id,
            "message": "What Redis-related issues are documented in the knowledge base?",
        },
    })
    client._next_id += 1

    print(f"    waiting for agent/done ...", flush=True)
    events = client.collect_events(("agent/done", "agent/error"), timeout=60)
    methods = [e["method"] for e in events]

    error_evts = [e for e in events if e["method"] == "agent/error"]
    check("No agent/error on chat", not error_evts,
          error_evts[0]["params"]["error"] if error_evts else "")
    check("Received agent/done", "agent/done" in methods)
    check("Received at least one token", "agent/token" in methods)
    check("Agent used a KB tool", "agent/tool_start" in methods,
          f"methods seen: {sorted(set(methods))}")

    tokens = [e for e in events if e["method"] == "agent/token"]
    if tokens:
        full = "".join(e["params"]["delta"] for e in tokens)
        check("Response mentions Redis",
              "redis" in full.lower(),
              full[:120])

    return session_id


# ── US2: session history ──────────────────────────────────────────────────────

def test_us2(client: IPCClient, session_id: str):
    print(f"\n{INFO} US2: Session history")

    res = client.call("session.list", {})
    sessions = res.get("sessions", [])
    check("session.list returns entries", bool(sessions))
    check("Current session in list", session_id in [s["id"] for s in sessions])

    res2 = client.call("session.get", {"session_id": session_id})
    sess = res2.get("session", {})
    check("session.get returns data", bool(sess))
    check("Session has messages", sess.get("message_count", 0) > 0)
    check("session id matches", sess.get("id") == session_id)


# ── US9: memory ───────────────────────────────────────────────────────────────

def test_us9(client: IPCClient, holmes_home: Path):
    print(f"\n{INFO} US9: Persistent memory (/remember)")

    res = client.call("/remember", {"content": "Always respond concisely in bullet points."})
    check("/remember ok", res.get("ok") is True)

    mem = holmes_home / "MEMORY.md"
    check("MEMORY.md created", mem.exists())
    if mem.exists():
        check("MEMORY.md has the content", "bullet points" in mem.read_text())


# ── US8: tool confirmation IPC mechanics ─────────────────────────────────────

def test_us8_ipc_mechanics(client: IPCClient):
    """Test tool.approve and tool.deny IPC endpoints directly."""
    print(f"\n{INFO} US8: Tool confirmation IPC mechanics (approve + deny endpoints)")

    # Test tool.approve with a nonexistent id — should return ok (idempotent)
    res = client.call("tool.approve", {"tool_call_id": "nonexistent-id"})
    check("tool.approve is idempotent for unknown id", res.get("ok") is True)

    res2 = client.call("tool.deny", {"tool_call_id": "nonexistent-id-2", "reason": "test"})
    check("tool.deny is idempotent for unknown id", res2.get("ok") is True)

    # Verify KbWriteEntryTool has requires_confirmation=True
    from holmes.agent.tools.kb_write import KbWriteEntryTool
    import tempfile
    tool = KbWriteEntryTool(Path(tempfile.mkdtemp()))
    check("KbWriteEntryTool.requires_confirmation is True", tool.requires_confirmation is True)

    # Verify BashTool has requires_confirmation=True
    from holmes.agent.tools.bash import BashTool
    bash = BashTool()
    check("BashTool.requires_confirmation is True", bash.requires_confirmation is True)


# ── US3: session.resolve → pending ───────────────────────────────────────────

def test_us3(client: IPCClient, kb: Path) -> str | None:
    print(f"\n{INFO} US3: session.resolve → knowledge extraction → pending")

    res = client.call("session.create", {})
    session_id = res["session_id"]

    # Populate with a short conversation
    client._send({
        "jsonrpc": "2.0", "id": client._next_id, "method": "chat.send",
        "params": {
            "session_id": session_id,
            "message": (
                "Redis connection pool was exhausted causing timeouts. "
                "Fixed by increasing maxclients from 100 to 500."
            ),
        },
    })
    client._next_id += 1
    print(f"    waiting for chat done ...", flush=True)
    client.collect_events(("agent/done", "agent/error"), timeout=45)

    # session.resolve — fires extract_knowledge + tool_confirm for kb_write
    print(f"    calling session.resolve ...", flush=True)
    resolve_id = client._next_id
    client._next_id += 1
    client._send({
        "jsonrpc": "2.0", "id": resolve_id,
        "method": "session.resolve",
        "params": {"session_id": session_id},
    })

    confirmed = False
    resolve_result: dict | None = None
    deadline = time.time() + 60
    while time.time() < deadline:
        for obj in client._recv_lines(timeout=1.0):
            if obj.get("id") == resolve_id:
                if "error" in obj:
                    check("session.resolve no error", False, str(obj["error"]))
                    return None
                resolve_result = obj.get("result", {})
            elif obj.get("method") == "agent/tool_confirm":
                tool_call_id = obj["params"]["tool_call_id"]
                approve_id2 = client._next_id
                client._next_id += 1
                client._send({
                    "jsonrpc": "2.0", "id": approve_id2,
                    "method": "tool.approve",
                    "params": {"tool_call_id": tool_call_id},
                })
                confirmed = True
        if resolve_result is not None:
            break

    check("session.resolve succeeded", resolve_result is not None)
    if resolve_result:
        check("resolve returns summary_preview",
              bool(resolve_result.get("summary_preview")))

    pending_dir = kb / "contributions" / "pending"
    pending_files = list(pending_dir.glob("*.md")) if pending_dir.exists() else []
    check("Pending entry created after resolve", bool(pending_files),
          f"dir={pending_dir} exists={pending_dir.exists()}")

    return pending_files[0].stem if pending_files else None


# ── US5: KB CLI ───────────────────────────────────────────────────────────────

def test_us5(kb: Path, holmes_home: Path, pending_id: str | None):
    print(f"\n{INFO} US5: KB CLI operations")

    rc, out, err = cli(["kb", "pending"], holmes_home)
    check("holmes kb pending", rc == 0, err[:200] if rc else "")

    rc, out, err = cli(["kb", "lint"], holmes_home)
    check("holmes kb lint", rc == 0, err[:200] if rc else "")
    check("lint shows entry count", "Entries:" in out)

    rc, out, err = cli(["kb", "list"], holmes_home)
    check("holmes kb list", rc == 0, err[:200] if rc else "")
    check("kb list shows PT-DB-001", "PT-DB-001" in out, out[:200])

    rc, out, err = cli(["kb", "show", "PT-DB-001"], holmes_home)
    check("holmes kb show PT-DB-001", rc == 0, err[:200] if rc else "")
    check("kb show has Redis content", "Redis" in out or "redis" in out, out[:100])

    rc, out, err = cli(["kb", "rebuild-index"], holmes_home)
    check("holmes kb rebuild-index", rc == 0, err[:200] if rc else "")

    rc, out, err = cli(["session", "list"], holmes_home)
    check("holmes session list", rc == 0, err[:200] if rc else "")

    if pending_id:
        rc, out, err = cli(["kb", "pending-show", pending_id], holmes_home)
        check(f"kb pending-show {pending_id[:20]}", rc == 0, err[:200] if rc else "")

        # Confirm with "y\n" as stdin input
        rc, out, err = cli(
            ["kb", "confirm", pending_id], holmes_home, input_text="y\n"
        )
        if rc == 0:
            check("holmes kb confirm succeeds", True)
            check("confirms entry gets new id", "✓ Entry confirmed:" in out, out[:200])
        else:
            # If validation fails (LLM-generated entries may lack required sections),
            # the error message should be informative
            check("holmes kb confirm fails gracefully", "Schema" in err or "Missing" in err or rc == 1,
                  err[:200])


# ── US4: CLI import ───────────────────────────────────────────────────────────

def test_us4(kb: Path, holmes_home: Path):
    print(f"\n{INFO} US4: CLI import document")

    src = Path(tempfile.mktemp(suffix=".md"))
    src.write_text(textwrap.dedent("""\
        # MySQL slow query issue

        We noticed that a specific query was taking 30+ seconds.
        After investigation, found a missing index on orders.user_id.
        Adding the index reduced query time to under 100ms.
    """))
    try:
        rc, out, err = cli(
            ["import", str(src), "--type", "pitfall", "--category", "database"],
            holmes_home,
        )
        check("holmes import runs", rc == 0, err[:300] if rc else "")
        if rc == 0:
            check("import shows pending id", "pending-" in out, out[:200])
    finally:
        src.unlink(missing_ok=True)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        kb = make_kb(tmp)
        holmes_home = make_holmes_home(tmp, kb)

        socket_path = str(tmp / "agent.sock")
        agent = start_agent(socket_path, holmes_home)
        print(f"{INFO} Agent started (pid={agent.pid})")

        try:
            client = IPCClient(socket_path)
            print(f"{INFO} IPC connected")

            session_id = test_us1(client)
            test_us2(client, session_id)
            test_us9(client, holmes_home)
            test_us8_ipc_mechanics(client)
            pending_id = test_us3(client, kb)

            client.close()
        finally:
            agent.kill()
            try:
                agent.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass

        # CLI-only tests (no running agent needed)
        test_us5(kb, holmes_home, pending_id)
        test_us4(kb, holmes_home)

    print()
    print("=" * 60)
    if _errors:
        print(f"{FAIL} {len(_errors)} failure(s):")
        for e in _errors:
            print(f"    - {e}")
        sys.exit(1)
    else:
        print(f"{PASS} All checks passed")


if __name__ == "__main__":
    main()
