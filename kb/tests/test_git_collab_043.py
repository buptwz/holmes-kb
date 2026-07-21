"""T028 — dual-client git collaboration integration test (spec 043, D2/D5).

Two clones of one bare remote each write_pending → confirm → commit → push
(same category, same time).  Client B's push is rejected, it rebases onto
A's commit and pushes again — with no manual conflict resolution.

Asserts:
- UUID-format IDs (D2) minted on both sides do not collide
- contributions/log.md union-merges via .gitattributes, no lines lost
- index.json / **/_index.md stay untracked (D5) — no merge conflicts
- both entries survive the merge; rebuild_index_files works afterwards
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from holmes.cli import cli
from holmes.kb.pending import write_pending
from holmes.kb.store import find_entry, list_entries, rebuild_index_files

KB_TEMPLATE = Path(__file__).resolve().parents[2] / "kb-template"

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Holmes Test",
    "GIT_AUTHOR_EMAIL": "holmes-test@example.com",
    "GIT_COMMITTER_NAME": "Holmes Test",
    "GIT_COMMITTER_EMAIL": "holmes-test@example.com",
    # Hermetic: ignore the developer's global/system gitconfig.
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}

_UUID_ID_RE = re.compile(r"[A-Z]{2}-[A-Z]{2,3}-[0-9a-f]{6}")


def _git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=_GIT_ENV, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed (exit {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result


def _pending_content(title: str, symptom: str) -> str:
    return (
        "---\n"
        "type: pitfall\n"
        f"title: {title}\n"
        "category: database\n"
        "tags: [git-collab]\n"
        "maturity: draft\n"
        'created_at: "2026-01-01T00:00:00+00:00"\n'
        'updated_at: "2026-01-01T00:00:00+00:00"\n'
        "---\n\n"
        "## Symptoms\n"
        f"{symptom}\n\n"
        "## Root Cause\n"
        "Root cause text.\n\n"
        "## Resolution\n"
        "Resolution text.\n"
    )


def _write_and_confirm(kb_root: Path, title: str, symptom: str, contributor: str) -> tuple[str, str]:
    """write_pending → `holmes confirm` (mints the UUID permanent ID).

    Returns (pending_id, permanent_id).
    """
    pending_id = write_pending(kb_root, _pending_content(title, symptom), source="auto")
    result = CliRunner().invoke(
        cli,
        ["--kb-path", str(kb_root), "confirm", pending_id, "--contributor", contributor],
        input="y\ny\n",
    )
    assert result.exit_code == 0, result.output
    match = re.search(r"Entry confirmed: (\S+)", result.output)
    assert match, result.output
    return pending_id, match.group(1)


def _commit_all(repo: Path, message: str) -> None:
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", message, cwd=repo)


@pytest.fixture()
def git_remotes(tmp_path: Path) -> tuple[Path, Path]:
    """Bare remote seeded from kb-template, plus two clones (A, B)."""
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    _git("init", "-b", "main", str(seed), cwd=tmp_path)
    shutil.copytree(KB_TEMPLATE, seed, dirs_exist_ok=True)
    _commit_all(seed, "seed kb-template")
    _git("remote", "add", "origin", str(remote), cwd=seed)
    _git("push", "-u", "origin", "main", cwd=seed)

    clone_a = tmp_path / "clone-a"
    clone_b = tmp_path / "clone-b"
    _git("clone", str(remote), str(clone_a), cwd=tmp_path)
    _git("clone", str(remote), str(clone_b), cwd=tmp_path)
    return clone_a, clone_b


def test_dual_client_collab(git_remotes: tuple[Path, Path]) -> None:
    clone_a, clone_b = git_remotes

    # --- Client A: pending → confirm → push ---
    pending_a, id_a = _write_and_confirm(
        clone_a, "Redis pool exhausted under peak load",
        "Redis operations timing out under load", contributor="alice",
    )
    _commit_all(clone_a, "alice: confirm redis pitfall")
    _git("push", "origin", "main", cwd=clone_a)

    # --- Client B: same flow concurrently; push rejected → rebase → push ---
    pending_b, id_b = _write_and_confirm(
        clone_b, "MySQL deadlock on concurrent inserts",
        "Transactions hang then roll back", contributor="bob",
    )
    _commit_all(clone_b, "bob: confirm mysql pitfall")
    rejected = _git("push", "origin", "main", cwd=clone_b, check=False)
    assert rejected.returncode != 0, "B's first push must be rejected (non-fast-forward)"
    _git("pull", "--rebase", "origin", "main", cwd=clone_b)
    _git("push", "origin", "main", cwd=clone_b)

    # --- D2: UUID-format IDs, no collision across clients ---
    assert _UUID_ID_RE.fullmatch(id_a), id_a
    assert _UUID_ID_RE.fullmatch(id_b), id_b
    assert id_a != id_b

    # --- D5: log.md union-merged by git, both sides' lines present ---
    log_text = (clone_b / "contributions" / "log.md").read_text(encoding="utf-8")
    assert pending_a in log_text
    assert pending_b in log_text

    # No conflict markers survived anywhere in the merged working tree.
    for path in clone_b.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            assert "<<<<<<<" not in path.read_text(
                encoding="utf-8", errors="ignore"
            ), f"conflict markers left in {path}"

    # `holmes merge` agrees there is nothing left to resolve.
    merge_result = CliRunner().invoke(cli, ["--kb-path", str(clone_b), "merge"])
    assert merge_result.exit_code == 0
    assert "No git conflict markers" in merge_result.output

    # --- D5: derived files never tracked → cannot conflict ---
    tracked = _git("ls-files", cwd=clone_b).stdout.splitlines()
    assert "index.json" not in tracked
    assert not any(t.endswith("_index.md") for t in tracked)

    # --- Both ordinary entries survive; index rebuild works post-merge ---
    ids = {e.id for e in list_entries(clone_b)}
    assert {id_a, id_b} <= ids

    rebuild_index_files(clone_b)
    index = json.loads((clone_b / "index.json").read_text(encoding="utf-8"))
    index_ids = {e["id"] for e in index["entries"]}
    assert {id_a, id_b} <= index_ids
    for rec in index["entries"]:
        assert not Path(rec["file_path"]).is_absolute()

    # find_entry resolves both entries through the rebuilt relative-path index.
    assert find_entry(clone_b, id_a) is not None
    assert find_entry(clone_b, id_b) is not None
