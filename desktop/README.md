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
| `tray.py` | Tray / menu-bar icon with Open, Start at login, and Quit |
| `autostart.py` | Start at login: Windows Run key, macOS Launch Agent |
| `starter_config.py` | Key mappings a new user starts with |
| `version.py` | App version used by both installers |
| `build_installer.ps1`, `installer/windows/MacroPad.iss` | Windows setup file (Inno Setup) |
| `build_macos.sh` | macOS `.app` and `.dmg` |
| `single_instance.py` | Keeps one running copy; a second launch opens the first copy's window |
| `MacroPad.spec` / `build_windows.ps1` | Windows build (PyInstaller, one-folder) |
| `MacroPad-macOS.spec` | macOS build (PyInstaller `.app`, arm64) |

## Running in the background

- The app lives in the tray (Windows notification area / macOS menu bar). There's no Dock
  icon in the macOS build.
- Closing the window hides it; the pad keeps working. Double-click the tray icon (Windows)
  or use its menu → **Open** to show it again. **Quit** in the tray menu stops the app.
- Launching the app again while it's running only opens the existing window.
- `app.py --background` starts hidden in the tray (used by start-at-login).

## Start at login

Tray menu → **Start at login** turns it on or off (`autostart.py`):

| OS | Where it's stored | Also visible in |
|---|---|---|
| Windows | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` → `Macro Pad` | Task Manager → Startup apps |
| macOS | `~/Library/LaunchAgents/com.macropad.desktop.plist` | System Settings → General → Login Items |

Turning it off in Task Manager also clears the tick in the app. Source runs use separate
entries (`Macro Pad (source)` / `com.macropad.desktop.dev`), so they never replace the
installed app's entry.

Don't run the CLI (`run_actions.py`) while the app is running, because they share the serial port.

## Config location

| Run | Config file |
|---|---|
| Windows, source (`python app.py`) | `desktop/config.json` (git-ignored) |
| Windows, installed | `%APPDATA%\Macro Pad\config.json` (per user) |
| macOS, source | `~/Library/Application Support/Macro Pad DEV/config.json` |
| macOS, installed | `~/Library/Application Support/Macro Pad/config.json` |

**First run:** if the file doesn't exist, the app creates it. It copies a `config.json`
left beside an older portable `Macro Pad.exe` if there is one; otherwise it writes the
starter set from `starter_config.py`. The starter set has General and Browser profiles
with all 12 keys and both knobs assigned, using Ctrl on Windows and Cmd on macOS. An
existing file is never overwritten. No config is bundled into any build.

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

## Version

`version.py` holds the version (`1.0.0`). Both installers read it, so bump it there before
a release.

## Build — Windows installer

Needs Inno Setup 6 (`winget install JRSoftware.InnoSetup`).

```powershell
.\build_installer.ps1
```

- Builds the app (`build_windows.ps1 -Clean` → `release\Macro Pad\`), then the setup file
  `dist\MacroPad-Setup-<version>.exe` from `installer\windows\MacroPad.iss`.
- The setup file installs for all users into `C:\Program Files\Macro Pad` (admin prompt),
  with a Start menu entry and two options, both ticked by default: **desktop shortcut** and
  **start at login**. Start at login is set for the user who runs the installer.
- Upgrading: run a newer setup file. It closes the running app first (`Macro Pad.exe
  --quit`, then ends the process if needed) and keeps every user's settings.
- Uninstalling (Settings → Apps → Macro Pad) closes the app and removes the program,
  shortcuts and login entry. Settings in `%APPDATA%\Macro Pad\` are kept.
- Silent install: `MacroPad-Setup-1.0.0.exe /SILENT /TASKS="desktopicon,startatlogin"`.
- The build is unsigned, so Windows SmartScreen shows "Windows protected your PC" →
  **More info → Run anyway**.

Just the app folder, without an installer: `.\build_windows.ps1 -Python .\.venv-win\Scripts\python.exe`.

### Command-line options (used by the installer)

| Option | Effect |
|---|---|
| `--background` | Start hidden in the tray |
| `--quit` | Close the running copy cleanly; returns once it has exited |
| `--enable-autostart` / `--disable-autostart` | Turn start at login on/off, then exit |

## Build — macOS disk image

Run on a Mac with Apple Silicon:

```sh
./build_macos.sh
```

- Output: `dist/Macro Pad.app` and `dist/MacroPad-<version>-macOS.dmg`. Open the `.dmg` and
  drag **Macro Pad** onto **Applications**.
- The app is ad-hoc signed but **not notarized** (that needs a paid Apple Developer
  account). The first time it's opened, macOS blocks it: open **System Settings → Privacy &
  Security**, scroll down and click **Open Anyway**.
- Give it **Accessibility** permission (System Settings → Privacy & Security →
  Accessibility) so it can send shortcuts. After replacing the app you may need to switch
  that permission off and on again.
- **Not yet tested** on a Mac: the script, the menu-bar mode and start at login.

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
