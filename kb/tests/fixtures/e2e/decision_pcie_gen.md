# Decision: Default PCIe Link Speed for NPI Validation Platform

## Context

Our NPI validation platform (codename "Granite") needs to support both PCIe Gen4 and
Gen5 accelerator cards. During early bring-up testing, we observed that Gen5 link
training has a ~15% failure rate on certain slot positions (slots 3-6) due to signal
integrity margin issues in the current PCB revision (Rev B).

The hardware team estimates the PCB fix (Rev C) will take 8 weeks. Meanwhile, the
software and firmware validation teams need stable platforms to continue their work.

We considered three options:

### Option A: Default to Gen5, accept failures

- Pro: Tests Gen5 at maximum speed for cards that support it
- Pro: No BIOS configuration change needed
- Con: 15% of card insertions fail link training, requiring manual BIOS override
- Con: Intermittent failures confuse the validation team and pollute test results

### Option B: Default to Gen4, manual Gen5 for specific tests

- Pro: 100% link training success rate on all slots
- Pro: Gen4 is sufficient for functional validation of most firmware features
- Con: Gen5-specific features (LTSSM, equalization) cannot be validated
- Con: Performance benchmarks will not reflect production configuration

### Option C: Per-slot configuration via BIOS profile

- Pro: Slots 1-2 (good SI) run Gen5, slots 3-6 run Gen4
- Pro: Maximizes Gen5 test coverage while maintaining stability
- Con: Requires custom BIOS profile management
- Con: Operators must track which slots support which speed

## Decision

We chose **Option C: Per-slot configuration via BIOS profile**.

The BIOS team will create a "Granite-NPI" profile that configures:

- Slots 1-2: PCIe Gen5 (full signal integrity margin)
- Slots 3-6: PCIe Gen4 (safe mode until Rev C PCB)

This profile is deployed via BMC:

```bash
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS raw 0x30 0x70 0x01
$ curl -k -u admin:$BMC_PASS \
    -X POST https://$BMC_IP/redfish/v1/Systems/1/Bios/Actions/Bios.ChangePassword \
    -H "Content-Type: application/json" \
    -d '{"NewPassword": "", "PasswordName": "SetupPassword"}'
$ curl -k -u admin:$BMC_PASS \
    -X PATCH https://$BMC_IP/redfish/v1/Systems/1/Bios/Settings \
    -H "Content-Type: application/json" \
    -d '{"Attributes": {"PcieSlot1Speed": "Gen5", "PcieSlot2Speed": "Gen5", "PcieSlot3Speed": "Gen4", "PcieSlot4Speed": "Gen4", "PcieSlot5Speed": "Gen4", "PcieSlot6Speed": "Gen4"}}'
```

Verification after reboot:

```bash
$ lspci -vvv | grep -E "LnkSta|Speed" | head -12
```

## Rationale

- **Stability over speed**: NPI validation depends on reproducible results. A 15%
  random failure rate on Gen5 would waste more engineering time than the Gen4
  performance gap.
- **Incremental approach**: When Rev C PCB arrives, the profile will be updated to
  enable Gen5 on all slots. The per-slot mechanism makes this a configuration change,
  not a process change.
- **Traceability**: Every test run logs which BIOS profile was active, so results can
  be correlated with link speed configuration.

This decision will be revisited when Rev C PCB samples arrive (estimated: 2024-Q3).
