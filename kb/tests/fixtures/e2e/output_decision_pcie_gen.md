---
brief: Granite NPI平台PCIe默认链路速度决策：Rev B PCB的slot3-6因信号完整性选择Gen4，slot1-2使用Gen5，2024-Q3
  Rev C到货后重新评估
category: pcie/link-training
id: granite-pcie-link-speed-decision
language: en
tags:
- granite
- pcie
- gen5
- signal-integrity
- npi
- bios-profile
- validation-platform
- redfish
title: Granite NPI平台PCIe默认链路速度决策
type: decision
---

## Context

Our NPI validation platform (codename "Granite") needs to support both PCIe Gen4 and Gen5 accelerator cards. During early bring-up testing, we observed that Gen5 link training has a ~15% failure rate on slot positions 3-6 due to signal integrity margin issues in the current PCB revision (Rev B). The hardware team estimates the PCB fix (Rev C) will take 8 weeks.

We considered three options:

**Option A: Default to Gen5, accept failures.** 15% of card insertions fail link training, requiring manual BIOS override. The intermittent failures confuse the validation team and pollute test results.

**Option B: Default to Gen4, manual Gen5 for specific tests.** Achieves 100% link training success rate on all slots. Gen4 is sufficient for functional validation of most firmware features. However, Gen5-specific features (LTSSM, equalization) cannot be validated, and performance benchmarks will not reflect production configuration.

**Option C: Per-slot configuration via BIOS profile.** Lets slots 1-2 (good signal integrity) run Gen5 while slots 3-6 run Gen4. Maximizes Gen5 test coverage while maintaining stability, but requires custom BIOS profile management and operators must track which slots support which speed.

## Decision

We chose **Option C: Per-slot configuration via BIOS profile**.

The BIOS team will create a "Granite-NPI" profile configuring slots 1-2 as PCIe Gen5 and slots 3-6 as PCIe Gen4. The profile is deployed via BMC using ipmitool and Redfish API:

```bash
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS raw 0x30 0x70 0x01
```

```bash
curl -k -u admin:$BMC_PASS \
    -X POST https://$BMC_IP/redfish/v1/Systems/1/Bios/Actions/Bios.ChangePassword \
    -H "Content-Type: application/json" \
    -d '{"NewPassword": "", "PasswordName": "SetupPassword"}'
```

```bash
curl -k -u admin:$BMC_PASS \
    -X PATCH https://$BMC_IP/redfish/v1/Systems/1/Bios/Settings \
    -H "Content-Type: application/json" \
    -d '{"Attributes": {"PcieSlot1Speed": "Gen5", "PcieSlot2Speed": "Gen5", "PcieSlot3Speed": "Gen4", "PcieSlot4Speed": "Gen4", "PcieSlot5Speed": "Gen4", "PcieSlot6Speed": "Gen4"}}'
```

Verification after reboot:

```bash
lspci -vvv | grep -E "LnkSta|Speed" | head -12
```

Every test run logs which BIOS profile was active, so results can be correlated with link speed configuration.

This decision will be revisited when Rev C PCB samples arrive (estimated: 2024-Q3). When Rev C PCB arrives, the profile will be updated to enable Gen5 on all slots. The per-slot mechanism makes this transition a configuration change, not a process change.

## Rationale

- **Stability over speed**: NPI validation depends on reproducible results. A 15% random failure rate on Gen5 would waste more engineering time than the Gen4 performance gap.
- **Incremental approach**: When Rev C PCB arrives, the profile will be updated to enable Gen5 on all slots. The per-slot mechanism makes the transition a configuration change, not a process change.
- **Traceability**: Every test run logs which BIOS profile was active, so results can be correlated with link speed configuration.