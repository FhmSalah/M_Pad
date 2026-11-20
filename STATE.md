# Macro Pad — current state

**Last updated:** 2026-11-20
**Milestone:** V1 complete on macOS and Windows, from a single shared source tree.

This file replaces `docs/history/CURRENT-STATE-V1-FINAL-2026-10-11.txt` wherever they
conflict. Update it at the end of every work session.

## Working rules

- Priorities: reliability / low latency > simplicity > functionality > customizability > visual polish.
- Inspect before editing. Back up working builds and configs before replacing them.
- **Firmware is frozen.** Don't touch it unless a firmware bug is proven.
- **V1 is finished.** New features go to V1.5 (see below), not into V1.
- One debugging or electronics step at a time.

## Status at a glance

| Part | Status |
|---|---|
| Hardware | Done. 12 keys + 2 encoders + 2 encoder clicks, all 18 events verified |
| Firmware | Frozen V1. Source is on the Mac, **not in this repo yet** |
| macOS app | Installed at `/Applications/Macro Pad.app`, working (2026-10-11) |
| Windows app | Tray version built 2026-11-20 and smoke-tested; installed at `D:\Desktop\Make MP APP\Macro Pad\` |
| Source | `desktop/`, one tree for both platforms. 176 tests pass on Windows (14 Mac-only skipped) |

## Open-source plan (started 2026-11-20)

Goal: publish the project so others can build and use it. Steps, in order:

1. **Clean up**: done 2026-11-20. Unused assets removed, the design mockup moved to
   `docs/design/`, the old project copies sent to the Recycle Bin or archived in `Backups\older\`.
2. **Run in the background**: done 2026-11-20 (Windows tested, macOS untested).
   - `tray.py`: tray / menu-bar icon. Double-click opens the window (Windows); the menu
     has Open and Quit. The tooltip shows the connection and the profile.
   - Closing the window hides it to the tray; only **Quit** stops the app.
   - `single_instance.py`: one copy per user. Launching again just opens the running
     copy's window, because two copies would fight over the serial port.
   - `--background` starts the app hidden in the tray (for step 3).
   - macOS build: `LSUIElement` in `MacroPad-macOS.spec`, so there's no Dock icon.
     **Check on a Mac**: the menu-bar icon, the window coming to the front, and Quit.
   - Windows desktop shortcut `D:\Desktop\Macro Pad.lnk` made by hand for now; the
     installer (step 4) will create it properly.
3. Start automatically at login on Windows and macOS, with an on/off option in the app.
4. Installers: a Windows setup `.exe` and a macOS download.
5. Plan the demo video for the project presentation.
6. Publish on GitHub as open source, with a full README (wiring, firmware, protocol,
   setup, roadmap). Review `docs/history/` for personal paths before going public.

## Earlier: Windows port (2026-11-17)

Ported the final Mac source to Windows; the Mac source became the single shared tree:

1. **Foreground detection**: the Mac version had replaced the Windows backend. It was
   restored (unchanged Win32 code) in `foreground_app.py` and is selected when
   `sys.platform == "win32"`. macOS still uses NSWorkspace.
2. **Assign Application… on Windows**: the profile menu now offers it on Windows. It picks
   an `.exe` and stores its lowercase file name (e.g. `krita.exe`). The Remove submenu
   and reassign prompt work as on the Mac.
3. **Manual vs default profile**: choosing a profile from the menu no longer changes
   `default_profile` on either platform. A manual choice lasts until the foreground app
   changes.
4. **Windows default profile set to `General`**, so unknown apps fall back to General.
5. **Tests**: Mac-only tests skip when PyObjC isn't installed. Added Windows detector and
   `.exe` assignment tests. Fixed a test that created a `QCoreApplication` and crashed
   later GUI tests.

The new Windows release was built with `desktop/build_windows.ps1` and its config
replaced with the real Windows config. The user tested it with the pad: keys, encoders,
profile switching and Assign Application all work.

**Not yet done on the Mac:** these shared changes have not been run or rebuilt on the Mac.
Before relying on them there, run the tests on the Mac and rebuild the `.app` (see Next steps).

## Where things live (outside this repo)

| What | Where |
|---|---|
| This repo (private) | https://github.com/FhmSalah/M_Pad (local clone on Windows: `D:\Desktop\Make MP APP\macro-pad`) |
| Windows packaged app (current) | `D:\Desktop\Make MP APP\Macro Pad\` (exe + `config.json` beside it); desktop shortcut `D:\Desktop\Macro Pad.lnk` |
| Windows live config | `config.json` next to `Macro Pad.exe` |
| Windows backups | `D:\Desktop\Make MP APP\Backups\2026-11-17_20-19-02\` (old release, configs, Mac source); `...\Backups\2026-11-20_before-tray-version\` (previous release + config) |
| Older snapshots | `D:\Desktop\Make MP APP\Backups\older\` (old Windows source zip, Mac source zips, old notes, wiring images) |
| Windows dev environment | `desktop\.venv-win\` inside this repo (git-ignored; recreate with the Quick start steps) |
| Mac installed app | `/Applications/Macro Pad.app` |
| Mac live configs | `~/Library/Application Support/Macro Pad/config.json` (real), `.../Macro Pad DEV/config.json` (source runs) |
| Mac backups | `~/Desktop/Macro-Pad-Backups/2026-10-11_00-29-14_426008+0000/` |
| Firmware source | On the Mac (PlatformIO project), not copied here yet |

Built apps (`release/`, `dist/`, `.app`) are **not** committed to git. They are big
and can be rebuilt from `desktop/`.

## Config rules

- JSON: `default_profile`, `locked_profile`, `applications`, `profiles`, `labels`.
- `applications` keys: Windows `.exe` names (`brave.exe`) or macOS bundle IDs
  (`com.brave.browser`), lowercase, mapped to a profile name.
- Profile pick order: lock > manual choice (until the app changes) > exact app binding
  > legacy `.exe` alias > built-in app names > `default_profile`.
- Saves are atomic; malformed or externally changed files are never overwritten.
- Snapshots of real configs live in `configs/`. Refresh them when mappings change
  (see `configs/README.md`).

## Known issues

- The full test run exits with a Qt crash (code 139) **after** all results print.
  It's a test-teardown quirk, not an app bug.
- The Windows build is unsigned, so SmartScreen shows "Windows protected your PC" on first run.
- On macOS, Accessibility permission may need re-enabling after replacing the `.app`.
- The `Affter Effects` profile name is misspelled. It doesn't match the built-in
  `After Effects` alias, so bind `afterfx.exe` to it explicitly or rename it.

## Next steps

1. **Firmware into the repo** (from the Mac): copy the PlatformIO project into
   `firmware/` (see `firmware/README.md`), without build outputs (`.pio/`).
2. **Verify the shared source on the Mac**: run the tests, run the DEV app, check
   Finder → Brave → Finder gives General → Browser → General, then rebuild and
   reinstall the `.app` (back up first).
3. Optionally move the old Windows release aside and keep only the new one.
4. Optionally attach built apps to a GitHub Release for easy download.

## Parked (V1.5 and later, not implemented)

- V1.5: Fn / layers, encoder modifiers, tap vs hold, MacBook brightness keys.
- V2 ideas: Bluetooth LE, battery / wireless, combos / chords, case redesign.
