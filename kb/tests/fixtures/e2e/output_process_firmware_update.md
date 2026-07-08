---
brief: Standard BMC firmware update procedure for production servers during NPI validation,
  with pre-update health check, flash via Redfish, verification, and rollback steps.
category: bmc/firmware-update
id: bmc-firmware-update-production-servers
language: en
tags:
- bmc
- firmware
- update
- redfish
- ipmi
- npi
- validation
title: BMC Firmware Update Procedure for Production Servers
type: process
---

## Purpose

This document defines the standard procedure for updating BMC (Baseboard Management Controller) firmware on production servers during NPI validation. BMC firmware updates are high-risk operations — a failed update can brick the management controller, requiring physical board replacement.

**Prerequisites:**
- Target server is accessible via BMC network (IPMI/Redfish).
- Firmware binary has been validated by the firmware team (SHA256 checksum verified).
- Maintenance window of minimum 30 minutes per server must be approved.
- Rollback firmware image must be available on the TFTP server before starting.

## Steps

### Step 1: Pre-Update Health Check

Verify the server and BMC are in a healthy state before proceeding:

[api] Run BMC info, SEL log, and chassis power status checks:
```bash
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS mc info
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS sel list | tail -20
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS chassis power status
```

[api] Record current firmware version for rollback reference:
```bash
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS mc info | grep "Firmware Revision"
```

[decide] If the server has active workloads, gracefully shut down the OS before the update:
```bash
ssh root@$SERVER_IP "shutdown -h now"
sleep 30
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS chassis power status
```
Verify power is off before continuing.

### Step 2: Backup Current Configuration

Export BMC configuration so settings can be restored after update:

[api] Export BMC configuration and state:
```bash
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS raw 0x32 0x70 > bmc_config_backup.bin
curl -k -u admin:$BMC_PASS https://$BMC_IP/redfish/v1/Managers/1 > bmc_state.json
```

[api] Record network settings (often lost on major version upgrades):
```bash
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan print 1
```

### Step 3: Upload and Flash Firmware

[api] Verify the firmware checksum matches the release manifest:
```bash
sha256sum bmc_firmware_v1.06.bin
```

[api] Initiate the firmware update via Redfish API:
```bash
curl -k -u admin:$BMC_PASS \
    -X POST https://$BMC_IP/redfish/v1/UpdateService/Actions/UpdateService.SimpleUpdate \
    -H "Content-Type: application/json" \
    -d '{"ImageURI": "tftp://192.168.1.100/bmc_firmware_v1.06.bin", "TransferProtocol": "TFTP"}'
```

[api] Monitor update progress:
```bash
watch -n 5 'curl -sk -u admin:$BMC_PASS https://$BMC_IP/redfish/v1/TaskService/Tasks/1 | python3 -m json.tool | grep -E "State|PercentComplete"'
```

**CRITICAL**: Do NOT power cycle the server or disconnect the network during the flash process — a partial flash will brick the BMC.

### Step 4: Post-Update Verification

After the update completes (typically 5-10 minutes), the BMC reboots automatically. Wait for it to come back online:

[api] Ping wait — 30 retries with 10s sleep:
```bash
for i in $(seq 1 30); do
    ping -c 1 -W 2 $BMC_IP > /dev/null 2>&1 && echo "BMC online at $(date)" && break
    echo "Waiting... ($i/30)"
    sleep 10
done
```

[api] Verify the new firmware version:
```bash
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS mc info | grep "Firmware Revision"
```

[api] Run basic functional tests — sensor list, SEL log, and power-on test:
```bash
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS sensor list | head -10
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS sel list | tail -5
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS chassis power on
```

### Step 5: Restore Configuration (if needed)

[decide] If BMC settings were reset by the update, restore IPMI LAN settings from backup:
```bash
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan set 1 ipsrc static
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan set 1 ipaddr $BMC_IP
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan set 1 netmask 255.255.255.0
ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan set 1 defgw ipaddr $GATEWAY_IP
```

### Step 6: Sign-Off

[api] Log the update in the asset management system:
```bash
holmes-qa log-firmware-update \
    --server $SERVER_SN \
    --component bmc \
    --from-version "1.05.02" \
    --to-version "1.06.00" \
    --operator "$USER" \
    --status success
```

## Outcome

After successful completion:
- BMC firmware is at the target version.
- All sensor readings are normal.
- Server can power on/off via IPMI.
- Network configuration is intact.
- Update is logged in asset management.

## Rollback Procedure

[decide] If the new firmware causes issues, flash the previous version using the same Step 3 procedure with the rollback image.

[physical] If the BMC is unreachable after update, use the physical recovery method: insert USB with recovery image and use the BMC recovery jumper. The BMC recovery jumper procedure is documented in the platform hardware guide, section 7.3.