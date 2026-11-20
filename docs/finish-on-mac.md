# Finishing the macOS side

> **Using an AI assistant (e.g. Claude Code) on the Mac?** Read the
> [rules for the assistant](#rules-for-an-ai-assistant-on-the-mac) at the end first.

Three things can only be done on the Mac:

1. **Build the macOS download** (`MacroPad-1.0.0-macOS.dmg`). A Mac app can only be built on a Mac.
2. **Add the firmware source.** The firmware is the small program inside the pad (on the
   ESP32-C3 chip) that reads the keys and knobs and sends `KEY:5`, `ENC1:CW` and so on over
   USB. It's already flashed in the pad, which is why the pad works, but its source code (the
   PlatformIO project, written in VS Code) is still only on the Mac. Without it, nobody else
   can build their own pad from this repo.
3. **Test the new features on macOS:** menu-bar icon, start at login, the installer.

## 1. Get the project on the Mac

Open **Terminal** (Cmd+Space, type "Terminal") and paste:

```sh
cd ~/Desktop
git clone https://github.com/FhmSalah/M_Pad.git
cd M_Pad
git config user.name "FhmSalah"
git config user.email "330160166+FhmSalah@users.noreply.github.com"
```

The last two lines keep your private email out of any commit you make from the Mac.

## 2. Run the finishing script

```sh
bash tools/finish_on_mac.sh
```

It does everything in order and stops with a clear message if something is missing:

| Step | What happens |
|---|---|
| 1. Python | Finds Python 3.10+ and installs the build tools into `desktop/.venv`. If Python is missing it tells you to run `brew install python@3.12`. |
| 2. Tests | Runs all tests; a failure is reported but doesn't stop the build. |
| 3. Firmware | Searches your home folder for PlatformIO projects. If it finds several, it asks which one is the Macro Pad firmware. It copies it into `firmware/` (without the `.pio` build folder). |
| 4. Build | Builds `Macro Pad.app` and `desktop/dist/MacroPad-1.0.0-macOS.dmg`. |

If you know where the firmware project is: `FIRMWARE_DIR=~/Documents/PlatformIO/Projects/YourProject bash tools/finish_on_mac.sh`

## 3. Install and test on the Mac

1. **Quit the old Macro Pad** (its menu-bar icon → Quit, or Cmd+Q).
2. Open `desktop/dist/MacroPad-1.0.0-macOS.dmg` and drag **Macro Pad** onto **Applications**,
   choosing **Replace**. Your settings stay in `~/Library/Application Support/Macro Pad/`.
3. Open Macro Pad from Applications. If macOS blocks it: **System Settings → Privacy &
   Security**, scroll down, click **Open Anyway**.
4. **System Settings → Privacy & Security → Accessibility:** switch Macro Pad on. If it's
   already listed, switch it off and on again.
5. Check:
   - [ ] A Macro Pad icon appears in the **menu bar** (top right), with no Dock icon.
   - [ ] Keys and knobs work.
   - [ ] Closing the window keeps the pad working; menu-bar icon → **Open** brings it back.
   - [ ] Menu-bar icon → **Start at login** → log out and back in → Macro Pad starts by itself.
   - [ ] Finder → Brave → Finder switches profiles: General → Browser → General.

## 4. Publish the `.dmg` and the firmware

**Option A: from the Mac** (needs GitHub CLI there too)

```sh
brew install gh                 # or download it from https://cli.github.com
gh auth login --web             # Terminal shows a one-time code: enter it at github.com/login/device
gh auth setup-git               # lets git push use the same login
gh release upload v1.0.0 desktop/dist/MacroPad-1.0.0-macOS.dmg
git add firmware
git commit -m "Add the ESP32-C3 firmware source"
git push
```

**Option B: hand it to the Windows PC**

Copy these to the Windows PC (USB stick, Google Drive, email…) into a `from-mac` folder
next to the project folder:

- `desktop/dist/MacroPad-1.0.0-macOS.dmg`
- the `firmware/` folder
- *(optional, stays private)* `~/Library/Application Support/Macro Pad/config.json`, your
  Mac mappings, as a backup

Then ask Claude on Windows to finish: upload the `.dmg` to the release, commit the firmware,
and update the README and roadmap.

## Rules for an AI assistant on the Mac

Context: the project owner did all the Windows work (tray mode, start at login, installers,
open-source release v1.0.0) with Claude Code on a Windows PC. Read `STATE.md` (status and
design) and this guide, then work through steps 1–4 above **one step at a time**,
confirming with the owner before each step that changes something outside the repo.

Must:
- Commit only as `FhmSalah <330160166+FhmSalah@users.noreply.github.com>` (set it with the
  `git config` lines in step 1 before any commit). Never put a personal email, real name,
  or personal file paths (e.g. `/Users/<name>/...`) into tracked files or commit messages:
  the repo is public.
- Treat the firmware as **frozen**: copy the existing PlatformIO project into `firmware/`
  without changing its code, and never flash the pad. Leave out `.pio/` and `.vscode/`.
  Before committing, check it for Wi-Fi passwords, keys or tokens.
- Never overwrite or delete `~/Library/Application Support/Macro Pad/config.json` (the
  owner's real mappings) or `.../Macro Pad DEV/config.json`. The new app reads the
  existing file as is.
- Before replacing `/Applications/Macro Pad.app`, make a dated backup copy of it (e.g. in
  `~/Desktop/Macro-Pad-Backups/`) and quit the running app.
- Don't push or upload until the owner has tested the new app (step 3) and agreed.

Publishing (step 4), once agreed:
1. `gh release upload v1.0.0 desktop/dist/MacroPad-1.0.0-macOS.dmg` (GitHub CLI; the owner
   signs in with `gh auth login --web`, entering the one-time code shown in Terminal).
2. Commit the firmware: "Add the ESP32-C3 firmware source".
3. Update the docs so nothing claims more than is true: the README roadmap and status lines,
   the README Install section, `firmware/README.md` (now: how to build and flash),
   `docs/release-notes/v1.0.0.md` (add the `.dmg` and its SHA-256, then
   `gh release edit v1.0.0 --notes-file docs/release-notes/v1.0.0.md`), and `STATE.md`
   (what was tested on macOS, what wasn't).
4. Report anything that failed on macOS with the exact error, so it can be fixed in the
   shared code (`desktop/`). Platform-specific code goes behind `sys.platform` checks;
   never fork a Mac-only copy.
