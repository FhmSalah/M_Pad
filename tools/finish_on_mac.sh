#!/bin/bash
# Finish the macOS side of Macro Pad in one go (run on the Mac, from anywhere inside the repo):
#   1. set up Python and the build tools   2. run the tests   3. build "Macro Pad.app" and the .dmg
# Nothing is installed in /Applications, uploaded or committed; the script prints what to do next.
# Usage:  bash tools/finish_on_mac.sh

set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="$REPO/desktop"
say() { printf '\n\033[1;32m== %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$1"; }
fail() { printf '\033[1;31mXX %s\033[0m\n' "$1"; exit 1; }

[ "$(uname)" = "Darwin" ] || fail "Run this on the Mac."
[ "$(uname -m)" = "arm64" ] || warn "This Mac isn't Apple Silicon; the build targets arm64."

# 1) Python 3.10 or newer --------------------------------------------------------------
say "1/3  Python"
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
say "2/3  Tests"
TEST_LOG="$(mktemp)"
( cd tests && QT_QPA_PLATFORM=offscreen ../.venv/bin/python -m unittest discover -s . ) >"$TEST_LOG" 2>&1
grep -E "^(FAIL|ERROR):|^Ran |^OK|^FAILED" "$TEST_LOG" || warn "No test summary printed (see $TEST_LOG)."
if grep -q "^OK" "$TEST_LOG"; then echo "Tests passed."; else warn "Some tests failed. The build continues; keep this log to fix later: $TEST_LOG"; fi

# 3) Build the app and the disk image -------------------------------------------------------
say "3/3  Building Macro Pad.app and the .dmg"
PYTHON="$DESKTOP/.venv/bin/python" ./build_macos.sh || fail "The build failed (see above)."
VERSION="$(.venv/bin/python -c 'from version import VERSION; print(VERSION)')"
DMG="$DESKTOP/dist/MacroPad-$VERSION-macOS.dmg"

say "Done"
cat <<EOF
Disk image: $DMG

Next (see docs/finish-on-mac.md):
  a) Back up /Applications/Macro Pad.app, then quit the old Macro Pad (Cmd+Q).
  b) Open the .dmg, drag Macro Pad to Applications (Replace).
  c) Open it: System Settings > Privacy & Security > Open Anyway (first time only),
     then allow it under Accessibility.
  d) Test: menu-bar icon, keys and knobs, Start at login, Finder > Brave > Finder profiles.
  e) Publish the .dmg (step 4 in docs/finish-on-mac.md).
EOF
