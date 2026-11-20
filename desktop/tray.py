"""Tray icon: Windows notification area, macOS menu bar.

Double-click (Windows) opens the window; the menu offers Open and Quit.
"""

import sys

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayIcon(QObject):
    open_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon, title, parent=None):
        super().__init__(parent)
        self.title = title
        self.connected = False
        self.profile = None
        self.hint_shown = False
        self.icon = QSystemTrayIcon(icon, self)
        self.menu = QMenu()
        self.open_action = self.menu.addAction("Open")
        self.open_action.triggered.connect(self.open_requested.emit)
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
