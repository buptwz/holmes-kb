---
brief: Intel/AMD 服务器平台热节流层次防御机制：RAPL→PROCHOT→THERMTRIP，NPI 验证需测试满配 DIMM、最高进风温度和风扇故障场景
category: thermal/throttling
id: server-platform-thermal-throttling-mechanisms
language: en
tags:
- thermal
- throttling
- PROCHOT
- THERMTRIP
- RAPL
- CLTT
- DDR5
- NPI
title: Server Platform Thermal Throttling Mechanisms
type: model
---

## Overview

Thermal throttling is a power management mechanism that reduces processor performance to prevent overheating. Understanding these mechanisms is critical for NPI teams when validating new hardware platforms, as improper thermal design can silently degrade performance without triggering obvious error conditions. The server platform thermal defense is organized as a layered hierarchy: RAPL (power budget) → PROCHOT (temperature signal) → THERMTRIP (emergency shutdown), with independent memory-level throttling via CLTT/OLTT on DDR5 DIMMs.

## Key Concepts

### PROCHOT (Processor Hot)

PROCHOT is an Intel-defined signal that indicates the processor has reached its maximum operating temperature (Tjunction max, typically 100–105°C). When PROCHOT is asserted, CPU frequency is immediately reduced to minimum P-state, and performance drops by 50–80%.

The PROCHOT signal can be bidirectional: internal (CPU self-asserts) or external (BMC/VRM asserts). External PROCHOT is often used by the BMC as a last-resort protection when other cooling strategies fail.

To check PROCHOT status:

```bash
rdmsr 0x19C    # IA32_THERM_STATUS — bit 0 = PROCHOT active
turbostat --show PkgWatt,CoreTmp,PkgTmp --interval 1
```

### THERMTRIP

THERMTRIP is a hardware-level emergency shutdown that activates when the processor die temperature exceeds a critical threshold, typically 125°C. THERMTRIP is non-negotiable — the system powers off immediately to prevent permanent damage, with no software notification. The BMC SEL may or may not capture the THERMTRIP event depending on timing. After THERMTRIP, the system will not power on until the temperature drops below threshold.

### Memory Thermal Throttling (CLTT / OLTT)

DDR5 DIMMs have integrated temperature sensors (TS) that report to the memory controller. Two throttling modes exist:

- **CLTT (Closed Loop Thermal Throttling)**: The memory controller reads DIMM temperature and proactively reduces refresh rate; typical onset at 85°C.
- **OLTT (Open Loop Thermal Throttling)**: Pre-configured throttling based on DIMM population and airflow assumptions, without real-time sensor feedback.

```bash
ipmitool sdr type Temperature | grep -i dimm
decode-dimm /dev/i2c-0 | grep -i thermal
```

### Platform-Level Thermal Budget (RAPL)

Running Average Power Limit (RAPL) is Intel's mechanism for enforcing power/thermal budgets across the platform:

- **PL1**: The sustained power limit, typically equal to TDP.
- **PL2**: The burst power limit, typically 1.25 × TDP with a 28-second window.
- **PL4**: The peak power limit (instantaneous, for current protection).

When any RAPL limit is hit, CPU frequency and voltage are reduced to stay within budget.

```bash
rdmsr 0x610    # MSR_PKG_POWER_LIMIT
turbostat --show PkgWatt,RAMWatt,Busy%,Bzy_MHz --interval 5
```

### Interaction Between Mechanisms

These thermal mechanisms form a layered defense:

1. **Normal operation**: CPU runs at requested P-state
2. **RAPL limit hit**: CPU frequency and voltage are gradually reduced (PL1/PL2 time window)
3. **PROCHOT asserted**: CPU drops to minimum frequency immediately
4. **THERMTRIP**: System powers off (emergency shutdown)

Each layer is independent — RAPL operates on power, PROCHOT on temperature, THERMTRIP on die temperature — and all three can trigger simultaneously.

## Usage

When validating a new platform design, the thermal subsystem must be tested at worst-case ambient: the max rated inlet temperature, typically 35°C or 40°C. Always test with full DIMM population, as memory thermals change significantly with all slots populated. Apply a sustained workload to verify RAPL PL2 timeout, as some BIOS have incorrect defaults. In fan failure scenarios, verify that PROCHOT activates before THERMTRIP in single-fan-failure mode.

Common NPI thermal validation commands:

```bash
stress-ng --cpu 0 --cpu-method matrixprod --timeout 3600 &
turbostat --show Avg_MHz,Busy%,CoreTmp,PkgTmp,PkgWatt --interval 10 --out thermal_log.csv
ipmitool sensor list | grep -iE "temp|fan"
```

If thermal throttling is observed during validation, the root cause investigation should follow this priority:

1. Verify fan curve and airflow CFD model match actual behavior.
2. Check heatsink mounting pressure (use thermal paste impression test).
3. Verify BIOS thermal parameters (PL1/PL2/PROCHOT threshold) match platform spec.
4. If the issue is platform-level, escalate to mechanical engineering for thermal redesign.