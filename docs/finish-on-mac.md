# Finishing the macOS side

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
