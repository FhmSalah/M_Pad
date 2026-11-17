"""Mock workspace events and use only a Qt core loop: no windows or devices."""
import gc
import json
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import Mock, patch
import weakref

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
import app as gui
import foreground_app as foreground
import importlib.util

HAS_PYOBJC = all(importlib.util.find_spec(name) is not None for name in ("objc", "AppKit", "Foundation"))
import run_actions as engine
from config_store import ConfigStore


def native_app(identifier, name='Example'):
    app = Mock()
    app.bundleIdentifier.return_value = identifier
    app.localizedName.return_value = name
    return app


@unittest.skipUnless(HAS_PYOBJC, "macOS observer needs PyObjC")
class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(foreground.sys, 'platform', 'darwin'))
        self.workspace = self.enterContext(patch.object(foreground, 'NSWorkspace'))
        self.queue = self.enterContext(patch('Foundation.NSOperationQueue'))
        self.center = self.workspace.sharedWorkspace.return_value.notificationCenter.return_value
        self.center.addObserverForName_object_queue_usingBlock_.return_value = object()
        self.received = Mock()
        self.observer = foreground.ActivationObserver(self.received)
        self.addCleanup(self.observer.stop)

    def notification(self, identifier='com.brave.Browser'):
        from AppKit import NSWorkspaceApplicationKey
        notification = Mock()
        notification.userInfo.return_value = {NSWorkspaceApplicationKey: native_app(identifier)}
        return notification

    def test_correct_center_queue_payload_and_idempotent_registration(self):
        from AppKit import NSWorkspaceDidActivateApplicationNotification
        self.assertTrue(self.observer.start())
        self.assertTrue(self.observer.start())
        register = self.center.addObserverForName_object_queue_usingBlock_
        register.assert_called_once()
        name, obj, queue, callback = register.call_args.args
        self.assertEqual(name, NSWorkspaceDidActivateApplicationNotification)
        self.assertIsNone(obj)
        self.assertIs(queue, self.queue.mainQueue.return_value)
        callback(self.notification())
        self.received.assert_called_once_with(foreground.ForegroundApplication('com.brave.browser', 'brave.exe'))

    def test_cleanup_once_and_old_callbacks_ignored_after_restart(self):
        self.observer.start()
        old_callback = self.observer.callback
        token = self.observer.token
        self.observer.stop()
        self.observer.stop()
        self.center.removeObserver_.assert_called_once_with(token)
        old_callback(self.notification())
        self.received.assert_not_called()
        self.observer.start()
        old_callback(self.notification())
        self.received.assert_not_called()
        self.observer.callback(self.notification())
        self.received.assert_called_once()

    def test_registration_failure_and_missing_token_return_false(self):
        register = self.center.addObserverForName_object_queue_usingBlock_
        register.side_effect = RuntimeError('registration failed')
        self.assertFalse(self.observer.start())
        self.assertFalse(self.observer.active)
        register.side_effect = None
        register.return_value = None
        self.assertFalse(self.observer.start())

    def test_bad_notification_and_conversion_exception_are_contained(self):
        self.observer.start()
        notification = Mock()
        notification.userInfo.return_value = {}
        self.observer.callback(notification)
        notification.userInfo.side_effect = RuntimeError('bad notification')
        self.observer.callback(notification)
        self.received.assert_not_called()

    def test_no_native_registration_on_windows_or_worker_thread(self):
        with patch.object(foreground.sys, 'platform', 'win32'):
            self.assertFalse(self.observer.start())
        result = []
        worker = Thread(target=lambda: result.append(self.observer.start()))
        worker.start()
        worker.join()
        self.assertEqual(result, [False])
        self.center.addObserverForName_object_queue_usingBlock_.assert_not_called()

    def test_native_callback_does_not_retain_observer(self):
        self.observer.start()
        callback = self.observer.callback
        reference = weakref.ref(self.observer)
        self.observer.stop()
        self.doCleanups()
        self.observer = None
        gc.collect()
        self.assertIsNone(reference())
        callback(self.notification())
        self.received.assert_not_called()


class MonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = root / 'config.json'
        self.path.write_text(json.dumps({
            'default_profile': 'General', 'profiles': {'General': {}, 'Browser': {}, 'Work': {}},
            'applications': {'com.example.custom': 'Work'}, 'locked_profile': None}))
        self.store = ConfigStore(self.path)
        self.factory = self.enterContext(patch.object(gui, 'ActivationObserver'))
        self.factory.return_value.start.return_value = True
        self.detect = self.enterContext(patch.object(gui, 'get_foreground_application',
            return_value=foreground.ForegroundApplication('com.apple.finder')))
        self.monitor = gui.MacForegroundMonitor(self.store)
        self.callback = self.factory.call_args.args[0]
        self.changes = []
        self.monitor.profile_changed.connect(self.changes.append)
        self.addCleanup(self.monitor.stop)

    def emit(self, identifier, alias=None):
        self.callback(foreground.ForegroundApplication(identifier, alias))
        self.qt.processEvents()

    def test_notifications_change_profile_without_waiting_for_timer(self):
        self.assertTrue(self.monitor.start())
        before = self.path.read_bytes()
        self.emit('com.brave.browser', 'brave.exe')
        self.emit('com.example.custom')
        self.emit('com.apple.finder')
        self.assertEqual(self.changes, ['Browser', 'Work', 'General'])
        self.assertEqual(self.path.read_bytes(), before)

    def choose_manually(self, profile, platform='darwin'):
        host = Mock(store=self.store)
        with patch.object(gui.sys, 'platform', platform):
            gui.MacroPadWindow.choose_profile(host, profile)
        host.report_error.assert_not_called()
        self.assertEqual(self.store.current_profile(), profile)

    def test_assigned_unknown_transitions_by_notifications_and_reconciliation(self):
        self.store.add_profile('Ps')
        self.store.assign_application('Ps', 'com.adobe.photoshop', {})
        self.monitor.start()
        before = self.path.read_bytes()
        transitions = (
            ('com.brave.browser', 'brave.exe', 'Browser'),
            ('test.unassigned', None, 'General'),
            ('com.adobe.photoshop', 'photoshop.exe', 'Ps'),
            ('com.apple.finder', None, 'General'),
            ('com.example.custom', None, 'Work'),
            ('com.apple.finder', None, 'General'),
        )
        for source in ('notification', 'reconcile'):
            for identifier, alias, expected in transitions:
                with self.subTest(source=source, application=identifier):
                    if source == 'notification':
                        self.emit(identifier, alias)
                    else:
                        self.detect.return_value = foreground.ForegroundApplication(identifier, alias)
                        self.monitor.timer.timeout.emit()
                    self.assertEqual(self.store.foreground_application, identifier)
                    self.assertEqual(self.store.current_profile(), expected)
                    self.assertIsNone(self.store.manual_profile)
        self.assertEqual(self.changes, ['Browser', 'General', 'Ps', 'General', 'Work', 'General'] * 2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_macos_manual_choice_expires_to_original_fallback_on_real_app_change(self):
        self.monitor.start()
        before = self.path.read_bytes()
        for source in ('notification', 'reconcile'):
            with self.subTest(source=source):
                self.emit('com.brave.browser', 'brave.exe')
                self.choose_manually('Work')
                self.assertEqual(self.store.compiled[0], 'General')
                self.assertEqual(self.path.read_bytes(), before)
                self.emit('com.brave.browser', 'brave.exe')
                self.detect.return_value = foreground.ForegroundApplication('com.brave.browser', 'brave.exe')
                self.monitor.timer.timeout.emit()
                self.assertEqual(self.store.current_profile(), 'Work')
                self.assertEqual(self.store.manual_profile, 'Work')
                if source == 'notification':
                    self.emit('test.unassigned')
                else:
                    self.detect.return_value = foreground.ForegroundApplication('test.unassigned')
                    self.monitor.timer.timeout.emit()
                self.assertEqual(self.store.current_profile(), 'General')
                self.assertIsNone(self.store.manual_profile)
        self.assertEqual(self.path.read_bytes(), before)

    def test_macos_manual_selection_while_locked_preserves_fallback_and_lock_behavior(self):
        self.monitor.start()
        self.store.set_locked_profile('General')
        self.choose_manually('Work')
        self.assertEqual(self.store.locked_profile(), 'Work')
        expected = dict(self.store.data, locked_profile=None)
        self.assertEqual(self.store.compiled[0], 'General')
        for identifier in ('com.brave.browser', 'test.unassigned', 'com.example.custom', 'com.apple.finder'):
            self.emit(identifier)
            self.assertEqual(self.store.current_profile(), 'Work')
            self.detect.return_value = foreground.ForegroundApplication(identifier)
            self.monitor.timer.timeout.emit()
            self.assertEqual(self.store.current_profile(), 'Work')
        self.store.set_locked_profile(None)
        self.assertEqual(self.store.current_profile(), 'General')
        self.assertEqual(self.store.data, expected)

    def test_windows_menu_selection_keeps_configured_default(self):
        # Windows now matches macOS: a menu choice is manual and expires on app change.
        self.store.update_foreground_profile('browser.exe')
        self.choose_manually('Work', platform='win32')
        self.assertEqual(self.store.data['default_profile'], 'General')
        self.assertEqual(ConfigStore(self.path).compiled[0], 'General')
        self.assertEqual(self.store.update_foreground_profile('browser.exe'), 'Work')
        self.assertEqual(self.store.update_foreground_profile('unknown.exe'), 'General')
        self.assertIsNone(self.store.manual_profile)

    def test_same_profile_identity_changes_clear_manual_choice(self):
        self.monitor.start()
        self.emit('com.brave.browser', 'brave.exe')
        self.store.select_profile('Work')
        self.emit('com.brave.browser', 'brave.exe')
        self.assertEqual(self.store.current_profile(), 'Work')
        self.emit('test.other-browser', 'brave.exe')
        self.assertEqual(self.store.current_profile(), 'Browser')
        self.assertIsNone(self.store.manual_profile)

    def test_same_profile_changes_record_identity_without_duplicate_ui_updates(self):
        self.monitor.start()
        self.emit('com.brave.browser', 'brave.exe')
        self.emit('test.other-browser', 'brave.exe')
        self.emit('test.other-browser', 'brave.exe')
        self.assertEqual(self.changes, ['Browser'])
        self.assertEqual(self.store.foreground_application, 'test.other-browser')

    def test_reconcile_timer_recovers_missed_event_and_configuration_changes(self):
        self.monitor.start()
        self.assertEqual(self.monitor.timer.interval(), 1000)
        self.assertTrue(self.monitor.timer.isActive())
        self.detect.return_value = foreground.ForegroundApplication('com.brave.browser', 'brave.exe')
        self.monitor.timer.timeout.emit()
        self.assertEqual(self.store.current_profile(), 'Browser')
        self.store.assign_application('Work', 'com.brave.browser', {})
        self.monitor.reconcile()
        self.assertEqual(self.store.current_profile(), 'Work')
        self.store.remove_application('Work', 'com.brave.browser')
        self.monitor.reconcile()
        self.assertEqual(self.store.current_profile(), 'Browser')

    def test_reconcile_does_not_overtake_pending_identity_transitions(self):
        self.monitor.start()
        self.callback(foreground.ForegroundApplication('com.brave.browser', 'brave.exe'))
        self.detect.reset_mock()
        self.monitor.reconcile()
        self.detect.assert_not_called()
        self.qt.processEvents()
        self.assertEqual(self.monitor.pending, 0)
        self.assertEqual(self.store.current_profile(), 'Browser')

    def test_locks_manual_selection_and_failed_query_preserved(self):
        self.monitor.start()
        self.store.select_profile('Work')
        self.monitor.reconcile()
        self.assertEqual(self.store.current_profile(), 'Work')
        self.store.set_locked_profile('Work')
        self.emit('com.brave.browser', 'brave.exe')
        self.assertEqual(self.store.current_profile(), 'Work')
        self.detect.return_value = None
        self.monitor.reconcile()
        self.assertEqual(self.store.foreground_application, 'com.brave.browser')
        self.store.set_locked_profile(None)
        self.assertEqual(self.store.current_profile(), 'Browser')

    def test_failed_observer_leaves_monitor_inactive_for_polling_fallback(self):
        self.factory.return_value.start.return_value = False
        self.assertFalse(self.monitor.start())
        self.assertFalse(self.monitor.running)
        self.assertFalse(self.monitor.timer.isActive())
        self.detect.assert_not_called()
        self.factory.return_value.stop.assert_called_once()

    def test_initial_snapshot_exception_cleans_up_for_polling_fallback(self):
        self.detect.side_effect = RuntimeError('initial snapshot failed')
        self.assertFalse(self.monitor.start())
        self.assertFalse(self.monitor.running)
        self.assertFalse(self.monitor.timer.isActive())
        self.factory.return_value.stop.assert_called_once()

    def test_assignment_and_removal_handlers_request_reconciliation(self):
        self.monitor.start()
        self.store.select_profile('Work')
        host = Mock()
        host.store = self.store
        host.reconcile_foreground_profile.side_effect = self.monitor.reconcile
        with patch.object(gui.sys, 'platform', 'darwin'), \
             patch.object(gui, 'choose_application_bundle', return_value='/test/Example.app'), \
             patch.object(gui, 'read_application_bundle', return_value=('com.example.new', None)), \
             patch.object(gui.ConfirmationDialog, 'confirm', return_value=True):
            gui.MacroPadWindow.assign_application(host)
            gui.MacroPadWindow.remove_application(host, 'Work', 'com.example.new')
        self.assertEqual(host.reconcile_foreground_profile.call_count, 2)
        self.assertEqual(self.store.current_profile(), 'Work')
        self.assertEqual(self.store.manual_profile, 'Work')
        self.assertNotIn('com.example.new', self.store.data['applications'])

    def test_cleanup_and_stale_queued_callbacks_after_restart(self):
        self.monitor.start()
        self.callback(foreground.ForegroundApplication('com.brave.browser', 'brave.exe'))
        self.monitor.stop()
        self.monitor.start()
        self.qt.processEvents()
        self.assertEqual(self.store.current_profile(), 'General')
        self.monitor.stop()
        self.callback(foreground.ForegroundApplication('com.example.custom'))
        self.qt.processEvents()
        self.assertFalse(self.monitor.timer.isActive())
        self.assertEqual(self.store.current_profile(), 'General')

    def test_monitor_callback_uses_weak_owner(self):
        callback = self.callback
        reference = weakref.ref(self.monitor)
        self.monitor.stop()
        self.doCleanups()
        self.monitor = None
        gc.collect()
        self.assertIsNone(reference())
        callback(foreground.ForegroundApplication('com.example.custom'))


class EngineRoutingTests(unittest.TestCase):
    def test_gui_routing_enables_events_only_on_successful_macos_registration(self):
        for platform, success in (('darwin', True), ('darwin', False), ('win32', True)):
            with self.subTest(platform=platform, success=success):
                host = Mock()
                host.worker.watch_foreground = True
                with patch.object(gui.sys, 'platform', platform), patch.object(gui, 'MacForegroundMonitor') as factory:
                    factory.return_value.start.return_value = success
                    gui.MacroPadWindow.start_foreground_monitor(host)
                    if platform == 'darwin' and success:
                        self.assertFalse(host.worker.watch_foreground)
                        self.assertIs(host.foreground_monitor, factory.return_value)
                    else:
                        self.assertTrue(host.worker.watch_foreground)
                        self.assertIsNone(host.foreground_monitor)
                    if platform == 'win32':
                        factory.assert_not_called()
                    elif not success:
                        factory.return_value.deleteLater.assert_called_once()

    def test_close_stops_observer_before_accepting_or_waiting_for_worker(self):
        for running in (True, False):
            host = Mock()
            host.recorder.active = False
            host.worker.isRunning.return_value = running
            event = Mock()
            host.attach_mock(event, 'close_event')
            gui.MacroPadWindow.closeEvent(host, event)
            names = [entry[0] for entry in host.mock_calls]
            self.assertLess(names.index('stop_foreground_monitor'),
                            names.index('close_event.ignore' if running else 'close_event.accept'))

    def test_default_engine_retains_polling_and_opt_out_does_not_create_watcher(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                stop = Event()
                store = Mock()
                store.current_profile.return_value = 'General'
                def discover(event):
                    event.set()
                    return None
                with patch.object(engine, 'Thread') as threads, patch.object(engine, 'Controller'), \
                     patch.object(engine, 'find_macro_pad', side_effect=discover):
                    kwargs = {} if enabled else {'watch_foreground': False}
                    engine.run_engine(stop, config_store=store, reconnect=True, **kwargs)
                    if enabled:
                        threads.assert_called_once()
                        threads.return_value.start.assert_called_once()
                        threads.return_value.join.assert_called_once()
                    else:
                        threads.assert_not_called()


if __name__ == '__main__':
    unittest.main()
