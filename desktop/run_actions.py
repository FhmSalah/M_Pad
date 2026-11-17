"""Run configured V1 hotkeys and media keys for logical Macro Pad events."""

from contextlib import ExitStack
from threading import Condition, Event, Lock, Thread

import serial
from pynput.keyboard import Controller
from pynput.mouse import Controller as MouseController

from config_store import ConfigStore, compile_actions
from detect_device import MAX_LINE_BYTES, find_macro_pad
from foreground_app import get_foreground_application
from monitor_events import VALID_EVENTS
from shortcut_keys import ScrollAction

PROFILE_POLL_SECONDS = 0.2


class ActivityDispatcher:
    """Bounded cosmetic delivery; a slow observer cannot stall serial actions."""
    def __init__(self, callback):
        self.callback = callback
        self.condition = Condition()
        self.pending = {}
        self.closed = False
        self.thread = Thread(target=self.run, name="MacroPad activity", daemon=True)
        self.thread.start()

    def submit(self, profile, event, assigned, label):
        with self.condition:
            if not self.closed:
                # At most one pending update per logical input (18 total).
                self.pending[event] = (profile, event, assigned, label)
                self.condition.notify()

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending)
                if self.closed:
                    return
                batch = tuple(self.pending.values())
                self.pending.clear()
            for activity in batch:
                with self.condition:
                    if self.closed:
                        return
                try:
                    self.callback(*activity)
                except Exception:
                    # Observer failures never change execution/reconnection.
                    pass

    def close(self):
        with self.condition:
            self.closed = True
            self.pending.clear()
            self.condition.notify()


class ActionGate:
    """Pause execution and invalidate queued serial input during recording."""
    def __init__(self):
        self.lock = Lock()
        self.paused = False
        self.generation = 0

    def set_paused(self, paused):
        with self.lock:
            if self.paused != paused:
                self.paused = paused
                self.generation += 1

    def snapshot(self):
        with self.lock:
            return self.paused, self.generation


def load_profiles():
    return ConfigStore().snapshot()


def watch_profiles(store, state, stop, on_profile=None):
    """Poll off the serial thread; publish the active profile name."""
    previous = None
    while not stop.is_set():
        try:
            executable = get_foreground_application()
        except OSError:
            executable = None
        profile = store.update_foreground_profile(executable)
        if profile != previous:
            state["profile"] = profile
            previous = profile
            if on_profile is None:
                print(f"Profile: {profile}", flush=True)
            else:
                on_profile(profile)
        stop.wait(PROFILE_POLL_SECONDS)


def release_key(keyboard, key):
    try:
        keyboard.release(key)
    except (OSError, RuntimeError):
        # Retry a transient backend failure once; other releases still unwind.
        keyboard.release(key)


def execute_hotkey(keyboard, keys, stop=None, gate=None, generation=None, mouse=None):
    # Release keys in reverse order, including on Ctrl+C or action errors.
    with ExitStack() as held_keys:
        for key in keys:
            if stop is not None and stop.is_set():
                break
            if gate is not None:
                paused, current_generation = gate.snapshot()
                if paused or current_generation != generation:
                    break
            if isinstance(key, ScrollAction):
                (mouse if mouse is not None else MouseController()).scroll(0, key.steps)
                continue
            # Register before pressing: pynput updates modifier state before
            # its backend can raise, including before pressed() enters its try.
            held_keys.callback(release_key, keyboard, key)
            keyboard.press(key)


def listen(connection, keyboard, state, stop=None, store=None, gate=None, on_activity=None):
    dispatcher = ActivityDispatcher(on_activity) if on_activity is not None else None
    try:
        return _listen(connection, keyboard, state, stop, store, gate, dispatcher)
    finally:
        if dispatcher is not None:
            dispatcher.close()


def _listen(connection, keyboard, state, stop, store, gate, dispatcher):
    line = bytearray()
    oversized = False
    mouse = None
    generation = gate.snapshot()[1] if gate is not None else 0
    while stop is None or not stop.is_set():
        if gate is not None:
            _, current_generation = gate.snapshot()
            if current_generation != generation:
                connection.reset_input_buffer()
                line.clear()
                oversized = False
                generation = current_generation
        character = connection.read(1)
        if gate is not None:
            paused, current_generation = gate.snapshot()
            if paused or current_generation != generation:
                line.clear()
                oversized = False
                continue
        if not character:
            continue
        if character == b"\n":
            event = bytes(line).removesuffix(b"\r")
            valid = not oversized and event in VALID_EVENTS
            profile, label = None, ""
            if valid and dispatcher is not None:
                keys, profile, label = store.active_input(event)
            else:
                keys = store.active_action_keys(event) if valid else None
            if keys is not None:
                try:
                    if mouse is None and any(isinstance(key, ScrollAction) for key in keys):
                        mouse = MouseController()
                    execute_hotkey(keyboard, keys, stop, gate, generation, mouse)
                except (ValueError, OSError, RuntimeError, Controller.InvalidKeyException,
                        Controller.InvalidCharacterException) as error:
                    print(f"Action failed for {event.decode('ascii')}: {error}", flush=True)
            if valid and dispatcher is not None:
                # Execution has already finished; cosmetic work happens elsewhere.
                dispatcher.submit(profile, event.decode("ascii"), bool(keys), label)
            line.clear()
            oversized = False
        elif not oversized:
            if len(line) < MAX_LINE_BYTES:
                line.extend(character)
            else:
                oversized = True


def run_engine(stop, on_connection=None, on_profile=None, on_status=None, reconnect=False,
               config_store=None, action_gate=None, on_activity=None, watch_foreground=True):
    """Shared CLI/GUI engine. Callbacks report state; no GUI imports are needed."""
    store = config_store if config_store is not None else ConfigStore()
    gate = action_gate if action_gate is not None else ActionGate()
    state = {"profile": store.current_profile()}
    watcher = Thread(
        target=watch_profiles,
        args=(store, state, stop, on_profile),
    ) if watch_foreground else None
    if on_connection is not None:
        on_connection(False)
    if on_profile is not None:
        on_profile(store.current_profile())
    try:
        if reconnect and watcher is not None:
            watcher.start()
        keyboard = Controller()
        while not stop.is_set():
            if on_status is not None:
                on_status(store.error or "Searching...")
            connection = find_macro_pad(stop)
            if connection is None:
                if not reconnect:
                    if not stop.is_set():
                        print("Macro Pad not found", flush=True)
                    return
                stop.wait(1.0)
                continue
            try:
                with connection:
                    if stop.is_set():
                        return
                    if on_connection is None:
                        print(f"Macro Pad found on {connection.port}", flush=True)
                        print("Listening...", flush=True)
                    else:
                        on_connection(True)
                    if on_status is not None:
                        on_status(store.error or "Ready")
                    if watcher is not None and watcher.ident is None:
                        watcher.start()
                    listen(connection, keyboard, state, stop, store, gate, on_activity)
            except (serial.SerialException, OSError) as error:
                if on_status is not None:
                    on_status("Disconnected")
                else:
                    print(f"Connection/action error: {error}", flush=True)
            finally:
                if on_connection is not None:
                    on_connection(False)
            if not reconnect:
                return
            stop.wait(1.0)
    finally:
        stop.set()
        if watcher is not None and watcher.ident is not None:
            watcher.join()


def main():
    stop = Event()
    try:
        run_engine(stop)
    except KeyboardInterrupt:
        pass
    except (serial.SerialException, OSError) as error:
        print(f"Connection/action error: {error}", flush=True)


if __name__ == "__main__":
    main()
