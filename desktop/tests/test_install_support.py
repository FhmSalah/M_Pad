"""First-run config, starter mappings, and the installer's command-line flags."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

import app as gui
import app_paths
from config_store import ConfigStore, compile_profiles
from monitor_events import VALID_EVENTS
from shortcut_keys import resolve_action
from single_instance import SingleInstance
from starter_config import starter_config

DESKTOP = Path(gui.__file__).resolve().parent
ALL_EVENTS = {event.decode("ascii") for event in VALID_EVENTS}


class StarterConfigTests(unittest.TestCase):
    def test_every_control_is_assigned_with_a_valid_action_on_both_platforms(self):
        for platform in ("win32", "darwin"):
            config = starter_config(platform)
            for name, profile in config["profiles"].items():
                with self.subTest(platform=platform, profile=name):
                    self.assertEqual(set(profile), ALL_EVENTS)
                    for event, action in profile.items():
                        self.assertIsNotNone(resolve_action(action), (event, action))
            default, profiles, _ = compile_profiles(config)
            self.assertEqual(default, "General")
            self.assertIn("Browser", profiles)

    def test_mac_uses_cmd_and_windows_uses_ctrl_for_copy(self):
        self.assertEqual(starter_config("win32")["profiles"]["General"]["KEY:1"]["keys"], ["ctrl", "c"])
        self.assertEqual(starter_config("darwin")["profiles"]["General"]["KEY:1"]["keys"], ["cmd", "c"])

    def test_every_key_and_knob_has_a_label(self):
        labels = starter_config("win32")["labels"]
        for profile in ("General", "Browser"):
            self.assertEqual(len([k for k in labels[profile] if k.startswith("KEY:")]), 12)
            self.assertIn("ENC1:ROTATE", labels[profile])

    def test_browser_profile_is_chosen_for_browsers_without_explicit_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(starter_config("win32")))
            store = ConfigStore(path)
            self.assertEqual(store.update_foreground_profile("chrome.exe"), "Browser")
            self.assertEqual(store.update_foreground_profile("explorer.exe"), "General")


class EnsureConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "AppData" / "Macro Pad" / "config.json"

    def test_first_run_writes_starter_set_that_loads_and_saves(self):
        self.assertEqual(app_paths.ensure_config(self.path, legacy=None, platform="win32"), "created")
        store = ConfigStore(self.path)
        self.assertEqual(store.error, "")
        store.save_mapping("General", "KEY:1", {"type": "hotkey", "keys": ["ctrl", "q"]})
        self.assertEqual(json.loads(self.path.read_text())["profiles"]["General"]["KEY:1"]["keys"], ["ctrl", "q"])
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_existing_config_is_never_touched(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("my settings")
        legacy = self.root / "old.json"
        legacy.write_text("{}")
        self.assertEqual(app_paths.ensure_config(self.path, legacy=legacy), "existing")
        self.assertEqual(self.path.read_text(), "my settings")

    def test_old_portable_config_is_carried_over(self):
        legacy = self.root / "Macro Pad" / "config.json"
        legacy.parent.mkdir()
        legacy.write_text(json.dumps({"default_profile": "Mine", "profiles": {"Mine": {}}}))
        self.assertEqual(app_paths.ensure_config(self.path, legacy=legacy), "migrated")
        self.assertEqual(json.loads(self.path.read_text())["default_profile"], "Mine")
        self.assertTrue(legacy.exists())  # The original stays as a backup.

    def test_no_personal_config_is_bundled_by_build_specs(self):
        for spec in ("MacroPad.spec", "MacroPad-macOS.spec", "build_windows.ps1"):
            with self.subTest(spec=spec):
                text = (DESKTOP / spec).read_text(encoding="utf-8")
                self.assertNotIn('"config.json"', text)
                self.assertNotIn("'config.json'", text)


class FakeAutostart:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def set_enabled(self, enabled):
        if self.error:
            raise self.error
        self.calls.append(enabled)


class CommandLineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def instance(self):
        instance = SingleInstance(f"MacroPadTest {uuid.uuid4().hex}")
        self.addCleanup(instance.release)
        return instance

    def test_normal_start_is_not_a_command(self):
        self.assertIsNone(gui.run_command([], self.instance()))
        self.assertIsNone(gui.run_command(["--background"], self.instance()))

    def test_autostart_flags_switch_login_start_and_exit(self):
        fake = FakeAutostart()
        with patch.object(gui, "platform_autostart", return_value=fake):
            self.assertEqual(gui.run_command(["--enable-autostart"], self.instance()), 0)
            self.assertEqual(gui.run_command(["--disable-autostart"], self.instance()), 0)
        self.assertEqual(fake.calls, [True, False])

    def test_autostart_flag_reports_failure(self):
        with patch.object(gui, "platform_autostart", return_value=FakeAutostart(PermissionError("no"))):
            self.assertEqual(gui.run_command(["--enable-autostart"], self.instance()), 1)
        with patch.object(gui, "platform_autostart", return_value=None):
            self.assertEqual(gui.run_command(["--enable-autostart"], self.instance()), 1)

    def test_quit_with_nothing_running_succeeds_and_leaves_lock_free(self):
        instance = self.instance()
        self.assertEqual(gui.run_command(["--quit"], instance), 0)
        self.assertTrue(instance.acquire())

    def test_quit_closes_a_running_copy(self):
        name = f"MacroPadTest {uuid.uuid4().hex}"
        # A separate process plays the running app: it quits when asked.
        script = ("import sys; sys.path.insert(0, sys.argv[2]);"
                  "from PySide6.QtCore import QCoreApplication, QTimer; app = QCoreApplication([]);"
                  "from single_instance import SingleInstance; s = SingleInstance(sys.argv[1]);"
                  "assert s.acquire() and s.listen(); print('ready', flush=True);"
                  "s.quit_requested.connect(app.quit); QTimer.singleShot(15000, lambda: app.exit(2));"
                  "code = app.exec(); s.release(); sys.exit(code)")
        running = subprocess.Popen([sys.executable, "-c", script, name, str(DESKTOP)],
                                   stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: running.poll() is None and running.kill())
        self.assertEqual(running.stdout.readline().strip(), "ready")
        started = time.monotonic()
        self.assertEqual(gui.run_command(["--quit"], SingleInstance(name)), 0)
        # The process has fully exited by the time --quit returns (the installer relies on it).
        self.assertIsNotNone(running.poll())
        self.assertEqual(running.returncode, 0)  # Quit cleanly, not by the 15 s timeout.
        self.assertLess(time.monotonic() - started, 10)

    def test_wait_for_exit(self):
        from single_instance import wait_for_exit
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
        self.assertFalse(wait_for_exit(child.pid, 0.05))
        self.assertTrue(wait_for_exit(child.pid, 5))
        child.wait()


if __name__ == "__main__":
    unittest.main()
