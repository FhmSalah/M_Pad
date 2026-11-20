"""Start at login: Windows registry (throwaway test key) and macOS Launch Agent (temp dir)."""

import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

import autostart
from tray import TrayIcon

APP = r"C:\Program Files\Macro Pad\Macro Pad.exe"


class LaunchCommandTests(unittest.TestCase):
    def test_packaged_app_starts_itself_in_background(self):
        with patch.object(autostart.sys, "frozen", True, create=True), \
                patch.object(autostart.sys, "executable", APP):
            self.assertEqual(autostart.launch_command(), [APP, "--background"])

    def test_source_run_starts_app_py_in_background(self):
        command = autostart.launch_command()
        self.assertEqual(Path(command[1]).name, "app.py")
        self.assertEqual(command[-1], "--background")
        if sys.platform == "win32" and Path(sys.executable).with_name("pythonw.exe").exists():
            self.assertEqual(Path(command[0]).name.lower(), "pythonw.exe")

    def test_packaged_and_source_entries_never_share_a_name(self):
        for platform in ("win32", "darwin"):
            with self.subTest(platform=platform), patch.object(autostart.sys, "platform", platform):
                with patch.object(autostart.sys, "frozen", True, create=True):
                    packaged = autostart.entry_name()
                source = autostart.entry_name()
                self.assertNotEqual(packaged, source)

    def test_unsupported_platform_has_no_backend(self):
        with patch.object(autostart.sys, "platform", "linux"):
            self.assertIsNone(autostart.platform_autostart())


@unittest.skipUnless(sys.platform == "win32", "Windows registry")
class WindowsAutostartTests(unittest.TestCase):
    def setUp(self):
        import winreg
        self.winreg = winreg
        root = rf"Software\MacroPadTest-{uuid.uuid4().hex}"
        self.root, self.run, self.approved = root, root + r"\Run", root + r"\Approved"
        self.addCleanup(self.remove_test_keys)
        self.entry = self.make([APP, "--background"])

    def make(self, command):
        return autostart.WindowsAutostart("Macro Pad", command, self.run, self.approved)

    def remove_test_keys(self):
        for key in (self.run, self.approved, self.root):
            try:
                self.winreg.DeleteKey(self.winreg.HKEY_CURRENT_USER, key)
            except FileNotFoundError:
                pass

    def read(self, key):
        return self.entry._read(key)

    def set_approved(self, data):
        with self.winreg.CreateKey(self.winreg.HKEY_CURRENT_USER, self.approved) as key:
            self.winreg.SetValueEx(key, "Macro Pad", 0, self.winreg.REG_BINARY, data)

    def test_enable_writes_quoted_command_and_disable_removes_it(self):
        self.assertFalse(self.entry.is_enabled())
        self.entry.set_enabled(True)
        self.assertTrue(self.entry.is_enabled())
        self.assertEqual(self.read(self.run), f'"{APP}" --background')
        self.entry.set_enabled(False)
        self.assertFalse(self.entry.is_enabled())
        self.assertIsNone(self.read(self.run))

    def test_task_manager_switch_is_respected_and_cleared_on_enable(self):
        self.entry.set_enabled(True)
        self.set_approved(bytes([3]) + bytes(11))  # Switched off in Task Manager.
        self.assertFalse(self.entry.is_enabled())
        self.set_approved(bytes([2]) + bytes(11))  # Switched back on.
        self.assertTrue(self.entry.is_enabled())
        self.set_approved(bytes([3]) + bytes(11))
        self.entry.set_enabled(True)  # Turning it on in the app wins.
        self.assertTrue(self.entry.is_enabled())
        self.assertIsNone(self.read(self.approved))

    def test_refresh_follows_a_moved_app_but_never_turns_it_on(self):
        self.entry.refresh()
        self.assertIsNone(self.read(self.run))
        self.entry.set_enabled(True)
        moved = self.make([r"D:\Apps\Macro Pad\Macro Pad.exe", "--background"])
        moved.refresh()
        self.assertEqual(self.read(self.run), r'"D:\Apps\Macro Pad\Macro Pad.exe" --background')

    def test_refresh_keeps_task_manager_off_switch(self):
        self.entry.set_enabled(True)
        self.set_approved(bytes([3]) + bytes(11))
        self.make([r"D:\Moved\Macro Pad.exe", "--background"]).refresh()
        self.assertFalse(self.entry.is_enabled())

    def test_real_startup_list_is_untouched_by_these_tests(self):
        self.assertEqual(self.entry.run_key, self.run)
        self.assertNotEqual(self.run, autostart.RUN_KEY)


class MacAutostartTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name) / "LaunchAgents"
        self.command = ["/Applications/Macro Pad.app/Contents/MacOS/Macro Pad", "--background"]
        self.entry = autostart.MacAutostart("com.macropad.desktop", self.command, self.dir)

    def test_enable_writes_launch_agent_and_disable_removes_it(self):
        self.assertFalse(self.entry.is_enabled())
        self.entry.set_enabled(True)
        with self.entry.path.open("rb") as source:
            plist = plistlib.load(source)
        self.assertEqual(plist["Label"], "com.macropad.desktop")
        self.assertEqual(plist["ProgramArguments"], self.command)
        self.assertTrue(plist["RunAtLoad"])
        self.assertNotIn("KeepAlive", plist)  # Quit must stay quit.
        self.entry.set_enabled(False)
        self.assertFalse(self.entry.is_enabled())
        self.entry.set_enabled(False)  # Already off: no error.

    def test_refresh_follows_moved_app_and_repairs_damaged_file(self):
        self.entry.refresh()
        self.assertFalse(self.entry.is_enabled())
        self.entry.set_enabled(True)
        moved = autostart.MacAutostart("com.macropad.desktop", ["/Users/x/Macro Pad.app/m", "--background"], self.dir)
        moved.refresh()
        self.assertEqual(moved._read()["ProgramArguments"][0], "/Users/x/Macro Pad.app/m")
        self.entry.path.write_bytes(b"not a plist")
        self.entry.refresh()
        self.assertEqual(self.entry._read()["ProgramArguments"], self.command)


class FakeAutostart:
    def __init__(self, enabled=False, error=None):
        self.enabled, self.error, self.calls = enabled, error, []

    def is_enabled(self):
        return self.enabled

    def set_enabled(self, enabled):
        self.calls.append(enabled)
        if self.error:
            raise self.error
        self.enabled = enabled


class TrayToggleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_menu_order_and_initial_state(self):
        tray = TrayIcon(QIcon(), "Macro Pad", autostart=FakeAutostart(enabled=True))
        labels = [a.text() for a in tray.menu.actions() if not a.isSeparator()]
        self.assertEqual(labels, ["Open", "Start at login", "Quit"])
        self.assertTrue(tray.autostart_action.isChecked())

    def test_toggle_turns_login_start_on_and_off(self):
        fake = FakeAutostart()
        tray = TrayIcon(QIcon(), "Macro Pad", autostart=fake)
        tray.autostart_action.trigger()
        self.assertEqual((fake.calls, tray.autostart_action.isChecked()), ([True], True))
        tray.autostart_action.trigger()
        self.assertEqual((fake.calls, tray.autostart_action.isChecked()), ([True, False], False))

    def test_change_outside_the_app_shows_when_menu_opens(self):
        fake = FakeAutostart(enabled=True)
        tray = TrayIcon(QIcon(), "Macro Pad", autostart=fake)
        fake.enabled = False  # e.g. switched off in Task Manager.
        tray.menu.aboutToShow.emit()
        self.assertFalse(tray.autostart_action.isChecked())
        self.assertEqual(fake.calls, [])

    def test_failure_reverts_tick_and_warns(self):
        tray = TrayIcon(QIcon(), "Macro Pad", autostart=FakeAutostart(error=PermissionError("denied")))
        with patch.object(tray.icon, "showMessage") as message:
            tray.autostart_action.trigger()
        self.assertFalse(tray.autostart_action.isChecked())
        message.assert_called_once()

    def test_no_option_where_unsupported(self):
        tray = TrayIcon(QIcon(), "Macro Pad")
        self.assertIsNone(tray.autostart_action)
        self.assertNotIn("Start at login", [a.text() for a in tray.menu.actions()])


if __name__ == "__main__":
    unittest.main()
