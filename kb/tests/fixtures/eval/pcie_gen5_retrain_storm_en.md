# PCIe Gen5 Link Retrain Storm After Cable Replacement

Platform: Phoenix-Gen2 riser, GPU card on slot 2. Firmware 2.3.5.

## Symptoms

After replacing the QSFP cable on J8, the PCIe Gen5 link comes up but
retrains every 30-90 seconds. `dmesg` floods with:

```
pcieport 0000:80:01.0: AER: Correctable error received
nvidia 0000:81:00.0: PCIe link retrain requested
```

`lspci -vv | grep LnkSta` shows the link bouncing between Gen5 x16 and
Gen4 x16. BERT-side BER stays clean between retrains, so this is not a
signal-integrity collapse — it looks like marginal equalization.

## Diagnosis

Check the link partner's EQ presets first:

```bash
lspci -s 81:00.0 -xxx | grep -i "lane"
setpci -s 80:01.0 CAP_EXP+0x0c.l
```

The root port logs `eq preset mismatch, fallback to P4` during every
retrain. The new cable is 2m passive (the old one was 1m); insertion
loss at 16GHz is ~19dB, over the Gen5 budget of 18dB for this channel.

Physical check: [physical] power down, reseat the cable at both ends
with proper SMA torque (0.9 N·m), inspect the connector pins under a
microscope — no damage found, so the cable length itself is the issue.

## Resolution

1. Swap the 2m passive cable for a 1.5m active cable (P/N CBL-QDD-AOC-1M5).
2. Verify: `lspci -vv | grep LnkSta` stays at Gen5 x16 for 10 minutes.
3. Run a 24h stress: `gpu-burn 86400` with AER monitoring —
   zero retrains allowed.
4. Record the cable part number in the board log; passive cables
   longer than 1m are not Gen5-capable on this platform.

Root cause: cable insertion loss over budget forced continuous
equalization fallback, which the link partner escalated to full
retrains. Preventive: update the lab cable inventory — mark all
>1m passive QSFP cables as "Gen4 max".
