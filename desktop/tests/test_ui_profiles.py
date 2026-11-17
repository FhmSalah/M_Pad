"""Profile/metadata safety and second-pass UI checks without physical I/O."""

import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import app as gui
from config_store import ConfigStore
import run_actions as engine
from shortcut_keys import MODIFIERS
from test_v1_editor import FakeConnection, FakeKeyboard


class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        # The Windows offscreen plugin does not discover system fonts itself.
        if sys.platform == "win32":
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/seguisym.ttf")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.json"
        self.original = {
            "default_profile": "General",
            "applications": {"browser.exe": "Browser"},
            "profiles": {
                "General": {"KEY:1": {"type": "hotkey", "keys": ["ctrl", "g"]}},
                "Browser": {"KEY:1": {"type": "hotkey", "keys": ["ctrl", "b"]}},
            },
            "unknown_metadata": {"preserve": True},
        }
        self.path.write_text(json.dumps(self.original), encoding="utf-8")
        self.store = ConfigStore(self.path)

    def window(self):
        with patch.object(gui.EngineWorker, "start"):
            window = gui.MacroPadWindow(self.store)
        self.addCleanup(window.close)
        return window

    def import_file(self, document):
        path = Path(self.directory.name) / "import.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_legacy_config_needs_no_migration(self):
        before = self.path.read_bytes()
        self.assertEqual(self.store.label("General", "KEY:1"), "")
        self.assertIsNone(self.store.locked_profile())
        self.assertEqual(self.store.current_profile(), "General")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.data, self.original)

    def test_label_persists_separately_without_changing_actions(self):
        compiled = self.store.snapshot()
        self.store.save_label("General", "KEY:1", "Undo")
        restored = ConfigStore(self.path)
        self.assertEqual(restored.label("General", "KEY:1"), "Undo")
        self.assertEqual(restored.data["profiles"], self.original["profiles"])
        self.assertEqual(restored.snapshot(), compiled)
        self.assertEqual(restored.data["unknown_metadata"], self.original["unknown_metadata"])
        self.store.save_label("General", "KEY:1", "")
        self.assertEqual(ConfigStore(self.path).label("General", "KEY:1"), "")

    def test_action_and_label_are_one_atomic_transaction(self):
        before = self.path.read_bytes()
        action = {"type": "hotkey", "keys": ["ctrl", "s"]}
        with patch("config_store.os.replace", side_effect=PermissionError("failure")):
            with self.assertRaises(OSError):
                self.store.save_assignment("General", "KEY:1", action, "Save")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.data, self.original)
        self.assertEqual(list(self.path.parent.glob(".config-*.tmp")), [])
        with patch("config_store.os.replace", wraps=os.replace) as replace:
            self.store.save_assignment("General", "KEY:1", action, "Save")
            self.assertEqual(replace.call_count, 1)
        restored = ConfigStore(self.path)
        self.assertEqual(restored.mapping("General", "KEY:1"), action)
        self.assertEqual(restored.label("General", "KEY:1"), "Save")

    def test_lock_survives_restart_and_manual_selection_changes_lock(self):
        self.store.set_locked_profile("Browser")
        restored = ConfigStore(self.path)
        self.assertEqual(restored.locked_profile(), "Browser")
        self.assertEqual(restored.current_profile(), "Browser")
        restored.select_profile("General")
        self.assertEqual(restored.current_profile(), "General")
        self.assertEqual(ConfigStore(self.path).locked_profile(), "General")

    def test_locked_watcher_blocks_auto_switch_and_unlock_restores_it(self):
        self.store.set_locked_profile("General")
        class PollStop:
            count = 0
            def is_set(inner):
                return inner.count == 2
            def wait(inner, interval):
                inner.count += 1
                if inner.count == 1:
                    self.store.set_locked_profile(None)
        state, changes = {}, []
        with patch.object(engine, "get_foreground_application", return_value="browser.exe"):
            engine.watch_profiles(self.store, state, PollStop(), changes.append)
        self.assertEqual(changes, ["General", "Browser"])
        self.assertEqual(state["profile"], "Browser")
        self.assertIsNone(ConfigStore(self.path).locked_profile())

    def test_manual_profile_is_immediate_and_auto_resumes_on_application_change(self):
        self.store.update_foreground_profile("browser.exe")
        self.store.select_profile("General")
        self.assertEqual(self.store.current_profile(), "General")
        self.assertEqual(self.store.update_foreground_profile("browser.exe"), "General")
        self.store.update_foreground_profile("other.exe")
        self.assertEqual(self.store.update_foreground_profile("browser.exe"), "Browser")
        self.assertEqual(ConfigStore(self.path).snapshot()[0], "General")

    def test_serial_actions_use_current_profile_even_with_stale_watcher_state(self):
        self.store.select_profile("Browser")
        stop, keyboard = Event(), FakeKeyboard()
        engine.listen(FakeConnection(b"KEY:1\n", stop), keyboard,
                      {"profile": "General"}, stop, self.store, engine.ActionGate())
        self.assertEqual(keyboard.presses, [MODIFIERS["ctrl"], "b"])
        self.assertEqual(keyboard.held, [])

    def test_locked_serial_actions_ignore_foreground_mapping(self):
        self.store.set_locked_profile("General")
        self.store.update_foreground_profile("browser.exe")
        stop, keyboard = Event(), FakeKeyboard()
        engine.listen(FakeConnection(b"KEY:1\n", stop), keyboard,
                      {"profile": "Browser"}, stop, self.store, engine.ActionGate())
        self.assertEqual(keyboard.presses, [MODIFIERS["ctrl"], "g"])

    def test_creation_is_empty_and_duplicates_do_not_overwrite(self):
        self.assertEqual(self.store.add_profile(" Photoshop "), "Photoshop")
        self.assertEqual(ConfigStore(self.path).data["profiles"]["Photoshop"], {})
        self.assertNotIn("Photoshop", self.store.snapshot()[2].values())
        before = self.path.read_bytes()
        for name in ("Photoshop", "", "   "):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.add_profile(name)
        self.assertEqual(self.path.read_bytes(), before)

    def test_delete_locked_default_profile_removes_stale_metadata(self):
        self.store.save_label("General", "KEY:1", "Undo")
        self.store.select_profile("General")
        self.store.set_locked_profile("General")
        self.store.delete_profile("General")
        restored = ConfigStore(self.path)
        self.assertEqual(restored.current_profile(), "Browser")
        self.assertEqual(restored.locked_profile(), "Browser")
        self.assertEqual(restored.snapshot()[0], "Browser")
        self.assertNotIn("General", restored.data.get("labels", {}))
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.delete_profile("Browser")
        self.assertEqual(self.path.read_bytes(), before)

    def test_delete_automatically_active_profile_removes_application_references(self):
        self.store.save_label("Browser", "KEY:1", "Address")
        self.store.update_foreground_profile("browser.exe")
        self.store.delete_profile("Browser")
        self.assertEqual(self.store.current_profile(), "General")
        self.assertEqual(self.store.data["applications"], {})
        self.assertNotIn("Browser", self.store.data["labels"])

    def test_valid_import_and_name_conflict(self):
        document = {"name": "Drawing", "mappings": {"KEY:3": {"type": "hotkey", "keys": ["b"]}},
                    "labels": {"KEY:3": "Brush"}}
        path = self.import_file(document)
        self.assertEqual(self.store.import_profile(path), "Drawing")
        self.assertEqual(self.store.label("Drawing", "KEY:3"), "Brush")
        self.assertEqual(self.store.mapping("Drawing", "KEY:3"), document["mappings"]["KEY:3"])
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.import_profile(path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.import_profile(path, "Drawing 2"), "Drawing 2")

    def test_one_profile_config_and_bare_mapping_import(self):
        path = self.import_file({"profiles": {"Empty": {}}, "labels": {"Empty": {"KEY:1": "Undo"}}})
        self.store.import_profile(path)
        self.assertEqual(self.store.label("Empty", "KEY:1"), "Undo")
        path = self.import_file({"ENC1:PRESS": {"type": "media_key", "key": "volume_mute"}})
        self.assertEqual(self.store.import_profile(path), "import")

    def test_malformed_and_unsupported_import_is_rejected_without_writes(self):
        invalid = [[], {"profiles": {}}, {"profiles": {"A": {}, "B": {}}},
                   {"name": "Bad", "mappings": []},
                   {"name": "Bad", "mappings": {"KEY:19": {"type": "unassigned"}}},
                   {"name": "Bad", "mappings": {"KEY:1": {"type": "script"}}},
                   {"name": "Bad", "mappings": {}, "labels": {"KEY:1": 2}}]
        before = self.path.read_bytes()
        for document in invalid:
            with self.subTest(document=document), self.assertRaises(ValueError):
                self.store.import_profile(self.import_file(document))
            self.assertEqual(self.path.read_bytes(), before)
        path = self.import_file({})
        path.write_text("not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.import_profile(path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_all_new_writes_refuse_external_edits(self):
        path = self.import_file({"name": "Imported", "mappings": {}})
        operations = [lambda: self.store.save_label("General", "KEY:1", "Undo"),
                      lambda: self.store.set_locked_profile("General"),
                      lambda: self.store.select_profile("Browser"),
                      lambda: self.store.add_profile("New"),
                      lambda: self.store.delete_profile("Browser"),
                      lambda: self.store.import_profile(path)]
        external = b'{"external":true}'
        self.path.write_bytes(external)
        for operation in operations:
            with self.assertRaises(ValueError):
                operation()
            self.assertEqual(self.path.read_bytes(), external)
            self.assertEqual(self.store.data, self.original)
            self.assertEqual(self.store.current_profile(), "General")

    def test_metadata_write_checks_external_change_during_flush(self):
        external = b'{"external":true}'
        with patch("config_store.os.fsync", side_effect=lambda _: self.path.write_bytes(external)):
            with self.assertRaises(ValueError):
                self.store.save_label("General", "KEY:1", "Undo")
        self.assertEqual(self.path.read_bytes(), external)
        self.assertEqual(self.store.data, self.original)
        self.assertEqual(list(self.path.parent.glob(".config-*.tmp")), [])

    def test_concurrent_writes_preserve_both_updates_without_blocking_action_reads(self):
        flushing, release, errors = Event(), Event(), []
        def pause_flush(_):
            flushing.set()
            if not release.wait(2):
                raise RuntimeError("Test did not release the writer")
        def write(operation):
            try:
                operation()
            except Exception as error:
                errors.append(error)
        label_writer = Thread(target=write, args=(lambda: self.store.save_label("General", "KEY:1", "Undo"),))
        action = {"type": "hotkey", "keys": ["ctrl", "s"]}
        mapping_writer = Thread(target=write, args=(lambda: self.store.save_mapping("General", "KEY:1", action),))
        with patch("config_store.os.fsync", side_effect=pause_flush):
            label_writer.start()
            try:
                self.assertTrue(flushing.wait(2))
                mapping_writer.start()
                self.assertEqual(self.store.active_action_keys(b"KEY:1"), [MODIFIERS["ctrl"], "g"])
            finally:
                release.set()
                label_writer.join(3)
                if mapping_writer.ident is not None:
                    mapping_writer.join(3)
        self.assertFalse(label_writer.is_alive())
        self.assertFalse(mapping_writer.is_alive())
        self.assertEqual(errors, [])
        restored = ConfigStore(self.path)
        self.assertEqual(restored.label("General", "KEY:1"), "Undo")
        self.assertEqual(restored.mapping("General", "KEY:1"), action)

    def test_show_mode_uses_only_labels_and_selection_still_works(self):
        self.store.save_label("General", "KEY:1", "Undo")
        window = self.window()
        window.show()
        self.qt.processEvents()
        self.assertFalse(window.eye_button.isChecked())
        self.assertFalse(window.buttons["KEY:1"].show_label)
        self.assertEqual(window.buttons["KEY:1"].text(), "Undo")
        self.assertEqual(window.buttons["KEY:2"].text(), "")
        window.eye_button.click()
        self.assertTrue(window.buttons["KEY:1"].show_label)
        self.assertEqual(window.buttons["KEY:1"].text(), "Undo")
        for event, button in window.buttons.items():
            if event.endswith((":CW", ":CCW")):
                QTest.mouseClick(window.pad_widget.knobs[int(event[3])], Qt.MouseButton.LeftButton)
                QTest.mouseClick(window.direction_buttons[event.split(":")[1]], Qt.MouseButton.LeftButton)
            else:
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            self.assertEqual(window.selected_control, event)
            self.assertTrue(button.isChecked())
        window.eye_button.click()
        self.assertFalse(window.buttons["KEY:1"].show_label)

    def test_encoder_directions_and_unassigned_type_selection(self):
        window = self.window()
        window.show()
        window.select_control(gui.CONTROLS.index("ENC1:CW"))
        self.assertTrue(window.direction_controls.isVisible())
        self.assertTrue(window.direction_buttons["CW"].isChecked())
        window.direction_buttons["CCW"].click()
        self.assertEqual(window.selected_control, "ENC1:CCW")
        self.assertTrue(window.buttons["ENC1:CCW"].isChecked())
        window.buttons["ENC1:PRESS"].click()
        self.assertFalse(window.direction_controls.isVisible())
        window.type_buttons["hotkey"].click()
        window.action_type.setCurrentIndex(window.action_type.findData("unassigned"))
        self.assertFalse(any(button.isChecked() for button in window.type_buttons.values()))
        self.assertNotIn("unassigned", window.type_buttons)

    def test_gui_save_includes_label_and_disconnection_does_not_disable_editor(self):
        window = self.window()
        window.set_connection(False)
        self.assertFalse(window.pad_widget.connected)
        self.assertTrue(window.pad_widget.isEnabled())
        self.assertTrue(window.name_field.isEnabled())
        QTest.keyClicks(window.name_field, "Undo")
        self.assertTrue(window.save_button.isEnabled())
        window.save_button.click()
        self.assertEqual(ConfigStore(self.path).label("General", "KEY:1"), "Undo")
        self.assertEqual(self.store.mapping("General", "KEY:1"), self.original["profiles"]["General"]["KEY:1"])
        window.clear_button.click()
        self.assertEqual(self.store.mapping("General", "KEY:1"), {"type": "unassigned"})
        self.assertEqual(self.store.label("General", "KEY:1"), "Undo")
        self.assertEqual(window.save_button.height(), window.clear_button.height())

    def test_gui_profile_matches_engine_and_stale_callbacks_are_ignored(self):
        window = self.window()
        window.choose_profile("Browser")
        self.assertEqual(window.profile_button.text(), self.store.current_profile())
        window.set_profile("General")
        self.assertEqual(window.profile_button.text(), "Browser")
        window.toggle_profile_lock()
        self.assertFalse(window.profile_button.icon().isNull())
        self.store.update_foreground_profile("other.exe")
        self.assertEqual(window.profile_button.text(), self.store.current_profile())
        window.toggle_profile_lock()
        self.assertTrue(window.profile_button.icon().isNull())
        self.store.update_foreground_profile("browser.exe")
        self.store.update_foreground_profile("other.exe")
        window.set_profile(self.store.current_profile())
        self.assertEqual(window.edit_profile.currentText(), self.store.current_profile())

    def test_gui_deletion_requires_confirmation(self):
        window = self.window()
        with patch.object(gui.ConfirmationDialog, "confirm", return_value=False):
            window.delete_profile()
        self.assertIn("General", self.store.data["profiles"])
        with patch.object(gui.ConfirmationDialog, "confirm", return_value=True):
            window.delete_profile()
        self.assertNotIn("General", self.store.data["profiles"])
        self.assertEqual(window.profile_button.text(), self.store.current_profile())

    def test_gui_add_and_import_conflict_prompt_select_new_profiles(self):
        window = self.window()
        with patch.object(gui.ProfileNameDialog, "get_name", return_value=("Drawing", True)):
            window.add_profile()
        self.assertEqual(window.profile_button.text(), "Drawing")
        self.assertEqual(self.store.current_profile(), "Drawing")
        path = self.import_file({"name": "Drawing", "mappings": {"KEY:1": {"type": "hotkey", "keys": ["b"]}}})
        with patch.object(gui.QFileDialog, "getOpenFileName", return_value=(str(path), "")), \
             patch.object(gui.QInputDialog, "getText", return_value=("Drawing 2", True)) as prompt:
            window.import_profile()
        prompt.assert_called_once()
        self.assertEqual(window.profile_button.text(), "Drawing 2")
        self.assertEqual(self.store.current_profile(), "Drawing 2")
        self.assertEqual(self.store.mapping("Drawing", "KEY:1"), None)

    def test_recording_gate_covers_new_editor_controls(self):
        window = self.window()
        window.recorder.start()
        self.assertTrue(window.gate.snapshot()[0])
        for widget in (window.profile_button, window.name_field, window.direction_controls, window.type_controls):
            self.assertFalse(widget.isEnabled())
        window.recorder.finish()
        self.assertFalse(window.gate.snapshot()[0])
        self.assertTrue(window.profile_button.isEnabled())

    def test_stale_draft_is_not_saved_after_automatic_profile_change(self):
        window = self.window()
        QTest.keyClicks(window.name_field, "Undo")
        self.store.update_foreground_profile("browser.exe")
        window.save_assignment()
        self.assertEqual(window.profile_button.text(), "Browser")
        self.assertEqual(self.store.label("General", "KEY:1"), "")
        self.assertEqual(self.store.label("Browser", "KEY:1"), "")

    def test_long_labels_are_limited_to_two_elided_lines(self):
        window = self.window()
        metrics = QFontMetrics(window.font())
        for name in ("A very long name that cannot fit onto a small physical keycap", "x" * 200):
            lines = gui.DeviceControl.label_lines(name, metrics, 55)
            self.assertLessEqual(len(lines), 2)
            self.assertTrue(all(metrics.horizontalAdvance(line) <= 55 for line in lines))
            self.assertTrue(lines[-1].endswith("…") or lines[-1].endswith("..."))


if __name__ == "__main__":
    unittest.main()
