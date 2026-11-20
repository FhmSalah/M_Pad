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
QUIT_MESSAGE = b"quit\n"  # Sent by `--quit` (the installer closes the running copy this way).


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


def wait_for_exit(pid, timeout_s):
    """True once process `pid` has ended (or never existed)."""
    if sys.platform == "win32":
        import ctypes
        SYNCHRONIZE, WAIT_TIMEOUT = 0x00100000, 0x00000102
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return True  # Already gone.
        try:
            return kernel32.WaitForSingleObject(ctypes.c_void_p(handle), int(timeout_s * 1000)) != WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    import os
    import time
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass  # Exists but belongs to someone else; keep waiting.
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


class SingleInstance(QObject):
    activation_requested = Signal()
    quit_requested = Signal()

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

    def notify_running(self, timeout_ms=1000, message=SHOW_MESSAGE):
        """Send a message ("show" by default) to the running copy. True when it was reached."""
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if not socket.waitForConnected(timeout_ms):
            return False
        allow_other_process_foreground()
        socket.write(message)
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
        data = bytes(connection.readAll())
        if QUIT_MESSAGE.strip() in data:
            self.quit_requested.emit()
        elif SHOW_MESSAGE.strip() in data:
            self.activation_requested.emit()

    def running_pid(self):
        """Process ID of the copy holding the lock (Qt writes it into the lock file)."""
        try:
            info = self.lock.getLockInfo()
            pid = info[0] if isinstance(info, tuple) else None
            return pid if isinstance(pid, int) and pid > 0 else None
        except Exception:
            return None

    def wait_until_free(self, timeout_s=10.0, pid=None):
        """After asking the running copy to quit: wait until it has really exited."""
        import time
        deadline = time.monotonic() + timeout_s
        while not self.acquire():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)
        self.lock.unlock()
        # The lock goes first; the process may still be finishing its shutdown.
        return pid is None or wait_for_exit(pid, max(0.0, deadline - time.monotonic()))

    def release(self):
        if self.server is not None:
            self.server.close()
            self.server.deleteLater()
            self.server = None
        self.lock.unlock()
