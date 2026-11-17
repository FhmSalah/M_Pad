"""Detect a V1 Macro Pad and print its valid logical events."""

import serial

from detect_device import MAX_LINE_BYTES, find_macro_pad

VALID_EVENTS = {f"KEY:{number}".encode("ascii") for number in range(1, 13)} | {
    b"ENC1:PRESS", b"ENC2:PRESS",
    b"ENC1:CW", b"ENC1:CCW", b"ENC2:CW", b"ENC2:CCW",
}


def listen(connection):
    line = bytearray()
    oversized = False
    while True:
        character = connection.read(1)
        if not character:
            continue
        if character == b"\n":
            event = bytes(line).removesuffix(b"\r")
            if not oversized and event in VALID_EVENTS:
                print(event.decode("ascii"), flush=True)
            line.clear()
            oversized = False
        elif not oversized:
            if len(line) < MAX_LINE_BYTES:
                line.extend(character)
            else:
                oversized = True


def main():
    try:
        connection = find_macro_pad()
        if connection is None:
            print("Macro Pad not found", flush=True)
            return
        # Keep the identified port open to avoid resetting it by reopening.
        with connection:
            print(f"Macro Pad found on {connection.port}", flush=True)
            print("Listening...", flush=True)
            listen(connection)
    except KeyboardInterrupt:
        pass
    except (serial.SerialException, OSError) as error:
        print(f"Serial connection error: {error}", flush=True)


if __name__ == "__main__":
    main()
