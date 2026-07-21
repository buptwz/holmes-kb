"""Golden loop test for spec 043 (M1): the full KB knowledge lifecycle.

One end-to-end pass through the documented workflow, asserting the state
transition at every step so any break in the chain turns this test red:

  import (mocked LLM) → pending → approve → browse visible
  → read(full, session A) → confirm(solved) → verified
  → read(full, session B) → confirm(solved, 2nd contributor) → proven
  → decay (evidence aged past threshold) → proven demoted to verified

The LLM is mocked with the same MockProvider pattern as
``test_042_pipeline.py`` — three scripted responses (classify → summarize →
generate) injected via ``ImportPipeline(_provider=...)``.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import frontmatter
import pytest

from holmes.config import HolmesConfig
from holmes.kb.agent.pipeline import ImportPipeline
from holmes.kb.decay import run_decay
from holmes.kb.store import approve_entry, derive_entry_maturity, rebuild_index_files
from holmes.mcp.tools import handle_kb_browse, handle_kb_confirm, handle_kb_read

# ---------------------------------------------------------------------------
# Mock LLM provider (same pattern as test_042_pipeline.py)
# ---------------------------------------------------------------------------


class MockProvider:
    """Scripted LLM provider: returns queued responses, then "{}" """

    def __init__(self, responses: list[str]):
        self._responses = responses
        self._call_idx = 0

    def _next(self) -> str:
        text = self._responses[self._call_idx] if self._call_idx < len(self._responses) else "{}"
        self._call_idx += 1
        return text

    def complete(self, messages, system, model, max_tokens, tools=None):
        text = self._next()
        return True, [], [*messages, {"role": "assistant", "content": text}], {}

    def simple_complete(self, messages, system="", max_tokens=512):
        return self._next()

    def append_tool_results(self, messages, results):
        for tool_id, result in results:
            messages.append({"role": "tool", "tool_use_id": tool_id, "content": result})
        return messages


# ---------------------------------------------------------------------------
# Synthetic source document + scripted LLM responses
# ---------------------------------------------------------------------------

_SOURCE_DOC = """\
# PLL Lock Failure on Gen2 DVT

During DVT bring-up of the Gen2 serdes board, PLL_LOCK stayed low after
reset release. The REFCLK amplitude measured 350mVpp, below the 400mVpp
spec minimum. Re-tuning the clock generator output drive to 500mVpp
restored PLL lock within 2ms.
"""

_CLASSIFIER_RESP = (
    '{"doc_type": "incident", "suggested_type": "pitfall", '
    '"language": "en", "reason": "hardware bring-up failure"}'
)

_SUMMARIZER_RESP = (
    '{"brief": "PLL lock failure on Gen2 DVT caused by out-of-spec REFCLK amplitude", '
    '"key_facts": ["REFCLK spec minimum is 400mVpp"], '
    '"commands": ["cat /sys/class/clkgen/output_drive"], '
    '"symptoms": ["PLL_LOCK stays low after reset release"], '
    '"resolution_branches": []}'
)

_GENERATOR_RESP = (
    "---\n"
    "id: pll-lock-001\n"
    "type: pitfall\n"
    "category: hardware\n"
    'title: "PLL Lock Failure on Gen2 DVT"\n'
    'brief: "PLL lock failure on Gen2 DVT caused by out-of-spec REFCLK amplitude"\n'
    "tags: [pll, dvt, refclk]\n"
    "language: en\n"
    "---\n\n"
    "## Contents\n\n"
    "| Section | Description |\n"
    "|---|---|\n"
    "| Symptoms | PLL_LOCK low |\n"
    "| Root Cause | REFCLK amplitude out of spec |\n"
    "| Resolution | Re-tune clock generator drive |\n\n"
    "## Symptoms\n"
    "- PLL_LOCK stays low after reset release\n\n"
    "## Root Cause\n"
    "REFCLK amplitude 350mVpp, below the 400mVpp spec minimum.\n\n"
    "## Resolution\n"
    "1. [physical] Probe REFCLK amplitude with oscilloscope\n"
    "2. [api] `cat /sys/class/clkgen/output_drive`\n"
    "3. [remote] Re-tune clock generator output drive to 500mVpp\n"
)


# ---------------------------------------------------------------------------
# The golden loop
# ---------------------------------------------------------------------------


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    return tmp_path


def _evidence_dir(kb_root: Path, entry_id: str) -> Path:
    return kb_root / "contributions" / "evidence" / entry_id


def test_golden_loop(kb_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # ------------------------------------------------------------------
    # Step 1 — import: synthetic doc through the real pipeline, mock LLM.
    # ------------------------------------------------------------------
    provider = MockProvider([_CLASSIFIER_RESP, _SUMMARIZER_RESP, _GENERATOR_RESP])
    pipeline = ImportPipeline(
        kb_root=kb_root,
        cfg=HolmesConfig(model="test"),
        no_interactive=True,
        _provider=provider,
    )
    report = pipeline.run(_SOURCE_DOC)
    assert len(report.errors) == 0, f"import errors: {report.errors}"
    assert len(report.created) == 1, f"expected exactly 1 entry, got {report.created}"

    pending_files = list((kb_root / "contributions" / "pending").glob("*.md"))
    assert len(pending_files) == 1, "import must produce one pending entry"
    pending_id = frontmatter.load(str(pending_files[0])).metadata["id"]

    # ------------------------------------------------------------------
    # Step 2 — approve: pending → confirmed space, kb_status=active.
    # Approve mints a permanent ID (spec 043, T021b); the temporary
    # pending ID is kept only in the `former_id` field for traceability.
    # ------------------------------------------------------------------
    new_path = approve_entry(kb_root, pending_id)
    entry_id = new_path.stem
    assert re.fullmatch(r"[A-Z]{2}-[A-Z]{2,3}-[0-9a-f]{6}", entry_id), (
        f"approve must mint a permanent ID, got {entry_id!r}"
    )
    assert new_path == kb_root / "pitfall" / "hardware" / f"{entry_id}.md"
    assert new_path.exists()
    assert not pending_files[0].exists(), "pending source file must be moved away"
    post = frontmatter.load(str(new_path))
    assert post.metadata["kb_status"] == "active"
    assert post.metadata["former_id"] == pending_id
    assert "pending" not in post.metadata, "pending-workflow fields must be stripped"

    # ------------------------------------------------------------------
    # Step 3 — browse: the approved entry is visible (as draft).
    # ------------------------------------------------------------------
    browse = handle_kb_browse(kb_root)
    matches = [e for e in browse.get("entries", []) if e.get("id") == entry_id]
    assert len(matches) == 1, f"entry not visible in kb_browse: {browse.get('entries')}"
    assert matches[0]["maturity"] == "draft"

    # ------------------------------------------------------------------
    # Step 4 — read(full, session A): referenced evidence is recorded.
    # ------------------------------------------------------------------
    read_result = handle_kb_read(kb_root, entry_id, detail="full", session_id="sess-A")
    assert "content" in read_result
    assert "## Resolution" in read_result["content"]
    sidecar_a = _evidence_dir(kb_root, entry_id) / "sess-A.json"
    assert sidecar_a.exists(), "read(full) must record a referenced evidence sidecar"
    assert json.loads(sidecar_a.read_text(encoding="utf-8"))["outcome"] == "referenced"

    # ------------------------------------------------------------------
    # Step 5 — confirm(solved, session A, 张三): ok + promoted to verified.
    # Guards the read→confirm upgrade path (must NOT be judged duplicate).
    # ------------------------------------------------------------------
    monkeypatch.setattr("holmes.mcp.tools._get_contributor", lambda _root: "zhangsan")
    confirm_a = handle_kb_confirm(kb_root, entry_id, "sess-A", outcome="solved")
    assert confirm_a.get("ok") is True, f"confirm after read rejected: {confirm_a}"
    assert confirm_a["maturity"] == "verified"
    assert confirm_a["promoted"] is True
    assert derive_entry_maturity(kb_root, entry_id) == "verified"
    post = frontmatter.load(str(new_path))
    assert post.metadata["maturity"] == "verified", "frontmatter cache must be promoted"

    # ------------------------------------------------------------------
    # Step 6 — second contributor (李四, session B): read → confirm → proven.
    # ------------------------------------------------------------------
    handle_kb_read(kb_root, entry_id, detail="full", session_id="sess-B")
    monkeypatch.setattr("holmes.mcp.tools._get_contributor", lambda _root: "lisi")
    confirm_b = handle_kb_confirm(kb_root, entry_id, "sess-B", outcome="solved")
    assert confirm_b.get("ok") is True, f"second confirm rejected: {confirm_b}"
    assert confirm_b["maturity"] == "proven", (
        "2 solved sessions x 2 distinct contributors must yield proven"
    )
    assert derive_entry_maturity(kb_root, entry_id) == "proven"
    post = frontmatter.load(str(new_path))
    assert post.metadata["maturity"] == "proven"

    # ------------------------------------------------------------------
    # Step 7 — decay: age all evidence past the 12-month proven threshold.
    # run_decay reads reference dates from evidence, so we rewrite the
    # sidecar record dates to 400 days ago (no clock injection point in
    # the decay module; 400 days → 13 months > DEFAULT_PROVEN_MONTHS).
    # ------------------------------------------------------------------
    stale_date = (date.today() - timedelta(days=400)).isoformat()
    evidence_dir = _evidence_dir(kb_root, entry_id)
    sidecars = sorted(evidence_dir.glob("*.json"))
    assert len(sidecars) == 2, f"expected 2 session sidecars, got {sidecars}"
    for sidecar in sidecars:
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        record["date"] = stale_date
        sidecar.write_text(json.dumps(record), encoding="utf-8")

    decay = run_decay(kb_root)
    demotions = [c for c in decay.changes if c.id == entry_id]
    assert len(demotions) == 1, f"expected one demotion, got {decay.changes}"
    assert demotions[0].old_maturity == "proven"
    assert demotions[0].new_maturity == "verified"

    # Decay demotes the frontmatter maturity cache, snapshots the old version
    # to .history/, and records a system "decayed" evidence sidecar — so the
    # evidence-derived maturity drops too and does not bounce back when
    # rebuild recalibrates the cache (T017a).
    post = frontmatter.load(str(new_path))
    assert post.metadata["maturity"] == "verified"
    assert list((kb_root / ".history").glob(f"{entry_id}-*.md")), "decay must snapshot first"
    decay_sidecars = list(_evidence_dir(kb_root, entry_id).glob("decay-*.json"))
    assert len(decay_sidecars) == 1, "decay must write a system evidence sidecar"
    decay_record = json.loads(decay_sidecars[0].read_text(encoding="utf-8"))
    assert decay_record["outcome"] == "decayed"
    assert decay_record["contributor"] == "system"
    assert decay_record["maturity_after"] == "verified"
    assert derive_entry_maturity(kb_root, entry_id) == "verified"
    rebuild_index_files(kb_root)
    assert derive_entry_maturity(kb_root, entry_id) == "verified", (
        "recalibration must not bounce the decayed level back to proven"
    )
