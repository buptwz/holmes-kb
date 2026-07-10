---
brief: 'Thermal throttling mechanisms (PROCHOT, THERMTRIP, RAPL, CLTT/OLTT) in server
  platforms: layered defense from RAPL frequency reduction to emergency shutdown.'
category: thermal
id: server-thermal-throttling-mechanisms
language: en
tags:
- thermal
- throttling
- prochot
- thermtrip
- rapl
- cltt
- ddr5
- validation
title: Server Thermal Throttling Mechanisms
type: pitfall
---

## Contents

| Section | Description |
|---|---|
| Overview | Thermal throttling as a power management mechanism critical for NPI validation. |
| Key Concepts | PROCHOT, THERMTRIP, Memory Thermal Throttling (CLTT/OLTT), RAPL with definitions and thresholds. |
| Interaction Between Mechanisms | Layered defense: normal operation → RAPL → PROCHOT → THERMTRIP. |
| NPI Validation Implications | Worst-case testing, fan failure scenarios, validation commands, root cause priority list. |

## Overview

Thermal throttling is a power management mechanism that reduces processor performance to prevent overheating. Understanding these mechanisms is critical for NPI teams when validating new hardware platforms, as improper thermal design can silently degrade performance without triggering obvious error conditions.

## Key Concepts

### PROCHOT (Processor Hot)

PROCHOT is an Intel-defined signal that indicates the processor has reached its maximum operating temperature, Tjunction max, typically 100–105°C. When PROCHOT is asserted:

- CPU frequency is immediately reduced to the minimum P-state, causing a 50–80% performance drop.
- The signal can be bidirectional: **internal** (CPU self-asserts) or **external** (BMC/VRM asserts).
- External PROCHOT is used by the BMC as a last-resort protection when other cooling strategies fail.

To check PROCHOT status:

1. [api:read] Read the IA32_THERM_STATUS MSR:
   ```bash
   rdmsr 0x19C
   ```
   Expected: Returns IA32_THERM_STATUS; bit 0 = 1 means PROCHOT active.

2. [api:read] Monitor package power, core temperature, and package temperature:
   ```bash
   turbostat --show PkgWatt,CoreTmp,PkgTmp --interval 1
   ```
   Expected: Shows package power, core temperature, package temperature every 1 second; used to detect thermal throttling.

### THERMTRIP

THERMTRIP is a hardware-level emergency shutdown that activates when the processor die temperature exceeds a critical threshold, typically ~125°C. Unlike PROCHOT, it is non-negotiable:

- THERMTRIP causes immediate system power off without software notification.
- The BMC SEL may or may not capture the event depending on timing.
- After THERMTRIP, the system will not power on until the temperature drops below the threshold.

### Memory Thermal Throttling (CLTT / OLTT)

DDR5 DIMMs have integrated temperature sensors that report to the memory controller for thermal throttling. Two modes exist:

- **CLTT (Closed Loop Thermal Throttling)**: The memory controller reads DIMM temperature and proactively reduces the refresh rate. Typical onset at 85°C.
- **OLTT (Open Loop Thermal Throttling)**: Pre-configured throttling based on DIMM population and airflow assumptions, without real-time sensor feedback.

Commands to inspect memory thermal status:

1. [api:read] Query DIMM temperature sensors via BMC:
   ```bash
   ipmitool sdr type Temperature | grep -i dimm
   ```
   Expected: Lists temperature sensor readings for DIMMs.

2. [api:read] Decode thermal sensor data from a DIMM over I2C:
   ```bash
   decode-dimm /dev/i2c-0 | grep -i thermal
   ```
   Expected: Decodes thermal sensor data from DIMM over I2C.

### Platform-Level Thermal Budget (RAPL)

Running Average Power Limit (RAPL) is Intel's mechanism for enforcing power and thermal budgets at the platform level:

- **PL1**: Sustained power limit, typically equal to TDP.
- **PL2**: Burst power limit, typically 1.25 × TDP with a 28-second window.
- **PL4**: Peak power limit for instantaneous current protection.

When any RAPL limit is hit, CPU frequency and voltage are reduced to stay within the budget.

Commands to inspect RAPL settings and effects:

1. [api:read] Read the RAPL power limit MSR:
   ```bash
   rdmsr 0x610
   ```
   Expected: Returns MSR_PKG_POWER_LIMIT; shows RAPL PL1/PL2 settings.

2. [api:read] Monitor power and frequency to verify power limiting:
   ```bash
   turbostat --show PkgWatt,RAMWatt,Busy%,Bzy_MHz --interval 5
   ```
   Expected: Shows package power, RAM power, busy percentage, average frequency every 5 seconds; used to verify power limiting.

## Interaction Between Mechanisms

These mechanisms form a layered defense against overheating:

1. **Normal operation**: CPU runs at the requested P-state.
2. **RAPL limit hit**: CPU frequency and voltage are gradually reduced to stay within the power budget (PL1/PL2 time window).
3. **PROCHOT asserted**: CPU frequency drops to the minimum P-state immediately.
4. **THERMTRIP**: System powers off as an emergency shutdown.

Each layer operates on different parameters — RAPL on power, PROCHOT on temperature, THERMTRIP on die temperature — so all three mechanisms can trigger simultaneously. The defense progression is: normal → RAPL → PROCHOT → THERMTRIP.

## NPI Validation Implications

When validating a new platform design, the thermal subsystem must be tested under the following conditions:

- **Worst-case ambient**: Test at the maximum rated inlet temperature (35°C or 40°C).
- **Full DIMM population**: Memory thermals change significantly with all slots populated.
- **Sustained workload**: RAPL PL2 timeout must be verified (some BIOS have incorrect defaults).
- **Fan failure scenarios**: Verify that PROCHOT activates before THERMTRIP in single-fan-failure mode.

Common NPI thermal validation commands:

1. [api:write] Generate a sustained thermal load on all CPUs:
   ```bash
   stress-ng --cpu 0 --cpu-method matrixprod --timeout 3600 &
   ```
   Expected: Stresses all CPUs with matrix product workload for 1 hour; used to generate thermal load.

2. [api:read] Log thermal validation data over time to CSV:
   ```bash
   turbostat --show Avg_MHz,Busy%,CoreTmp,PkgTmp,PkgWatt --interval 10 --out thermal_log.csv
   ```
   Expected: Logs average frequency, busy%, core temp, package temp, power every 10 seconds to CSV; used for thermal validation recording.

3. [api:read] Check current temperature and fan sensor status:
   ```bash
   ipmitool sensor list | grep -iE "temp|fan"
   ```
   Expected: Lists all temperature and fan sensors; used to check current thermal status.

If thermal throttling is observed during validation, the root cause investigation should follow this priority:

1. Verify fan curve and airflow CFD model match actual behavior.
2. Check heatsink mounting pressure (use thermal paste impression test).
3. Verify BIOS thermal parameters (PL1, PL2, PROCHOT threshold) match the platform specification.
4. If the issue is at the platform level, escalate to mechanical engineering for thermal redesign.