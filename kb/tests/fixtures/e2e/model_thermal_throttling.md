# Thermal Throttling Mechanisms in Modern Server Platforms

## Overview

Thermal throttling is a power management mechanism that reduces processor performance
to prevent overheating. Understanding these mechanisms is critical for NPI teams when
validating new hardware platforms, as improper thermal design can silently degrade
performance without triggering obvious error conditions.

## Key Concepts

### PROCHOT (Processor Hot)

PROCHOT is an Intel-defined signal that indicates the processor has reached its
maximum operating temperature (Tjunction max, typically 100-105C). When asserted:

- CPU frequency is immediately reduced to minimum P-state
- Performance drops by 50-80%
- The signal can be bidirectional: internal (CPU self-asserts) or external (BMC/VRM asserts)

External PROCHOT is often used by the BMC as a last-resort protection when other
cooling strategies fail. To check PROCHOT status:

```bash
$ rdmsr 0x19C    # IA32_THERM_STATUS — bit 0 = PROCHOT active
$ turbostat --show PkgWatt,CoreTmp,PkgTmp --interval 1
```

### THERMTRIP

THERMTRIP is a hardware-level emergency shutdown that activates when the processor
die temperature exceeds a critical threshold (typically 125C). Unlike PROCHOT, it is
non-negotiable — the system powers off immediately to prevent permanent damage.

- No software notification — the system simply turns off
- BMC SEL may or may not capture the event depending on timing
- After THERMTRIP, system will not power on until temperature drops below threshold

### Memory Thermal Throttling (CLTT / OLTT)

DDR5 DIMMs have integrated temperature sensors (TS) that report to the memory
controller. Two throttling modes exist:

- **CLTT (Closed Loop Thermal Throttling)**: Memory controller reads DIMM temperature
  and proactively reduces refresh rate. Typical onset: 85C.
- **OLTT (Open Loop Thermal Throttling)**: Pre-configured throttling based on DIMM
  population and airflow assumptions, without real-time sensor feedback.

```bash
$ ipmitool sdr type Temperature | grep -i dimm
$ decode-dimm /dev/i2c-0 | grep -i thermal
```

### Platform-Level Thermal Budget (RAPL)

Running Average Power Limit (RAPL) is Intel's mechanism for enforcing power/thermal
budgets across the platform:

- PL1: Sustained power limit (typically = TDP)
- PL2: Burst power limit (typically 1.25 × TDP, 28-second window)
- PL4: Peak power limit (instantaneous, for current protection)

When any limit is hit, CPU frequency and voltage are reduced to stay within budget.

```bash
$ rdmsr 0x610    # MSR_PKG_POWER_LIMIT
$ turbostat --show PkgWatt,RAMWatt,Busy%,Bzy_MHz --interval 5
```

## Interaction Between Mechanisms

These mechanisms form a layered defense:

1. **Normal operation**: CPU runs at requested P-state
2. **RAPL limit hit**: CPU frequency gradually reduced (PL1/PL2 time window)
3. **PROCHOT asserted**: CPU drops to minimum frequency immediately
4. **THERMTRIP**: System powers off (emergency)

Each layer is independent — RAPL operates on power, PROCHOT on temperature, THERMTRIP
on die temperature. All three can trigger simultaneously.

## NPI Validation Implications

When validating a new platform design, the thermal subsystem must be tested at:

- **Worst-case ambient**: Test at max rated inlet temperature (typically 35C or 40C)
- **Full DIMM population**: Memory thermals change significantly with all slots populated
- **Sustained workload**: RAPL PL2 timeout must be verified (some BIOS have incorrect defaults)
- **Fan failure scenarios**: Verify PROCHOT activates before THERMTRIP in single-fan-failure mode

Common NPI thermal validation commands:

```bash
$ stress-ng --cpu 0 --cpu-method matrixprod --timeout 3600 &
$ turbostat --show Avg_MHz,Busy%,CoreTmp,PkgTmp,PkgWatt --interval 10 --out thermal_log.csv
$ ipmitool sensor list | grep -iE "temp|fan"
```

If thermal throttling is observed during validation, the root cause investigation
should follow this priority:

1. Verify fan curve and airflow CFD model match actual behavior
2. Check heatsink mounting pressure (use thermal paste impression test)
3. Verify BIOS thermal parameters (PL1/PL2/PROCHOT threshold) match platform spec
4. If platform-level issue, escalate to mechanical engineering for thermal redesign
