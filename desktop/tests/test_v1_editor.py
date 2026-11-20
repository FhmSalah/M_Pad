"""Offscreen Qt/config/engine checks; no real serial ports or keyboard injection."""

import contextlib
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QApplication

import app as gui
import config_store
from config_store import ConfigStore
import run_actions as engine
import serial
from shortcut_keys import (
    MEDIA_KEYS, MODIFIERS, PUNCTUATION, SPECIAL_NAMES, resolve_action, resolve_key,
)
from shortcut_recorder import ShortcutRecorder, event_key_name


# Qt's Control key is the Command key on macOS, so record_ctrl_shift_s() records Shift+Cmd+S there.
CTRL_SHIFT_S = ["shift", "cmd", "s"] if sys.platform == "darwin" else ["ctrl", "shift", "s"]

class FakeKeyboard:
    def __init__(self):
        self.presses = []
        self.held = []
        self.on_press = lambda key: None

    @contextlib.contextmanager
    def pressed(self, key):
        self.press(key)
        try:
            yield
        finally:
            self.release(key)

    def press(self, key):
        self.presses.append(key)
        self.held.append(key)
        self.on_press(key)

    def release(self, key):
        if key in self.held:
            self.held.remove(key)


class FakeConnection:
    port = "MOCK"

    def __init__(self, data, stop):
        self.data = bytearray(data)
        self.stop = stop
        self.closed = False
        self.resets = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self, count):
        if self.data:
            return bytes([self.data.pop(0)])
        self.stop.set()
        return b""

    def reset_input_buffer(self):
        self.resets += 1
        self.data.clear()


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "config.json"
        self.original = json.loads((Path(__file__).resolve().parent / "fixtures" / "config.json").read_text(encoding="utf-8-sig"))
        # User-selected defaults/locks must not change these regression fixtures.
        self.original["default_profile"] = "General"
        self.original["locked_profile"] = None
        self.original["applications"] = {exe: "Browser" for exe in ("brave.exe", "opera.exe", "opera_gx.exe")}
        self.original["preserved_metadata"] = {"example": True}
        self.path.write_text(json.dumps(self.original), encoding="utf-8")
        self.store = ConfigStore(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def key_event(self, recorder, key, modifiers=Qt.KeyboardModifier.NoModifier,
                  release=False, native=0, autorepeat=False):
        event = QKeyEvent(
            QEvent.Type.KeyRelease if release else QEvent.Type.KeyPress,
            key, modifiers, 0, native, 0, "", autorepeat, 1,
        )
        QApplication.sendEvent(recorder, event)
        return event

    def record_ctrl_shift_s(self, recorder):
        ctrl = Qt.KeyboardModifier.ControlModifier
        shift = Qt.KeyboardModifier.ShiftModifier
        recorder.start()
        self.key_event(recorder, Qt.Key.Key_Control, ctrl)
        self.key_event(recorder, Qt.Key.Key_Shift, ctrl | shift)
        self.key_event(recorder, Qt.Key.Key_S, ctrl | shift)
        self.key_event(recorder, Qt.Key.Key_S, ctrl | shift, release=True)
        self.assertTrue(recorder.active)
        self.key_event(recorder, Qt.Key.Key_Shift, ctrl, release=True)
        self.assertTrue(recorder.active)
        self.key_event(recorder, Qt.Key.Key_Control, release=True)
        self.assertFalse(recorder.active)

    def test_atomic_save_preserves_other_profiles_and_unknown_fields(self):
        action = {"type": "hotkey", "keys": ["ctrl", "shift", "s"]}
        self.assertTrue(self.store.save_mapping("General", "KEY:3", action))
        saved = json.loads(self.path.read_text())
        expected = copy.deepcopy(self.original)
        expected["profiles"]["General"]["KEY:3"] = action
        self.assertEqual(saved, expected)
        self.assertEqual(self.store.action_keys("General", b"KEY:3"),
                         [MODIFIERS["ctrl"], MODIFIERS["shift"], "s"])
        with patch("config_store.os.replace") as replace:
            self.assertFalse(self.store.save_mapping("General", "KEY:3", action))
            replace.assert_not_called()

    def test_failed_save_keeps_disk_memory_and_removes_temporary_file(self):
        before = self.path.read_bytes()
        keys = self.store.action_keys("General", b"KEY:1")
        with patch("config_store.os.replace", side_effect=PermissionError("mock failure")):
            with self.assertRaises(OSError):
                self.store.save_mapping("General", "KEY:1", {"type": "unassigned"})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.action_keys("General", b"KEY:1"), keys)
        self.assertEqual(list(self.path.parent.glob(".config-*.tmp")), [])

    def test_invalid_and_external_config_is_not_overwritten(self):
        self.path.write_text("not json")
        broken = ConfigStore(self.path)
        with self.assertRaises(ValueError):
            broken.save_mapping("General", "KEY:1", {"type": "unassigned"})
        self.assertEqual(self.path.read_text(), "not json")
        with self.assertRaises(ValueError):
            self.store.save_mapping("General", "KEY:1", {"type": "unassigned"})

    def test_supported_key_names_and_invalid_entries(self):
        for name in (*SPECIAL_NAMES, *PUNCTUATION, *"abcdefghijklmnopqrstuvwxyz0123456789"):
            if name == "insert" and sys.platform == "darwin":
                # Macs have no Insert key (pynput has none there): such a mapping does nothing.
                self.assertIsNone(resolve_key(name))
                continue
            self.assertIsNotNone(resolve_key(name), name)
        self.assertIsNotNone(resolve_action({"type": "media_key", "key": "volume_mute"}))
        for action in (None, [], {"type": "script"}, {"type": "hotkey", "keys": []},
                       {"type": "hotkey", "keys": ["ctrl", []]},
                       {"type": "media_key", "key": []}):
            self.assertIsNone(resolve_action(action))
        self.assertEqual(resolve_action({"type": "unassigned"}), [])

    def test_recorder_waits_for_releases_and_ignores_repeat(self):
        recorder = ShortcutRecorder()
        captured = []
        recorder.recorded.connect(captured.append)
        self.record_ctrl_shift_s(recorder)
        self.assertEqual(captured, [CTRL_SHIFT_S])
        self.assertEqual(recorder.held, set())
        recorder.start()
        self.key_event(recorder, Qt.Key.Key_A)
        self.key_event(recorder, Qt.Key.Key_A, autorepeat=True)
        self.key_event(recorder, Qt.Key.Key_A, release=True)
        self.assertEqual(captured[-1], ["a"])
        recorder.close()

    def test_recorder_escape_tab_punctuation_and_alt_f4(self):
        recorder = ShortcutRecorder()
        captured, cancellations = [], []
        recorder.recorded.connect(captured.append)
        recorder.cancelled.connect(lambda: cancellations.append(True))
        recorder.start()
        self.key_event(recorder, Qt.Key.Key_Escape)
        self.assertFalse(recorder.active)
        self.assertEqual(cancellations, [True])
        for key, name, modifier, native in (
            (Qt.Key.Key_Tab, "tab", Qt.KeyboardModifier.NoModifier, 0),
            (Qt.Key.Key_F4, "f4", Qt.KeyboardModifier.AltModifier, 0),
            (Qt.Key.Key_BraceLeft, "left_bracket", Qt.KeyboardModifier.ShiftModifier, 0xDB),
        ):
            recorder.start()
            event = self.key_event(recorder, key, modifier, native=native)
            self.assertEqual(event_key_name(event), name)
            self.key_event(recorder, key, modifier, release=True, native=native)
            if modifier == Qt.KeyboardModifier.AltModifier:
                self.key_event(recorder, Qt.Key.Key_Alt, release=True)
            elif modifier == Qt.KeyboardModifier.ShiftModifier:
                self.key_event(recorder, Qt.Key.Key_Shift, release=True)
            self.assertFalse(recorder.active)
        self.assertEqual(captured, [["tab"], ["alt", "f4"], ["shift", "left_bracket"]])
        recorder.close()

    def test_editor_follows_active_profile_and_save_is_live(self):
        with patch.object(gui.EngineWorker, "start"):
            window = gui.MacroPadWindow(self.store)
        self.assertEqual(len(window.buttons), 18)
        self.assertEqual(window.edit_profile.currentText(), "General")
        self.store.update_foreground_profile("brave.exe")
        window.set_profile("Browser")
        self.assertEqual(window.edit_profile.currentText(), "Browser")
        self.assertEqual(window.profile_button.text(), self.store.current_profile())
        window.action_type.setCurrentIndex(window.action_type.findData("hotkey"))
        self.record_ctrl_shift_s(window.recorder)
        self.assertFalse(window.gate.snapshot()[0])
        window.save_assignment()
        self.assertEqual(self.store.mapping("Browser", "KEY:1")["keys"], CTRL_SHIFT_S)
        self.assertEqual(self.store.mapping("General", "KEY:1"),
                         self.original["profiles"]["General"]["KEY:1"])
        window.choose_profile("Browser")
        window.select_control(gui.CONTROLS.index("ENC1:PRESS"))
        window.action_type.setCurrentIndex(window.action_type.findData("media_key"))
        window.media_widget.setCurrentIndex(window.media_widget.findData("play_pause"))
        window.save_assignment()
        self.assertEqual(self.store.action_keys("Browser", b"ENC1:PRESS"), [MEDIA_KEYS["play_pause"]])
        window.clear_assignment()
        self.assertIsNone(self.store.action_keys("Browser", b"ENC1:PRESS"))
        window.close()

    def test_close_during_recording_cancels_gate_and_requests_shutdown(self):
        with patch.object(gui.EngineWorker, "start"):
            window = gui.MacroPadWindow(self.store)
        window.recorder.start()
        self.assertTrue(window.gate.snapshot()[0])
        with patch.object(gui.EngineWorker, "isRunning", return_value=True):
            event = QCloseEvent()
            window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(window.worker.stop.is_set())
        self.assertFalse(window.recorder.active)
        self.assertFalse(window.gate.snapshot()[0])
        window.close()

    def test_serial_dispatch_is_once_and_live_mapping_is_used(self):
        stop = Event()
        keyboard = FakeKeyboard()
        connection = FakeConnection(b"READY\r\nMACROPAD:V1\nKEY:1\nKEY:1\nKEY:13\nENC2:CW\n", stop)
        def update_after_first_key(key):
            if key == "f":
                self.store.save_mapping("General", "KEY:1", {"type": "hotkey", "keys": ["ctrl", "s"]})
        keyboard.on_press = update_after_first_key
        engine.listen(connection, keyboard, {"profile": "General"}, stop, self.store, engine.ActionGate())
        self.assertEqual(keyboard.presses,
                         [MODIFIERS["ctrl"], "f", MODIFIERS["ctrl"], "s", MEDIA_KEYS["volume_up"]])
        self.assertEqual(keyboard.held, [])

    def test_pause_discards_queued_input_before_resume(self):
        stop, gate = Event(), engine.ActionGate()
        keyboard = FakeKeyboard()
        connection = FakeConnection(b"KEY:1\n", stop)
        gate.set_paused(True)
        original_read = connection.read
        def resume_on_read(count):
            character = original_read(count)
            gate.set_paused(False)
            return character
        connection.read = resume_on_read
        engine.listen(connection, keyboard, {"profile": "General"}, stop, self.store, gate)
        self.assertEqual(keyboard.presses, [])
        self.assertEqual(connection.resets, 1)

    def test_modifier_release_on_cancellation_and_exception(self):
        keyboard, gate = FakeKeyboard(), engine.ActionGate()
        keyboard.on_press = lambda key: gate.set_paused(True)
        engine.execute_hotkey(keyboard, [MODIFIERS["ctrl"], "f"], gate=gate, generation=0)
        self.assertEqual(keyboard.presses, [MODIFIERS["ctrl"]])
        self.assertEqual(keyboard.held, [])
        keyboard = FakeKeyboard()
        def fail(key):
            if key == "f":
                raise ValueError("mock failure")
        keyboard.on_press = fail
        with self.assertRaises(ValueError):
            engine.execute_hotkey(keyboard, [MODIFIERS["ctrl"], "f"])
        self.assertEqual(keyboard.held, [])

    def test_engine_closes_serial_and_stops_worker(self):
        stop = Event()
        connection = FakeConnection(b"KEY:1\n", stop)
        keyboard = FakeKeyboard()
        statuses = []
        with patch.object(engine, "Controller", return_value=keyboard), \
             patch.object(engine, "find_macro_pad", return_value=connection), \
             patch.object(engine, "get_foreground_application", return_value="other.exe"):
            engine.run_engine(stop, on_connection=statuses.append, config_store=self.store)
        self.assertTrue(connection.closed)
        self.assertEqual(statuses, [False, True, False])
        self.assertEqual(keyboard.held, [])

    def test_profile_changes_are_reported_once(self):
        applications = iter(["brave.exe", "opera_gx.exe", "other.exe", None, "opera.exe"])
        class PollStop:
            count = 0
            def is_set(self):
                return self.count == 5
            def wait(self, interval):
                self.count += 1
        state, changes = {"profile": "General"}, []
        with patch.object(engine, "get_foreground_application", side_effect=lambda: next(applications)):
            engine.watch_profiles(self.store, state, PollStop(), changes.append)
        self.assertEqual(changes, ["Browser", "General", "Browser"])
        self.assertEqual(state["profile"], "Browser")

    def test_engine_reconnects_without_duplicate_execution(self):
        # Keep this fixture independent of the user's editable config.json.
        self.store.save_mapping("General", "KEY:2", {"type": "hotkey", "keys": ["ctrl", "a"]})
        stop = Event()
        first = FakeConnection(b"", stop)
        first.read = lambda count: (_ for _ in ()).throw(serial.SerialException("unplugged"))
        second = FakeConnection(b"KEY:2\n", stop)
        keyboard, connections = FakeKeyboard(), []
        with patch.object(engine, "Controller", return_value=keyboard), \
             patch.object(engine, "find_macro_pad", side_effect=[first, second]), \
             patch.object(engine, "get_foreground_application", return_value="other.exe"):
            engine.run_engine(stop, on_connection=connections.append,
                              config_store=self.store, reconnect=True)
        self.assertTrue(first.closed and second.closed)
        self.assertEqual(connections, [False, True, False, True, False])
        self.assertEqual(keyboard.presses, [MODIFIERS["ctrl"], "a"])
        self.assertEqual(keyboard.held, [])


if __name__ == "__main__":
    unittest.main()
