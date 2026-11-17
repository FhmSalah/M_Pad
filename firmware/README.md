# Firmware (ESP32-C3) — not copied in yet

The firmware source is a PlatformIO project on the Mac. Copy it here next time you
work on the Mac, **without** build outputs (`.pio/`).

- Framework: Arduino, board `esp32-c3-devkitm-1`, serial 115200, native USB CDC (not HID).
- Status: **V1 frozen**. Don't change it without a demonstrated firmware bug.
- Protocol: answers `WHO` with `MACROPAD:V1`; sends `KEY:1`–`KEY:12`,
  `ENC1:CW|CCW|PRESS`, `ENC2:CW|CCW|PRESS`.

## Current wiring (confirmed)

Matrix columns: C1 GPIO8, C2 GPIO2, C3 GPIO1, C4 GPIO0
Rows: R1 GPIO10 (K1–K4), R2 GPIO20 (K5–K8), R3 GPIO21 (K9–K12), R4 GPIO7 (encoder clicks)

- Left encoder: rotation GPIO5 + GPIO6 (common to GND), click GPIO7 + GPIO8
- Right encoder: rotation GPIO3 + GPIO4 (common to GND), click GPIO7 + GPIO0

Picture: [`../docs/hardware/wiring-current-matrix.jpeg`](../docs/hardware/wiring-current-matrix.jpeg).
The seller's original one-key-per-GPIO wiring is **obsolete**; see `docs/hardware/historical/`.
