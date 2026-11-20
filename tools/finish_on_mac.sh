#!/bin/bash
# Finish the macOS side of Macro Pad in one go (run on the Mac, from anywhere inside the repo):
#   1. set up Python and the build tools        2. run the tests
#   3. copy the firmware project into firmware/  4. build "Macro Pad.app" and the .dmg
# Nothing is uploaded or committed; the script prints what to do next.
# Usage:  bash tools/finish_on_mac.sh            (optional: FIRMWARE_DIR=/path/to/project)

set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="$REPO/desktop"
say() { printf '\n\033[1;32m== %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$1"; }
fail() { printf '\033[1;31mXX %s\033[0m\n' "$1"; exit 1; }

[ "$(uname)" = "Darwin" ] || fail "Run this on the Mac."
[ "$(uname -m)" = "arm64" ] || warn "This Mac isn't Apple Silicon; the build targets arm64."

# 1) Python 3.10 or newer --------------------------------------------------------------
say "1/4  Python"
PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
        PYTHON_BIN="$(command -v "$candidate")"; break
    fi
done
[ -n "$PYTHON_BIN" ] || fail "Need Python 3.10+. Install it with: brew install python@3.12  (or from python.org), then run this again."
echo "Using $PYTHON_BIN ($("$PYTHON_BIN" --version))"
cd "$DESKTOP" || fail "desktop/ folder not found"
if [ ! -x .venv/bin/python ]; then
    "$PYTHON_BIN" -m venv .venv || fail "Could not create desktop/.venv"
fi
.venv/bin/python -m pip install --upgrade --quiet pip
.venv/bin/python -m pip install --quiet -r requirements-build.txt || fail "Installing requirements failed (see above)."
echo "Build tools ready."

# 2) Tests -------------------------------------------------------------------------------
say "2/4  Tests"
TEST_LOG="$(mktemp)"
( cd tests && QT_QPA_PLATFORM=offscreen ../.venv/bin/python -m unittest discover -s . ) >"$TEST_LOG" 2>&1
grep -E "^(FAIL|ERROR):|^Ran |^OK|^FAILED" "$TEST_LOG" || warn "No test summary printed (see $TEST_LOG)."
if grep -q "^OK" "$TEST_LOG"; then echo "Tests passed."; else warn "Some tests failed. The build continues; send the log to fix later: $TEST_LOG"; fi

# 3) Firmware ----------------------------------------------------------------------------
say "3/4  Firmware source"
FW_SRC="${FIRMWARE_DIR:-}"
if [ -z "$FW_SRC" ]; then
    echo "Looking for PlatformIO projects (platformio.ini) in your home folder..."
    CANDIDATES="$(find "$HOME" -maxdepth 7 -name platformio.ini \
        -not -path '*/.platformio/*' -not -path "$HOME/Library/*" -not -path '*/.Trash/*' \
        -not -path '*/node_modules/*' -not -path "$REPO/*" 2>/dev/null | xargs -I{} dirname {})"
    COUNT="$(printf '%s\n' "$CANDIDATES" | grep -c . || true)"
    if [ "$COUNT" -eq 0 ]; then
        warn "No PlatformIO project found. Run again with FIRMWARE_DIR=/path/to/project to copy it."
    elif [ "$COUNT" -eq 1 ]; then
        FW_SRC="$CANDIDATES"
        echo "Found: $FW_SRC"
    else
        echo "Found several projects. Pick the Macro Pad firmware (the one with the matrix code):"
        OLD_IFS="$IFS"; IFS=$'\n'
        select choice in $CANDIDATES "None of these"; do
            [ -n "$choice" ] && break
        done
        IFS="$OLD_IFS"
        [ "$choice" = "None of these" ] || FW_SRC="$choice"
    fi
fi
if [ -n "$FW_SRC" ]; then
    [ -f "$FW_SRC/platformio.ini" ] || fail "$FW_SRC has no platformio.ini"
    # Keep our firmware/README.md; leave out build output and editor folders.
    rsync -a --exclude '.pio/' --exclude '.vscode/' --exclude '.git/' --exclude '.DS_Store' \
          --exclude 'README.md' "$FW_SRC/" "$REPO/firmware/"
    echo "Copied into firmware/:"
    ( cd "$REPO/firmware" && find . -type f -not -name README.md | sed 's#^\./#  #' )
    if grep -RInE "password|passwd|ssid|api[_-]?key|token|secret" "$REPO/firmware" --exclude=README.md >/dev/null 2>&1; then
        warn "The firmware mentions a password/key/token. Check before publishing:"
        grep -RInE "password|passwd|ssid|api[_-]?key|token|secret" "$REPO/firmware" --exclude=README.md
    fi
fi

# 4) Build the app and the disk image -------------------------------------------------------
say "4/4  Building Macro Pad.app and the .dmg"
PYTHON="$DESKTOP/.venv/bin/python" ./build_macos.sh || fail "The build failed (see above)."
VERSION="$(.venv/bin/python -c 'from version import VERSION; print(VERSION)')"
DMG="$DESKTOP/dist/MacroPad-$VERSION-macOS.dmg"

say "Done"
cat <<EOF
Disk image: $DMG

Next (see docs/finish-on-mac.md for details):
  a) Quit the old Macro Pad (menu bar icon > Quit, or Cmd+Q).
  b) Open the .dmg, drag Macro Pad to Applications (replace the old one).
  c) Open it: System Settings > Privacy & Security > Open Anyway (first time only),
     then allow it under Accessibility.
  d) Test: menu-bar icon, keys and knobs, Start at login, Finder > Brave > Finder profiles.
  e) Publish the .dmg and the firmware (step 4 in docs/finish-on-mac.md).
EOF
