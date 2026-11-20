"""Focused V1 failure-path checks; no real serial or keyboard I/O."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

import app_paths
from config_store import ConfigStore
import detect_device
import run_actions as engine
from shortcut_keys import MODIFIERS
from shortcut_recorder import ShortcutRecorder
from test_v1_editor import FakeConnection, FakeKeyboard
from threading import Event


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_config_path_source_and_frozen_ignore_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            try:
                os.chdir(directory)
                with patch.object(sys, "frozen", False, create=True), \
                     patch.object(sys, "platform", "win32"):
                    self.assertEqual(app_paths.config_path(),
                                     Path(app_paths.__file__).resolve().parent / "config.json")
                with patch.object(sys, "frozen", False, create=True), \
                     patch.object(sys, "platform", "darwin"):
                    # macOS source runs use their own "Macro Pad DEV" settings folder.
                    self.assertEqual(app_paths.config_path(), Path.home() / "Library" / "Application Support"
                                     / "Macro Pad DEV" / "config.json")
                executable = Path(directory).resolve() / "Macro Pad.exe"  # macOS: /var -> /private/var
                app_data = Path(directory) / "AppData"
                with patch.object(sys, "frozen", True, create=True), \
                     patch.object(sys, "platform", "win32"), \
                     patch.dict(os.environ, {"APPDATA": str(app_data)}), \
                     patch.object(sys, "executable", str(executable)), \
                     patch.object(sys, "_MEIPASS", str(Path(directory) / "_internal"), create=True):
                    # Installed builds keep per-user settings in %APPDATA%, never beside the exe.
                    self.assertEqual(app_paths.config_path(), app_data / "Macro Pad" / "config.json")
                    self.assertEqual(app_paths.legacy_config_path(), executable.parent / "config.json")
            finally:
                os.chdir(previous)

    def test_press_failure_still_releases_attempted_modifier(self):
        keyboard = FakeKeyboard()
        keyboard.on_press = lambda key: (_ for _ in ()).throw(OSError("backend press failure"))
        with self.assertRaises(OSError):
            engine.execute_hotkey(keyboard, [MODIFIERS["ctrl"], "f"])
        self.assertEqual(keyboard.held, [])
        self.assertEqual(keyboard.presses, [MODIFIERS["ctrl"]])

    def test_transient_release_failure_retries_and_releases_modifiers(self):
        keyboard = FakeKeyboard()
        release = keyboard.release
        attempts = []
        def fail_once(key):
            attempts.append(key)
            if len(attempts) == 1:
                raise OSError("transient release failure")
            release(key)
        keyboard.release = fail_once
        engine.execute_hotkey(keyboard, [MODIFIERS["ctrl"], "f"])
        self.assertEqual(attempts, ["f", "f", MODIFIERS["ctrl"]])
        self.assertEqual(keyboard.held, [])

    def test_unsupported_media_backend_does_not_end_serial_reader(self):
        stop = Event()
        keyboard = FakeKeyboard()
        def reject_media(key):
            if key != MODIFIERS["ctrl"] and key != "f":
                raise NotImplementedError("unsupported backend key")
        keyboard.on_press = reject_media
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes((Path(__file__).resolve().parent / "fixtures" / "config.json").read_bytes())
            store = ConfigStore(path)
            store.select_profile("General")
            connection = FakeConnection(b"ENC2:CW\nKEY:1\n", stop)
            engine.listen(connection, keyboard, {"profile": "General"}, stop, store, engine.ActionGate())
        self.assertEqual(keyboard.presses[-2:], [MODIFIERS["ctrl"], "f"])
        self.assertEqual(keyboard.held, [])

    def test_recorder_ignores_input_when_inactive_and_clears_state(self):
        recorder = ShortcutRecorder()
        recorder.start()
        recorder.candidate = ["alt", "f4"]
        recorder.invalid_chord = True
        recorder.finish()
        self.assertIsNone(recorder.candidate)
        self.assertFalse(recorder.invalid_chord)
        recorder.setText("Original preview")
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(recorder, QKeyEvent(kind, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(recorder.text(), "Original preview")
        self.assertEqual(recorder.held, set())
        recorder.close()

    def test_discovery_errors_and_disappearing_probe_are_safe(self):
        with patch.object(detect_device.list_ports, "comports", side_effect=OSError("enumeration failed")):
            self.assertIsNone(detect_device.find_macro_pad())
        class Probe:
            def close(self):
                raise OSError("port already gone")
        with patch.object(detect_device.serial, "Serial", return_value=Probe()), \
             patch.object(detect_device, "handshake", return_value=False):
            self.assertIsNone(detect_device.open_macro_pad("MOCK"))

    def test_external_edit_during_flush_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes((Path(__file__).resolve().parent / "fixtures" / "config.json").read_bytes())
            store = ConfigStore(path)
            previous = store.mapping("General", "KEY:1")
            changed = json.loads(path.read_text())
            changed["external_edit"] = True
            external = json.dumps(changed).encode("utf-8")
            with patch("config_store.os.fsync", side_effect=lambda _: path.write_bytes(external)):
                with self.assertRaises(ValueError):
                    store.save_mapping("General", "KEY:1", {"type": "unassigned"})
            self.assertEqual(path.read_bytes(), external)
            self.assertEqual(store.mapping("General", "KEY:1"), previous)
            self.assertEqual(list(path.parent.glob(".config-*.tmp")), [])

    def test_windowed_missing_console_streams_do_not_break_config_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("bad json")
            with patch.object(sys, "stdout", None), patch.object(sys, "stderr", None):
                store = ConfigStore(path)
            self.assertTrue(store.error)


if __name__ == "__main__":
    unittest.main()
