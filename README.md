# Macro Pad

A handmade ESP32-C3 macro pad (12 keys, 2 rotary encoders with push-clicks) plus
a desktop app for **Windows and macOS** that turns pad input into shortcuts,
media keys and scrolling, with per-application profiles.

```
Macro Pad (USB serial, 115200)  ->  desktop app  ->  Windows / macOS shortcuts & actions
```

> **Coming back after a break? Read [`STATE.md`](STATE.md) first.**
> It says what works, what was last done, and what to do next.

## Repository layout

| Path | What it is |
|---|---|
| [`STATE.md`](STATE.md) | **Source of truth**: current status, decisions, next steps |
| [`desktop/`](desktop/) | The one desktop app source for **both** Windows and macOS (Python, PySide6) |
| [`configs/`](configs/) | Snapshots of real `config.json` mappings (Windows, Mac) |
| [`firmware/`](firmware/) | ESP32-C3 firmware (PlatformIO). **Not yet copied in — lives on the Mac** |
| [`docs/hardware/`](docs/hardware/) | Wiring images (current matrix + obsolete original) |
| [`docs/history/`](docs/history/) | Older state notes, audits and handoffs, kept for reference |

There is **one** source tree for both platforms. Platform-specific code is
selected at runtime with `sys.platform` checks; never fork a separate
"Windows copy" or "Mac copy" again.

## Quick start

### Windows

```powershell
cd desktop
py -3.13 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -r requirements-build.txt
copy ..\configs\windows-config.json config.json
.\.venv-win\Scripts\python.exe app.py
```

### macOS

```sh
cd desktop
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python app.py      # runs as "Macro Pad DEV" with its own config
```

On macOS the source app uses `~/Library/Application Support/Macro Pad DEV/config.json`
and the installed app uses `~/Library/Application Support/Macro Pad/config.json`.
Grant **Accessibility** permission so shortcuts and media keys work.

Build, test and release steps for both platforms: [`desktop/README.md`](desktop/README.md).

## Device protocol (firmware is frozen)

- Desktop sends `WHO`, the pad answers `MACROPAD:V1`.
- Events: `KEY:1`–`KEY:12`, `ENC1:CW`, `ENC1:CCW`, `ENC1:PRESS`, `ENC2:CW`, `ENC2:CCW`, `ENC2:PRESS`.
- No GPIO numbers are exposed to the desktop app. V1 is USB serial, not USB HID.
