"""Tray icon: Windows notification area, macOS menu bar.

Double-click (Windows) opens the window; the menu offers Open and Quit.
"""

import sys

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayIcon(QObject):
    open_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon, title, parent=None, autostart=None):
        super().__init__(parent)
        self.title = title
        self.connected = False
        self.profile = None
        self.hint_shown = False
        self.autostart = autostart
        self.icon = QSystemTrayIcon(icon, self)
        self.menu = QMenu()
        self.open_action = self.menu.addAction("Open")
        self.open_action.triggered.connect(self.open_requested.emit)
        self.autostart_action = None
        if autostart is not None:
            self.autostart_action = self.menu.addAction("Start at login")
            self.autostart_action.setCheckable(True)
            self.autostart_action.toggled.connect(self.set_autostart)
            # Re-read each time: the user may change it in Task Manager / System Settings.
            self.menu.aboutToShow.connect(self.sync_autostart)
            self.sync_autostart()
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction("Quit")
        self.quit_action.triggered.connect(self.quit_requested.emit)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self.activated)
        self.update_tooltip()

    @staticmethod
    def available():
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self):
        self.icon.show()

    def hide(self):
        self.icon.hide()

    @Slot(QSystemTrayIcon.ActivationReason)
    def activated(self, reason):
        # macOS shows the menu on click, so only double-click opens the window directly.
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_requested.emit()

    @Slot()
    def sync_autostart(self):
        try:
            enabled = self.autostart.is_enabled()
        except OSError:
            enabled = False
        blocked = self.autostart_action.blockSignals(True)
        self.autostart_action.setChecked(enabled)
        self.autostart_action.blockSignals(blocked)

    @Slot(bool)
    def set_autostart(self, enabled):
        try:
            self.autostart.set_enabled(enabled)
        except OSError as error:
            self.icon.showMessage(self.title, f"Couldn't change Start at login: {error}",
                                  QSystemTrayIcon.MessageIcon.Warning, 5000)
        self.sync_autostart()

    @Slot(bool)
    def set_connection(self, connected):
        self.connected = connected
        self.update_tooltip()

    def set_profile(self, profile):
        self.profile = profile
        self.update_tooltip()

    def update_tooltip(self):
        parts = [self.title, "Connected" if self.connected else "Not connected"]
        if self.profile:
            parts.append(f"Profile: {self.profile}")
        self.icon.setToolTip(" — ".join(parts))

    def show_hidden_hint(self):
        """Explain once per run where the window went."""
        if self.hint_shown or not self.icon.supportsMessages():
            return
        self.hint_shown = True
        where = ("Click the menu bar icon to open or quit." if sys.platform == "darwin"
                 else "Double-click the tray icon to open it, or right-click to quit.")
        self.icon.showMessage(self.title, f"Still running in the background. {where}",
                              QSystemTrayIcon.MessageIcon.Information, 4000)
