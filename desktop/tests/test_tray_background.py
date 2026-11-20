"""Tray mode and single running copy; offscreen Qt, no real engine or hardware."""

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

from PySide6.QtCore import QCoreApplication, QDir, QEvent, QSysInfo
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

import app as gui
from config_store import ConfigStore
from single_instance import SingleInstance, instance_name
from tray import TrayIcon


def wait_until(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    return condition()


class TrayWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.json"
        path.write_text(json.dumps({"default_profile": "General", "profiles": {"General": {}, "Work": {}}}))
        self.store = ConfigStore(path)
        with patch.object(gui.EngineWorker, "start"):
            self.window = gui.MacroPadWindow(self.store)
        self.quit = self.enterContext(patch.object(gui.QApplication, "quit"))
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.window.tray = None
        self.window.close()

    def with_tray(self):
        tray = TrayIcon(QIcon(), "Macro Pad", self.window)
        self.window.attach_tray(tray)
        self.window.show()
        return tray

    def test_close_hides_to_tray_and_keeps_running(self):
        self.with_tray()
        self.assertTrue(self.window.isVisible())
        self.window.close()
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window.closing)
        self.assertFalse(self.window.quit_requested)
        self.quit.assert_not_called()

    def test_open_from_tray_shows_hidden_window(self):
        tray = self.with_tray()
        self.window.close()
        tray.open_requested.emit()
        self.assertTrue(self.window.isVisible())

    def test_quit_from_tray_really_quits_even_when_hidden(self):
        tray = self.with_tray()
        self.window.close()
        tray.quit_requested.emit()
        self.assertTrue(self.window.quit_requested)
        self.quit.assert_called()

    def test_hiding_cancels_recording(self):
        self.with_tray()
        with patch.object(self.window.recorder, "finish") as finish:
            self.window.close()
        finish.assert_called()

    def test_without_tray_close_quits_as_before(self):
        self.window.show()
        self.window.close()
        self.assertFalse(self.window.isVisible())
        self.quit.assert_not_called()  # Qt quits by itself when the last window closes.

    def test_tray_tracks_profile_and_connection(self):
        tray = self.with_tray()
        self.assertEqual(tray.profile, "General")
        self.window.choose_profile("Work")
        self.assertEqual(tray.profile, "Work")
        self.window.worker.connection_changed.emit(True)
        self.assertIn("Connected", tray.icon.toolTip())
        self.assertIn("Profile: Work", tray.icon.toolTip())


class TrayIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_menu_offers_open_and_quit(self):
        tray = TrayIcon(QIcon(), "Macro Pad")
        labels = [action.text() for action in tray.menu.actions() if not action.isSeparator()]
        self.assertEqual(labels, ["Open", "Quit"])
        opened, quitted = [], []
        tray.open_requested.connect(lambda: opened.append(True))
        tray.quit_requested.connect(lambda: quitted.append(True))
        tray.open_action.trigger()
        tray.quit_action.trigger()
        self.assertEqual((opened, quitted), ([True], [True]))

    def test_only_double_click_opens(self):
        tray = TrayIcon(QIcon(), "Macro Pad")
        opened = []
        tray.open_requested.connect(lambda: opened.append(True))
        tray.activated(QSystemTrayIcon.ActivationReason.Trigger)
        tray.activated(QSystemTrayIcon.ActivationReason.Context)
        self.assertEqual(opened, [])
        tray.activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        self.assertEqual(opened, [True])

    def test_hint_shown_once(self):
        tray = TrayIcon(QIcon(), "Macro Pad")
        with patch.object(tray.icon, "supportsMessages", return_value=True), \
                patch.object(tray.icon, "showMessage") as show:
            tray.show_hidden_hint()
            tray.show_hidden_hint()
        show.assert_called_once()


class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def make(self, name):
        instance = SingleInstance(name)
        self.addCleanup(instance.release)
        return instance

    def test_second_copy_is_refused_and_wakes_the_first(self):
        name = f"MacroPadTest {uuid.uuid4().hex}"
        first = self.make(name)
        self.assertTrue(first.acquire())
        self.assertTrue(first.listen())
        woken = []
        first.activation_requested.connect(lambda: woken.append(True))

        # The second copy is a real separate process, as when the user relaunches.
        script = ("import sys; sys.path.insert(0, sys.argv[2]);"
                  "from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]);"
                  "from single_instance import SingleInstance; s = SingleInstance(sys.argv[1]);"
                  "sys.exit(10 * s.acquire() + s.notify_running())")
        child = subprocess.Popen([sys.executable, "-c", script, name, str(Path(gui.__file__).parent)])
        self.assertTrue(wait_until(lambda: woken, timeout=10))
        self.assertEqual(child.wait(10), 1)  # Refused the lock (0), reached the first copy (1).
        # Let Qt finish deleting the closed connection before other tests run.
        first.release()
        wait_until(lambda: False, timeout=0.2)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_lock_is_free_again_after_release(self):
        name = f"MacroPadTest {uuid.uuid4().hex}"
        first = SingleInstance(name)
        self.assertTrue(first.acquire())
        first.release()
        self.assertTrue(self.make(name).acquire())

    def test_lock_left_by_a_crashed_copy_is_taken_over(self):
        name = f"MacroPadTest {uuid.uuid4().hex}"
        path = Path(QDir.temp().absoluteFilePath(f"{instance_name(name)}.lock"))
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        # PID that cannot be running, on this machine, in Qt's lock-file format.
        path.write_text(f"999999999\nMacroPadTest\n{QSysInfo.machineHostName()}\n")
        self.assertTrue(self.make(name).acquire())

    def test_nothing_to_notify_when_no_copy_runs(self):
        self.assertFalse(self.make(f"MacroPadTest {uuid.uuid4().hex}").notify_running(200))

    def test_names_are_safe_and_per_user(self):
        name = instance_name("Macro Pad DEV")
        self.assertRegex(name, r"^[a-z0-9_-]+$")
        self.assertTrue(name.startswith("macro-pad-dev-"))


if __name__ == "__main__":
    unittest.main()
