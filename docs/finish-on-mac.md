# Finishing the macOS side

> **Using an AI assistant (e.g. Claude Code) on the Mac?** Read the
> [rules for the assistant](#rules-for-an-ai-assistant-on-the-mac) at the end first.

The firmware and the Windows side are done. Two things can only be done on a Mac:

1. **Build the macOS download** (`MacroPad-1.0.0-macOS.dmg`). A Mac app can only be built on a Mac.
2. **Test the new features on macOS:** menu-bar icon, start at login, and installing from the `.dmg`.

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

| Step | What happens |
|---|---|
| 1. Python | Finds Python 3.10+ and installs the build tools into `desktop/.venv`. If Python is missing it tells you to run `brew install python@3.12`. |
| 2. Tests | Runs all tests; a failure is reported but doesn't stop the build. |
| 3. Build | Builds `Macro Pad.app` and `desktop/dist/MacroPad-1.0.0-macOS.dmg`. |

It doesn't install, upload or commit anything.

## 3. Install and test on the Mac

1. **Back up the current app:**
   `mkdir -p ~/Desktop/Macro-Pad-Backups && cp -R "/Applications/Macro Pad.app" ~/Desktop/Macro-Pad-Backups/"Macro Pad $(date +%F).app"`
2. **Quit the old Macro Pad** (click it, then Cmd+Q).
3. Open `desktop/dist/MacroPad-1.0.0-macOS.dmg` and drag **Macro Pad** onto **Applications**,
   choosing **Replace**. Your settings stay in `~/Library/Application Support/Macro Pad/`.
4. Open Macro Pad from Applications. If macOS blocks it: **System Settings → Privacy &
   Security**, scroll down, click **Open Anyway**.
5. **System Settings → Privacy & Security → Accessibility:** switch Macro Pad on. If it's
   already listed, switch it off and on again.
6. Check:
   - [ ] A Macro Pad icon appears in the **menu bar** (top right), with no Dock icon.
   - [ ] Keys and knobs work.
   - [ ] Closing the window keeps the pad working; menu-bar icon → **Open** brings it back.
   - [ ] Menu-bar icon → **Start at login** → log out and back in → Macro Pad starts by itself.
   - [ ] Finder → Brave → Finder switches profiles: General → Browser → General.

## 4. Publish the `.dmg`

**Option A: from the Mac** (needs GitHub CLI there too)

```sh
brew install gh                 # or download it from https://cli.github.com
gh auth login --web             # Terminal shows a one-time code: enter it at github.com/login/device
gh release upload v1.0.0 desktop/dist/MacroPad-1.0.0-macOS.dmg
```

**Option B: hand it to the Windows PC.** Copy `desktop/dist/MacroPad-1.0.0-macOS.dmg` to
the Windows PC (USB stick, Google Drive, email…). Then ask Claude there to upload it to the
release and update the README, the roadmap and the release notes.

## Rules for an AI assistant on the Mac

Context: the project owner did the Windows work (tray mode, start at login, installers,
firmware source, open-source release v1.0.0) with Claude Code on a Windows PC. Read
`STATE.md` (status and design) and this guide, then work through steps 1–4 above **one
step at a time**, confirming with the owner before each step that changes something
outside the repo.

Must:
- Commit only as `FhmSalah <330160166+FhmSalah@users.noreply.github.com>` (set it with the
  `git config` lines in step 1 before any commit). Never put a personal email, real name,
  or personal file paths (e.g. `/Users/<name>/...`) into tracked files or commit messages:
  the repo is public.
- Don't modify or flash the firmware (`firmware/` is frozen V1).
- Never overwrite or delete `~/Library/Application Support/Macro Pad/config.json` (the
  owner's real mappings) or `.../Macro Pad DEV/config.json`. The new app reads the
  existing file as is.
- Back up `/Applications/Macro Pad.app` (step 3.1) and quit the running app before replacing it.
- Don't push or upload until the owner has tested the new app (step 3) and agreed.

Publishing (step 4), once agreed:
1. `gh release upload v1.0.0 desktop/dist/MacroPad-1.0.0-macOS.dmg` (GitHub CLI; the owner
   signs in with `gh auth login --web`, entering the one-time code shown in Terminal).
2. Update the docs so nothing claims more than is true: the README roadmap, status and
   Install lines, `docs/release-notes/v1.0.0.md` (add the `.dmg` and its SHA-256, then
   `gh release edit v1.0.0 --notes-file docs/release-notes/v1.0.0.md`), and `STATE.md`
   (what was tested on macOS and what wasn't). Commit and push (`gh auth setup-git` first).
3. Report anything that failed on macOS with the exact error, so it can be fixed in the
   shared code (`desktop/`). Platform-specific code goes behind `sys.platform` checks;
   never fork a Mac-only copy.
