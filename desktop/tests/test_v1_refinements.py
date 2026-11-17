"""Third-pass behavior checks; all keyboard, mouse and audio output is mocked."""

import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import app as gui
from config_store import APPLICATION_PROFILES, ConfigStore, PROFILE_FORMAT
import run_actions as engine
from shortcut_keys import MEDIA_LABELS, MODIFIERS, ScrollAction, action_label, resolve_action
from test_v1_editor import FakeConnection, FakeKeyboard


class RefinementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        if sys.platform == "win32":
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/seguisym.ttf")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.json"
        self.document = {
            "default_profile": "General",
            "profiles": {
                "General": {"KEY:1": {"type": "hotkey", "keys": ["ctrl", "a"]},
                            "ENC1:CW": {"type": "media_key", "key": "scroll_up"}},
                "Browser": {},
            },
            "labels": {"General": {"KEY:1": "Undo", "ENC1:CW": "Scroll", "ENC1:PRESS": "Mute"}},
            "applications": {"personal.exe": "General"},
            "preserved": {"example": True},
        }
        self.path.write_text(json.dumps(self.document), encoding="utf-8")
        self.store = ConfigStore(self.path)

    def window(self):
        with patch.object(gui.EngineWorker, "start"):
            window = gui.MacroPadWindow(self.store)
        self.addCleanup(window.close)
        window.show()
        self.qt.processEvents()
        return window

    def test_all_18_valid_inputs_report_activity_after_output(self):
        stop, keyboard, mouse = Event(), FakeKeyboard(), Mock()
        data = b"READY\nKEY:19\n" + b"".join(event.encode("ascii") + b"\n" for event in gui.CONTROLS)
        delivered = []
        def submit(profile, event, assigned, label):
            if event == "KEY:1":
                self.assertEqual(keyboard.presses, [MODIFIERS["ctrl"], "a"])
            if event == "ENC1:CW":
                mouse.scroll.assert_called_once_with(0, 1)
            delivered.append((profile, event, assigned, label))
        with patch.object(engine, "ActivityDispatcher") as dispatcher, \
             patch.object(engine, "MouseController", return_value=mouse):
            dispatcher.return_value.submit.side_effect = submit
            engine.listen(FakeConnection(data, stop), keyboard, {}, stop, self.store, engine.ActionGate(), Mock())
        self.assertEqual([item[1] for item in delivered], gui.CONTROLS)
        self.assertEqual(delivered[0], ("General", "KEY:1", True, "Undo"))
        self.assertEqual(delivered[1], ("General", "KEY:2", False, ""))

    def test_blocked_activity_observer_does_not_delay_next_action(self):
        started, release, stop = Event(), Event(), Event()
        keyboard = FakeKeyboard()
        def callback(*activity):
            started.set()
            release.wait(2)
        dispatcher = engine.ActivityDispatcher(callback)
        self.addCleanup(lambda: (release.set(), dispatcher.close(), dispatcher.thread.join(2)))
        class Connection(FakeConnection):
            def read(inner, count):
                if len(inner.data) == len(b"KEY:1\n"):
                    self.assertTrue(started.wait(1))
                return super().read(count)
        with patch.object(engine, "ActivityDispatcher", return_value=dispatcher):
            engine.listen(Connection(b"KEY:1\nKEY:1\n", stop), keyboard, {}, stop,
                          self.store, engine.ActionGate(), callback)
        self.assertFalse(release.is_set())
        self.assertEqual(keyboard.presses, [MODIFIERS["ctrl"], "a"] * 2)

    def test_dispatcher_coalesces_rapid_input_and_bounds_pending_feedback(self):
        started, release = Event(), Event()
        dispatcher = engine.ActivityDispatcher(lambda *args: (started.set(), release.wait(2)))
        self.addCleanup(lambda: (release.set(), dispatcher.close(), dispatcher.thread.join(2)))
        dispatcher.submit("General", "ENC1:CW", True, "First")
        self.assertTrue(started.wait(1))
        for number in range(1000):
            dispatcher.submit("General", "ENC1:CW", True, str(number))
        with dispatcher.condition:
            self.assertEqual(len(dispatcher.pending), 1)
            self.assertEqual(dispatcher.pending["ENC1:CW"][-1], "999")
        for control in gui.CONTROLS:
            dispatcher.submit("General", control, True, "")
        with dispatcher.condition:
            self.assertEqual(len(dispatcher.pending), 18)

    def test_scroll_up_and_down_resolve_and_use_mouse_without_keyboard_output(self):
        for name, steps in (("scroll_up", 1), ("scroll_down", -1)):
            with self.subTest(name=name):
                keys = resolve_action({"type": "media_key", "key": name})
                self.assertEqual(keys, [ScrollAction(steps)])
                self.assertEqual(action_label({"type": "media_key", "key": name}), MEDIA_LABELS[name])
                keyboard, mouse = FakeKeyboard(), Mock()
                with patch.object(engine, "MouseController", return_value=mouse):
                    engine.execute_hotkey(keyboard, keys)
                mouse.scroll.assert_called_once_with(0, steps)
                self.assertEqual(keyboard.presses, [])

    def test_scroll_respects_recorder_gate_and_stop(self):
        gate, mouse = engine.ActionGate(), Mock()
        gate.set_paused(True)
        engine.execute_hotkey(FakeKeyboard(), [ScrollAction(1)], gate=gate, generation=gate.snapshot()[1], mouse=mouse)
        mouse.scroll.assert_not_called()
        stop = Event()
        stop.set()
        engine.execute_hotkey(FakeKeyboard(), [ScrollAction(-1)], stop=stop, mouse=mouse)
        mouse.scroll.assert_not_called()

    def test_scroll_controller_is_reused_by_serial_loop(self):
        stop, mouse = Event(), Mock()
        with patch.object(engine, "MouseController", return_value=mouse) as factory:
            engine.listen(FakeConnection(b"ENC1:CW\nENC1:CW\n", stop), FakeKeyboard(), {}, stop, self.store, engine.ActionGate())
        factory.assert_called_once()
        self.assertEqual(mouse.scroll.call_count, 2)

    def test_feedback_restarts_one_animation_and_keeps_edit_selection(self):
        window = self.window()
        selected = window.selected_control
        activity = window.pad_widget.activities["KEY:1"]
        animation = activity.animation
        for number in range(100):
            window.show_activity("General", "KEY:1", True, str(number))
        self.assertIs(activity.animation, animation)
        self.assertEqual(activity.animation.state(), QAbstractAnimation.State.Running)
        self.assertEqual(activity.animation.currentTime(), 0)
        self.assertEqual(activity.label, "99")
        activity.animation.setCurrentTime(220)
        self.assertEqual(activity.level, 1.0)
        self.assertEqual(window.selected_control, selected)
        self.assertTrue(window.buttons["KEY:1"].isChecked())
        self.assertFalse(window.eye_button.isChecked())
        activity.animation.setCurrentTime(1300)
        self.assertGreater(activity.level, 0)
        self.assertLess(activity.level, 1)
        activity.animation.setCurrentTime(2200)
        self.assertEqual(activity.level, 0)
        self.assertTrue(window.buttons["KEY:1"].isChecked())

    def test_encoder_contacts_share_feedback_and_unassigned_is_neutral(self):
        window = self.window()
        for control in ("ENC1:CW", "ENC1:CCW", "ENC1:PRESS"):
            window.show_activity("General", control, False, "Mute")
            state = window.pad_widget.activities["ENC1"]
            self.assertIs(window.buttons[control].feedback, state)
            self.assertEqual(state.control_id, control)
            self.assertEqual(state.color().name(), "#d8dce2")
        window.show_activity("General", "KEY:1", True, "Undo")
        self.assertEqual(window.pad_widget.activities["KEY:1"].color().name(), "#f5a34b")

    def test_profile_change_clears_feedback_and_drops_old_events(self):
        window = self.window()
        window.show_activity("General", "KEY:1", True, "Undo")
        window.choose_profile("Browser")
        activity = window.pad_widget.activities["KEY:1"]
        self.assertEqual(activity.animation.state(), QAbstractAnimation.State.Stopped)
        self.assertEqual(activity.label, "")
        window.show_activity("General", "KEY:1", True, "Old label")
        self.assertEqual(activity.label, "")

    def test_rename_updates_every_profile_reference_and_keeps_mappings(self):
        self.store.select_profile("General")
        self.store.set_locked_profile("General")
        self.store.rename_profile("General", "Work")
        restored = ConfigStore(self.path)
        self.assertNotIn("General", restored.data["profiles"])
        self.assertEqual(restored.data["profiles"]["Work"], self.document["profiles"]["General"])
        self.assertEqual(restored.label("Work", "KEY:1"), "Undo")
        self.assertEqual(restored.locked_profile(), "Work")
        self.assertEqual(restored.current_profile(), "Work")
        self.assertEqual(restored.snapshot()[0], "Work")
        self.assertIsNone(self.store.manual_profile)
        self.assertEqual(restored.data["applications"]["personal.exe"], "Work")
        self.assertEqual(restored.data["preserved"], self.document["preserved"])

    def test_rename_updates_unlocked_manual_profile(self):
        self.store.select_profile("General")
        self.store.rename_profile("General", "Work")
        self.assertEqual(self.store.manual_profile, "Work")
        self.assertEqual(self.store.current_profile(), "Work")
        self.assertEqual(self.store.active_action_keys(b"KEY:1"), [MODIFIERS["ctrl"], "a"])

    def test_rename_preserves_implicit_application_alias(self):
        self.store.add_profile("Photoshop")
        self.assertEqual(self.store.update_foreground_profile("photoshop.exe"), "Photoshop")
        self.store.rename_profile("Photoshop", "Photo work")
        self.assertEqual(self.store.current_profile(), "Photo work")
        self.assertEqual(self.store.update_foreground_profile("photoshop.exe"), "Photo work")
        self.assertEqual(ConfigStore(self.path).data["applications"]["photoshop.exe"], "Photo work")

    def test_import_preserves_existing_application_binding_case_insensitively(self):
        self.document["applications"] = {"PERSONAL.EXE": "Browser"}
        self.path.write_text(json.dumps(self.document))
        store = ConfigStore(self.path)
        destination = Path(self.directory.name) / "import.json"
        destination.write_text(json.dumps({"format": PROFILE_FORMAT, "name": "Work", "mappings": {},
                                           "applications": {"personal.exe": "Work"}}))
        store.import_profile(destination)
        self.assertEqual(store.update_foreground_profile("personal.exe"), "Browser")

    def test_empty_duplicate_and_failed_rename_preserve_disk_and_state(self):
        before = self.path.read_bytes()
        for name in ("", " ", "Browser"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.rename_profile("General", name)
        with patch("config_store.os.replace", side_effect=PermissionError("mock failure")):
            with self.assertRaises(OSError):
                self.store.rename_profile("General", "Work")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.current_profile(), "General")
        self.assertEqual(self.store.data, self.document)

    def test_export_contains_one_profile_and_no_lock_state(self):
        self.store.set_locked_profile("General")
        destination = Path(self.directory.name) / "export.json"
        config_before = self.path.read_bytes()
        self.store.export_profile("General", destination)
        document = json.loads(destination.read_text())
        self.assertEqual(document["format"], PROFILE_FORMAT)
        self.assertEqual(document["name"], "General")
        self.assertEqual(document["mappings"], self.document["profiles"]["General"])
        self.assertEqual(document["labels"], self.document["labels"]["General"])
        self.assertEqual(document["applications"], {"personal.exe": "General"})
        self.assertNotIn("locked_profile", document)
        self.assertNotIn("profiles", document)
        self.assertEqual(self.path.read_bytes(), config_before)
        with self.assertRaises(ValueError):
            self.store.export_profile("General", self.path, overwrite=True)
        with self.assertRaises(ValueError):
            self.store.export_profile("General", destination)

    def test_export_import_round_trip_includes_labels_and_associations(self):
        destination = Path(self.directory.name) / "export.json"
        self.store.export_profile("General", destination)
        imported = self.store.import_profile(destination, "Imported")
        self.assertEqual(self.store.data["profiles"][imported], self.document["profiles"]["General"])
        self.assertEqual(self.store.data["labels"][imported], self.document["labels"]["General"])
        # An import may not redirect an application already assigned elsewhere.
        self.assertEqual(self.store.data["applications"]["personal.exe"], "General")
        fresh_path = Path(self.directory.name) / "fresh.json"
        fresh_path.write_text(json.dumps({"default_profile": "Empty", "profiles": {"Empty": {}}}))
        fresh = ConfigStore(fresh_path)
        fresh.import_profile(destination)
        self.assertEqual(fresh.data["applications"], {"personal.exe": "General"})
        self.assertEqual(fresh.data["profiles"]["General"], self.document["profiles"]["General"])
        self.assertEqual(fresh.data["labels"]["General"], self.document["labels"]["General"])

    def test_export_failure_and_external_destination_change_are_safe(self):
        destination = Path(self.directory.name) / "export.json"
        destination.write_bytes(b"previous")
        with patch("config_store.os.fsync", side_effect=lambda _: destination.write_bytes(b"external")):
            with self.assertRaises(ValueError):
                self.store.export_profile("General", destination, overwrite=True)
        self.assertEqual(destination.read_bytes(), b"external")
        self.assertEqual(list(destination.parent.glob(".profile-*.tmp")), [])

    def test_versioned_import_rejects_unknown_format_and_other_profile_references(self):
        destination = Path(self.directory.name) / "import.json"
        for document in ({"format": "MacroPadProfileV9", "name": "X", "mappings": {}},
                         {"format": PROFILE_FORMAT, "name": "X", "mappings": {}, "applications": {"app.exe": "Other"}}):
            destination.write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                self.store.import_profile(destination)

    def test_all_application_aliases_switch_only_when_profile_exists(self):
        for profile in set(APPLICATION_PROFILES.values()):
            if profile not in self.store.snapshot()[1]:
                self.store.add_profile(profile)
        for executable, profile in APPLICATION_PROFILES.items():
            with self.subTest(executable=executable):
                self.assertEqual(self.store.update_foreground_profile(executable.upper()), profile)
        self.store.delete_profile("Photoshop")
        self.assertEqual(self.store.update_foreground_profile("photoshop.exe"), "General")
        self.assertNotIn("Photoshop", self.store.data["profiles"])

    def test_explicit_application_mapping_and_lock_override_aliases(self):
        self.store.add_profile("Photoshop")
        self.store.set_locked_profile("General")
        for executable in APPLICATION_PROFILES:
            self.assertEqual(self.store.update_foreground_profile(executable), "General")
        self.store.set_locked_profile(None)
        self.assertEqual(self.store.update_foreground_profile("photoshop.exe"), "Photoshop")
        # A user association wins over the built-in alias.
        self.document["applications"]["photoshop.exe"] = "Browser"
        self.path.write_text(json.dumps(self.document))
        explicit = ConfigStore(self.path)
        self.assertEqual(explicit.update_foreground_profile("photoshop.exe"), "Browser")

    def test_normal_eye_click_toggles_and_alt_eye_click_only_triggers_overlay(self):
        window = self.window()
        with patch.object(gui, "QSoundEffect") as sound:
            QTest.mouseClick(window.eye_button, Qt.MouseButton.LeftButton)
            self.assertTrue(window.eye_button.isChecked())
            self.assertFalse(window.easter_overlay.isVisible())
            sound.assert_not_called()
            QTest.mouseClick(window.eye_button, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier)
            self.assertTrue(window.eye_button.isChecked())
            self.assertTrue(window.easter_overlay.isVisible())
            self.assertEqual(window.easter_overlay.geometry(), window.rect())
            sound.return_value.play.assert_called_once()
            self.assertEqual(window.easter_timer.interval(), 1000)
            window.easter_timer.timeout.emit()
            self.assertFalse(window.easter_overlay.isVisible())
            window.eye_button.setChecked(False)
            QTest.mouseClick(window.eye_button, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier)
            self.assertFalse(window.eye_button.isChecked())
            self.assertTrue(window.easter_overlay.isVisible())
            window.stop_easter_egg()

    def test_audio_failure_still_shows_overlay_without_pausing_engine(self):
        window = self.window()
        with patch.object(gui, "QSoundEffect", side_effect=RuntimeError("audio unavailable")):
            QTest.mouseClick(window.eye_button, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier)
        self.assertTrue(window.audio_failed)
        self.assertTrue(window.easter_overlay.isVisible())
        self.assertFalse(window.eye_button.isChecked())
        self.assertFalse(window.gate.snapshot()[0])

    def test_gui_rename_and_export_menu_wiring(self):
        window = self.window()
        with patch.object(gui.ProfileNameDialog, "get_name", return_value=("Work", True)):
            window.rename_profile()
        self.assertEqual(window.profile_button.text(), "Work")
        self.assertEqual(self.store.current_profile(), "Work")
        destination = Path(self.directory.name) / "export.json"
        with patch.object(gui.QFileDialog, "getSaveFileName", return_value=(str(destination), "")):
            window.export_profile()
        self.assertEqual(json.loads(destination.read_text())["name"], "Work")
        window.open_profile_menu()
        actions = [action.text() for action in window.profile_menu.actions()]
        self.assertIn("Rename...", actions)
        self.assertIn("Export...", actions)
        window.profile_menu.close()

    def test_inspector_heights_and_bottom_row_gap(self):
        window = self.window()
        for widget in (window.record_button, window.escape_button, window.media_widget,
                       *window.type_buttons.values(), *window.direction_buttons.values()):
            self.assertEqual(widget.height(), gui.INPUT_HEIGHT)
        self.assertEqual(window.clear_button.height(), window.save_button.height())
        self.assertEqual(window.clear_button.y(), window.save_button.y())
        self.assertGreater(window.save_button.x() - window.clear_button.geometry().right(), gui.S)


if __name__ == "__main__":
    unittest.main()
