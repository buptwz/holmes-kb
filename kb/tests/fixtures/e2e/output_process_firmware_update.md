---
brief: 'Standard procedure for BMC firmware update on production servers: pre-update
  health check, backup, flash, post-update verification, and rollback.'
category: bmc/firmware-update
id: bmc-firmware-update-procedure
language: en
tags:
- bmc
- firmware
- ipmi
- redfish
- update
- rollback
- recovery
title: BMC Firmware Update Procedure for Production Servers
type: process
---

## Contents

| Section | Description |
|---|---|
| Purpose | Defines the standard procedure for BMC firmware update on production servers |
| Prerequisites | Lists required conditions: BMC access, validated firmware, maintenance window, rollback image |
| Steps | 6 sequential steps including pre-update health check, backup, flash, post-update verification, config restore, sign-off |
| Outcome | Describes expected state after successful update |
| Rollback Procedure | Instructions for reverting firmware, including physical recovery method |

## Purpose

This document defines the standard procedure for updating BMC (Baseboard Management Controller) firmware on production servers during NPI validation. BMC firmware updates are high-risk operations — a failed update can brick the management controller, requiring physical board replacement.

## Prerequisites

- Target server is accessible via BMC network (IPMI/Redfish).
- Firmware binary has been validated by the firmware team — SHA256 checksum verified against release notes.
- Maintenance window approved — minimum 30 minutes per server.
- Rollback firmware image is available on the TFTP server.

## Steps

### Step 1: Pre-Update Health Check

Verify the server and BMC are in a healthy state before proceeding.

1. [api:read] Verify BMC is reachable:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS mc info
   ```
   Expected: shows BMC info including firmware revision; non-empty indicates BMC reachable and healthy

2. [api:read] Check SEL for critical events:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS sel list | tail -20
   ```
   Expected: shows last 20 SEL entries; empty or only informational entries indicates no critical events

3. [api:read] Record current firmware version for rollback reference:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS mc info | grep "Firmware Revision"
   ```
   Expected: prints current firmware version for rollback reference

4. [api:write] If the server has active workloads, gracefully shut down the OS:
   ```bash
   ssh root@$SERVER_IP "shutdown -h now"
   ```
   Expected: initiates graceful shutdown of OS; verify later with power status

5. [api:read] Wait for shutdown to complete:
   ```bash
   sleep 30
   ```
   Expected: waits 30 seconds for OS shutdown to complete

6. [api:read] Verify power is off before continuing:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS chassis power status
   ```
   Expected: shows power status; should be 'Chassis Power is off' before update

### Step 2: Backup Current Configuration

Export BMC configuration so it can be restored if the update resets settings.

1. [api:read] Export BMC configuration via IPMI raw command:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS raw 0x32 0x70 > bmc_config_backup.bin
   ```
   Expected: exports BMC configuration to binary file; success if file created non-empty

2. [api:read] Export BMC state via Redfish:
   ```bash
   curl -k -u admin:$BMC_PASS https://$BMC_IP/redfish/v1/Managers/1 > bmc_state.json
   ```
   Expected: exports BMC Redfish state to JSON; success if file created

3. [api:read] Record current network settings (these are often lost on major version upgrades):
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan print 1
   ```
   Expected: prints current network settings (IP, netmask, gateway) for rollback reference

### Step 3: Upload and Flash Firmware

1. [api:read] Verify the firmware checksum matches the release manifest:
   ```bash
   sha256sum bmc_firmware_v1.06.bin
   ```
   Expected: outputs SHA256 hash; compare to expected hash from release notes (e.g. a3f2e8d1...)

2. [api:danger] Initiate the firmware update via Redfish SimpleUpdate:
   ```bash
   curl -k -u admin:$BMC_PASS -X POST https://$BMC_IP/redfish/v1/UpdateService/Actions/UpdateService.SimpleUpdate -H "Content-Type: application/json" -d '{"ImageURI": "tftp://192.168.1.100/bmc_firmware_v1.06.bin", "TransferProtocol": "TFTP"}'
   ```
   Expected: initiates firmware update; returns task ID for monitoring progress

3. [api:read] Monitor update progress:
   ```bash
   watch -n 5 'curl -sk -u admin:$BMC_PASS https://$BMC_IP/redfish/v1/TaskService/Tasks/1 | python3 -m json.tool | grep -E "State|PercentComplete"'
   ```
   Expected: repeatedly shows update state and progress; wait until State=Completed

**CRITICAL**: Do NOT power cycle the server or disconnect the network during the flash process. A partial flash will brick the BMC.

### Step 4: Post-Update Verification

After the update completes (typically 5-10 minutes), the BMC will reboot automatically.

1. [api:read] Wait for BMC to come back online (up to 5 minutes):
   ```bash
   for i in $(seq 1 30); do ping -c 1 -W 2 $BMC_IP > /dev/null 2>&1 && echo "BMC online at $(date)" && break; echo "Waiting... ($i/30)"; sleep 10; done
   ```
   Expected: loops up to 5 minutes until BMC responds to ping; prints online when ready

2. [api:read] Verify the new firmware version:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS mc info | grep "Firmware Revision"
   ```
   Expected: prints current firmware version; should match the target version just flashed

3. [api:read] Check sensor readings — confirm all are in normal range:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS sensor list | head -10
   ```
   Expected: shows first 10 sensor readings; all should be in normal range

4. [api:read] Check SEL for any new critical events:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS sel list | tail -5
   ```
   Expected: shows last 5 SEL entries; should not show critical events

5. [api:write] Test IPMI power control:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS chassis power on
   ```
   Expected: powers on server; confirms IPMI power control works; check power status if needed

### Step 5: Restore Configuration (if needed)

If BMC network settings were reset by the update, restore from backup.

1. [api:write] Set IP source to static:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan set 1 ipsrc static
   ```
   Expected: sets IP source to static; no output on success

2. [api:write] Restore BMC IP address:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan set 1 ipaddr $BMC_IP
   ```
   Expected: sets BMC IP address; no output on success

3. [api:write] Restore netmask:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan set 1 netmask 255.255.255.0
   ```
   Expected: sets netmask; no output on success

4. [api:write] Restore default gateway:
   ```bash
   ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan set 1 defgw ipaddr $GATEWAY_IP
   ```
   Expected: sets default gateway; no output on success

### Step 6: Sign-Off

Log the update in the asset management system.

1. [api:write] Record the firmware update in the asset management system:
   ```bash
   holmes-qa log-firmware-update --server $SERVER_SN --component bmc --from-version "1.05.02" --to-version "1.06.00" --operator "$USER" --status success
   ```
   Expected: logs the update in asset management system; prints confirmation of successful log

## Outcome

After successful completion:
- BMC firmware is at the target version.
- All sensor readings are normal.
- Server can power on/off via IPMI.
- Network configuration is intact.
- Update is logged in asset management.

## Rollback Procedure

If the new firmware causes issues, flash the previous version using the same Step 3 procedure with the rollback image. If the BMC is unreachable after the update, use the physical recovery method: insert a USB drive with the recovery image and use the BMC recovery jumper (refer to the platform hardware guide, section 7.3).