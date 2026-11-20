"""Start Macro Pad hidden in the tray when the user logs in.

Windows: a value in HKCU\\...\\CurrentVersion\\Run (the list in Task Manager → Startup apps).
macOS:   a Launch Agent plist in ~/Library/LaunchAgents (System Settings → General →
         Login Items lists it under "Allow in the Background").

The OS entry itself is the on/off state; nothing is stored in config.json.
"""

import os
from pathlib import Path
import plistlib
import subprocess
import sys

BACKGROUND_FLAG = "--background"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


def launch_command():
    """How to start this copy of the app in the background."""
    if getattr(sys, "frozen", False):
        return [sys.executable, BACKGROUND_FLAG]
    python = Path(sys.executable)
    if sys.platform == "win32":
        # pythonw has no console window.
        windowless = python.with_name("pythonw.exe")
        python = windowless if windowless.exists() else python
    return [str(python), str(Path(__file__).resolve().with_name("app.py")), BACKGROUND_FLAG]


def entry_name():
    """Packaged and source runs get separate entries so they never overwrite each other."""
    frozen = getattr(sys, "frozen", False)
    if sys.platform == "darwin":
        return "com.macropad.desktop" if frozen else "com.macropad.desktop.dev"
    return "Macro Pad" if frozen else "Macro Pad (source)"


class WindowsAutostart:
    def __init__(self, name=None, command=None, run_key=RUN_KEY, approved_key=APPROVED_KEY):
        import winreg
        self.winreg = winreg
        self.name = name or entry_name()
        self.command = subprocess.list2cmdline(command or launch_command())
        self.run_key = run_key
        self.approved_key = approved_key

    def _read(self, key_path):
        try:
            with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, key_path) as key:
                return self.winreg.QueryValueEx(key, self.name)[0]
        except FileNotFoundError:
            return None

    def _delete(self, key_path):
        try:
            with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, key_path, 0,
                                     self.winreg.KEY_SET_VALUE) as key:
                self.winreg.DeleteValue(key, self.name)
        except FileNotFoundError:
            pass

    def _write_command(self):
        with self.winreg.CreateKey(self.winreg.HKEY_CURRENT_USER, self.run_key) as key:
            self.winreg.SetValueEx(key, self.name, 0, self.winreg.REG_SZ, self.command)

    def disabled_in_task_manager(self):
        flag = self._read(self.approved_key)
        # First byte 2 = enabled, odd values = switched off in Task Manager.
        return isinstance(flag, (bytes, bytearray)) and len(flag) > 0 and flag[0] & 1 == 1

    def is_enabled(self):
        return self._read(self.run_key) is not None and not self.disabled_in_task_manager()

    def set_enabled(self, enabled):
        if enabled:
            self._write_command()
            self._delete(self.approved_key)  # Clear an old "disabled" switch from Task Manager.
        else:
            self._delete(self.run_key)
            self._delete(self.approved_key)

    def refresh(self):
        """If the app moved, point an existing entry at this copy (on/off state unchanged)."""
        current = self._read(self.run_key)
        if current is not None and current != self.command:
            self._write_command()


class MacAutostart:
    def __init__(self, label=None, command=None, agents_dir=None):
        self.label = label or entry_name()
        self.command = list(command or launch_command())
        self.path = Path(agents_dir or Path.home() / "Library" / "LaunchAgents") / f"{self.label}.plist"

    def _plist(self):
        return {
            "Label": self.label,
            "ProgramArguments": self.command,
            "RunAtLoad": True,
            "LimitLoadToSessionType": "Aqua",  # Only in a logged-in desktop session.
            "ProcessType": "Interactive",
        }

    def _read(self):
        try:
            with self.path.open("rb") as source:
                return plistlib.load(source)
        except (OSError, ValueError, plistlib.InvalidFileException):
            return None

    def is_enabled(self):
        return self.path.exists()

    def set_enabled(self, enabled):
        if enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".plist.tmp")
            with temporary.open("wb") as target:
                plistlib.dump(self._plist(), target)
            os.replace(temporary, self.path)
        else:
            self.path.unlink(missing_ok=True)

    def refresh(self):
        current = self._read()
        if self.path.exists() and (current is None or current.get("ProgramArguments") != self.command):
            self.set_enabled(True)


def platform_autostart():
    """The start-at-login backend for this OS, or None where unsupported."""
    try:
        if sys.platform == "win32":
            return WindowsAutostart()
        if sys.platform == "darwin":
            return MacAutostart()
    except Exception:
        return None
    return None
