---
brief: Per-slot BIOS profile enables Gen5 on slots 1-2 and Gen4 on slots 3-6 to avoid
  15% Gen5 link training failure on Rev B PCB.
category: pcie/link-training
id: per-slot-bios-profile-pcie-speed-decision
language: en
tags:
- pcie
- gen5
- gen4
- bios
- link-training
- signal-integrity
- redfish
- npi
title: Per-Slot BIOS Profile for PCIe Gen5/Gen4 Speed
type: decision
---

## Contents

| Section | Description |
|---|---|
| Context | 问题背景：Gen5 link training 在 Slot 3-6 有 15% 失败率，PCB Rev C 需 8 周 |
| Decision | 采用 Option C：per-slot BIOS profile，Slot 1-2 Gen5，Slot 3-6 Gen4 |
| Rationale | 稳定性优先、增量演进、可追溯性，2024-Q3 复盘 |

## Context

The NPI validation platform ("Granite") needs to support both PCIe Gen4 and Gen5 accelerator cards. During early bring-up testing, Gen5 link training exhibited a **~15% failure rate on slot positions 3-6** due to signal integrity margin issues in the current PCB revision (**Rev B**). The hardware team estimates the PCB fix (**Rev C**) will take approximately **8 weeks**.

Three options were considered:

- **Option A**: Default to Gen5 on all slots, accept the ~15% failure rate.
- **Option B**: Default to Gen4 on all slots, require manual Gen5 configuration for specific tests.
- **Option C**: Per-slot configuration via a custom BIOS profile.

## Decision

**Option C (Per-slot BIOS profile) was selected.** The BIOS team created a "Granite-NPI" profile that configures:

- **Slots 1-2**: PCIe **Gen5** (full signal integrity margin)
- **Slots 3-6**: PCIe **Gen4** (safe mode until Rev C PCB arrives)

The profile is deployed via BMC using `ipmitool` and the Redfish API:

1. [api:write] Prepare the BMC for BIOS configuration changes:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS raw 0x30 0x70 0x01
   ```
   Expected: Prepares the BMC for BIOS configuration changes; success returns no output.

2. [api:write] Reset the BIOS setup password to empty:
   ```bash
   curl -k -u admin:$BMC_PASS -X POST https://$BMC_IP/redfish/v1/Systems/1/Bios/Actions/Bios.ChangePassword -H "Content-Type: application/json" -d '{"NewPassword": "", "PasswordName": "SetupPassword"}'
   ```
   Expected: Resets the BIOS setup password to empty; allows subsequent configuration changes.

3. [api:write] Apply the per-slot speed profile:
   ```bash
   curl -k -u admin:$BMC_PASS -X PATCH https://$BMC_IP/redfish/v1/Systems/1/Bios/Settings -H "Content-Type: application/json" -d '{"Attributes": {"PcieSlot1Speed": "Gen5", "PcieSlot2Speed": "Gen5", "PcieSlot3Speed": "Gen4", "PcieSlot4Speed": "Gen4", "PcieSlot5Speed": "Gen4", "PcieSlot6Speed": "Gen4"}}'
   ```
   Expected: Applies the per-slot speed profile to the system; no immediate output on success.

4. [api:read] Verify configuration after reboot:
   ```bash
   lspci -vvv | grep -E "LnkSta|Speed" | head -12
   ```
   Expected: Displays negotiated link speed and status for each PCIe device; confirms correct per-slot configuration after reboot.

## Rationale

The decision was driven by three priorities:

- **Stability over speed**: NPI validation depends on reproducible results. A 15% random failure rate on Gen5 would waste more engineering time than the Gen4 performance gap on slots 3-6.
- **Incremental approach**: When Rev C PCB samples arrive (estimated **2024-Q3**), the profile will be updated to enable Gen5 on all slots. The per-slot mechanism makes this a configuration change, not a process change.
- **Traceability**: Every test run logs which BIOS profile was active, so results can be correlated with link speed configuration for clear root cause analysis.

This decision will be revisited when Rev C PCB samples arrive.