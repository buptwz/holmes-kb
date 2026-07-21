"""Tests for spec 043 D3/D4 (T023-T026): caller-declared identity,
hardened session_id, and local/central deployment modes.

- contributor param on kb_browse/kb_read/kb_confirm/kb_draft takes priority
  over the git-config fallback (_get_contributor).
- kb_browse session_id is a full uuid4; kb_confirm rejects empty session_id.
- Two distinct contributors confirming on the same kb_root reach proven
  (P4 reverse proof: previously mathematically impossible in central mode).
- central mode: contributor is mandatory on kb_confirm/kb_draft, and the
  HTTP transport requires the static bearer token from config.mcp_token.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from click.testing import CliRunner

from holmes.config import HolmesConfig
from holmes.kb.store import derive_entry_maturity
from holmes.mcp.tools import (
    handle_kb_browse,
    handle_kb_confirm,
    handle_kb_draft,
    handle_kb_read,
)


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    return tmp_path


def _make_entry(kb_root: Path, entry_id: str = "PT-DB-001") -> Path:
    entry_dir = kb_root / "pitfall" / "db"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    content = (
        f"---\n"
        f"id: {entry_id}\n"
        f"type: pitfall\n"
        f"title: Redis OOM\n"
        f"maturity: draft\n"
        f"category: db\n"
        f"tags: [redis]\n"
        f'created_at: "2024-01-01T00:00:00+00:00"\n'
        f'updated_at: "2024-01-01T00:00:00+00:00"\n'
        f'brief: "Redis OOM troubleshooting"\n'
        f"---\n\n"
        "## Symptoms\n- OOM\n\n## Root Cause\nX\n\n## Resolution\n1. X\n"
    )
    entry_path.write_text(content, encoding="utf-8")
    return entry_path


def _evidence(kb_root: Path, entry_id: str, session_id: str) -> dict:
    sidecar = kb_root / "contributions" / "evidence" / entry_id / f"{session_id}.json"
    return json.loads(sidecar.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# T024 — session_id hardening
# ---------------------------------------------------------------------------


class TestSessionId:
    def test_browse_generates_full_uuid(self, kb_root: Path):
        result = handle_kb_browse(kb_root)
        # Must parse as a uuid — the old [:8] truncation would fail this.
        assert str(uuid.UUID(result["session_id"])) == result["session_id"]

    def test_confirm_empty_session_id_rejected(self, kb_root: Path):
        _make_entry(kb_root)
        for sid in ("", "   "):
            result = handle_kb_confirm(kb_root, "PT-DB-001", sid, outcome="solved")
            assert result["ok"] is False
            assert result["reason"] == "missing_session_id"
            assert result["hint"] == "call kb_browse first to get a session_id"
        # No anonymous evidence bucket may be written (store.py unknown.json path).
        evidence_dir = kb_root / "contributions" / "evidence" / "PT-DB-001"
        assert not evidence_dir.exists()

    def test_confirm_empty_sid_rejected_before_not_found(self, kb_root: Path):
        result = handle_kb_confirm(kb_root, "NOPE", "", outcome="solved")
        assert result["reason"] == "missing_session_id"


# ---------------------------------------------------------------------------
# T023/T025 — contributor declaration
# ---------------------------------------------------------------------------


class TestContributor:
    def test_param_overrides_git_config(self, kb_root: Path, monkeypatch: pytest.MonkeyPatch):
        _make_entry(kb_root)
        monkeypatch.setattr("holmes.mcp.tools._get_contributor", lambda _root: "git-user")
        result = handle_kb_confirm(
            kb_root, "PT-DB-001", "sess-1", outcome="solved", contributor="declared-user"
        )
        assert result["ok"] is True
        assert result["contributor"] == "declared-user"
        assert _evidence(kb_root, "PT-DB-001", "sess-1")["contributor"] == "declared-user"

    def test_falls_back_to_git_config_when_empty(self, kb_root: Path, monkeypatch: pytest.MonkeyPatch):
        _make_entry(kb_root)
        monkeypatch.setattr("holmes.mcp.tools._get_contributor", lambda _root: "git-user")
        result = handle_kb_confirm(kb_root, "PT-DB-001", "sess-1", outcome="solved")
        assert result["ok"] is True
        assert result["contributor"] == "git-user"

    def test_read_full_records_declared_contributor(self, kb_root: Path):
        _make_entry(kb_root)
        handle_kb_read(kb_root, "PT-DB-001", detail="full", session_id="sess-1", contributor="alice")
        record = _evidence(kb_root, "PT-DB-001", "sess-1")
        assert record["outcome"] == "referenced"
        assert record["contributor"] == "alice"

    def test_two_contributors_reach_proven(self, kb_root: Path):
        """P4 reverse proof: two distinct declared contributors on the same
        kb_root (central-mode shape) read+confirm → proven."""
        _make_entry(kb_root)

        browse = handle_kb_browse(kb_root)
        sid_a = browse["session_id"]
        handle_kb_read(kb_root, "PT-DB-001", detail="full", session_id=sid_a, contributor="alice")
        confirm_a = handle_kb_confirm(kb_root, "PT-DB-001", sid_a, outcome="solved", contributor="alice")
        assert confirm_a["ok"] is True
        assert confirm_a["maturity"] == "verified"

        sid_b = handle_kb_browse(kb_root)["session_id"]
        handle_kb_read(kb_root, "PT-DB-001", detail="full", session_id=sid_b, contributor="bob")
        confirm_b = handle_kb_confirm(kb_root, "PT-DB-001", sid_b, outcome="solved", contributor="bob")
        assert confirm_b["ok"] is True
        assert confirm_b["maturity"] == "proven"
        assert derive_entry_maturity(kb_root, "PT-DB-001") == "proven"

    def test_browse_guide_mentions_contributor(self, kb_root: Path):
        result = handle_kb_browse(kb_root)
        assert "contributor" in result["guide"]


# ---------------------------------------------------------------------------
# T042 — embedded guidance (the guide is the agent's only user manual)
# ---------------------------------------------------------------------------


class TestBrowseGuide:
    def test_guide_covers_methodology_keywords(self, kb_root: Path):
        guide = handle_kb_browse(kb_root)["guide"]
        for keyword in ("kb_confirm", "contributor", "session_id", "kb_draft", "kb_read"):
            assert keyword in guide, f"guide missing {keyword!r}"

    def test_guide_covers_all_behavior_tags(self, kb_root: Path):
        guide = handle_kb_browse(kb_root)["guide"]
        for tag in ("[api:read]", "[api:write]", "[api:danger]", "[physical]",
                    "[remote]", "[decide]", "[verify]"):
            assert tag in guide, f"guide missing behavior tag {tag!r}"


# ---------------------------------------------------------------------------
# T026 — central mode enforcement (tools layer)
# ---------------------------------------------------------------------------


class TestCentralEnforcement:
    def test_confirm_requires_contributor(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_confirm(
            kb_root, "PT-DB-001", "sess-1", outcome="solved", require_contributor=True
        )
        assert result["ok"] is False
        assert result["reason"] == "missing_contributor"
        assert "contributor" in result["hint"]

        ok = handle_kb_confirm(
            kb_root, "PT-DB-001", "sess-1", outcome="solved",
            contributor="alice", require_contributor=True,
        )
        assert ok["ok"] is True
        assert ok["contributor"] == "alice"

    def test_draft_requires_contributor(self, kb_root: Path):
        cfg = HolmesConfig(username="someone")
        result = handle_kb_draft(
            kb_root, content="x", title=None, config=cfg, require_contributor=True
        )
        assert result["ok"] is False
        assert result["reason"] == "missing_contributor"

    def test_draft_contributor_becomes_author(self, kb_root: Path):
        cfg = HolmesConfig(username="config-user")
        result = handle_kb_draft(
            kb_root, content="body", title="t1", config=cfg, contributor="declared-user"
        )
        assert result["ok"] is True
        draft = (kb_root / "_drafts" / "t1.md").read_text(encoding="utf-8")
        assert "author: declared-user" in draft


# ---------------------------------------------------------------------------
# T026 — static token auth (server layer)
# ---------------------------------------------------------------------------


class TestStaticTokenAuth:
    def test_verifier_accepts_config_token(self):
        from holmes.mcp.server import StaticTokenVerifier

        verifier = StaticTokenVerifier("secret-token")
        token = asyncio.run(verifier.verify_token("secret-token"))
        assert token is not None
        assert token.token == "secret-token"

    def test_verifier_rejects_wrong_token(self):
        from holmes.mcp.server import StaticTokenVerifier

        verifier = StaticTokenVerifier("secret-token")
        assert asyncio.run(verifier.verify_token("wrong")) is None

    def test_http_layer_requires_bearer_token(self):
        """The FastMCP auth wiring rejects unauthenticated /mcp requests."""
        from mcp.server.auth.settings import AuthSettings
        from mcp.server.fastmcp import FastMCP
        from starlette.testclient import TestClient

        from holmes.mcp.server import StaticTokenVerifier

        m = FastMCP(
            "test-auth",
            token_verifier=StaticTokenVerifier("secret-token"),
            auth=AuthSettings(
                issuer_url="http://127.0.0.1:8765",
                resource_server_url="http://127.0.0.1:8765",
            ),
        )
        m.settings.stateless_http = True
        app = m.streamable_http_app()
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        with TestClient(app, raise_server_exceptions=False) as client:
            assert client.post("/mcp", json=body).status_code == 401
            assert client.post(
                "/mcp", json=body, headers={"Authorization": "Bearer wrong"}
            ).status_code == 401
            # Auth passed → any non-401 response (the MCP layer may still
            # reject the request itself, but not with an auth error).
            assert client.post(
                "/mcp", json=body, headers={"Authorization": "Bearer secret-token"}
            ).status_code != 401


# ---------------------------------------------------------------------------
# T026 — CLI --mode/--host wiring
# ---------------------------------------------------------------------------


class TestStartCommand:
    def _invoke(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, args: list[str]):
        import holmes.mcp.server as server_mod
        from holmes.cli import cli

        calls: list[dict] = []
        monkeypatch.setattr(
            server_mod, "run_server",
            lambda kb_root, **kwargs: calls.append({"kb_root": kb_root, **kwargs}),
        )
        result = CliRunner().invoke(cli, ["--kb-path", str(tmp_path), "start", *args])
        assert result.exit_code == 0, result.output
        assert len(calls) == 1
        return calls[0]

    def test_local_defaults(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        call = self._invoke(monkeypatch, tmp_path, [])
        assert call["mode"] == "local"
        assert call["host"] == "127.0.0.1"
        assert call["port"] == 8765

    def test_central_binds_all_interfaces(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        call = self._invoke(monkeypatch, tmp_path, ["--mode", "central"])
        assert call["mode"] == "central"
        assert call["host"] == "0.0.0.0"

    def test_host_overrides_central_default(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        call = self._invoke(monkeypatch, tmp_path, ["--mode", "central", "--host", "10.0.0.5"])
        assert call["host"] == "10.0.0.5"


class TestRunServerCentral:
    def test_central_without_token_refuses(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        import holmes.mcp.server as server_mod

        monkeypatch.setattr(server_mod, "load_config", lambda: HolmesConfig(mcp_token=""))
        with pytest.raises(ValueError, match="mcp_token"):
            server_mod.run_server(tmp_path, mode="central")

    def test_central_with_token_configures_auth(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        import holmes.mcp.server as server_mod

        monkeypatch.setattr(
            server_mod, "load_config", lambda: HolmesConfig(mcp_token="secret-token")
        )
        monkeypatch.setattr(server_mod.mcp, "run", lambda **kwargs: None)
        try:
            server_mod.run_server(tmp_path, host="0.0.0.0", port=9999, mode="central")
            assert server_mod.mcp.settings.auth is not None
            assert isinstance(server_mod.mcp._token_verifier, server_mod.StaticTokenVerifier)
            assert server_mod._mode == "central"
        finally:
            server_mod.mcp.settings.auth = None
            server_mod.mcp._token_verifier = None
            server_mod._mode = "local"

    def test_local_mode_requires_no_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        import holmes.mcp.server as server_mod

        monkeypatch.setattr(server_mod, "load_config", lambda: HolmesConfig())
        monkeypatch.setattr(server_mod.mcp, "run", lambda **kwargs: None)
        server_mod.run_server(tmp_path, mode="local")
        assert server_mod.mcp.settings.auth is None
