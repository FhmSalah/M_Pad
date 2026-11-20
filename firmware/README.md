# Firmware (ESP32-C3)

The program that runs on the pad. It reads the 12 keys, both knob turns and both knob
clicks, and sends one short text line per input over USB (`KEY:5`, `ENC1:CW`, …). The
[desktop app](../desktop/) turns those lines into shortcuts. The pad is **not** a USB
keyboard (HID), so nothing happens on the computer without the app.

**Status:** V1, frozen. All 18 inputs verified, including 20-press stress tests and
simultaneous key + knob presses.

## Build and flash

1. Install [VS Code](https://code.visualstudio.com/) and the **PlatformIO IDE** extension.
   VS Code suggests it when you open this folder.
2. **File → Open Folder…** and choose this `firmware/` folder.
3. Connect the pad with a USB-C data cable.
4. Click **PlatformIO: Upload** (the → arrow in the bottom bar). The first build downloads
   the ESP32 tools, which takes a few minutes.
5. **Check it:** open **PlatformIO: Serial Monitor** (115200 baud). After a reset it prints
   `READY`; type `WHO` + Enter and it answers `MACROPAD:V1`; press keys to see `KEY:1` and so on.

Command line: `pio run` (build), `pio run -t upload` (flash), `pio device monitor` (serial).

If the upload can't find the board: hold **BOOT**, tap **RESET** (or plug the cable in while
holding BOOT), release BOOT, then upload again.

| Setting (`platformio.ini`) | Value |
|---|---|
| Board | `esp32-c3-devkitm-1` (works for ESP32-C3 SuperMini-style boards) |
| Framework | Arduino (`espressif32` platform) |
| USB | Native USB CDC (`ARDUINO_USB_MODE=1`, `ARDUINO_USB_CDC_ON_BOOT=1`) |
| Size | about 4% RAM, 19% flash |

## Code

| File | What it does |
|---|---|
| [`src/hardware_config.h`](src/hardware_config.h) | **All pins and timings in one place.** Change this file if your wiring differs |
| [`src/input_scanner.cpp`](src/input_scanner.cpp) | Matrix scan, debouncing, encoder decoding; prints the events |
| [`src/main.cpp`](src/main.cpp) | Serial setup, `READY` at start, and the `WHO` → `MACROPAD:V1` handshake |
| [`docs/BASELINE-known-good-main.cpp.txt`](docs/BASELINE-known-good-main.cpp.txt) | The original single-file test sketch the current code was split from (reference only) |

### How it works

- **Key matrix:** the columns (GPIO8, 2, 1, 0) are inputs with pull-ups. Each row (GPIO10,
  20, 21, then the knob-click row GPIO7) is driven LOW in turn; a column reading LOW means
  that key is pressed. Rows not being scanned are left floating (inputs), as in the tested
  setup.
- **Debounce:** a change must stay stable for **15 ms**. Only the press is reported, never
  the release.
- **Knobs:** quadrature decoding with a transition table. One detent = **4** valid
  transitions, so one click of the knob sends exactly one `CW` or `CCW`.
- **Serial:** 115200 baud. Incoming bytes are processed at most 16 per loop, so traffic can
  never stall the key scanning. Lines longer than the command are discarded whole.

### Messages

| From the pad | Meaning |
|---|---|
| `READY` | Sent once after start-up (the app ignores it) |
| `MACROPAD:V1` | Reply to `WHO` (the app's handshake) |
| `KEY:1` … `KEY:12` | Key pressed |
| `ENC1:CW` / `ENC1:CCW` / `ENC1:PRESS` | Left knob: turned clockwise / counter-clockwise, clicked |
| `ENC2:CW` / `ENC2:CCW` / `ENC2:PRESS` | Right knob |

Full protocol and wiring map: [main README](../README.md#message-format-pad--app).

## Changing it

The wiring lives in `hardware_config.h`. If your build uses different pins, edit only that
file, and keep the message names unchanged so the desktop app keeps working. If a knob
counts the wrong way, swap its `a`/`b` pins there.
