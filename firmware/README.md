# Firmware (ESP32-C3)

**The source code will be added here soon** (a PlatformIO project).

Until then, everything needed to write compatible firmware is documented in the main
[README](../README.md#firmware): the wiring map, the handshake (`WHO` → `MACROPAD:V1`) and
the event messages (`KEY:1`–`KEY:12`, `ENC1:CW|CCW|PRESS`, `ENC2:CW|CCW|PRESS`).

## Summary

- Board: ESP32-C3 with native USB, PlatformIO board `esp32-c3-devkitm-1`, Arduino framework.
- USB CDC serial at 115200 baud. Not a USB keyboard (HID): the desktop app performs the actions.
- Keys: 4 × 4 matrix. Rows GPIO10, GPIO20, GPIO21 (keys) and GPIO7 (knob clicks); columns
  GPIO8, GPIO2, GPIO1, GPIO0.
- Knobs: left encoder GPIO5 + GPIO6, right encoder GPIO3 + GPIO4, common to GND.
- Status: V1, frozen. All 18 inputs verified, including stress tests and simultaneous presses.

## Building and flashing (once the source is here)

1. Install VS Code and the PlatformIO extension.
2. Open this `firmware/` folder.
3. Connect the pad by USB and click **PlatformIO: Upload**.
4. Check it with the serial monitor at 115200 baud: type `WHO` and the pad answers
   `MACROPAD:V1`; pressing keys prints `KEY:1` and so on.

Wiring picture: [`../docs/hardware/wiring-current-matrix.jpeg`](../docs/hardware/wiring-current-matrix.jpeg).
