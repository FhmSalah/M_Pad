"""Final Windows UI checks using temporary configs and mocked action output."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QFontDatabase, QIcon, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel

import app as gui
from config_store import ConfigStore, compile_actions
import run_actions as engine
from shortcut_keys import ScrollAction
from test_v1_editor import FakeKeyboard


class PolishTests(unittest.TestCase):
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
            "profiles": {"General": {
                "ENC1:CW": {"type": "media_key", "key": "scroll_up"},
                "ENC1:CCW": {"type": "media_key", "key": "scroll_down"},
                "ENC1:PRESS": {"type": "media_key", "key": "volume_mute"},
            }, "Browser": {}},
            "labels": {"General": {"KEY:1": "Undo", "ENC1:CW": "Legacy name",
                                   "ENC1:PRESS": "Mute", "ENC2:PRESS": "Reset"}},
            "preserved": {"user_metadata": True},
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

    def test_app_naming_and_resource_icon(self):
        window = self.window()
        # Source runs on macOS are "Macro Pad DEV" so they never share the installed app's settings.
        expected_name = "Macro Pad DEV" if sys.platform == "darwin" else "Macro Pad"
        self.assertEqual(window.windowTitle(), expected_name)
        self.assertEqual(window.findChild(QLabel, "title").text(), expected_name)
        expected = QIcon(gui.resource_path("assets/app_icon.png"))
        self.assertFalse(expected.isNull())
        self.assertEqual(window.windowIcon().pixmap(32, 32).toImage(), expected.pixmap(32, 32).toImage())

    def test_confirmation_has_explicit_actions_and_cancel_default(self):
        window = self.window()
        dialog = gui.ConfirmationDialog(window, "Delete Profile", 'Delete "<Work>" and its assignments?', "Delete")
        self.addCleanup(dialog.close)
        dialog.show()
        self.qt.processEvents()
        self.assertEqual(dialog.cancel_button.text(), "Cancel")
        self.assertEqual(dialog.confirm_button.text(), "Delete")
        self.assertTrue(dialog.cancel_button.isDefault())
        self.assertFalse(dialog.confirm_button.autoDefault())
        self.assertEqual(dialog.cancel_button.height(), gui.INPUT_HEIGHT)
        self.assertEqual(dialog.confirm_button.height(), gui.INPUT_HEIGHT)
        self.assertEqual(dialog.cancel_button.y(), dialog.confirm_button.y())
        self.assertEqual(dialog.findChild(QLabel, "confirmationText").textFormat(), Qt.TextFormat.PlainText)

    def test_escape_and_cancel_leave_profile_and_lock_unchanged(self):
        window = self.window()
        self.store.set_locked_profile("General")
        before = self.path.read_bytes()
        for method in ("escape", "cancel", "return"):
            def cancel(method=method):
                dialog = QApplication.activeModalWidget()
                if method == "cancel":
                    dialog.cancel_button.click()
                else:
                    QTest.keyClick(dialog, Qt.Key.Key_Escape if method == "escape" else Qt.Key.Key_Return)
            QTimer.singleShot(0, cancel)
            window.delete_profile()
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(self.store.current_profile(), "General")
            self.assertEqual(self.store.locked_profile(), "General")

    def test_custom_delete_button_confirms_and_refreshes_profile(self):
        window = self.window()
        QTimer.singleShot(0, lambda: QApplication.activeModalWidget().confirm_button.click())
        window.delete_profile()
        self.assertNotIn("General", self.store.data["profiles"])
        self.assertEqual(self.store.current_profile(), "Browser")
        self.assertEqual(window.profile_button.text(), "Browser")

    def test_profile_input_blocks_empty_duplicate_and_stale_names(self):
        window = self.window()
        dialog = gui.ProfileNameDialog(window, self.store, "Add Profile", "Add")
        self.addCleanup(dialog.close)
        dialog.show()
        self.qt.processEvents()
        accepted = Mock()
        dialog.accepted.connect(accepted)
        for name in ("", "   ", "General", " Browser "):
            dialog.name_input.setText(name)
            self.assertFalse(dialog.confirm_button.isEnabled())
            QTest.keyClick(dialog.name_input, Qt.Key.Key_Return)
            dialog.accept()
            self.assertTrue(dialog.isVisible())
            accepted.assert_not_called()
        dialog.name_input.setText("Drawing")
        self.assertTrue(dialog.confirm_button.isEnabled())
        self.store.add_profile("Drawing")
        QTest.keyClick(dialog.name_input, Qt.Key.Key_Return)
        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog.confirm_button.isEnabled())
        accepted.assert_not_called()
        dialog.name_input.setText("Work")
        QTest.keyClick(dialog.name_input, Qt.Key.Key_Enter)
        accepted.assert_called_once()

    def test_profile_input_escape_and_cancel_do_not_write(self):
        window = self.window()
        before = self.path.read_bytes()
        for operation in (window.add_profile, window.rename_profile):
            for method in ("escape", "cancel"):
                def cancel(method=method):
                    dialog = QApplication.activeModalWidget()
                    dialog.name_input.setText("Work")
                    if method == "cancel":
                        dialog.cancel_button.click()
                    else:
                        QTest.keyClick(dialog.name_input, Qt.Key.Key_Escape)
                QTimer.singleShot(0, cancel)
                operation()
                self.assertEqual(self.path.read_bytes(), before)

    def test_add_accepts_valid_name_on_enter_and_keeps_lock_behavior(self):
        window = self.window()
        self.store.set_locked_profile("General")
        def add():
            dialog = QApplication.activeModalWidget()
            self.assertEqual(dialog.confirm_button.text(), "Add")
            dialog.name_input.setText("  Work  ")
            QTest.keyClick(dialog.name_input, Qt.Key.Key_Return)
        QTimer.singleShot(0, add)
        window.add_profile()
        self.assertIn("Work", self.store.data["profiles"])
        self.assertEqual(self.store.current_profile(), "Work")
        self.assertEqual(self.store.locked_profile(), "Work")
        self.assertEqual(window.profile_button.text(), "Work")

    def test_rename_input_prefills_and_preserves_profile_metadata(self):
        window = self.window()
        self.store.set_locked_profile("General")
        def rename():
            dialog = QApplication.activeModalWidget()
            self.assertEqual(dialog.confirm_button.text(), "Rename")
            self.assertEqual(dialog.name_input.text(), "General")
            self.assertTrue(dialog.confirm_button.isEnabled())
            dialog.name_input.setText("Browser")
            self.assertFalse(dialog.confirm_button.isEnabled())
            dialog.name_input.setText("  Work  ")
            dialog.confirm_button.click()
        QTimer.singleShot(0, rename)
        window.rename_profile()
        self.assertNotIn("General", self.store.data["profiles"])
        self.assertEqual(self.store.data["profiles"]["Work"], self.document["profiles"]["General"])
        self.assertEqual(self.store.data["labels"]["Work"], self.document["labels"]["General"])
        self.assertEqual(self.store.current_profile(), "Work")
        self.assertEqual(self.store.locked_profile(), "Work")
        self.assertEqual(window.profile_button.text(), "Work")

    def test_both_directions_edit_shared_name_without_merging_actions(self):
        window = self.window()
        original = self.store.data["profiles"]["General"].copy()
        for direction, name in (("CW", "Scroll"), ("CCW", "Timeline")):
            window.select_control(gui.CONTROLS.index("ENC1:" + direction))
            window.name_field.setText(name)
            window.mark_dirty()
            window.save_assignment()
            other = "CCW" if direction == "CW" else "CW"
            window.direction_buttons[other].click()
            self.assertEqual(window.name_field.text(), name)
        restored = ConfigStore(self.path)
        self.assertEqual(restored.data["profiles"]["General"], original)
        self.assertEqual(restored.label("General", "ENC1:ROTATE"), "Timeline")
        self.assertEqual(restored.label("General", "ENC1:PRESS"), "Mute")
        self.assertEqual(restored.label("General", "ENC1:CW"), "Legacy name")
        for direction in (b"ENC1:CW", b"ENC1:CCW"):
            self.assertEqual(restored.active_input(direction)[2], "Timeline")
        window.buttons["ENC1:PRESS"].click()
        self.assertEqual(window.name_field.text(), "Mute")
        self.assertEqual(restored.data["preserved"], self.document["preserved"])

    def test_shared_names_are_metadata_only_and_cannot_execute(self):
        for event in ("ENC1:ROTATE", "ENC2:ROTATE"):
            self.store.save_label("General", event, "Volume")
            with self.assertRaises(ValueError):
                self.store.save_mapping("General", event, {"type": "hotkey", "keys": ["a"]})
            with self.assertRaises(ValueError):
                self.store.save_assignment("General", event, {"type": "unassigned"}, "Name")
            self.assertNotIn(event, self.store.data["profiles"]["General"])
            self.assertIsNone(self.store.active_action_keys(event.encode("ascii")))
            with patch("builtins.print"):
                self.assertEqual(compile_actions({event: {"type": "hotkey", "keys": ["a"]}}), {})

    def test_legacy_config_stays_unchanged_and_rotation_name_has_no_fallback(self):
        before = self.path.read_bytes()
        window = self.window()
        window.select_control(gui.CONTROLS.index("ENC1:CW"))
        self.assertEqual(window.name_field.text(), "")
        self.assertEqual(window.pad_widget.encoder_names, {1: "", 2: ""})
        self.assertEqual(self.store.active_input(b"ENC1:CW")[2], "")
        self.assertEqual(self.path.read_bytes(), before)

    def test_shared_names_export_and_import_without_changing_mappings(self):
        self.store.save_label("General", "ENC1:ROTATE", "Scroll")
        self.store.save_label("General", "ENC2:ROTATE", "Brightness")
        exported = Path(self.directory.name) / "export.json"
        self.store.export_profile("General", exported)
        self.store.import_profile(exported, "Imported")
        self.assertEqual(self.store.data["profiles"]["Imported"], self.document["profiles"]["General"])
        self.assertEqual(self.store.data["labels"]["Imported"], self.store.data["labels"]["General"])
        payload = json.loads(exported.read_text(encoding="utf-8"))
        payload["mappings"]["ENC1:ROTATE"] = {"type": "unassigned"}
        exported.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.read_profile_import(exported)

    def test_eye_changes_only_mechanical_key_labels(self):
        self.store.save_label("General", "ENC1:ROTATE", "Scroll")
        self.store.save_label("General", "ENC2:ROTATE", "Brightness")
        window = self.window()
        preview = window.pad_widget
        encoder_strip = preview.image_rect.toAlignedRect()
        encoder_strip.setBottom(int(preview.image_rect.y() + preview.image_rect.height() * 430 / 1167))
        before = preview.grab().toImage().copy(encoder_strip)
        for shown in (True, False):
            window.eye_button.click()
            self.qt.processEvents()
            for number in range(1, 13):
                self.assertEqual(window.buttons[f"KEY:{number}"].show_label, shown)
            for number, name in ((1, "Scroll"), (2, "Brightness")):
                self.assertEqual(preview.encoder_names[number], name)
                self.assertTrue(window.buttons[f"ENC{number}:PRESS"].show_label)
            self.assertEqual(preview.grab().toImage().copy(encoder_strip), before)

    def test_physical_knobs_preserve_direction_or_default_to_cw(self):
        window = self.window()
        self.assertEqual(len(window.pad_widget.regions), 16)
        for number in (1, 2):
            knob = window.pad_widget.knobs[number]
            self.assertTrue(knob.hitButton(knob.target_rect.center().toPoint()))
            self.assertFalse(knob.hitButton(knob.target_rect.topLeft().toPoint()))
            window.select_control(gui.CONTROLS.index("KEY:1"))
            QTest.mouseClick(knob, Qt.MouseButton.LeftButton)
            self.assertEqual(window.selected_control, f"ENC{number}:CW")
            QTest.mouseClick(window.direction_buttons["CCW"], Qt.MouseButton.LeftButton)
            QTest.mouseClick(knob, Qt.MouseButton.LeftButton)
            self.assertEqual(window.selected_control, f"ENC{number}:CCW")
            for direction in ("CW", "CCW"):
                self.assertTrue(window.buttons[f"ENC{number}:{direction}"].isHidden())
                self.assertNotIn(f"ENC{number}:{direction}", window.pad_widget.regions)
            QTest.mouseClick(window.buttons[f"ENC{number}:PRESS"], Qt.MouseButton.LeftButton)
            self.assertFalse(knob.isChecked())
            self.assertFalse(window.direction_controls.isVisible())
            QTest.mouseClick(knob, Qt.MouseButton.LeftButton)
            self.assertEqual(window.selected_control, f"ENC{number}:CW")

    def test_rotation_activity_highlights_only_knob_and_press_only_small_pill(self):
        self.store.save_label("General", "ENC1:ROTATE", "Scroll")
        window = self.window()
        preview = window.pad_widget
        for suffix in ("CW", "CCW", "PRESS"):
            preview.clear_activity()
            before = preview.grab().toImage()
            window.show_activity("General", "ENC1:" + suffix, True, "Mute" if suffix == "PRESS" else "Scroll")
            activity = preview.activities["ENC1"]
            activity.animation.setCurrentTime(220)
            knob, press = preview.knobs[1], window.buttons["ENC1:PRESS"]
            active, inactive = (press, knob) if suffix == "PRESS" else (knob, press)
            self.assertIs(active.active_feedback(), activity)
            self.assertIsNone(inactive.active_feedback())
            after = preview.grab().toImage()
            self.assertNotEqual(before.copy(active.geometry()), after.copy(active.geometry()))
            self.assertEqual(before.copy(inactive.geometry()), after.copy(inactive.geometry()))
            label_rect = preview.display_rect(preview.ROTATION_LABEL_REGIONS[1]).toAlignedRect()
            self.assertEqual(before.copy(label_rect), after.copy(label_rect))

    def test_targets_and_inset_outlines_share_image_transform_after_resize(self):
        window = self.window()
        preview = window.pad_widget
        for width, height in ((760, 540), (800, 576), (1100, 800)):
            window.resize(width, height)
            self.qt.processEvents()
            for button, normalized in preview.regions.values():
                target = preview.display_rect(normalized)
                painted = button.target_rect.translated(button.x(), button.y())
                for expected, actual in zip(target.getRect(), painted.getRect()):
                    self.assertAlmostEqual(expected, actual, places=6)
                for stroke in (1, 2, 3):
                    # Even the outside edge of the pen remains within the target.
                    outline = button.outline_rect(stroke).adjusted(-stroke / 2, -stroke / 2, stroke / 2, stroke / 2)
                    self.assertTrue(button.target_rect.contains(outline))
                self.assertTrue(button.hitButton(button.target_rect.center().toPoint()))
                if button.circular:
                    self.assertAlmostEqual(target.width(), target.height(), places=6)

    @staticmethod
    def wheel(widget, delta):
        position = widget.rect().center()
        event = QWheelEvent(QPointF(position), QPointF(widget.mapToGlobal(position)),
                            QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(widget, event)

    def test_wheel_is_blocked_for_window_children_and_combo_popup(self):
        window = self.window()
        window.type_buttons["media_key"].click()
        window.media_widget.setCurrentIndex(3)
        window.name_field.setFocus()
        self.qt.processEvents()
        focused = QApplication.focusWidget()
        selected = window.selected_control
        for widget in (window, window.pad_widget, window.name_field, window.media_widget,
                       window.profile_button, window.action_type, window.edit_profile, window.recorder):
            for delta in (-120, 120):
                self.wheel(widget, delta)
                self.assertEqual(window.media_widget.currentIndex(), 3)
                self.assertEqual(window.selected_control, selected)
                self.assertEqual(self.store.current_profile(), "General")
                self.assertIs(QApplication.focusWidget(), focused)
        window.media_widget.showPopup()
        self.qt.processEvents()
        view = window.media_widget.view()
        original_row = view.currentIndex().row()
        original_scroll = view.verticalScrollBar().value()
        for widget in (view, view.viewport(), view.verticalScrollBar()):
            for delta in (-120, 120):
                self.wheel(widget, delta)
                self.assertEqual(view.currentIndex().row(), original_row)
                self.assertEqual(view.verticalScrollBar().value(), original_scroll)
        model_index = view.model().index(1, 0)
        view.scrollTo(model_index)
        self.qt.processEvents()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(model_index).center())
        self.assertEqual(window.media_widget.currentIndex(), 1)

    def test_profile_menu_wheel_blocked_and_mouse_profile_selection_works(self):
        window = self.window()
        window.open_profile_menu()
        self.qt.processEvents()
        menu = window.profile_menu
        actions = menu.actions()
        for text in ("Add...", "Rename...", "Delete...", "Import...", "Export...", "Lock profile"):
            self.assertIn(text, [action.text() for action in actions])
        browser = next(action for action in actions if action.text() == "Browser")
        menu.setActiveAction(browser)
        for delta in (-120, 120):
            self.wheel(menu, delta)
            self.assertIs(menu.activeAction(), browser)
            self.assertEqual(self.store.current_profile(), "General")
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(browser).center())
        self.assertEqual(self.store.current_profile(), "Browser")

    def test_wheel_filter_leaves_other_windows_and_scroll_output_unchanged(self):
        self.window()
        outside = QComboBox()
        self.addCleanup(outside.close)
        outside.addItems(["One", "Two", "Three"])
        outside.setCurrentIndex(1)
        outside.show()
        outside.setFocus()
        self.qt.processEvents()
        self.wheel(outside, -120)
        self.assertEqual(outside.currentIndex(), 2)
        for steps in (-1, 1):
            mouse, keyboard = Mock(), FakeKeyboard()
            engine.execute_hotkey(keyboard, [ScrollAction(steps)], mouse=mouse)
            mouse.scroll.assert_called_once_with(0, steps)
            self.assertEqual(keyboard.presses, [])


if __name__ == "__main__":
    unittest.main()
