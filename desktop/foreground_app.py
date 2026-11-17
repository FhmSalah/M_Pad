"""Foreground identity for profile selection: Windows executables, macOS bundles."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import ntpath
import re
import sys
from threading import current_thread, main_thread
import weakref
import unicodedata

try:
    from AppKit import NSWorkspace
except ImportError:
    NSWorkspace = None

if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
    ]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD)
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PATH_CHARACTERS = 32768


# Confirmed from installed applications' Contents/Info.plist on this Mac.
MACOS_APPLICATION_ALIASES = {
    "com.brave.browser": "brave.exe",
    "com.adobe.photoshop": "photoshop.exe",
    "com.adobe.aftereffects.application": "afterfx.exe",
    "com.adobe.premierepro.24": "adobe premiere pro.exe",
    "com.adobe.illustrator": "illustrator.exe",
    "org.blenderfoundation.blender": "blender.exe",
    "org.krita": "krita.exe",
    "com.microsoft.vscode": "code.exe",
    "net.whatsapp.whatsapp": "whatsapp.exe",
    "com.lemon.lvoverseas": "capcut.exe",
}

APPLICATION_NAME_ALIASES = {
    "brave": "brave.exe", "brave browser": "brave.exe",
    "photoshop": "photoshop.exe", "adobe photoshop": "photoshop.exe",
    "after effects": "afterfx.exe", "adobe after effects": "afterfx.exe",
    "premiere pro": "adobe premiere pro.exe", "adobe premiere pro": "adobe premiere pro.exe",
    "illustrator": "illustrator.exe", "adobe illustrator": "illustrator.exe",
    "blender": "blender.exe", "krita": "krita.exe",
    "code": "code.exe", "visual studio code": "code.exe", "vs code": "code.exe",
    "whatsapp": "whatsapp.exe", "capcut": "capcut.exe",
    "google chrome": "chrome.exe", "microsoft edge": "msedge.exe",
    "firefox": "firefox.exe", "opera": "opera.exe", "opera gx": "opera_gx.exe",
}


def normalize_application_name(name):
    # Ignore Unicode direction marks (e.g. WhatsApp) and optional release suffixes.
    name = "".join(c for c in unicodedata.normalize("NFKC", name)
                   if unicodedata.category(c) != "Cf")
    name = " ".join(name.casefold().split())
    return re.sub(r"\s+\d+(?:\.\d+)*$", "", name)


@dataclass(frozen=True)
class ForegroundApplication:
    identifier: str
    alias: str | None = None



def foreground_application_from_running_app(app):
    """Share identity/alias conversion between polling and activation events."""
    if app is None:
        return None
    bundle_id = str(app.bundleIdentifier() or "").strip().lower()
    name = normalize_application_name(str(app.localizedName() or ""))
    alias = MACOS_APPLICATION_ALIASES.get(bundle_id) or APPLICATION_NAME_ALIASES.get(name)
    if not bundle_id and not name:
        return None
    return ForegroundApplication(bundle_id or f"name:{name}", alias)


def get_windows_foreground_application():
    """Return the lowercase foreground executable name, or None when unavailable."""
    window = _user32.GetForegroundWindow()
    process_id = wintypes.DWORD()
    if not window or not _user32.GetWindowThreadProcessId(window, ctypes.byref(process_id)):
        return None
    process = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value)
    if not process:
        return None
    try:
        path = ctypes.create_unicode_buffer(MAX_PATH_CHARACTERS)
        size = wintypes.DWORD(len(path))
        if not _kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
            return None
        return ntpath.basename(path.value).lower()
    finally:
        _kernel32.CloseHandle(process)


def get_foreground_application():
    """Windows: lowercase executable name. macOS: bundle identity plus legacy alias.

    Returns None on failure or on unsupported platforms.
    """
    if sys.platform == "win32":
        return get_windows_foreground_application()
    if NSWorkspace is None:
        return None
    try:
        # Polling runs in a Python worker thread, so drain Cocoa temporaries here.
        from objc import autorelease_pool
        with autorelease_pool():
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if app is None:
                return None
            return foreground_application_from_running_app(app)
    except Exception:
        return None


class ActivationObserver:
    """One main-queue workspace observer, explicitly owned and stopped by Qt."""

    def __init__(self, on_application):
        self.on_application = on_application
        self.center = None
        self.token = None
        self.callback = None
        self.active = False
        self.generation = 0

    def start(self):
        if self.active:
            return True
        if sys.platform != "darwin" or NSWorkspace is None or current_thread() is not main_thread():
            return False
        try:
            from AppKit import NSWorkspaceDidActivateApplicationNotification, NSWorkspaceApplicationKey
            from Foundation import NSOperationQueue
            self.generation += 1
            generation = self.generation
            owner = weakref.ref(self)
            def activated(notification):
                observer = owner()
                if observer is None or not observer.active or observer.generation != generation:
                    return
                try:
                    application = foreground_application_from_running_app(
                        notification.userInfo().get(NSWorkspaceApplicationKey))
                    if application is not None:
                        observer.on_application(application)
                except Exception:
                    # Never let a Python exception escape into Cocoa notification delivery.
                    pass
            self.center = NSWorkspace.sharedWorkspace().notificationCenter()
            self.callback = activated
            self.active = True
            self.token = self.center.addObserverForName_object_queue_usingBlock_(
                NSWorkspaceDidActivateApplicationNotification, None,
                NSOperationQueue.mainQueue(), self.callback)
            if self.token is None:
                raise RuntimeError("Workspace did not return an observer token")
            return True
        except Exception:
            self.stop()
            return False

    def stop(self):
        self.active = False
        self.generation += 1
        if self.token is not None:
            try:
                self.center.removeObserver_(self.token)
            except Exception:
                pass
            self.token = None
        self.callback = None
        self.center = None
