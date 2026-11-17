# Macro Pad desktop app (Windows + macOS)

One Python / PySide6 code base for both platforms.

| File | Role |
|---|---|
| `app.py` | GUI (pad editor, profile menu, Assign Application) |
| `run_actions.py` | Action engine: serial listener, actions, profile watcher (also a CLI) |
| `config_store.py` | Config load/save, profile selection rules |
| `foreground_app.py` | Foreground app detection: Win32 on Windows, NSWorkspace on macOS |
| `detect_device.py` | Finds the pad on serial ports via the `WHO` handshake |
| `shortcut_keys.py`, `shortcut_recorder.py` | Key names, shortcut recording |
| `app_paths.py` | Where the config lives on each platform |
| `MacroPad.spec` / `build_windows.ps1` | Windows build (PyInstaller, one-folder) |
| `MacroPad-macOS.spec` | macOS build (PyInstaller `.app`, arm64) |

Only run one copy of the app (or the CLI) at a time, because they share the serial port.

## Config location

| Run | Config file |
|---|---|
| Windows, source (`python app.py`) | `desktop/config.json` |
| Windows, packaged | `config.json` beside `Macro Pad.exe` |
| macOS, source | `~/Library/Application Support/Macro Pad DEV/config.json` |
| macOS, packaged | `~/Library/Application Support/Macro Pad/config.json` |

`desktop/config.json` is git-ignored. Copy one from `../configs/` before running from
source on Windows or building. Both build specs need it.

## Tests

```powershell
cd tests
$env:QT_QPA_PLATFORM = "offscreen"
..\.venv-win\Scripts\python.exe -m unittest discover -s .
```

```sh
cd tests && QT_QPA_PLATFORM=offscreen ../.venv/bin/python -m unittest discover -s .
```

Run from inside `tests/`, because some test files import each other. Tests use the fixed
sample config `tests/fixtures/config.json`, never your real one. Expect
`OK (skipped=14)` on Windows; the Mac-only tests run on macOS. The process may exit
with code 139 after printing results (Qt teardown quirk), which is harmless.

## Build — Windows

```powershell
copy ..\configs\windows-config.json config.json
.\build_windows.ps1 -Python .\.venv-win\Scripts\python.exe
```

- Output: `release\Macro Pad\` (`Macro Pad.exe`, `config.json`, `_internal\`).
- The script refuses to overwrite an existing `release\Macro Pad`, so move it aside first.
- It copies `desktop/config.json` into the release. Check it's the config you want.
- Keep the folder together. The packaged app reads and writes the `config.json` next to the exe.

## Build — macOS

```sh
cp ../configs/mac-source-folder-config.json config.json   # spec bundles it; real config is in Application Support
.venv/bin/python -m PyInstaller MacroPad-macOS.spec
```

- Output: `dist/Macro Pad.app` (arm64).
- Back up `/Applications/Macro Pad.app` and its config before replacing it.
- Re-enable Accessibility for the new app if shortcuts stop working.

## Action format

```json
{"type": "hotkey", "keys": ["ctrl", "shift", "s"]}
{"type": "media_key", "key": "play_pause"}
{"type": "unassigned"}
```

Key names: modifiers `ctrl shift alt cmd`; `a`–`z`, `0`–`9`, `f1`–`f12`; `up down left
right space enter tab escape backspace delete home end page_up page_down insert`;
punctuation `left_bracket right_bracket backslash semicolon apostrophe comma period slash
minus equal grave`; media `volume_up volume_down volume_mute play_pause`.
