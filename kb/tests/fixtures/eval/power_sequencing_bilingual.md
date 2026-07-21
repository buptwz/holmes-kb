# PMIC Latch-up on Cold Power-up / 冷上电 PMIC 锁死

Problem / 问题描述: On DVT-0167, the PMIC (U5) latches up on cold
power-up and outputs nothing. 冷上电时 PMIC 无输出，整板不上电；
warm reboot 正常。Failure rate about 20% on first power of the day.
每天首次上电失败率约 20%。

Symptoms / 症状:

- 12V main input present, but VDD_CORE/VDD_TX/VDD_ANA all stay 0V.
  主输入正常，三路输出全部为零。
- `pwr-mon read vdd_core` returns 0.00V。
- PMIC fault register 0x02 reads 0x40 (bit6 = SEQ_TIMEOUT).
  读故障寄存器：`i2cget -y 2 0x28 0x02` 返回 0x40。
- Toggling the power button does not help; only a full 12V removal
  for >= 60 seconds clears the latch. 必须拔掉 12V 输入 60 秒以上
  才能恢复。

Root cause / 根因: The input bulk capacitor C108 is undersized
(47µF fitted, 100µF per BOM). 输入大电容 C108 错料，容值不足导致
冷上电 inrush 时输入电压跌落超过 PMIC 的 UVLO 阈值，时序状态机
停在中间态并锁死。The sequencer times out and latches the fault.

Resolution / 修复:

1. Confirm the fault: read 0x02, expect 0x40. 先读故障寄存器确认。
   `i2cget -y 2 0x28 0x02`
2. [物理] Power off, remove the board, replace C108 with 100µF/25V
   (P/N CAP-100U-25V-1210). 断电更换 C108 为 100µF。
3. Clear the fault latch: `i2cset -y 2 0x28 0x02 0x40`（写 1 清零）。
4. Cold-boot test 10 times. 冷启动 10 次验证全部通过。
5. Check incoming inspection for the capacitor batch B2026-0620;
   same batch may affect other boards. 追溯同批电容。

Verification / 验证: scope capture of 12V input during cold plug-in
shows droop < 0.5V after fix (was 2.1V before). 修复后示波器抓
12V 输入，跌落从 2.1V 降到 0.5V 以内。
