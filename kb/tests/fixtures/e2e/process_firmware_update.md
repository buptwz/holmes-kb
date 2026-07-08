# BMC Firmware Update Procedure for Production Servers

## Purpose

This document defines the standard procedure for updating BMC (Baseboard Management
Controller) firmware on production servers during NPI validation. BMC firmware updates
are high-risk operations — a failed update can brick the management controller,
requiring physical board replacement.

## Prerequisites

- Target server is accessible via BMC network (IPMI/Redfish)
- Firmware binary has been validated by the firmware team (SHA256 checksum verified)
- Maintenance window approved (minimum 30 minutes per server)
- Rollback firmware image available on the TFTP server

## Steps

### Step 1: Pre-Update Health Check

Verify the server and BMC are in a healthy state before proceeding:

```bash
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS mc info
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS sel list | tail -20
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS chassis power status
```

Record current firmware version for rollback reference:

```bash
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS mc info | grep "Firmware Revision"
```

If the server has active workloads, gracefully shut down the OS first:

```bash
$ ssh root@$SERVER_IP "shutdown -h now"
$ sleep 30
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS chassis power status
```

Verify power is off before continuing.

### Step 2: Backup Current Configuration

Export BMC configuration so it can be restored if the update resets settings:

```bash
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS raw 0x32 0x70 > bmc_config_backup.bin
$ curl -k -u admin:$BMC_PASS https://$BMC_IP/redfish/v1/Managers/1 > bmc_state.json
```

Also record network settings (these are often lost on major version upgrades):

```bash
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan print 1
```

### Step 3: Upload and Flash Firmware

Verify the firmware checksum matches the release manifest:

```bash
$ sha256sum bmc_firmware_v1.06.bin
# Expected: a3f2e8d1... (from release notes)
```

Initiate the firmware update via Redfish API:

```bash
$ curl -k -u admin:$BMC_PASS \
    -X POST https://$BMC_IP/redfish/v1/UpdateService/Actions/UpdateService.SimpleUpdate \
    -H "Content-Type: application/json" \
    -d '{"ImageURI": "tftp://192.168.1.100/bmc_firmware_v1.06.bin", "TransferProtocol": "TFTP"}'
```

Monitor update progress:

```bash
$ watch -n 5 'curl -sk -u admin:$BMC_PASS https://$BMC_IP/redfish/v1/TaskService/Tasks/1 | python3 -m json.tool | grep -E "State|PercentComplete"'
```

**CRITICAL**: Do NOT power cycle the server or disconnect network during the flash
process. A partial flash will brick the BMC.

### Step 4: Post-Update Verification

After the update completes (typically 5-10 minutes), the BMC will reboot automatically.
Wait for it to come back online:

```bash
$ for i in $(seq 1 30); do
    ping -c 1 -W 2 $BMC_IP > /dev/null 2>&1 && echo "BMC online at $(date)" && break
    echo "Waiting... ($i/30)"
    sleep 10
  done
```

Verify the new firmware version:

```bash
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS mc info | grep "Firmware Revision"
```

Run a basic functional test:

```bash
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS sensor list | head -10
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS sel list | tail -5
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS chassis power on
```

### Step 5: Restore Configuration (if needed)

If BMC settings were reset by the update, restore from backup:

```bash
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan set 1 ipsrc static
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan set 1 ipaddr $BMC_IP
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan set 1 netmask 255.255.255.0
$ ipmitool -I lanplus -H $BMC_IP -U admin -P $BMC_PASS lan set 1 defgw ipaddr $GATEWAY_IP
```

### Step 6: Sign-Off

Log the update in the asset management system:

```bash
$ holmes-qa log-firmware-update \
    --server $SERVER_SN \
    --component bmc \
    --from-version "1.05.02" \
    --to-version "1.06.00" \
    --operator "$USER" \
    --status success
```

## Outcome

After successful completion:
- BMC firmware is at the target version
- All sensor readings are normal
- Server can power on/off via IPMI
- Network configuration is intact
- Update is logged in asset management

## Rollback Procedure

If the new firmware causes issues, flash the previous version using the same
Step 3 procedure with the rollback image. If BMC is unreachable after update,
use the physical recovery method: insert USB with recovery image and use the
BMC recovery jumper (refer to platform hardware guide, section 7.3).
