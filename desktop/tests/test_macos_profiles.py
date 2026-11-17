"""macOS detection and selection regressions; no foreground or settings changes."""

import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import foreground_app as foreground
from config_store import APPLICATION_PROFILES, ConfigStore
import run_actions as engine

import importlib.util

HAS_PYOBJC = all(importlib.util.find_spec(name) is not None for name in ("objc", "AppKit", "Foundation"))


@unittest.skipUnless(HAS_PYOBJC, "macOS detector needs PyObjC")
class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(foreground.sys, "platform", "darwin"))

    def detect(self, bundle, name):
        app = Mock()
        app.bundleIdentifier.return_value = bundle
        app.localizedName.return_value = name
        workspace = Mock()
        workspace.sharedWorkspace.return_value.frontmostApplication.return_value = app
        with patch.object(foreground, "NSWorkspace", workspace):
            return foreground.get_foreground_application()

    def test_installed_identifiers_keep_identity_and_alias(self):
        for identifier, alias in foreground.MACOS_APPLICATION_ALIASES.items():
            with self.subTest(identifier=identifier):
                self.assertEqual(self.detect(identifier.upper(), "Localized name"),
                                 foreground.ForegroundApplication(identifier, alias))

    def test_normalized_names_support_versions_and_direction_marks(self):
        cases = {
            " Brave Browser ": "brave.exe",
            "Adobe Photoshop 2024": "photoshop.exe",
            "Adobe After Effects 2025": "afterfx.exe",
            "Adobe Premiere Pro 2026": "adobe premiere pro.exe",
            "Adobe Illustrator 2024": "illustrator.exe",
            "Blender 4.2": "blender.exe", "Krita": "krita.exe",
            "Visual Studio Code": "code.exe", "Code": "code.exe",
            "\u200eWhatsApp": "whatsapp.exe", "CapCut": "capcut.exe",
        }
        for name, alias in cases.items():
            with self.subTest(name=name):
                # Synthetic IDs exercise name fallback; they are not real bundle IDs.
                self.assertEqual(self.detect("test.unknown", name),
                                 foreground.ForegroundApplication("test.unknown", alias))

    def test_missing_bundle_uses_name_identity(self):
        self.assertEqual(self.detect(None, "Brave Browser"),
                         foreground.ForegroundApplication("name:brave browser", "brave.exe"))
        self.assertIsNone(self.detect(None, None))

    def test_unknown_and_helper_apps_do_not_use_substring_matching(self):
        for name in ("Adobe After Effects Render Engine", "Photoshop Helper", "Code Helper", "CapCut Helper"):
            self.assertIsNone(self.detect("test.helper", name).alias)
        self.assertEqual(self.detect("com.apple.finder", "Finder"),
                         foreground.ForegroundApplication("com.apple.finder"))

    def test_absent_appkit_no_frontmost_app_and_detection_errors(self):
        with patch.object(foreground, "NSWorkspace", None):
            self.assertIsNone(foreground.get_foreground_application())
        workspace = Mock()
        workspace.sharedWorkspace.return_value.frontmostApplication.return_value = None
        with patch.object(foreground, "NSWorkspace", workspace):
            self.assertIsNone(foreground.get_foreground_application())
            workspace.sharedWorkspace.side_effect = RuntimeError("unavailable")
            self.assertIsNone(foreground.get_foreground_application())

    def test_cocoa_pool_exited_on_success_and_error(self):
        pool = Mock()
        pool.return_value.__enter__ = Mock()
        pool.return_value.__exit__ = Mock(return_value=False)
        with patch("objc.autorelease_pool", pool):
            self.detect("com.apple.finder", "Finder")
            pool.return_value.__exit__.assert_called_once()
            pool.reset_mock()
            workspace = Mock()
            workspace.sharedWorkspace.side_effect = RuntimeError("unavailable")
            with patch.object(foreground, "NSWorkspace", workspace):
                self.assertIsNone(foreground.get_foreground_application())
            pool.return_value.__exit__.assert_called_once()


class SelectionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "config.json"
        self.document = {
            "default_profile": "General", "locked_profile": None,
            "profiles": {name: {} for name in {"General", "Personal", *APPLICATION_PROFILES.values()}},
            "applications": {"brave.exe": "Browser"},
        }
        self.store = self.load()

    def load(self):
        self.path.write_text(json.dumps(self.document))
        return ConfigStore(self.path)

    def test_finder_brave_finder_and_no_settings_write(self):
        before = self.path.read_bytes()
        for app, expected in ((foreground.ForegroundApplication("com.apple.finder"), "General"),
                              (foreground.ForegroundApplication("com.brave.browser", "brave.exe"), "Browser"),
                              (foreground.ForegroundApplication("com.apple.finder"), "General")):
            self.assertEqual(self.store.update_foreground_profile(app), expected)
        self.assertEqual(self.path.read_bytes(), before)

    def test_all_verified_ids_and_legacy_executables(self):
        for identifier, alias in foreground.MACOS_APPLICATION_ALIASES.items():
            for identity in (identifier.upper(), alias.upper(), foreground.ForegroundApplication(identifier, alias)):
                with self.subTest(identity=identity):
                    self.assertEqual(self.store.update_foreground_profile(identity), APPLICATION_PROFILES[alias])

    def test_exact_mapping_then_legacy_mapping_then_builtin(self):
        self.document["applications"] = {"COM.BRAVE.BROWSER": "Personal", "brave.exe": "General"}
        self.store = self.load()
        app = foreground.ForegroundApplication("com.brave.browser", "brave.exe")
        self.assertEqual(self.store.update_foreground_profile(app), "Personal")
        del self.document["applications"]["COM.BRAVE.BROWSER"]
        self.store = self.load()
        self.assertEqual(self.store.update_foreground_profile(app), "General")
        self.document["applications"] = {}
        self.store = self.load()
        self.assertEqual(self.store.update_foreground_profile(app), "Browser")

    def test_name_fallback_preserves_exact_and_legacy_mappings(self):
        app = foreground.ForegroundApplication("test.versioned", "afterfx.exe")
        self.document["applications"] = {"test.versioned": "Personal", "afterfx.exe": "General"}
        self.store = self.load()
        self.assertEqual(self.store.update_foreground_profile(app), "Personal")
        del self.document["applications"]["test.versioned"]
        self.store = self.load()
        self.assertEqual(self.store.update_foreground_profile(app), "General")

    def test_configured_default_missing_profile_and_detection_failure(self):
        self.document["default_profile"] = "Personal"
        del self.document["profiles"]["Photoshop"]
        self.store = self.load()
        for app in ("com.apple.finder", "com.adobe.photoshop", "test.unknown", None):
            self.assertEqual(self.store.update_foreground_profile(app), "Personal")

    def test_lock_and_unlock_on_current_application(self):
        self.store.set_locked_profile("Personal")
        for app in ("com.apple.finder", "com.brave.browser", "com.adobe.photoshop"):
            self.assertEqual(self.store.update_foreground_profile(app), "Personal")
        self.store.set_locked_profile(None)
        self.assertEqual(self.store.current_profile(), "Photoshop")

    def test_manual_selection_lasts_until_identity_changes(self):
        app = foreground.ForegroundApplication("com.brave.browser", "brave.exe")
        self.store.update_foreground_profile(app)
        self.store.select_profile("Personal")
        self.assertEqual(self.store.update_foreground_profile(app), "Personal")
        self.assertEqual(self.store.update_foreground_profile("com.brave.browser"), "Personal")
        self.assertEqual(self.store.update_foreground_profile("com.adobe.photoshop"), "Photoshop")
        self.assertEqual(self.store.update_foreground_profile("com.apple.finder"), "Personal")

    def test_different_apps_with_same_alias_clear_manual_selection(self):
        self.store.update_foreground_profile(foreground.ForegroundApplication("test.browser.one", "brave.exe"))
        self.store.select_profile("Personal")
        self.assertEqual(self.store.update_foreground_profile(
            foreground.ForegroundApplication("test.browser.two", "brave.exe")), "Browser")

    def test_renamed_profiles_follow_aliases_without_redirecting_explicit_binding(self):
        self.store.rename_profile("After Effects", "Motion work")
        self.assertEqual(self.store.update_foreground_profile("com.adobe.aftereffects.application"), "Motion work")
        self.assertEqual(self.store.update_foreground_profile(
            foreground.ForegroundApplication("test.versioned", "afterfx.exe")), "Motion work")
        self.document["applications"] = {"brave.exe": "Personal"}
        self.store = self.load()
        self.store.rename_profile("Browser", "Web work")
        self.assertEqual(self.store.update_foreground_profile("com.brave.browser"), "Personal")

    @unittest.skipUnless(HAS_PYOBJC, "macOS detector needs PyObjC")
    def test_watcher_detector_store_pipeline(self):
        apps = []
        for bundle, name in (("com.apple.finder", "Finder"), ("com.brave.Browser", "Brave Browser"),
                             ("com.apple.finder", "Finder")):
            app = Mock()
            app.bundleIdentifier.return_value = bundle
            app.localizedName.return_value = name
            apps.append(app)
        workspace = Mock()
        workspace.sharedWorkspace.return_value.frontmostApplication.side_effect = apps
        stop = Event()
        changes = []
        def changed(profile):
            changes.append(profile)
            if len(changes) == 3:
                stop.set()
        state = {}
        with patch.object(foreground.sys, "platform", "darwin"), \
                patch.object(foreground, "NSWorkspace", workspace), \
                patch.object(engine, "PROFILE_POLL_SECONDS", 0):
            engine.watch_profiles(self.store, state, stop, changed)
        self.assertEqual(changes, ["General", "Browser", "General"])
        self.assertEqual(state["profile"], "General")

    def test_windows_watcher_detector_store_pipeline(self):
        executables = iter(("explorer.exe", "brave.exe", "explorer.exe"))
        stop = Event()
        changes = []
        def changed(profile):
            changes.append(profile)
            if len(changes) == 3:
                stop.set()
        state = {}
        with patch.object(foreground.sys, "platform", "win32"), \
                patch.object(foreground, "get_windows_foreground_application",
                             side_effect=lambda: next(executables)), \
                patch.object(engine, "PROFILE_POLL_SECONDS", 0):
            engine.watch_profiles(self.store, state, stop, changed)
        self.assertEqual(changes, ["General", "Browser", "General"])


class WindowsDetectorTests(unittest.TestCase):
    def test_windows_dispatch_returns_executable_name(self):
        with patch.object(foreground.sys, "platform", "win32"), \
                patch.object(foreground, "get_windows_foreground_application", return_value="krita.exe"):
            self.assertEqual(foreground.get_foreground_application(), "krita.exe")

    def test_other_platforms_never_use_windows_backend(self):
        with patch.object(foreground.sys, "platform", "linux"), \
                patch.object(foreground, "NSWorkspace", None), \
                patch.object(foreground, "get_windows_foreground_application") as windows:
            self.assertIsNone(foreground.get_foreground_application())
            windows.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "live Windows API")
    def test_live_windows_detector_returns_lowercase_executable_or_none(self):
        result = foreground.get_foreground_application()
        if result is not None:
            self.assertEqual(result, result.lower())
            self.assertTrue(result.endswith(".exe"))
            self.assertNotIn("\\", result)


if __name__ == "__main__":
    unittest.main()
