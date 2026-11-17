"""Find a V1 Macro Pad using its serial identification handshake."""

import sys
import time

import serial
from serial.tools import list_ports

BAUD_RATE = 115200
READ_TIMEOUT_SECONDS = 0.1
WRITE_TIMEOUT_SECONDS = 0.2
DETECTION_SECONDS = 3.5
RETRY_SECONDS = 0.4
MAX_LINE_BYTES = 64
REQUEST = b"WHO\n"
RESPONSE = b"MACROPAD:V1"


def handshake(connection, stop=None):
    """Identify an open port using the proven bounded handshake retries."""
    deadline = time.monotonic() + DETECTION_SECONDS
    next_request = 0.0
    line = bytearray()
    oversized = False

    while time.monotonic() < deadline and (stop is None or not stop.is_set()):
        now = time.monotonic()
        if now >= next_request:
            connection.write(REQUEST)
            next_request = now + RETRY_SECONDS

        character = connection.read(1)
        if not character:
            continue
        if character == b"\n":
            # Arduino println sends CRLF; also accept plain LF.
            if not oversized and bytes(line).removesuffix(b"\r") == RESPONSE:
                return True
            line.clear()
            oversized = False
        elif not oversized:
            if len(line) < MAX_LINE_BYTES:
                line.extend(character)
            else:
                # Discard oversized lines through their next newline.
                oversized = True
    return False


def open_macro_pad(port_name, stop=None):
    """Return an identified open connection; close every unsuccessful probe."""
    connection = None
    identified = False
    try:
        connection = serial.Serial(
            port_name,
            baudrate=BAUD_RATE,
            timeout=READ_TIMEOUT_SECONDS,
            write_timeout=WRITE_TIMEOUT_SECONDS,
        )
        identified = handshake(connection, stop)
        if identified:
            return connection
    except (serial.SerialException, OSError):
        # Busy, inaccessible, disconnected, or timed-out ports are skipped.
        pass
    finally:
        if connection is not None and not identified:
            try:
                connection.close()
            except OSError:
                pass  # A port disappearing during cleanup must not end discovery.
    return None


def is_macro_pad(port_name):
    """Probe one port, closing it on every exit path."""
    connection = open_macro_pad(port_name)
    if connection is None:
        return False
    connection.close()
    return True


def find_macro_pad(stop=None):
    """Return the first identified connection; the caller must close it."""
    try:
        ports = list_ports.comports()
    except OSError:
        return None  # The GUI retries discovery on its existing bounded schedule.
    if sys.platform == "darwin":
        # Skip Bluetooth/accessory ports before the bounded handshake probes.
        ports = [port for port in ports if port.vid is not None and port.pid is not None]
        ports.sort(key=lambda port: (
            0 if (port.vid, port.pid) == (0x303A, 0x1001)
            else 1 if "usbmodem" in port.device.lower()
            else 2
        ))
    for port in ports:
        if stop is not None and stop.is_set():
            break
        connection = open_macro_pad(port.device, stop)
        if connection is not None:
            return connection
    return None


def main():
    connection = find_macro_pad()
    if connection is None:
        print("Macro Pad not found")
        return
    with connection:
        print(f"Macro Pad found on {connection.port}")


if __name__ == "__main__":
    main()
