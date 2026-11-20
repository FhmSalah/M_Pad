# Development status

**Last updated:** 2026-11-20 · **Version:** 1.0.0

Status, decisions and to-dos for anyone working on the code. User docs are in
[`README.md`](README.md); build details are in [`desktop/README.md`](desktop/README.md).

## Working rules

- Priorities: reliability / low latency > simplicity > functionality > customizability > looks.
- **One code base** for Windows and macOS (`desktop/`). Platform code is chosen with
  `sys.platform` checks; never fork a separate copy per platform.
- **Firmware V1 is frozen.** Change it only for a proven firmware bug. Profiles, media
  keys and similar features belong in the desktop app.
- **V1 is feature-complete.** New features go to V1.5 (see the roadmap in the README).
- Back up working builds and settings before replacing them.

## Status

| Part | Status |
|---|---|
| Hardware | Done. All 18 inputs (12 keys, 4 knob turns, 2 knob clicks) verified |
| Firmware | V1, frozen. **Source not in the repo yet** (to be added to `firmware/`) |
| Windows app | 1.0.0, tested: tray, start at login, installer (install, upgrade, uninstall) |
| macOS app | Used daily as of Oct 2026. **Not yet tested on a Mac:** tray/menu-bar mode, start at login, `build_macos.sh`, first-run starter config |
| Tests | 206 pass on Windows (14 Mac-only tests skip there) |

## How it fits together

| Area | Files | Notes |
|---|---|---|
| Serial + handshake | `detect_device.py`, `run_actions.py` | `WHO` → `MACROPAD:V1`, then one event per line (see README) |
| Actions | `run_actions.py`, `shortcut_keys.py` | Hotkeys and media keys via pynput; scroll via the mouse wheel |
| Settings | `config_store.py`, `app_paths.py`, `starter_config.py` | Atomic saves; never overwrites a malformed or externally changed file |
| App in front | `foreground_app.py` | Windows: Win32 process name. macOS: NSWorkspace bundle ID plus activation notifications |
| GUI | `app.py`, `shortcut_recorder.py` | PySide6 |
| Background | `tray.py`, `single_instance.py`, `autostart.py` | Tray icon, one copy per user, start at login |
| Packaging | `MacroPad.spec`, `MacroPad-macOS.spec`, `build_*.ps1/sh`, `installer/windows/MacroPad.iss`, `version.py` | |

### Settings

- Windows installed: `%APPDATA%\Macro Pad\config.json`. macOS: `~/Library/Application
  Support/Macro Pad/config.json` (source runs on macOS use `Macro Pad DEV`). Windows source
  runs use `desktop/config.json` (git-ignored).
- First run: copy a config left beside an older portable `Macro Pad.exe`, otherwise write
  the starter set. Never bundled into builds.
- Format: `default_profile`, `locked_profile`, `applications` (app → profile), `profiles`
  (event → action), `labels`.
- `applications` keys: Windows `.exe` names (`krita.exe`) or macOS bundle IDs
  (`org.krita`), lowercase.
- Profile pick order: lock > manual choice (until the app in front changes) > exact app
  binding > legacy `.exe` alias > built-in app names > `default_profile`.

### Background behaviour

- Closing the window hides it; tray **Quit** (or `--quit`) stops the app. Only one copy
  runs per user. A second launch opens the first copy's window. `--quit` sends "quit" and
  returns once the first copy has exited, so installers can replace files safely.
- Start at login is stored only in the OS: Windows `HKCU\...\Run` value `Macro Pad`
  (respects Task Manager's switch); macOS `~/Library/LaunchAgents/com.macropad.desktop.plist`
  (no `KeepAlive`, so Quit stays quit). Source runs use separate entries.
- The macOS build is a menu-bar app (`LSUIElement`, no Dock icon).

## Next steps

1. **Add the firmware source** to `firmware/` (PlatformIO project, without `.pio/`).
2. **Test on a Mac:** run the tests, run from source, then `./build_macos.sh` and check
   the drag-install, Open Anyway, Accessibility, menu bar, start at login, the first-run
   starter config, and automatic profiles (Finder → Brave → Finder gives General → Browser → General).
3. Publish the `.dmg` alongside the Windows installer in the GitHub Release.
4. Record the demo video (`docs/presentation/demo-video-plan.md`) and link it from the README.

## Known issues

- The full test run can exit with a Qt crash (code 139) **after** all results print.
  It's a test-teardown quirk, not an app bug.
- Builds are unsigned: Windows SmartScreen and macOS Gatekeeper warn on first launch.
- On macOS, Accessibility permission may need switching off and on again after replacing the `.app`.
