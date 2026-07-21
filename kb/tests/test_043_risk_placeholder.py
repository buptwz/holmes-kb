"""Tests for spec 043 T045 (deterministic risk floor) and T047 (placeholder noise).

T045: write-ish commands must never be tagged [api:read] even when the LLM
mislabels risk — regression cases are real commands from the 2026-07-20 E2E
imports (PLL i2cset/fw-update mistagged read; PCIe setpci correctly write).
T047: applies_to placeholder strings ("unknown", "N/A", …) mean "no
information" and must be dropped, not stored.
"""

from __future__ import annotations

from holmes.kb.agent.phases.generator import _step_behavior_tag
from holmes.kb.agent.phases.summarizer import _normalize_summary
from holmes.kb.agent.risk import correct_command_risk, infer_command_risk

# ---------------------------------------------------------------------------
# T045 — deterministic risk floor
# ---------------------------------------------------------------------------


class TestInferCommandRisk:
    def test_write_verbs_are_write(self) -> None:
        for cmd in (
            "i2cset -y 3 0x50 0x14 0x77",
            "setpci -s $ROOT_BDF CAP_EXP+0x10.w=0020:0020",
            "retimer-cli cfg save",
            "fanctl set --all 100",
        ):
            assert infer_command_risk(cmd) == "write", cmd

    def test_danger_verbs_are_danger(self) -> None:
        for cmd in (
            "retimer-cli fw update /tmp/retimer-fw-2.3.5.bin",
            "firmware update --slot 0",
            "flash bios --force",
        ):
            assert infer_command_risk(cmd) == "danger", cmd

    def test_generic_update_is_write_not_danger(self) -> None:
        # Bare "update" (e.g. phosphor-bmc-code-mgmt update) floors at write;
        # the LLM may still escalate it to danger, which is preserved.
        assert infer_command_risk("phosphor-bmc-code-mgmt update /tmp/obmc.static.mtd.tar") == "write"
        assert correct_command_risk("danger", "phosphor-bmc-code-mgmt update /tmp/x.tar") == "danger"

    def test_read_commands_stay_read(self) -> None:
        for cmd in ("lspci -tv", "i2cget -y 3 0x50 0x0C", "dmesg | tail -20", "cat /tmp/x"):
            assert infer_command_risk(cmd) == "read", cmd


class TestCorrectCommandRisk:
    def test_llm_cannot_downgrade_inferred_risk(self) -> None:
        # The E2E failure mode: LLM said "read" for write commands.
        assert correct_command_risk("read", "i2cset -y 3 0x50 0x14 0x77") == "write"
        assert correct_command_risk("read", "retimer-cli fw update /tmp/x.bin") == "danger"

    def test_llm_may_escalate(self) -> None:
        assert correct_command_risk("danger", "lspci -tv") == "danger"
        assert correct_command_risk("write", "i2cget -y 3 0x50 0x0C") == "write"

    def test_agreement_passthrough(self) -> None:
        assert correct_command_risk("write", "setpci -s 00:01.0 CAP_EXP+0x10.w=0020:0020") == "write"
        assert correct_command_risk("read", "lspci") == "read"


class TestNormalizeSummaryRiskCorrection:
    def test_commands_risk_corrected(self) -> None:
        summary = _normalize_summary({
            "commands": [
                {"cmd": "i2cset -y 3 0x50 0x14 0x77", "expected": "", "risk": "read"},
                {"cmd": "i2cget -y 3 0x50 0x0C", "expected": "", "risk": "read"},
                {"cmd": "retimer-cli fw update /tmp/x.bin", "expected": "", "risk": "read"},
            ],
        })
        risks = {c["cmd"]: c["risk"] for c in summary["commands"]}
        assert risks["i2cset -y 3 0x50 0x14 0x77"] == "write"
        assert risks["i2cget -y 3 0x50 0x0C"] == "read"
        assert risks["retimer-cli fw update /tmp/x.bin"] == "danger"

    def test_legacy_string_commands_inferred(self) -> None:
        summary = _normalize_summary({"commands": ["i2cset -y 3 0x50 0x14 0x77"]})
        assert summary["commands"][0]["risk"] == "write"


class TestStepBehaviorTagRiskFloor:
    def test_step_command_not_in_commands_table_uses_inference(self) -> None:
        # Step commands absent from commands[] previously defaulted to read.
        step = {"action": "改写寄存器", "actor": "agent", "kind": "action",
                "command": "i2cset -y 3 0x50 0x14 0x77"}
        assert _step_behavior_tag(step, {}) == "[api:write]"

    def test_lookup_hit_wins(self) -> None:
        step = {"action": "读状态", "actor": "agent", "kind": "action",
                "command": "i2cget -y 3 0x50 0x0C"}
        assert _step_behavior_tag(step, {"i2cget -y 3 0x50 0x0C": "read"}) == "[api:read]"

    def test_human_and_remote_unaffected(self) -> None:
        assert _step_behavior_tag({"actor": "human", "kind": "action", "action": "量信号"}, {}) == "[physical]"
        assert _step_behavior_tag({"actor": "remote", "kind": "action", "action": "改配置"}, {}) == "[remote]"


# ---------------------------------------------------------------------------
# T047 — placeholder noise in applies_to
# ---------------------------------------------------------------------------


class TestAppliesToPlaceholderFilter:
    def test_unknown_firmware_dropped(self) -> None:
        summary = _normalize_summary({
            "applies_to": {"firmware": "unknown", "product_line": ["serdes-gen2"], "test_stage": ["dvt"]},
        })
        at = summary["applies_to"]
        assert "firmware" not in at
        assert at["product_line"] == ["serdes-gen2"]
        assert at["test_stage"] == ["dvt"]

    def test_placeholder_values_filtered_from_lists(self) -> None:
        summary = _normalize_summary({
            "applies_to": {"product_line": ["N/A", "serdes-gen2"], "test_stage": ["未知"]},
        })
        at = summary["applies_to"]
        assert at["product_line"] == ["serdes-gen2"]
        assert "test_stage" not in at

    def test_all_placeholder_removes_field(self) -> None:
        summary = _normalize_summary({"applies_to": {"firmware": "TBD", "product_line": ["none"]}})
        assert "applies_to" not in summary

    def test_real_values_kept(self) -> None:
        summary = _normalize_summary({
            "applies_to": {"firmware": ">=2.3.0", "product_line": ["phoenix-gen2-retimer"], "test_stage": ["dvt"]},
        })
        assert summary["applies_to"] == {
            "firmware": ">=2.3.0",
            "product_line": ["phoenix-gen2-retimer"],
            "test_stage": ["dvt"],
        }
