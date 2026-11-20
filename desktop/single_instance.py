"""Keep one running copy per user; a second launch asks the first to show its window.

Two copies would compete for the pad's serial port, so the second one only sends
"show" to the first and exits.
"""

import getpass
import re
import sys

from PySide6.QtCore import QDir, QLockFile, QObject, Signal, Slot
from PySide6.QtNetwork import QLocalServer, QLocalSocket

SHOW_MESSAGE = b"show\n"


def instance_name(app_name):
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return re.sub(r"[^A-Za-z0-9_-]+", "-", f"{app_name}-{user}").strip("-").lower()


def allow_other_process_foreground():
    """Windows: let the running copy bring its window to the front for us."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ASFW_ANY = -1
        ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
    except Exception:
        pass


class SingleInstance(QObject):
    activation_requested = Signal()

    def __init__(self, app_name, parent=None):
        super().__init__(parent)
        self.name = instance_name(app_name)
        self.lock = QLockFile(QDir.temp().absoluteFilePath(f"{self.name}.lock"))
        self.lock.setStaleLockTime(0)  # Rely on process-alive checks, never on age.
        self.server = None

    def acquire(self):
        """True when this is the only running copy."""
        if self.lock.tryLock(0):
            return True
        # A crashed copy leaves a lock whose process is gone; Qt detects that here.
        return self.lock.removeStaleLockFile() and self.lock.tryLock(0)

    def notify_running(self, timeout_ms=1000):
        """Ask the running copy to show its window. True when it was reached."""
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if not socket.waitForConnected(timeout_ms):
            return False
        allow_other_process_foreground()
        socket.write(SHOW_MESSAGE)
        socket.flush()
        socket.waitForBytesWritten(timeout_ms)
        socket.disconnectFromServer()
        return True

    def listen(self):
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self.accept_connections)
        if not self.server.listen(self.name):
            # A leftover socket file from a crash (macOS); we hold the lock, so it's ours.
            QLocalServer.removeServer(self.name)
            return self.server.listen(self.name)
        return True

    @Slot()
    def accept_connections(self):
        while self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            connection.readyRead.connect(self.read_message)
            connection.disconnected.connect(connection.deleteLater)
            if connection.bytesAvailable():
                self.handle(connection)

    @Slot()
    def read_message(self):
        connection = self.sender()
        if isinstance(connection, QLocalSocket):
            self.handle(connection)

    def handle(self, connection):
        if SHOW_MESSAGE.strip() in bytes(connection.readAll()):
            self.activation_requested.emit()

    def release(self):
        if self.server is not None:
            self.server.close()
            self.server.deleteLater()
            self.server = None
        self.lock.unlock()
