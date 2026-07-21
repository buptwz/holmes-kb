"""Tests for doctor check 18: entry hygiene (--fix) and not_solved feedback."""

from __future__ import annotations

import json
from pathlib import Path

from holmes.kb.doctor import run_doctor


def _make_entry(kb_root: Path, entry_id: str, body: str, extra_fm: str = "") -> Path:
    entry_dir = kb_root / "pitfall" / "hardware"
    entry_dir.mkdir(parents=True, exist_ok=True)
    path = entry_dir / f"{entry_id}.md"
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        "type: pitfall\n"
        "title: Test Entry\n"
        "maturity: draft\n"
        "category: hardware\n"
        "tags: [test]\n"
        'created_at: "2024-01-01T00:00:00+00:00"\n'
        'updated_at: "2024-01-01T00:00:00+00:00"\n'
        f"{extra_fm}"
        "---\n\n"
        "## Symptoms\n- something fails\n\n"
        "## Root Cause\nSomething.\n\n"
        "## Resolution\n"
        f"{body}",
        encoding="utf-8",
    )
    return path


def _levels(report, level: str) -> list[str]:
    return [i.message for i in report.items if i.level == level]


class TestEntryHygiene:
    def test_mistagged_write_command_warns(self, tmp_path: Path) -> None:
        _make_entry(
            tmp_path, "PT-HW-aaaaaa",
            "1. [api:read] 改写寄存器\n   ```bash\n   i2cset -y 3 0x50 0x14 0x77\n   ```\n",
        )
        report = run_doctor(tmp_path, fix=False, check_api=False)
        warns = _levels(report, "warn")
        assert any("行为标签疑似误标" in w and "read→write" in w for w in warns)

    def test_fix_corrects_tag(self, tmp_path: Path) -> None:
        path = _make_entry(
            tmp_path, "PT-HW-bbbbbb",
            "1. [api:read] 改写寄存器\n   ```bash\n   i2cset -y 3 0x50 0x14 0x77\n   ```\n",
        )
        report = run_doctor(tmp_path, fix=True, check_api=False)
        assert any("corrected 1 behavior tag" in m for m in _levels(report, "fixed"))
        assert "[api:write]" in path.read_text(encoding="utf-8")

    def test_correct_tag_untouched(self, tmp_path: Path) -> None:
        _make_entry(
            tmp_path, "PT-HW-cccccc",
            "1. [api:read] 读状态\n   ```bash\n   i2cget -y 3 0x50 0x0C\n   ```\n",
        )
        report = run_doctor(tmp_path, fix=False, check_api=False)
        assert not any("行为标签疑似误标" in w for w in _levels(report, "warn"))

    def test_danger_escalation(self, tmp_path: Path) -> None:
        _make_entry(
            tmp_path, "PT-HW-dddddd",
            "1. [api:read] 升级固件\n   ```bash\n   retimer-cli fw update /tmp/fw.bin\n   ```\n",
        )
        report = run_doctor(tmp_path, fix=False, check_api=False)
        assert any("read→danger" in w for w in _levels(report, "warn"))

    def test_placeholder_firmware_warns_and_fixed(self, tmp_path: Path) -> None:
        path = _make_entry(
            tmp_path, "PT-HW-eeeeee",
            "1. [api:read] `i2cget -y 3 0x50 0x0C`\n",
            extra_fm="applies_to:\n  firmware: unknown\n  product_line: [serdes-gen2]\n",
        )
        report = run_doctor(tmp_path, fix=False, check_api=False)
        assert any("占位噪声" in w for w in _levels(report, "warn"))

        report = run_doctor(tmp_path, fix=True, check_api=False)
        text = path.read_text(encoding="utf-8")
        assert "unknown" not in text
        assert "serdes-gen2" in text  # real values preserved


class TestNotSolvedFeedback:
    def test_not_solved_flagged(self, tmp_path: Path) -> None:
        _make_entry(tmp_path, "PT-HW-ffffff", "1. [api:read] `i2cget -y 3 0x50 0x0C`\n")
        sidecar_dir = tmp_path / "contributions" / "evidence" / "PT-HW-ffffff"
        sidecar_dir.mkdir(parents=True)
        (sidecar_dir / "sess-1.json").write_text(json.dumps({
            "session_id": "sess-1", "contributor": "a", "date": "2026-07-20", "outcome": "not_solved",
        }), encoding="utf-8")
        report = run_doctor(tmp_path, fix=False, check_api=False, verbose=True)
        warns = _levels(report, "warn")
        assert any("not_solved" in w and "PT-HW-ffffff" in w for w in warns)

    def test_solved_only_not_flagged(self, tmp_path: Path) -> None:
        _make_entry(tmp_path, "PT-HW-777777", "1. [api:read] `i2cget -y 3 0x50 0x0C`\n")
        sidecar_dir = tmp_path / "contributions" / "evidence" / "PT-HW-777777"
        sidecar_dir.mkdir(parents=True)
        (sidecar_dir / "sess-1.json").write_text(json.dumps({
            "session_id": "sess-1", "contributor": "a", "date:": "2026-07-20", "outcome": "solved",
        }), encoding="utf-8")
        report = run_doctor(tmp_path, fix=False, check_api=False)
        assert any(i.level == "ok" and i.category == "feedback" for i in report.items)
