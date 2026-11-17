"""Application assignment with temporary data and mocked native dialogs; no windows."""
import copy
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gui
from config_store import ConfigStore

NATIVE_CHOOSER = gui.choose_application_bundle
import importlib.util

HAS_PYOBJC = all(importlib.util.find_spec(name) is not None for name in ("objc", "AppKit", "Foundation"))


class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.directory)
        self.path = self.root / 'config.json'
        self.document = {
            'default_profile': 'General', 'locked_profile': None,
            'profiles': {'General': {}, 'Work': {}, 'Other': {}, 'Browser': {}},
            'applications': {'personal.exe': 'Other'},
            'labels': {'Work': {'KEY:1': 'Custom label'}}, 'custom': {'preserve': True},
        }
        self.write_document()
        self.store = ConfigStore(self.path)
        self.host = Mock()
        self.host.store = self.store
        self.host.profile_button.height.return_value = 30
        self.enterContext(patch.object(gui.sys, 'platform', 'darwin'))
        self.picker = self.enterContext(patch.object(gui, 'choose_application_bundle'))
        self.confirm = self.enterContext(patch.object(gui.ConfirmationDialog, 'confirm', return_value=True))

    def write_document(self):
        self.path.write_text(json.dumps(self.document))

    def bundle(self, identifier='COM.EXAMPLE.APP', name='Example.app', **metadata):
        path = self.root / name
        (path / 'Contents').mkdir(parents=True, exist_ok=True)
        (path / 'Contents/Info.plist').write_bytes(plistlib.dumps(
            {'CFBundleIdentifier': identifier, **metadata}))
        return path

    def select_work(self):
        self.store.select_profile('Work')

    def assign(self, path):
        self.picker.return_value = str(path)
        gui.MacroPadWindow.assign_application(self.host)

    def test_assignment_multiple_apps_and_preservation(self):
        self.select_work()
        before = copy.deepcopy(self.store.data)
        self.assign(self.bundle())
        self.assign(self.bundle('com.example.second', 'Second.app'))
        expected = copy.deepcopy(before)
        expected['applications'].update({'com.example.app': 'Work', 'com.example.second': 'Work'})
        self.assertEqual(self.store.data, expected)
        self.assertEqual(ConfigStore(self.path).data, expected)
        self.assertEqual(self.store.application_assignments('Work'), ['com.example.app', 'com.example.second'])
        self.assertEqual(self.store.update_foreground_profile('com.example.app'), 'Work')
        self.confirm.assert_not_called()

    def test_profile_captured_before_picker_foreground_change(self):
        self.select_work()
        path = self.bundle()
        def choose():
            self.store.update_foreground_profile('personal.exe')
            self.assertEqual(self.store.current_profile(), 'Other')
            return str(path)
        self.picker.side_effect = choose
        gui.MacroPadWindow.assign_application(self.host)
        self.assertEqual(self.store.data['applications']['com.example.app'], 'Work')

    def test_reassignment_requires_confirmation_and_keeps_other_bindings(self):
        self.document['applications']['COM.EXAMPLE.APP'] = 'Other'
        self.write_document()
        self.store = ConfigStore(self.path)
        self.host.store = self.store
        self.select_work()
        self.assign(self.bundle())
        self.confirm.assert_called_once()
        self.assertEqual(self.store.data['applications'], {'personal.exe': 'Other', 'com.example.app': 'Work'})

    def test_cancel_reassignment_and_cancel_picker_do_not_write(self):
        self.document['applications']['com.example.app'] = 'Other'
        self.write_document()
        self.store = ConfigStore(self.path)
        self.host.store = self.store
        self.select_work()
        before = self.path.read_bytes()
        self.confirm.return_value = False
        self.assign(self.bundle())
        self.assertEqual(self.path.read_bytes(), before)
        self.picker.return_value = None
        gui.MacroPadWindow.assign_application(self.host)
        self.assertEqual(self.path.read_bytes(), before)

    def test_case_duplicates_canonicalized_and_same_assignment_noop(self):
        self.document['applications'].update({'COM.EXAMPLE.APP': 'Work', 'com.example.app': 'Work'})
        self.write_document()
        self.store = ConfigStore(self.path)
        bindings = self.store.application_bindings('com.example.app')
        self.store.assign_application('Work', 'COM.EXAMPLE.APP', bindings)
        self.assertEqual(self.store.application_bindings('com.example.app'), {'com.example.app': 'Work'})
        before = self.path.read_bytes()
        self.assertFalse(self.store.assign_application('Work', 'com.example.app', {'com.example.app': 'Work'}))
        self.assertEqual(self.path.read_bytes(), before)

    def test_conflicting_case_duplicates_require_confirmation(self):
        self.document['applications'].update({'COM.EXAMPLE.APP': 'Other', 'com.example.app': 'Work'})
        self.write_document()
        self.store = ConfigStore(self.path)
        self.host.store = self.store
        self.select_work()
        self.confirm.return_value = False
        before = self.path.read_bytes()
        self.assign(self.bundle())
        self.confirm.assert_called_once()
        self.assertEqual(self.path.read_bytes(), before)

    def test_legacy_conflict_confirmed_but_legacy_binding_preserved(self):
        self.document['applications']['brave.exe'] = 'Other'
        self.write_document()
        self.store = ConfigStore(self.path)
        self.host.store = self.store
        self.select_work()
        self.assign(self.bundle('com.brave.Browser', 'Brave Browser.app'))
        self.confirm.assert_called_once()
        self.assertEqual(self.store.data['applications']['brave.exe'], 'Other')
        self.assertEqual(self.store.data['applications']['com.brave.browser'], 'Work')

    def test_binding_changed_during_confirmation_rejected(self):
        self.document['applications']['com.example.app'] = 'Other'
        self.write_document()
        self.store = ConfigStore(self.path)
        self.host.store = self.store
        self.select_work()
        def confirm(*args):
            self.store.assign_application('General', 'com.example.app', {'com.example.app': 'Other'})
            return True
        self.confirm.side_effect = confirm
        self.assign(self.bundle())
        self.assertEqual(self.store.data['applications']['com.example.app'], 'General')
        self.host.report_error.assert_called_once()

    def test_removal_restores_builtin_and_default(self):
        for identity in ('com.brave.browser', 'com.example.app'):
            self.store.assign_application('Work', identity, {})
        self.assertEqual(self.store.update_foreground_profile('com.brave.browser'), 'Work')
        gui.MacroPadWindow.remove_application(self.host, 'Work', 'com.brave.browser')
        self.assertEqual(self.store.update_foreground_profile('com.brave.browser'), 'Browser')
        gui.MacroPadWindow.remove_application(self.host, 'Work', 'com.example.app')
        self.assertEqual(self.store.update_foreground_profile('com.example.app'), 'General')
        self.assertEqual(self.store.data['applications'], {'personal.exe': 'Other'})

    def test_cancel_removal_and_reassigned_removal_preserve_settings(self):
        self.store.assign_application('Work', 'com.example.app', {})
        before = self.path.read_bytes()
        self.confirm.return_value = False
        gui.MacroPadWindow.remove_application(self.host, 'Work', 'com.example.app')
        self.assertEqual(self.path.read_bytes(), before)
        self.store.assign_application('Other', 'com.example.app', {'com.example.app': 'Work'})
        with self.assertRaises(ValueError):
            self.store.remove_application('Work', 'com.example.app')
        self.assertEqual(self.store.data['applications']['com.example.app'], 'Other')

    def test_invalid_bundles_and_ids_never_save(self):
        before = self.path.read_bytes()
        for identifier in ('', ' ', 'com..app', 'com.app_name', 123):
            with self.subTest(identifier=identifier):
                self.assign(self.bundle(identifier))
                self.assertEqual(self.path.read_bytes(), before)
        path = self.bundle()
        (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleName': 'No ID'}))
        self.assign(path)
        (path / 'Contents/Info.plist').write_bytes(b'not a plist')
        self.assign(path)
        (path / 'Contents/Info.plist').write_bytes(b'<?xml version="1.0"?><plist><dict>')
        self.assign(path)
        (path / 'Contents/Info.plist').unlink()
        self.assign(path)
        self.assign(path / 'Contents')
        self.assertEqual(self.path.read_bytes(), before)

    def test_rename_delete_and_lock_manual_default_preserved(self):
        self.store.select_profile('Work')
        self.store.set_locked_profile('Work')
        before = (self.store.locked_profile(), self.store.manual_profile, self.store.snapshot()[0])
        self.store.assign_application('Other', 'com.example.app', {})
        self.assertEqual((self.store.locked_profile(), self.store.manual_profile, self.store.snapshot()[0]), before)
        self.assertEqual(self.store.update_foreground_profile('com.example.app'), 'Work')
        self.store.rename_profile('Other', 'Creative')
        self.assertEqual(self.store.data['applications']['com.example.app'], 'Creative')
        self.store.delete_profile('Creative')
        self.assertNotIn('com.example.app', self.store.data['applications'])

    def test_deleted_target_and_external_edit_and_atomic_failure(self):
        self.store.delete_profile('Work')
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.assign_application('Work', 'com.example.app', {})
        self.assertEqual(self.path.read_bytes(), before)
        with patch('config_store.os.replace', side_effect=PermissionError('mock failure')):
            with self.assertRaises(OSError):
                self.store.assign_application('Other', 'com.example.app', {})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertNotIn('com.example.app', self.store.data['applications'])
        self.path.write_bytes(before + b'\n')
        with self.assertRaises(ValueError):
            self.store.assign_application('Other', 'com.example.app', {})
        self.assertEqual(self.path.read_bytes(), before + b'\n')

    def test_malformed_mapping_rejected_without_overwrite(self):
        self.document['applications'] = ['invalid']
        self.write_document()
        store = ConfigStore(self.path)
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            store.assign_application('Work', 'com.example.app', {})
        self.assertEqual(self.path.read_bytes(), before)

    @unittest.skipUnless(HAS_PYOBJC, "macOS panel needs PyObjC")
    def test_native_panel_selects_bundle_as_single_file(self):
        # The real native panel is never shown.
        with patch('AppKit.NSOpenPanel') as factory:
            panel = factory.openPanel.return_value
            panel.runModal.return_value = 1
            panel.URL.return_value.path.return_value = '/Applications/Example.app'
            self.assertEqual(NATIVE_CHOOSER(), '/Applications/Example.app')
            panel.setTreatsFilePackagesAsDirectories_.assert_called_once_with(False)
            panel.setCanChooseDirectories_.assert_called_once_with(False)
            panel.setCanChooseFiles_.assert_called_once_with(True)
            panel.setAllowedFileTypes_.assert_called_once_with(['app'])
            panel.runModal.return_value = 0
            self.assertIsNone(NATIVE_CHOOSER())

    def test_menu_available_in_frozen_execution_on_mac_and_windows(self):
        with patch.object(gui, 'QMenu') as menus, patch.object(gui.sys, 'frozen', True, create=True):
            menus.return_value.actions.return_value = []
            gui.MacroPadWindow.open_profile_menu(self.host)
            labels = [entry.args[0] for entry in menus.return_value.addAction.call_args_list]
            self.assertIn('Assign Application…', labels)
            menus.reset_mock()
            with patch.object(gui.sys, 'platform', 'win32'):
                gui.MacroPadWindow.open_profile_menu(self.host)
                labels = [entry.args[0] for entry in menus.return_value.addAction.call_args_list]
                self.assertIn('Assign Application…', labels)
            menus.reset_mock()
            with patch.object(gui.sys, 'platform', 'linux'):
                gui.MacroPadWindow.open_profile_menu(self.host)
                labels = [entry.args[0] for entry in menus.return_value.addAction.call_args_list]
                self.assertNotIn('Assign Application…', labels)
                gui.MacroPadWindow.assign_application(self.host)
                self.picker.assert_not_called()

    def windows_assign(self, path):
        with patch.object(gui.sys, 'platform', 'win32'), \
                patch.object(gui, 'choose_windows_executable', return_value=str(path) if path else None):
            gui.MacroPadWindow.assign_application(self.host)

    def test_windows_executable_assignment_and_removal(self):
        exe = self.root / 'Krita.EXE'
        exe.write_bytes(b'MZ')
        self.windows_assign(exe)
        self.assertEqual(self.store.data['applications']['krita.exe'], 'General')
        self.picker.assert_not_called()
        self.assertEqual(self.store.update_foreground_profile('krita.exe'), 'General')
        with patch.object(gui.sys, 'platform', 'win32'):
            gui.MacroPadWindow.remove_application(self.host, 'General', 'krita.exe')
        self.assertNotIn('krita.exe', self.store.data['applications'])
        self.assertEqual(self.store.data['applications']['personal.exe'], 'Other')

    def test_windows_reassign_prompts_and_cancel_keeps_file(self):
        exe = self.root / 'personal.exe'
        exe.write_bytes(b'MZ')
        before = self.path.read_bytes()
        self.confirm.return_value = False
        self.windows_assign(exe)
        self.confirm.assert_called_once()
        self.assertEqual(self.path.read_bytes(), before)
        self.confirm.return_value = True
        self.windows_assign(exe)
        self.assertEqual(self.store.data['applications']['personal.exe'], 'General')

    def test_windows_invalid_or_cancelled_executable_never_saves(self):
        before = self.path.read_bytes()
        self.windows_assign(None)
        self.windows_assign(self.root / 'missing.exe')
        notes = self.root / 'notes.txt'
        notes.write_text('x')
        self.windows_assign(notes)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
